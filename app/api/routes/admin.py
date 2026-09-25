from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.admin import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminMetricsResponse,
    AdminOrderDeleteResponse,
    AdminOrderDetailResponse,
    AdminOrdersListResponse,
    AdminPurgeDataResponse,
)
from app.schemas.live_ops import (
    LiveVisitorsResponse,
    RecordingDetailResponse,
    RecordingsListResponse,
    VisitorHistoryResponse,
    WhatsAppConversationsResponse,
    WhatsAppMessagesResponse,
    WhatsAppReplyRequest,
    WhatsAppReplyResponse,
)
from app.services.admin_auth import TOKEN_TTL_SECONDS, authenticate_admin, verify_admin_token
from app.services.admin_service import (
    delete_admin_order,
    get_admin_metrics,
    get_admin_order_detail,
    list_admin_orders,
    purge_all_data,
)
from app.services.live_ops_service import (
    get_or_create_visitor_recording,
    get_recording_detail,
    list_live_visitors,
    list_recordings,
    list_visitor_history,
)
from app.services.whatsapp_service import (
    get_conversation_messages,
    list_conversations,
    reply_to_conversation,
)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


async def require_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_admin_token(token)


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest) -> AdminLoginResponse:
    token = authenticate_admin(payload.username, payload.password)
    return AdminLoginResponse(access_token=token, expires_in=TOKEN_TTL_SECONDS)


@router.get("/metrics", response_model=AdminMetricsResponse)
async def admin_metrics(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> AdminMetricsResponse:
    return await get_admin_metrics(db, date_from, date_to)


@router.get("/orders", response_model=AdminOrdersListResponse)
async def admin_orders(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> AdminOrdersListResponse:
    return await list_admin_orders(db, page, page_size, status, search, date_from, date_to)


@router.post("/purge-data", response_model=AdminPurgeDataResponse)
async def admin_purge_data(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> AdminPurgeDataResponse:
    deleted = await purge_all_data(db)
    return AdminPurgeDataResponse(deleted=deleted)


@router.get("/orders/{order_id}", response_model=AdminOrderDetailResponse)
async def admin_order_detail(
    order_id: str,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> AdminOrderDetailResponse:
    return await get_admin_order_detail(db, order_id)


@router.delete("/orders/{order_id}", response_model=AdminOrderDeleteResponse)
async def admin_order_delete(
    order_id: str,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> AdminOrderDeleteResponse:
    return await delete_admin_order(db, order_id)


@router.get("/visitors/live", response_model=LiveVisitorsResponse)
async def admin_live_visitors(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> LiveVisitorsResponse:
    return await list_live_visitors(db)


@router.get("/visitors/history", response_model=VisitorHistoryResponse)
async def admin_visitor_history(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    date: str = Query(..., description="Calendar day YYYY-MM-DD (Europe/Rome)"),
) -> VisitorHistoryResponse:
    """Daily visitor log — country, IP, timestamps for the selected day."""
    try:
        return await list_visitor_history(db, date)
    except ValueError as exc:
        from fastapi import HTTPException

        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/visitors/{session_id}/recording", response_model=RecordingDetailResponse)
async def admin_visitor_recording(
    session_id: str,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> RecordingDetailResponse:
    """Legacy watch endpoint — kept for API compatibility."""
    return await get_or_create_visitor_recording(db, session_id)


@router.get("/recordings", response_model=RecordingsListResponse)
async def admin_recordings(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    session_id: str | None = Query(default=None),
    client_ip: str | None = Query(default=None),
) -> RecordingsListResponse:
    return await list_recordings(db, page, page_size, session_id, client_ip)


@router.get("/recordings/{recording_id}", response_model=RecordingDetailResponse)
async def admin_recording_detail(
    recording_id: str,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> RecordingDetailResponse:
    return await get_recording_detail(db, recording_id)


@router.get("/whatsapp/conversations", response_model=WhatsAppConversationsResponse)
async def admin_whatsapp_conversations(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> WhatsAppConversationsResponse:
    return await list_conversations(db)


@router.get(
    "/whatsapp/conversations/{conversation_id}/messages",
    response_model=WhatsAppMessagesResponse,
)
async def admin_whatsapp_messages(
    conversation_id: str,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> WhatsAppMessagesResponse:
    result = await get_conversation_messages(db, conversation_id)
    await db.commit()
    return result


@router.post(
    "/whatsapp/conversations/{conversation_id}/reply",
    response_model=WhatsAppReplyResponse,
)
async def admin_whatsapp_reply(
    conversation_id: str,
    payload: WhatsAppReplyRequest,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> WhatsAppReplyResponse:
    result = await reply_to_conversation(db, conversation_id, payload.body.strip())
    await db.commit()
    return result
