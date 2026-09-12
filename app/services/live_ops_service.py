from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import settings
from app.db.models import SessionRecording, SessionRecordingChunk, VisitorPresence
from app.schemas.live_ops import (
    HeartbeatRequest,
    LiveVisitorItem,
    LiveVisitorsResponse,
    RecordingChunkRequest,
    RecordingChunkResponse,
    RecordingDetailResponse,
    RecordingListItem,
    RecordingsListResponse,
)
from app.services.visitor_fraud import check_visitor_ip_fraud

logger = logging.getLogger(__name__)


async def upsert_visitor_heartbeat(
    db: AsyncSession,
    payload: HeartbeatRequest,
    client_ip: str | None,
    client_country: str | None,
) -> VisitorPresence:
    now = datetime.now(timezone.utc)
    decision = await check_visitor_ip_fraud(
        client_ip=client_ip,
        client_country=client_country,
        user_agent=payload.client_user_agent,
    )

    result = await db.execute(
        select(VisitorPresence).where(VisitorPresence.session_id == payload.session_id)
    )
    presence = result.scalar_one_or_none()

    if presence is None:
        presence = VisitorPresence(
            session_id=payload.session_id,
            page_path=payload.page_path,
            client_ip=client_ip,
            client_country=decision.country_code or client_country,
            client_user_agent=payload.client_user_agent,
            is_valid_traffic=decision.allowed,
            fraud_reason=None if decision.allowed else decision.reason,
            first_seen_at=now,
            last_seen_at=now,
        )
        db.add(presence)
    else:
        presence.page_path = payload.page_path or presence.page_path
        presence.client_ip = client_ip or presence.client_ip
        presence.client_country = decision.country_code or client_country or presence.client_country
        presence.client_user_agent = payload.client_user_agent or presence.client_user_agent
        presence.is_valid_traffic = decision.allowed
        presence.fraud_reason = None if decision.allowed else decision.reason
        presence.last_seen_at = now

    await db.flush()
    return presence


async def list_live_visitors(db: AsyncSession) -> LiveVisitorsResponse:
    now = datetime.now(timezone.utc)
    ttl = max(30, int(settings.LIVE_VISITOR_TTL_SECONDS or 60))
    cutoff = now - timedelta(seconds=ttl)

    try:
        result = await db.execute(
            select(VisitorPresence)
            .where(VisitorPresence.last_seen_at >= cutoff)
            .order_by(VisitorPresence.last_seen_at.desc())
            .limit(200)
        )
        rows = list(result.scalars().all())
    except Exception:
        logger.exception("list_live_visitors presence query failed")
        rows = []

    # Fallback: recent page-view sessions if heartbeat table is empty/missing
    if not rows:
        try:
            from app.db.models import SiteEvent

            events = await db.execute(
                select(
                    SiteEvent.session_id,
                    func.max(SiteEvent.created_at).label("last_seen_at"),
                    func.max(SiteEvent.page_path).label("page_path"),
                    func.max(SiteEvent.client_ip).label("client_ip"),
                    func.max(SiteEvent.client_country).label("client_country"),
                    func.max(SiteEvent.client_user_agent).label("client_user_agent"),
                )
                .where(SiteEvent.created_at >= cutoff)
                .group_by(SiteEvent.session_id)
                .order_by(func.max(SiteEvent.created_at).desc())
                .limit(200)
            )
            fallback_rows = events.all()
            visitors = []
            for row in fallback_rows:
                last_seen = row.last_seen_at
                if last_seen is not None and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                visitors.append(
                    LiveVisitorItem(
                        session_id=row.session_id,
                        page_path=row.page_path,
                        client_ip=row.client_ip,
                        client_country=row.client_country,
                        client_user_agent=row.client_user_agent,
                        is_valid_traffic=True,
                        first_seen_at=last_seen or now,
                        last_seen_at=last_seen or now,
                        seconds_ago=max(
                            0, int((now - (last_seen or now)).total_seconds())
                        ),
                        has_recording=False,
                    )
                )
            return LiveVisitorsResponse(live_count=len(visitors), visitors=visitors)
        except Exception:
            logger.exception("list_live_visitors fallback failed")
            return LiveVisitorsResponse(live_count=0, visitors=[])

    session_ids = [r.session_id for r in rows]
    recording_sessions: set[str] = set()
    if session_ids:
        try:
            rec_result = await db.execute(
                select(SessionRecording.session_id)
                .where(SessionRecording.session_id.in_(session_ids))
                .distinct()
            )
            recording_sessions = {row[0] for row in rec_result.all()}
        except Exception:
            logger.exception("list_live_visitors recordings lookup failed")

    visitors = []
    for row in rows:
        last_seen = row.last_seen_at
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        first_seen = row.first_seen_at
        if first_seen is not None and first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        visitors.append(
            LiveVisitorItem(
                session_id=row.session_id,
                page_path=row.page_path,
                client_ip=row.client_ip,
                client_country=row.client_country,
                client_user_agent=row.client_user_agent,
                is_valid_traffic=row.is_valid_traffic,
                first_seen_at=first_seen or now,
                last_seen_at=last_seen or now,
                seconds_ago=max(0, int((now - (last_seen or now)).total_seconds())),
                has_recording=row.session_id in recording_sessions,
            )
        )

    return LiveVisitorsResponse(live_count=len(visitors), visitors=visitors)


async def append_recording_chunk(
    db: AsyncSession,
    payload: RecordingChunkRequest,
    client_ip: str | None,
    client_country: str | None,
) -> RecordingChunkResponse:
    events = payload.events[:500]
    now = datetime.now(timezone.utc)

    def _new_recording() -> SessionRecording:
        return SessionRecording(
            id=uuid.uuid4(),
            session_id=payload.session_id,
            page_path=payload.page_path,
            client_ip=client_ip,
            client_country=client_country,
            client_user_agent=payload.client_user_agent,
            event_count=0,
            chunk_count=0,
            status="recording",
            started_at=now,
            updated_at=now,
        )

    recording: SessionRecording | None = None
    if payload.recording_id:
        try:
            rid = uuid.UUID(payload.recording_id)
        except ValueError:
            rid = None
        else:
            result = await db.execute(select(SessionRecording).where(SessionRecording.id == rid))
            recording = result.scalar_one_or_none()

    # Never create an empty recording shell — that produces "0 events" in admin.
    if not events:
        if recording is not None and payload.is_final:
            recording.status = "completed"
            recording.ended_at = now
            recording.updated_at = now
            await db.flush()
            return RecordingChunkResponse(
                recording_id=str(recording.id), accepted=0, stopped=True
            )
        return RecordingChunkResponse(
            recording_id=payload.recording_id or "",
            accepted=0,
            stopped=bool(payload.is_final),
        )

    if recording is None:
        result = await db.execute(
            select(SessionRecording)
            .where(
                SessionRecording.session_id == payload.session_id,
                SessionRecording.status == "recording",
            )
            .order_by(SessionRecording.started_at.desc())
            .limit(1)
        )
        recording = result.scalar_one_or_none()

    if recording is None:
        recording = _new_recording()
        db.add(recording)
        await db.flush()

    stopped = recording.event_count >= settings.RECORDING_MAX_EVENTS or (
        recording.chunk_count >= settings.RECORDING_MAX_CHUNKS
    )
    accepted = 0

    if not stopped:
        remaining = settings.RECORDING_MAX_EVENTS - recording.event_count
        to_store = events[: max(0, remaining)]
        if to_store:
            chunk = SessionRecordingChunk(
                id=uuid.uuid4(),
                recording_id=recording.id,
                seq=recording.chunk_count,
                events_json=json.dumps(to_store, separators=(",", ":"), default=str),
                event_count=len(to_store),
            )
            db.add(chunk)
            recording.event_count += len(to_store)
            recording.chunk_count += 1
            accepted = len(to_store)
            if payload.page_path:
                recording.page_path = payload.page_path
            recording.client_ip = client_ip or recording.client_ip
            recording.client_country = client_country or recording.client_country
            recording.updated_at = now

        stopped = recording.event_count >= settings.RECORDING_MAX_EVENTS or (
            recording.chunk_count >= settings.RECORDING_MAX_CHUNKS
        )

    if payload.is_final or stopped:
        recording.status = "completed"
        recording.ended_at = now
        recording.updated_at = now

    await db.flush()
    return RecordingChunkResponse(
        recording_id=str(recording.id),
        accepted=accepted,
        stopped=recording.status == "completed",
    )


async def list_recordings(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    session_id: str | None = None,
) -> RecordingsListResponse:
    filters = []
    if session_id:
        filters.append(SessionRecording.session_id == session_id)

    count_q = select(func.count()).select_from(SessionRecording)
    if filters:
        count_q = count_q.where(*filters)
    total = int((await db.execute(count_q)).scalar_one())

    q = select(SessionRecording).order_by(SessionRecording.started_at.desc())
    if filters:
        q = q.where(*filters)
    q = q.offset((page - 1) * page_size).limit(page_size)
    rows = list((await db.execute(q)).scalars().all())

    return RecordingsListResponse(
        total=total,
        page=page,
        page_size=page_size,
        recordings=[
            RecordingListItem(
                id=str(r.id),
                session_id=r.session_id,
                page_path=r.page_path,
                client_ip=r.client_ip,
                client_country=r.client_country,
                event_count=r.event_count,
                chunk_count=r.chunk_count,
                status=r.status,
                started_at=r.started_at,
                ended_at=r.ended_at,
            )
            for r in rows
            if r.event_count > 0
        ],
    )


async def get_recording_detail(db: AsyncSession, recording_id: str) -> RecordingDetailResponse:
    try:
        rid = uuid.UUID(recording_id)
    except ValueError as exc:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found") from exc

    result = await db.execute(
        select(SessionRecording)
        .options(selectinload(SessionRecording.chunks))
        .where(SessionRecording.id == rid)
    )
    recording = result.scalar_one_or_none()
    if recording is None:
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    events: list[dict] = []
    for chunk in sorted(recording.chunks, key=lambda c: c.seq):
        try:
            parsed = json.loads(chunk.events_json)
            if isinstance(parsed, list):
                events.extend(parsed)
        except json.JSONDecodeError:
            logger.warning("Corrupt recording chunk %s", chunk.id)

    return RecordingDetailResponse(
        id=str(recording.id),
        session_id=recording.session_id,
        page_path=recording.page_path,
        client_ip=recording.client_ip,
        client_country=recording.client_country,
        client_user_agent=recording.client_user_agent,
        event_count=recording.event_count,
        status=recording.status,
        started_at=recording.started_at,
        ended_at=recording.ended_at,
        events=events,
    )
