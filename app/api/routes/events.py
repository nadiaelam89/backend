from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.events import TrackEventRequest, TrackEventResponse
from app.services.event_service import track_site_event
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
