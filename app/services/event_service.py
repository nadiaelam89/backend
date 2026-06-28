from __future__ import annotations

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import SiteEvent
from app.schemas.events import TrackEventRequest
from app.services.visitor_fraud import check_visitor_ip_fraud


async def track_site_event(
    db: AsyncSession,
    payload: TrackEventRequest,
    client_ip: str | None,
    client_country: str | None,
) -> SiteEvent:
    decision = await check_visitor_ip_fraud(
        client_ip=client_ip,
        client_country=client_country,
        user_agent=payload.client_user_agent,
    )

    event = SiteEvent(
        id=uuid.uuid4(),
        session_id=payload.session_id,
        event_name=payload.event_name,
        page_path=payload.page_path,
        product_id=payload.product_id,
        value_sar=payload.value_sar,
        utm=payload.utm,
        client_ip=client_ip,
        client_country=decision.country_code or client_country,
        client_user_agent=payload.client_user_agent,
        is_valid_traffic=decision.allowed,
        fraud_reason=None if decision.allowed else decision.reason,
        risk_score=decision.risk_score,
    )
    db.add(event)
    await db.flush()
    return event
