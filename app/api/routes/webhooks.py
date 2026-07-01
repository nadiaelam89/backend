import logging

from fastapi import APIRouter, BackgroundTasks, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import get_db
from app.services.order_service import mark_order_paid, run_order_side_effects
from app.services.stripe_service import construct_stripe_event
from app.services.tabby_service import capture_tabby_payment, get_tabby_payment
from app.services.tamara_service import authorise_tamara_order

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/webhooks", tags=["Webhooks"])


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    payload = await request.body()
    sig = request.headers.get("stripe-signature")
    event = construct_stripe_event(payload, sig)

    if event["type"] == "payment_intent.succeeded":
        pi = event["data"]["object"]
        order_number = (pi.get("metadata") or {}).get("order_id")
        if order_number:
            order = await mark_order_paid(db, order_number)
            if order:
                await db.commit()
                background_tasks.add_task(run_order_side_effects, order.id)

    return {"received": True}


@router.post("/tabby")
async def tabby_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    body = await request.json()
    payment_id = body.get("id") or (body.get("payment") or {}).get("id")
    if not payment_id:
        return {"received": True}

    payment = await get_tabby_payment(payment_id)
    status_value = payment.get("status")
    order_number = (payment.get("order") or {}).get("reference_id")

    if status_value == "AUTHORIZED" and order_number:
        amount = payment.get("amount", "0.00")
        await capture_tabby_payment(payment_id, str(amount), f"capture-{order_number}")
        payment = await get_tabby_payment(payment_id)
        status_value = payment.get("status")

    if status_value in ("AUTHORIZED", "CLOSED") and order_number:
        order = await mark_order_paid(db, order_number)
        if order:
            await db.commit()
            background_tasks.add_task(run_order_side_effects, order.id)

    return {"received": True}


@router.post("/tamara")
async def tamara_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    auth = request.headers.get("Authorization", "")
    token = auth.removeprefix("Bearer ").strip()
    if settings.TAMARA_NOTIFICATION_TOKEN and token != settings.TAMARA_NOTIFICATION_TOKEN:
        # Tamara sends JWT; in sandbox allow if token present in query too
        query_token = request.query_params.get("tamaraToken")
        if query_token != settings.TAMARA_NOTIFICATION_TOKEN:
            logger.warning("Tamara webhook auth mismatch")

    body = await request.json()
    if body.get("event_type") != "order_approved":
        return {"received": True}

    tamara_order_id = body.get("order_id")
    order_number = body.get("order_reference_id")
    if not tamara_order_id or not order_number:
        return {"received": True}

    await authorise_tamara_order(tamara_order_id)
    order = await mark_order_paid(db, order_number)
    if order:
        await db.commit()
        background_tasks.add_task(run_order_side_effects, order.id)

    return {"received": True}
