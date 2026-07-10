from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AdRedirect

ALLOWED_REDIRECT_PATHS: frozenset[str] = frozenset(
    {
        "/",
        "/lp",
        "/products",
        "/products/magnesium-glycinate-gummies",
        "/products/saffron-magnesium-gummies",
        "/products/organic-mushroom-coffee",
        "/about",
        "/contact",
        "/policies/shipping",
        "/policies/returns",
        "/policies/privacy",
        "/policies/terms",
    }
)

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


def normalize_slug(slug: str) -> str:
    normalized = slug.strip().lower()
    if not _SLUG_RE.match(normalized):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid slug format",
        )
    return normalized


def validate_target_path(target_path: str) -> str:
    path = target_path.strip()
    if path not in ALLOWED_REDIRECT_PATHS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Target path is not allowed",
        )
    return path


async def list_redirects(db: AsyncSession) -> list[AdRedirect]:
    result = await db.execute(select(AdRedirect).order_by(AdRedirect.created_at.desc()))
    return list(result.scalars().all())


async def get_redirect_by_slug(db: AsyncSession, slug: str) -> AdRedirect | None:
    normalized = normalize_slug(slug)
    result = await db.execute(select(AdRedirect).where(AdRedirect.slug == normalized))
    return result.scalar_one_or_none()


async def create_redirect(
    db: AsyncSession, slug: str, target_path: str, comment: str | None = None
) -> AdRedirect:
    normalized_slug = normalize_slug(slug)
    validated_path = validate_target_path(target_path)

    existing = await get_redirect_by_slug(db, normalized_slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Slug already exists",
        )

    redirect = AdRedirect(
        id=uuid.uuid4(),
        slug=normalized_slug,
        target_path=validated_path,
        comment=comment,
    )
    db.add(redirect)
    await db.commit()
    await db.refresh(redirect)
    return redirect


async def update_redirect(
    db: AsyncSession, redirect_id: uuid.UUID, target_path: str, comment: str | None = None
) -> AdRedirect:
    validated_path = validate_target_path(target_path)
    result = await db.execute(select(AdRedirect).where(AdRedirect.id == redirect_id))
    redirect = result.scalar_one_or_none()
    if not redirect:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redirect not found")

    redirect.target_path = validated_path
    redirect.comment = comment
    redirect.updated_at = datetime.now(tz=timezone.utc)
    await db.commit()
    await db.refresh(redirect)
    return redirect


async def delete_redirect(db: AsyncSession, redirect_id: uuid.UUID) -> None:
    result = await db.execute(select(AdRedirect).where(AdRedirect.id == redirect_id))
    redirect = result.scalar_one_or_none()
    if not redirect:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Redirect not found")

    await db.delete(redirect)
    await db.commit()
