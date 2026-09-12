from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class HeartbeatRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=80)
    page_path: str | None = None
    client_user_agent: str | None = None


class HeartbeatResponse(BaseModel):
    ok: bool = True


class RecordingChunkRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=80)
    recording_id: str | None = None
    page_path: str | None = None
    client_user_agent: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list, max_length=500)
    is_final: bool = False


class RecordingChunkResponse(BaseModel):
    ok: bool = True
    recording_id: str
    accepted: int = 0
    stopped: bool = False


class LiveVisitorItem(BaseModel):
    session_id: str
    page_path: str | None
    client_ip: str | None
    client_country: str | None
    client_user_agent: str | None
    is_valid_traffic: bool
    first_seen_at: datetime
    last_seen_at: datetime
    seconds_ago: int
    has_recording: bool = False


class LiveVisitorsResponse(BaseModel):
    ok: bool = True
    live_count: int
    visitors: list[LiveVisitorItem]


class RecordingListItem(BaseModel):
    id: str
    session_id: str
    page_path: str | None
    client_ip: str | None
    client_country: str | None
    event_count: int
    chunk_count: int
    status: str
    started_at: datetime
    ended_at: datetime | None


class RecordingsListResponse(BaseModel):
    ok: bool = True
    total: int
    page: int
    page_size: int
    recordings: list[RecordingListItem]


class RecordingDetailResponse(BaseModel):
    ok: bool = True
    id: str
    session_id: str
    page_path: str | None
    client_ip: str | None
    client_country: str | None
    client_user_agent: str | None
    event_count: int
    status: str
    started_at: datetime
    ended_at: datetime | None
    events: list[dict[str, Any]]


class WhatsAppConversationItem(BaseModel):
    id: str
    wa_id: str
    customer_name: str | None
    customer_phone: str | None
    last_message_preview: str | None
    unread_count: int
    last_message_at: datetime | None


class WhatsAppConversationsResponse(BaseModel):
    ok: bool = True
    configured: bool
    business_number: str
    total: int
    conversations: list[WhatsAppConversationItem]


class WhatsAppMessageItem(BaseModel):
    id: str
    direction: Literal["inbound", "outbound"]
    body: str
    status: str
    created_at: datetime


class WhatsAppMessagesResponse(BaseModel):
    ok: bool = True
    conversation: WhatsAppConversationItem
    messages: list[WhatsAppMessageItem]


class WhatsAppReplyRequest(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


class WhatsAppReplyResponse(BaseModel):
    ok: bool = True
    message: WhatsAppMessageItem


class ContactConfigResponse(BaseModel):
    ok: bool = True
    whatsapp_number: str
    whatsapp_url: str
    prefill_message: str
    inbox_configured: bool
