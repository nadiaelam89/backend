import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/payments", tags=["Payments"])


@router.get("/status")
async def payments_status() -> dict:
    """Payment providers available on the server."""
    return {
        "ok": True,
        "cod": True,
    }
