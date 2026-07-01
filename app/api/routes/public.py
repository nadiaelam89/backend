from fastapi import APIRouter

from app.core.config import settings

router = APIRouter(prefix="/api/public", tags=["Public"])


@router.get("/pixels")
async def get_pixel_config() -> dict[str, str]:
    """Public pixel IDs for browser analytics (no secrets)."""
    return {
        "meta": settings.META_PIXEL_ID,
        "tiktok": settings.TIKTOK_PIXEL_CODE,
        "snap": settings.SNAP_PIXEL_ID,
    }
