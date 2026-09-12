from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Query, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.schemas.live_ops import ContactConfigResponse
from app.services.whatsapp_service import get_contact_config, process_webhook_payload

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WhatsApp"])


@router.get("/api/public/contact-config", response_model=ContactConfigResponse)
async def contact_config() -> ContactConfigResponse:
    return get_contact_config()


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

    # Always 200 so Meta does not disable the webhook
    return {"ok": True}
