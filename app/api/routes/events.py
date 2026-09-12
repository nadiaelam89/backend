from __future__ import annotations

import logging
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base
from app.db.session import engine, get_db
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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/events", tags=["Events"])


async def _ensure_tables() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


@router.post("/track", response_model=TrackEventResponse)
async def track_event_endpoint(
    request: Request,
    payload: TrackEventRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> TrackEventResponse:
    client_ip = get_client_ip(request)
    client_country = get_client_country(request)
    event = await track_site_event(db, payload, client_ip, client_country)
    return TrackEventResponse(ok=True, is_valid_traffic=event.is_valid_traffic)


@router.post("/heartbeat", response_model=HeartbeatResponse)
async def visitor_heartbeat(
    request: Request,
    payload: HeartbeatRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> HeartbeatResponse:
    client_ip = get_client_ip(request)
    client_country = get_client_country(request)
    try:
        await upsert_visitor_heartbeat(db, payload, client_ip, client_country)
        return HeartbeatResponse(ok=True)
    except Exception as exc:
        logger.exception("heartbeat failed")
        msg = str(exc).lower()
        if (
            "visitor_presence" in msg
            or "session_recording" in msg
            or "does not exist" in msg
            or "no such table" in msg
        ):
            try:
                await db.rollback()
                await _ensure_tables()
                await upsert_visitor_heartbeat(db, payload, client_ip, client_country)
                return HeartbeatResponse(ok=True)
            except Exception as retry_exc:
                logger.exception("heartbeat retry failed")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"{type(retry_exc).__name__}: {retry_exc}",
                ) from retry_exc
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc


@router.post("/recording/chunk", response_model=RecordingChunkResponse)
async def recording_chunk(
    request: Request,
    payload: RecordingChunkRequest = Body(...),
    db: AsyncSession = Depends(get_db),
) -> RecordingChunkResponse:
    client_ip = get_client_ip(request)
    client_country = get_client_country(request)
    try:
        return await append_recording_chunk(db, payload, client_ip, client_country)
    except Exception as exc:
        logger.exception("recording chunk failed")
        msg = str(exc).lower()
        if "session_recording" in msg or "does not exist" in msg or "no such table" in msg:
            await db.rollback()
            await _ensure_tables()
            return await append_recording_chunk(db, payload, client_ip, client_country)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"{type(exc).__name__}: {exc}",
        ) from exc
