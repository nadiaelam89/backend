from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.live_ops import WhatsAppMessageItem


class SiteChatSendRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=80)
    body: str = Field(..., min_length=1, max_length=4000)
    customer_name: str | None = Field(default=None, max_length=120)
    customer_phone: str | None = Field(default=None, max_length=40)


class SiteChatSendResponse(BaseModel):
    ok: bool = True
    conversation_id: str
    message: WhatsAppMessageItem


class SiteChatMessagesResponse(BaseModel):
    ok: bool = True
    conversation_id: str | None = None
    messages: list[WhatsAppMessageItem] = Field(default_factory=list)
