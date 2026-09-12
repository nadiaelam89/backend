from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.events import TrackEventRequest, TrackEventResponse
from app.schemas.live_ops import (
    HeartbeatRequest,
    HeartbeatResponse,
    RecordingChunkRequest,
    RecordingChunkResponse,
)
from app.services.event_service import track_site_event
from app.services.live_ops_service import append_recording_chunk, upsert_visitor_heartbeat
from app.utils.request_meta import get_client_country, get_client_ip

router = APIRouter(prefix="/api/events", tags=["Events"])
limiter = Limiter(key_func=get_remote_address)


@router.post("/track", response_model=TrackEventResponse)
@limiter.limit("120/minute")
async def track_event_endpoint(
    request: Request,
    payload: Annotated[TrackEventRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> TrackEventResponse:
    client_ip = get_client_ip(request)
    client_country = get_client_country(request)
    event = await track_site_event(db, payload, client_ip, client_country)
    await db.commit()
    return TrackEventResponse(ok=True, is_valid_traffic=event.is_valid_traffic)


@router.post("/heartbeat", response_model=HeartbeatResponse)
@limiter.limit("60/minute")
async def visitor_heartbeat(
    request: Request,
    payload: Annotated[HeartbeatRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> HeartbeatResponse:
    client_ip = get_client_ip(request)
    client_country = get_client_country(request)
    await upsert_visitor_heartbeat(db, payload, client_ip, client_country)
    await db.commit()
    return HeartbeatResponse(ok=True)


@router.post("/recording/chunk", response_model=RecordingChunkResponse)
@limiter.limit("30/minute")
async def recording_chunk(
    request: Request,
    payload: Annotated[RecordingChunkRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> RecordingChunkResponse:
    client_ip = get_client_ip(request)
    client_country = get_client_country(request)
    result = await append_recording_chunk(db, payload, client_ip, client_country)
    await db.commit()
    return result
