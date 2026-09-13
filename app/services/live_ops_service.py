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

_ACTIVE_RECORDING_WINDOW = timedelta(minutes=45)


async def _resolve_continuable_recording(
    db: AsyncSession,
    *,
    session_id: str | None,
    recording_id: str | None,
    client_ip: str | None,
    now: datetime | None = None,
) -> SessionRecording | None:
    """
    Prefer the richest recent trail for this visitor.

    Thank-you hard reloads often mint a 1-event stub; without this, Replay opens
    the stub instead of the product-scroll recording.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - _ACTIVE_RECORDING_WINDOW
    candidates: list[SessionRecording] = []
    seen: set[uuid.UUID] = set()

    def _add(rec: SessionRecording | None) -> None:
        if rec is None or rec.id in seen:
            return
        seen.add(rec.id)
        candidates.append(rec)

    if recording_id:
        try:
            rid = uuid.UUID(recording_id)
        except ValueError:
            rid = None
        if rid is not None:
            result = await db.execute(select(SessionRecording).where(SessionRecording.id == rid))
            _add(result.scalar_one_or_none())

    if session_id:
        result = await db.execute(
            select(SessionRecording)
            .where(
                SessionRecording.session_id == session_id,
                SessionRecording.updated_at >= cutoff,
            )
            .order_by(SessionRecording.event_count.desc(), SessionRecording.updated_at.desc())
            .limit(5)
        )
        for row in result.scalars().all():
            _add(row)

    if client_ip:
        result = await db.execute(
            select(SessionRecording)
            .where(
                SessionRecording.client_ip == client_ip,
                SessionRecording.updated_at >= cutoff,
            )
            .order_by(SessionRecording.event_count.desc(), SessionRecording.updated_at.desc())
            .limit(8)
        )
        for row in result.scalars().all():
            _add(row)

    if not candidates:
        return None

    best = max(
        candidates,
        key=lambda r: (
            int(r.event_count or 0),
            r.updated_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
    )
    if session_id:
        best.session_id = session_id
    return best


async def upsert_visitor_heartbeat(
    db: AsyncSession,
    payload: HeartbeatRequest,
    client_ip: str | None,
    client_country: str | None,
) -> tuple[VisitorPresence, str | None]:
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

    recording_id: str | None = None
    country = decision.country_code or client_country

    # Always append trail data on heartbeat (client events and/or a page tick).
    # This is what makes Replay have more than 1 event.
    started_ms = 0
    try:
        existing = await db.execute(
            select(SessionRecording)
            .where(SessionRecording.session_id == payload.session_id)
            .order_by(SessionRecording.started_at.desc())
            .limit(1)
        )
        rec = existing.scalar_one_or_none()
        if rec and rec.started_at is not None:
            started = rec.started_at
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            started_ms = max(0, int((now - started).total_seconds() * 1000))
    except Exception:
        started_ms = 0

    events = list(payload.trail_events or [])
    if not events:
        events = [
            {
                "t": started_ms,
                "type": "nav",
                "path": payload.page_path or "/",
            }
        ]

    try:
        chunk = await append_recording_chunk(
            db,
            RecordingChunkRequest(
                session_id=payload.session_id,
                recording_id=payload.recording_id,
                page_path=payload.page_path,
                client_user_agent=payload.client_user_agent,
                events=events,
                is_final=False,
            ),
            client_ip,
            country,
        )
        recording_id = chunk.recording_id or None
    except Exception as exc:
        logger.exception("heartbeat trail append failed")
        msg = str(exc).lower()
        if "session_recording" in msg or "does not exist" in msg or "no such table" in msg:
            raise
        try:
            recording_id = await _ensure_presence_trail(
                db,
                session_id=payload.session_id,
                page_path=payload.page_path,
                client_ip=client_ip,
                client_country=country,
                client_user_agent=payload.client_user_agent,
                now=now,
            )
        except Exception:
            logger.exception("presence trail seed failed")

    return presence, recording_id


async def _ensure_presence_trail(
    db: AsyncSession,
    *,
    session_id: str,
    page_path: str | None,
    client_ip: str | None,
    client_country: str | None,
    client_user_agent: str | None,
    now: datetime | None = None,
) -> str:
    """Append a throttled nav tick so live visitors always have a recording row. Returns recording id."""
    now = now or datetime.now(timezone.utc)
    recording = await _resolve_continuable_recording(
        db,
        session_id=session_id,
        recording_id=None,
        client_ip=client_ip,
        now=now,
    )

    if recording is None:
        recording = SessionRecording(
            id=uuid.uuid4(),
            session_id=session_id,
            page_path=page_path,
            client_ip=client_ip,
            client_country=client_country,
            client_user_agent=client_user_agent,
            event_count=0,
            chunk_count=0,
            status="recording",
            started_at=now,
            updated_at=now,
        )
        db.add(recording)
        await db.flush()
    else:
        updated = recording.updated_at
        if updated is not None and updated.tzinfo is None:
            updated = updated.replace(tzinfo=timezone.utc)
        # Light throttle only (2s) so Replay timelines grow while visitors stay on a page
        if (
            updated
            and page_path == recording.page_path
            and recording.event_count > 0
            and (now - updated).total_seconds() < 2
        ):
            return str(recording.id)

    if recording.event_count >= settings.RECORDING_MAX_EVENTS:
        return str(recording.id)
    if recording.chunk_count >= settings.RECORDING_MAX_CHUNKS:
        return str(recording.id)

    elapsed_ms = 0
    if recording.started_at is not None:
        started = recording.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        elapsed_ms = max(0, int((now - started).total_seconds() * 1000))

    event = {"t": elapsed_ms, "type": "nav", "path": page_path or recording.page_path or "/"}
    chunk = SessionRecordingChunk(
        id=uuid.uuid4(),
        recording_id=recording.id,
        seq=recording.chunk_count,
        events_json=json.dumps([event], separators=(",", ":")),
        event_count=1,
    )
    db.add(chunk)
    recording.event_count += 1
    recording.chunk_count += 1
    if page_path:
        recording.page_path = page_path
    recording.client_ip = client_ip or recording.client_ip
    recording.client_country = client_country or recording.client_country
    recording.client_user_agent = client_user_agent or recording.client_user_agent
    recording.status = "recording"
    recording.ended_at = None
    recording.updated_at = now
    await db.flush()
    return str(recording.id)


async def get_or_create_visitor_recording(
    db: AsyncSession, session_id: str
) -> RecordingDetailResponse:
    """Used by admin Watch — always returns a recording for a live (or recent) session."""
    now = datetime.now(timezone.utc)

    presence_result = await db.execute(
        select(VisitorPresence).where(VisitorPresence.session_id == session_id)
    )
    presence = presence_result.scalar_one_or_none()

    existing = await _resolve_continuable_recording(
        db,
        session_id=session_id,
        recording_id=None,
        client_ip=presence.client_ip if presence else None,
        now=now,
    )
    if existing is not None and existing.event_count > 0:
        return await get_recording_detail(db, str(existing.id))

    recording_id = await _ensure_presence_trail(
        db,
        session_id=session_id,
        page_path=presence.page_path if presence else None,
        client_ip=presence.client_ip if presence else None,
        client_country=presence.client_country if presence else None,
        client_user_agent=presence.client_user_agent if presence else None,
        now=now,
    )
    await db.flush()
    return await get_recording_detail(db, recording_id)


async def _recording_index_for(
    db: AsyncSession,
    *,
    session_ids: list[str],
    client_ips: list[str],
) -> tuple[dict[str, str], dict[str, str]]:
    """Map session_id / client_ip -> latest recording_id (with events) for live rows."""
    by_session: dict[str, str] = {}
    by_ip: dict[str, str] = {}
    if not session_ids and not client_ips:
        return by_session, by_ip
    try:
        filters = [SessionRecording.event_count > 0]
        if session_ids and client_ips:
            from sqlalchemy import or_

            filters.append(
                or_(
                    SessionRecording.session_id.in_(session_ids),
                    SessionRecording.client_ip.in_(client_ips),
                )
            )
        elif session_ids:
            filters.append(SessionRecording.session_id.in_(session_ids))
        else:
            filters.append(SessionRecording.client_ip.in_(client_ips))

        result = await db.execute(
            select(SessionRecording)
            .where(*filters)
            .order_by(SessionRecording.event_count.desc(), SessionRecording.updated_at.desc())
            .limit(500)
        )
        for rec in result.scalars().all():
            if rec.session_id and rec.session_id not in by_session:
                by_session[rec.session_id] = str(rec.id)
            if rec.client_ip and rec.client_ip not in by_ip:
                by_ip[rec.client_ip] = str(rec.id)
    except Exception:
        logger.exception("recording index lookup failed")
    return by_session, by_ip


def _attach_recording(
    *,
    session_id: str,
    client_ip: str | None,
    by_session: dict[str, str],
    by_ip: dict[str, str],
) -> tuple[bool, str | None, str | None]:
    if session_id in by_session:
        return True, by_session[session_id], "session"
    if client_ip and client_ip in by_ip:
        return True, by_ip[client_ip], "ip"
    return False, None, None


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
            session_ids = [row.session_id for row in fallback_rows if row.session_id]
            client_ips = [row.client_ip for row in fallback_rows if row.client_ip]
            by_session, by_ip = await _recording_index_for(
                db, session_ids=session_ids, client_ips=client_ips
            )
            visitors = []
            for row in fallback_rows:
                last_seen = row.last_seen_at
                if last_seen is not None and last_seen.tzinfo is None:
                    last_seen = last_seen.replace(tzinfo=timezone.utc)
                has_rec, rec_id, match = _attach_recording(
                    session_id=row.session_id,
                    client_ip=row.client_ip,
                    by_session=by_session,
                    by_ip=by_ip,
                )
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
                        has_recording=has_rec,
                        recording_id=rec_id,
                        recording_match=match,
                    )
                )
            return LiveVisitorsResponse(live_count=len(visitors), visitors=visitors)
        except Exception:
            logger.exception("list_live_visitors fallback failed")
            return LiveVisitorsResponse(live_count=0, visitors=[])

    session_ids = [row.session_id for row in rows if row.session_id]
    client_ips = [row.client_ip for row in rows if row.client_ip]
    by_session, by_ip = await _recording_index_for(
        db, session_ids=session_ids, client_ips=client_ips
    )

    # Seed missing trails so Watch never shows empty for a live presence row
    for row in rows:
        if row.session_id in by_session:
            continue
        if row.client_ip and row.client_ip in by_ip:
            continue
        try:
            rid = await _ensure_presence_trail(
                db,
                session_id=row.session_id,
                page_path=row.page_path,
                client_ip=row.client_ip,
                client_country=row.client_country,
                client_user_agent=row.client_user_agent,
            )
            by_session[row.session_id] = rid
        except Exception:
            logger.exception("live visitor trail seed failed for %s", row.session_id)

    visitors = []
    for row in rows:
        last_seen = row.last_seen_at
        if last_seen is not None and last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        first_seen = row.first_seen_at
        if first_seen is not None and first_seen.tzinfo is None:
            first_seen = first_seen.replace(tzinfo=timezone.utc)
        has_rec, rec_id, match = _attach_recording(
            session_id=row.session_id,
            client_ip=row.client_ip,
            by_session=by_session,
            by_ip=by_ip,
        )
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
                has_recording=has_rec,
                recording_id=rec_id,
                recording_match=match,
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

    recording = await _resolve_continuable_recording(
        db,
        session_id=payload.session_id,
        recording_id=payload.recording_id,
        client_ip=client_ip,
        now=now,
    )

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
            recording_id=payload.recording_id or (str(recording.id) if recording else ""),
            accepted=0,
            stopped=bool(payload.is_final),
        )

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
            # Resume if visitor came back after a prior finalize
            if not payload.is_final:
                recording.status = "recording"
                recording.ended_at = None

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
        stopped=recording.status == "completed" and stopped,
    )


async def list_recordings(
    db: AsyncSession,
    page: int = 1,
    page_size: int = 20,
    session_id: str | None = None,
    client_ip: str | None = None,
) -> RecordingsListResponse:
    filters = [SessionRecording.event_count > 0]
    if session_id:
        filters.append(SessionRecording.session_id == session_id)
    if client_ip:
        filters.append(SessionRecording.client_ip == client_ip)

    # Wider fetch, then drop 1-event thank-you stubs when a richer IP sibling exists
    fetch_limit = min(max(page * page_size * 4, page_size), 400)
    q = (
        select(SessionRecording)
        .where(*filters)
        .order_by(SessionRecording.event_count.desc(), SessionRecording.started_at.desc())
        .limit(fetch_limit)
    )
    all_rows = list((await db.execute(q)).scalars().all())

    richest_by_ip: dict[str, int] = {}
    for r in all_rows:
        if not r.client_ip:
            continue
        richest_by_ip[r.client_ip] = max(richest_by_ip.get(r.client_ip, 0), int(r.event_count or 0))

    def _is_stub(r: SessionRecording) -> bool:
        if int(r.event_count or 0) > 2:
            return False
        if not r.client_ip:
            return False
        return richest_by_ip.get(r.client_ip, 0) > int(r.event_count or 0)

    filtered = [r for r in all_rows if not _is_stub(r)]
    filtered.sort(
        key=lambda r: r.started_at or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    total = len(filtered)
    start = (page - 1) * page_size
    rows = filtered[start : start + page_size]

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

    siblings: list[SessionRecording] = [recording]
    # Same session always — thank-you hard reload must not orphan product scroll
    by_session = await db.execute(
        select(SessionRecording)
        .options(selectinload(SessionRecording.chunks))
        .where(
            SessionRecording.session_id == recording.session_id,
            SessionRecording.event_count > 0,
        )
        .order_by(SessionRecording.started_at.asc())
    )
    session_siblings = list(by_session.scalars().unique().all())
    if session_siblings:
        siblings = session_siblings

    if recording.client_ip and recording.started_at is not None:
        started = recording.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=timezone.utc)
        window_start = started - timedelta(hours=2)
        window_end = started + timedelta(hours=2)
        sib_result = await db.execute(
            select(SessionRecording)
            .options(selectinload(SessionRecording.chunks))
            .where(
                SessionRecording.client_ip == recording.client_ip,
                SessionRecording.event_count > 0,
                SessionRecording.started_at >= window_start,
                SessionRecording.started_at <= window_end,
            )
            .order_by(SessionRecording.started_at.asc())
        )
        found = list(sib_result.scalars().unique().all())
        if found:
            by_id = {s.id: s for s in siblings}
            for s in found:
                by_id[s.id] = s
            siblings = sorted(
                by_id.values(),
                key=lambda r: r.started_at or datetime.min.replace(tzinfo=timezone.utc),
            )

    primary = max(
        siblings,
        key=lambda r: (
            int(r.event_count or 0),
            r.updated_at or r.started_at or datetime.min.replace(tzinfo=timezone.utc),
        ),
    )

    events: list[dict] = []
    for sib in siblings:
        for chunk in sorted(sib.chunks, key=lambda c: c.seq):
            try:
                parsed = json.loads(chunk.events_json)
                if isinstance(parsed, list):
                    events.extend(parsed)
            except json.JSONDecodeError:
                logger.warning("Corrupt recording chunk %s", chunk.id)

    events.sort(key=lambda e: (e.get("t") if isinstance(e, dict) else 0) or 0)

    return RecordingDetailResponse(
        id=str(primary.id),
        session_id=primary.session_id,
        page_path=primary.page_path,
        client_ip=primary.client_ip,
        client_country=primary.client_country,
        client_user_agent=primary.client_user_agent,
        event_count=len(events) or primary.event_count,
        status=primary.status,
        started_at=min(
            (s.started_at for s in siblings if s.started_at is not None),
            default=primary.started_at,
        ),
        ended_at=primary.ended_at,
        events=events,
    )
