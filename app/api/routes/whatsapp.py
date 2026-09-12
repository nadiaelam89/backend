from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Base
from app.db.session import engine, get_db
from app.schemas.chat import (
    SiteChatMessagesResponse,
    SiteChatSendRequest,
    SiteChatSendResponse,
)
from app.schemas.live_ops import ContactConfigResponse
from app.services.chat_service import list_site_chat_messages, send_site_chat_message
from app.services.whatsapp_service import get_contact_config, process_webhook_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Chat"])


async def _ensure_chat_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@router.get("/api/public/contact-config", response_model=ContactConfigResponse)
async def contact_config() -> ContactConfigResponse:
    return get_contact_config()


@router.post("/api/chat/send", response_model=SiteChatSendResponse)
async def chat_send(
    payload: SiteChatSendRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> SiteChatSendResponse:
    try:
        result = await send_site_chat_message(
            db,
            session_id=payload.session_id.strip(),
            body=payload.body.strip(),
            customer_name=(payload.customer_name or "").strip() or None,
            customer_phone=(payload.customer_phone or "").strip() or None,
        )
        return result
    except Exception as exc:
        logger.exception("chat send failed")
        # Missing-table / schema drift: create tables and retry once
        msg = str(exc).lower()
        if "whatsapp_" in msg or "does not exist" in msg or "no such table" in msg:
            try:
                await db.rollback()
                await _ensure_chat_tables()
                result = await send_site_chat_message(
                    db,
                    session_id=payload.session_id.strip(),
                    body=payload.body.strip(),
                    customer_name=(payload.customer_name or "").strip() or None,
                    customer_phone=(payload.customer_phone or "").strip() or None,
                )
                return result
            except Exception as retry_exc:
                logger.exception("chat send retry failed")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{type(retry_exc).__name__}: {retry_exc}",
                ) from retry_exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


@router.get("/api/chat/messages", response_model=SiteChatMessagesResponse)
async def chat_messages(
    session_id: str = Query(..., min_length=8, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> SiteChatMessagesResponse:
    try:
        return await list_site_chat_messages(db, session_id.strip())
    except Exception as exc:
        logger.exception("chat messages failed")
        msg = str(exc).lower()
        if "whatsapp_" in msg or "does not exist" in msg or "no such table" in msg:
            await db.rollback()
            await _ensure_chat_tables()
            return await list_site_chat_messages(db, session_id.strip())
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


@router.get("/api/whatsapp/webhook")
async def whatsapp_verify(
    hub_mode: str | None = Query(default=None, alias="hub.mode"),
    hub_verify_token: str | None = Query(default=None, alias="hub.verify_token"),
    hub_challenge: str | None = Query(default=None, alias="hub.challenge"),
) -> Response:
    if (
        hub_mode == "subscribe"
        and hub_verify_token
        and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN
        and hub_challenge is not None
    ):
        return Response(content=hub_challenge, media_type="text/plain")
    return Response(content="Forbidden", status_code=403)


@router.post("/api/whatsapp/webhook")
async def whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    try:
        payload = await request.json()
    except Exception:
        return {"ok": True}

    try:
        stored = await process_webhook_payload(db, payload if isinstance(payload, dict) else {})
        if stored:
            logger.info("Stored %s WhatsApp inbound message(s)", stored)
    except Exception:
        logger.exception("WhatsApp webhook processing failed")
        await db.rollback()

    return {"ok": True}
