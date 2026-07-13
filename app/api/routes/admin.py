from __future__ import annotations

from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.admin import (
    AdminLoginRequest,
    AdminLoginResponse,
    AdminMetricsResponse,
    AdminOrderDetailResponse,
    AdminOrdersListResponse,
    AdminPurgeDataResponse,
)
from app.services.admin_auth import TOKEN_TTL_SECONDS, authenticate_admin, verify_admin_token
from app.services.admin_service import (
    get_admin_metrics,
    get_admin_order_detail,
    list_admin_orders,
    purge_all_data,
)

router = APIRouter(prefix="/api/admin", tags=["Admin"])


async def require_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> str:
    if not authorization or not authorization.lower().startswith("bearer "):
        from fastapi import HTTPException, status

        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    return verify_admin_token(token)


@router.post("/login", response_model=AdminLoginResponse)
async def admin_login(payload: AdminLoginRequest) -> AdminLoginResponse:
    token = authenticate_admin(payload.username, payload.password)
    return AdminLoginResponse(access_token=token, expires_in=TOKEN_TTL_SECONDS)


@router.get("/metrics", response_model=AdminMetricsResponse)
async def admin_metrics(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> AdminMetricsResponse:
    return await get_admin_metrics(db, date_from, date_to)


@router.get("/orders", response_model=AdminOrdersListResponse)
async def admin_orders(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = Query(default=None),
    search: str | None = Query(default=None),
    date_from: datetime | None = Query(default=None),
    date_to: datetime | None = Query(default=None),
) -> AdminOrdersListResponse:
    return await list_admin_orders(db, page, page_size, status, search, date_from, date_to)


@router.post("/purge-data", response_model=AdminPurgeDataResponse)
async def admin_purge_data(
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> AdminPurgeDataResponse:
    deleted = await purge_all_data(db)
    return AdminPurgeDataResponse(deleted=deleted)


@router.get("/orders/{order_id}", response_model=AdminOrderDetailResponse)
async def admin_order_detail(
    order_id: str,
    _: Annotated[str, Depends(require_admin)],
    db: AsyncSession = Depends(get_db),
) -> AdminOrderDetailResponse:
    return await get_admin_order_detail(db, order_id)
