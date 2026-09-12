from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.db.models import WhatsAppConversation, WhatsAppMessage
from app.schemas.chat import SiteChatMessagesResponse, SiteChatSendResponse
from app.schemas.live_ops import WhatsAppMessageItem


def web_chat_id(session_id: str) -> str:
    return f"web:{session_id}"


def _message_item(m: WhatsAppMessage) -> WhatsAppMessageItem:
    direction = "inbound" if m.direction == "inbound" else "outbound"
    return WhatsAppMessageItem(
        id=str(m.id),
        direction=direction,  # type: ignore[arg-type]
        body=m.body,
        status=m.status,
        created_at=m.created_at,
    )


async def send_site_chat_message(
    db: AsyncSession,
    *,
    session_id: str,
    body: str,
    customer_name: str | None = None,
    customer_phone: str | None = None,
) -> SiteChatSendResponse:
    wa_id = web_chat_id(session_id)
    now = datetime.now(timezone.utc)
    text = body.strip()

    result = await db.execute(select(WhatsAppConversation).where(WhatsAppConversation.wa_id == wa_id))
    conversation = result.scalar_one_or_none()

    if conversation is None:
        conversation = WhatsAppConversation(
            id=uuid.uuid4(),
            wa_id=wa_id,
            customer_name=customer_name or "Visitor",
            customer_phone=customer_phone,
            unread_count=1,
            last_message_at=now,
            last_message_preview=text[:240],
            created_at=now,
            updated_at=now,
        )
        db.add(conversation)
        await db.flush()
    else:
        if customer_name:
            conversation.customer_name = customer_name
        if customer_phone:
            conversation.customer_phone = customer_phone
        conversation.last_message_at = now
        conversation.last_message_preview = text[:240]
        conversation.updated_at = now
        conversation.unread_count = int(conversation.unread_count or 0) + 1

    message = WhatsAppMessage(
        id=uuid.uuid4(),
        conversation_id=conversation.id,
        direction="inbound",
        body=text,
        wa_message_id=None,
        status="received",
        created_at=now,
    )
    db.add(message)
    await db.flush()

    return SiteChatSendResponse(
        conversation_id=str(conversation.id),
        message=_message_item(message),
    )


async def list_site_chat_messages(db: AsyncSession, session_id: str) -> SiteChatMessagesResponse:
    wa_id = web_chat_id(session_id)
    result = await db.execute(
        select(WhatsAppConversation)
        .options(selectinload(WhatsAppConversation.messages))
        .where(WhatsAppConversation.wa_id == wa_id)
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        return SiteChatMessagesResponse(conversation_id=None, messages=[])

    messages = sorted(conversation.messages, key=lambda m: m.created_at)
    return SiteChatMessagesResponse(
        conversation_id=str(conversation.id),
        messages=[_message_item(m) for m in messages],
    )


async def reply_site_or_whatsapp(
    db: AsyncSession,
    conversation_id: str,
    body: str,
    *,
    send_whatsapp_fn,
) -> WhatsAppMessageItem:
    """Reply in admin: web chats stay on-site; phone chats may use Cloud API."""
    try:
        cid = uuid.UUID(conversation_id)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    result = await db.execute(select(WhatsAppConversation).where(WhatsAppConversation.id == cid))
    conversation = result.scalar_one_or_none()
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    wa_message_id = None
    is_web = conversation.wa_id.startswith("web:")
    if not is_web:
        api_result = await send_whatsapp_fn(conversation.wa_id, body)
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
    return _message_item(message)
