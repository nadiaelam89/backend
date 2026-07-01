import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Body, Depends, Request, status
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.payments import (
    CheckoutPaymentRequest,
    RedirectPaymentResponse,
    StripeIntentResponse,
)
from app.services.stripe_service import create_stripe_payment_intent
from app.services.tabby_service import create_tabby_session
from app.services.tamara_service import create_tamara_checkout
from app.utils.request_meta import get_client_country, get_client_ip

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])
limiter = Limiter(key_func=get_remote_address)


@router.get("/status")
async def payments_status() -> dict:
    """Which payment providers are configured on the server."""
    from app.core.config import settings

    return {
        "ok": True,
        "stripe": bool(settings.STRIPE_SECRET_KEY),
        "tabby": bool(settings.TABBY_SECRET_KEY and settings.TABBY_MERCHANT_CODE),
        "tamara": bool(settings.TAMARA_API_TOKEN),
        "cod": True,
    }


@router.post("/stripe/create-intent", response_model=StripeIntentResponse)
@limiter.limit("15/minute")
async def stripe_create_intent(
    request: Request,
    data: Annotated[CheckoutPaymentRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> StripeIntentResponse:
    client_secret, order_id, total = await create_stripe_payment_intent(
        db,
        data,
        get_client_ip(request),
        get_client_country(request),
    )
    await db.commit()
    return StripeIntentResponse(
        client_secret=client_secret,
        order_id=order_id,
        total_sar=total,
    )


@router.post("/tabby/create-session", response_model=RedirectPaymentResponse)
@limiter.limit("15/minute")
async def tabby_create_session(
    request: Request,
    data: Annotated[CheckoutPaymentRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> RedirectPaymentResponse:
    payment_url, order_id, total = await create_tabby_session(
        db,
        data,
        get_client_ip(request),
        get_client_country(request),
    )
    await db.commit()
    return RedirectPaymentResponse(
        payment_url=payment_url,
        order_id=order_id,
        total_sar=total,
    )


@router.post("/tamara/create-checkout", response_model=RedirectPaymentResponse)
@limiter.limit("15/minute")
async def tamara_create_checkout(
    request: Request,
    data: Annotated[CheckoutPaymentRequest, Body()],
    db: AsyncSession = Depends(get_db),
) -> RedirectPaymentResponse:
    payment_url, order_id, total = await create_tamara_checkout(
        db,
        data,
        get_client_ip(request),
        get_client_country(request),
    )
    await db.commit()
    return RedirectPaymentResponse(
        payment_url=payment_url,
        order_id=order_id,
        total_sar=total,
    )
