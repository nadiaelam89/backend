from __future__ import annotations

import logging

import stripe
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.schemas.payments import CheckoutPaymentRequest
from app.services.checkout_order import create_checkout_order_from_payment_request

logger = logging.getLogger(__name__)


def _require_stripe() -> None:
    if not settings.STRIPE_SECRET_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Stripe is not configured",
        )


async def create_stripe_payment_intent(
    db: AsyncSession,
    data: CheckoutPaymentRequest,
    client_ip: str | None,
    client_country: str | None,
) -> tuple[str, str, int]:
    _require_stripe()
    stripe.api_key = settings.STRIPE_SECRET_KEY

    order = await create_checkout_order_from_payment_request(
        db,
        data,
        payment_method="stripe",
        payment_status="pending",
        client_ip=client_ip,
        client_country=client_country,
    )

    try:
        intent = stripe.PaymentIntent.create(
            amount=order.total_sar * 100,
            currency="sar",
            automatic_payment_methods={"enabled": True},
            metadata={"order_id": order.order_number},
            idempotency_key=str(order.id),
        )
    except stripe.StripeError as exc:
        logger.error("Stripe PaymentIntent failed for %s: %s", order.order_number, exc)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="تعذر إنشاء جلسة الدفع",
        ) from exc

    order.stripe_payment_intent_id = intent.id
    await db.flush()

    client_secret = intent.client_secret
    if not client_secret:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Stripe client secret missing",
        )

    return client_secret, order.order_number, order.total_sar


def construct_stripe_event(payload: bytes, sig_header: str | None):
    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhook not configured")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing stripe-signature")
    stripe.api_key = settings.STRIPE_SECRET_KEY
    return stripe.Webhook.construct_event(
        payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
    )
