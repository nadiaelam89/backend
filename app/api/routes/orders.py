import logging
from typing import Annotated

from fastapi import APIRouter, Body, Depends, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.orders import (
    CreateOrderRequest,
    CreateOrderResponse,
    EligibleUpsell,
    OrderSummaryResponse,
    UpsellRequest,
    UpsellResponse,
)
from app.services.order_service import add_upsell, create_order, get_order_summary
from app.services.pricing import UPSELL_PRICE, get_eligible_upsell

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["Orders"])
limiter = Limiter(key_func=get_remote_address)

UPSELL_EXPIRES_SECONDS = 15


def _get_client_ip(request: Request) -> str | None:
    cloudflare_ip = request.headers.get("CF-Connecting-IP")
    if cloudflare_ip:
        return cloudflare_ip.strip()

    true_client_ip = request.headers.get("True-Client-IP")
    if true_client_ip:
        return true_client_ip.strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip.strip()

    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None


@router.post("", response_model=CreateOrderResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("10/minute")
async def create_order_endpoint(
    request: Request,
    order_data: Annotated[CreateOrderRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> CreateOrderResponse:
    client_ip = _get_client_ip(request)

    order = await create_order(db, order_data, client_ip)

    # Determine upsell offer
    product_ids = [item.product_id for item in order.items]
    upsell_pid = get_eligible_upsell(product_ids)
    eligible_upsell: EligibleUpsell | None = None
    if upsell_pid:
        eligible_upsell = EligibleUpsell(
            product_id=upsell_pid,
            price_sar=UPSELL_PRICE,
            expires_in_seconds=UPSELL_EXPIRES_SECONDS,
        )

    return CreateOrderResponse(
        ok=True,
        order_id=order.order_number,
        event_id=order_data.event_id,
        total_sar=order.total_sar,
        eligible_upsell=eligible_upsell,
    )


@router.post("/{order_id}/upsell", response_model=UpsellResponse)
async def add_upsell_endpoint(
    order_id: str,
    upsell_data: Annotated[UpsellRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> UpsellResponse:
    order = await add_upsell(db, order_id, upsell_data)
    return UpsellResponse(ok=True, order_id=order.order_number, new_total_sar=order.total_sar)


@router.get("/{order_id}/summary", response_model=OrderSummaryResponse)
async def order_summary_endpoint(
    order_id: str,
    db: AsyncSession = Depends(get_db),
) -> OrderSummaryResponse:
    summary = await get_order_summary(db, order_id)
    return OrderSummaryResponse(**summary)
