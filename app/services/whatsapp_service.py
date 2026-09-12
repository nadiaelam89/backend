from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone

import httpx
from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import WhatsAppConversation, WhatsAppMessage
from app.schemas.live_ops import (
    ContactConfigResponse,
    WhatsAppConversationItem,
    WhatsAppConversationsResponse,
    WhatsAppMessageItem,
    WhatsAppMessagesResponse,
    WhatsAppReplyResponse,
)

logger = logging.getLogger(__name__)


def whatsapp_configured() -> bool:
    return bool(settings.WHATSAPP_PHONE_NUMBER_ID and settings.WHATSAPP_ACCESS_TOKEN)


def build_whatsapp_url(number: str | None = None, message: str | None = None) -> str:
    digits = "".join(c for c in (number or settings.WHATSAPP_BUSINESS_NUMBER) if c.isdigit())
    if not digits or "X" in (number or settings.WHATSAPP_BUSINESS_NUMBER).upper() or len(digits) < 12:
        return ""
    from urllib.parse import quote

    text = message if message is not None else settings.WHATSAPP_PREFILL_MESSAGE
    if text:
        return f"https://wa.me/{digits}?text={quote(text)}"
    return f"https://wa.me/{digits}"


def get_contact_config() -> ContactConfigResponse:
    raw = settings.WHATSAPP_BUSINESS_NUMBER or ""
    number = "".join(c for c in raw if c.isdigit())
    if "X" in raw.upper() or len(number) < 12:
        number = ""
    return ContactConfigResponse(
        whatsapp_number=number,
        whatsapp_url=build_whatsapp_url(number),
        prefill_message=settings.WHATSAPP_PREFILL_MESSAGE,
        inbox_configured=whatsapp_configured(),
    )


def _conversation_item(c: WhatsAppConversation) -> WhatsAppConversationItem:
    return WhatsAppConversationItem(
        id=str(c.id),
        wa_id=c.wa_id,
        customer_name=c.customer_name,
        customer_phone=c.customer_phone or c.wa_id,
        last_message_preview=c.last_message_preview,
        unread_count=c.unread_count,
        last_message_at=c.last_message_at,
    )


def _message_item(m: WhatsAppMessage) -> WhatsAppMessageItem:
    direction = "inbound" if m.direction == "inbound" else "outbound"
    return WhatsAppMessageItem(
        id=str(m.id),
        direction=direction,  # type: ignore[arg-type]
        body=m.body,
        status=m.status,
        created_at=m.created_at,
    )


async def list_conversations(db: AsyncSession) -> WhatsAppConversationsResponse:
    result = await db.execute(
        select(WhatsAppConversation).order_by(
            WhatsAppConversation.last_message_at.desc().nullslast(),
            WhatsAppConversation.created_at.desc(),
        )
    )
    rows = list(result.scalars().all())
    number = "".join(c for c in settings.WHATSAPP_BUSINESS_NUMBER if c.isdigit())
    return WhatsAppConversationsResponse(
        configured=whatsapp_configured(),
        business_number=number,
        total=len(rows),
        conversations=[_conversation_item(c) for c in rows],
    )


async def get_conversation_messages(
    db: AsyncSession, conversation_id: str
) -> WhatsAppMessagesResponse:
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    result = await db.execute(
        select(WhatsAppConversation)
        .options(selectinload(WhatsAppConversation.messages))
        .where(WhatsAppConversation.id == cid)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    conversation.unread_count = 0
    await db.flush()

    messages = sorted(conversation.messages, key=lambda m: m.created_at)
    return WhatsAppMessagesResponse(
        conversation=_conversation_item(conversation),
        messages=[_message_item(m) for m in messages],
    )


async def _get_or_create_conversation(
    db: AsyncSession,
    wa_id: str,
    customer_name: str | None = None,
) -> WhatsAppConversation:
    result = await db.execute(
        select(WhatsAppConversation).where(WhatsAppConversation.wa_id == wa_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = WhatsAppConversation(
            id=uuid.uuid4(),
            wa_id=wa_id,
            customer_name=customer_name,
            customer_phone=wa_id,
            unread_count=0,
        )
        db.add(conversation)
        await db.flush()
    elif customer_name and not conversation.customer_name:
        conversation.customer_name = customer_name
    return conversation


async def ingest_inbound_message(
    db: AsyncSession,
    *,
    wa_id: str,
    body: str,
    wa_message_id: str | None,
    customer_name: str | None = None,
) -> WhatsAppMessage | None:
    if wa_message_id:
        existing = await db.execute(
            select(WhatsAppMessage).where(WhatsAppMessage.wa_message_id == wa_message_id)
        )
        if existing.scalar_one_or_none():
            return None

    conversation = await _get_or_create_conversation(db, wa_id, customer_name)
    now = datetime.now(timezone.utc)
    message = WhatsAppMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        direction="inbound",
        body=body,
        wa_message_id=wa_message_id,
        status="received",
        created_at=now,
    )
    db.add(message)
    conversation.last_message_at = now
    conversation.last_message_preview = body[:240]
    conversation.unread_count = int(conversation.unread_count or 0) + 1
    await db.flush()
    return message


async def send_whatsapp_text(to_wa_id: str, body: str) -> dict:
    if not whatsapp_configured():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="WhatsApp Cloud API is not configured",
        )

    url = (
        f"https://graph.facebook.com/{settings.WHATSAPP_API_VERSION}/"
        f"{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    )
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(url, json=payload, headers=headers)

    if response.status_code >= 400:
        logger.error("WhatsApp send failed: %s %s", response.status_code, response.text)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Failed to send WhatsApp message",
        )

    return response.json()


async def reply_to_conversation(
    db: AsyncSession, conversation_id: str, body: str
) -> WhatsAppReplyResponse:
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    result = await db.execute(
        select(WhatsAppConversation).where(WhatsAppConversation.id == cid)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    api_result = await send_whatsapp_text(conversation.wa_id, body)
    wa_message_id = None
    try:
        wa_message_id = api_result["messages"][0]["id"]
    except (KeyError, IndexError, TypeError):
        pass

    now = datetime.now(timezone.utc)
    message = WhatsAppMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        direction="outbound",
        body=body,
        wa_message_id=wa_message_id,
        status="sent",
        created_at=now,
    )
    db.add(message)
    conversation.last_message_at = now
    conversation.last_message_preview = body[:240]
    await db.flush()

    return WhatsAppReplyResponse(message=_message_item(message))


async def process_webhook_payload(db: AsyncSession, payload: dict) -> int:
    """Parse Meta WhatsApp Cloud API webhook and store inbound messages."""
    stored = 0
    for entry in payload.get("entry", []) or []:
        for change in entry.get("changes", []) or []:
            value = change.get("value") or {}
            contacts = {
                c.get("wa_id"): (c.get("profile") or {}).get("name")
                for c in (value.get("contacts") or [])
                if c.get("wa_id")
            }
            for msg in value.get("messages") or []:
                wa_id = msg.get("from")
                if not wa_id:
                    continue
                msg_type = msg.get("type")
                body = ""
                if msg_type == "text":
                    body = ((msg.get("text") or {}).get("body")) or ""
                elif msg_type == "button":
                    body = ((msg.get("button") or {}).get("text")) or "[button]"
                elif msg_type == "interactive":
                    interactive = msg.get("interactive") or {}
                    body = (
                        ((interactive.get("button_reply") or {}).get("title"))
                        or ((interactive.get("list_reply") or {}).get("title"))
                        or "[interactive]"
                    )
                else:
                    body = f"[{msg_type or 'unsupported'} message]"

                saved = await ingest_inbound_message(
                    db,
                    wa_id=str(wa_id),
                    body=body,
                    wa_message_id=msg.get("id"),
                    customer_name=contacts.get(wa_id),
                )
                if saved:
                    stored += 1
    return stored


async def unread_total(db: AsyncSession) -> int:
    result = await db.execute(select(func.coalesce(func.sum(WhatsAppConversation.unread_count), 0)))
    return int(result.scalar_one() or 0)
