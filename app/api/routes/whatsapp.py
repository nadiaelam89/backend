from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, Query, Request, Response
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
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
limiter = Limiter(key_func=get_remote_address)


@router.get("/api/public/contact-config", response_model=ContactConfigResponse)
async def contact_config() -> ContactConfigResponse:
    return get_contact_config()


@router.post("/api/chat/send", response_model=SiteChatSendResponse)
@limiter.limit("30/minute")
async def chat_send(
    request: Request,
    payload: Annotated[SiteChatSendRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> SiteChatSendResponse:
    result = await send_site_chat_message(
        db,
        session_id=payload.session_id,
        body=payload.body,
        customer_name=payload.customer_name,
        customer_phone=payload.customer_phone,
    )
    await db.commit()
    return result


@router.get("/api/chat/messages", response_model=SiteChatMessagesResponse)
@limiter.limit("60/minute")
async def chat_messages(
    request: Request,
    session_id: str = Query(..., min_length=8, max_length=80),
    db: AsyncSession = Depends(get_db),
) -> SiteChatMessagesResponse:
    return await list_site_chat_messages(db, session_id)


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
        await db.commit()
        if stored:
            logger.info("Stored %s WhatsApp inbound message(s)", stored)
    except Exception:
        logger.exception("WhatsApp webhook processing failed")
        await db.rollback()

    return {"ok": True}
