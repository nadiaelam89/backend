from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.redirects import (
    RedirectCreateRequest,
    RedirectListResponse,
    RedirectLoginRequest,
    RedirectLoginResponse,
    RedirectResolveResponse,
    RedirectResponse,
    RedirectUpdateRequest,
)
from app.services.redirect_auth import TOKEN_TTL_SECONDS, authenticate_redirect_admin, verify_redirect_token
from app.services.redirect_service import (
    ALLOWED_REDIRECT_PATHS,
    create_redirect,
    delete_redirect,
    get_redirect_by_slug,
    list_redirects,
    update_redirect,
)

public_router = APIRouter(prefix="/api/redirects", tags=["Redirects"])
admin_router = APIRouter(prefix="/api/redirectnadia", tags=["Redirect Admin"])


async def require_redirect_admin(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing token")
    token = authorization.split(" ", 1)[1].strip()
    verify_redirect_token(token)


@public_router.get("/paths")
async def list_allowed_paths() -> dict[str, list[str]]:
    return {"paths": sorted(ALLOWED_REDIRECT_PATHS)}


@public_router.get("/{slug}", response_model=RedirectResolveResponse)
async def resolve_redirect(slug: str, db: AsyncSession = Depends(get_db)) -> RedirectResolveResponse:
    redirect = await get_redirect_by_slug(db, slug)
    if not redirect:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redirect not found")
    return RedirectResolveResponse(slug=redirect.slug, target_path=redirect.target_path)


@admin_router.post("/login", response_model=RedirectLoginResponse)
async def redirect_admin_login(payload: RedirectLoginRequest) -> RedirectLoginResponse:
    token = authenticate_redirect_admin(payload.password)
    return RedirectLoginResponse(access_token=token, expires_in=TOKEN_TTL_SECONDS)


@admin_router.get("/redirects", response_model=RedirectListResponse)
async def redirect_admin_list(
    _: Annotated[None, Depends(require_redirect_admin)],
    db: AsyncSession = Depends(get_db),
) -> RedirectListResponse:
    items = await list_redirects(db)
    return RedirectListResponse(
        items=[
            RedirectResponse(
                id=item.id,
                slug=item.slug,
                target_path=item.target_path,
                created_at=item.created_at,
                updated_at=item.updated_at,
            )
            for item in items
        ]
    )


@admin_router.post("/redirects", response_model=RedirectResponse, status_code=status.HTTP_201_CREATED)
async def redirect_admin_create(
    payload: RedirectCreateRequest,
    _: Annotated[None, Depends(require_redirect_admin)],
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    redirect = await create_redirect(db, payload.slug, payload.target_path)
    return RedirectResponse(
        id=redirect.id,
        slug=redirect.slug,
        target_path=redirect.target_path,
        created_at=redirect.created_at,
        updated_at=redirect.updated_at,
    )


@admin_router.put("/redirects/{redirect_id}", response_model=RedirectResponse)
async def redirect_admin_update(
    redirect_id: UUID,
    payload: RedirectUpdateRequest,
    _: Annotated[None, Depends(require_redirect_admin)],
    db: AsyncSession = Depends(get_db),
) -> RedirectResponse:
    redirect = await update_redirect(db, redirect_id, payload.target_path)
    return RedirectResponse(
        id=redirect.id,
        slug=redirect.slug,
        target_path=redirect.target_path,
        created_at=redirect.created_at,
        updated_at=redirect.updated_at,
    )


@admin_router.delete("/redirects/{redirect_id}", status_code=status.HTTP_204_NO_CONTENT)
async def redirect_admin_delete(
    redirect_id: UUID,
    _: Annotated[None, Depends(require_redirect_admin)],
    db: AsyncSession = Depends(get_db),
) -> None:
    await delete_redirect(db, redirect_id)
