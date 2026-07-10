from __future__ import annotations

import re
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.services.redirect_service import ALLOWED_REDIRECT_PATHS

_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}[a-z0-9]$|^[a-z0-9]$")


class RedirectLoginRequest(BaseModel):
    password: str = Field(min_length=1, max_length=200)


class RedirectLoginResponse(BaseModel):
    access_token: str
    expires_in: int


def _normalize_comment(value: str | None) -> str | None:
    if value is None:
        return None
    trimmed = value.strip()
    return trimmed or None


class RedirectCreateRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=64)
    target_path: str = Field(min_length=1, max_length=500)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        slug = value.strip().lower()
        if not _SLUG_RE.match(slug):
            raise ValueError("Slug must be lowercase letters, numbers, and hyphens only")
        return slug

    @field_validator("target_path")
    @classmethod
    def validate_target_path(cls, value: str) -> str:
        path = value.strip()
        if path not in ALLOWED_REDIRECT_PATHS:
            raise ValueError("Target path is not allowed")
        return path

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        return _normalize_comment(value)


class RedirectUpdateRequest(BaseModel):
    target_path: str = Field(min_length=1, max_length=500)
    comment: str | None = Field(default=None, max_length=500)

    @field_validator("target_path")
    @classmethod
    def validate_target_path(cls, value: str) -> str:
        path = value.strip()
        if path not in ALLOWED_REDIRECT_PATHS:
            raise ValueError("Target path is not allowed")
        return path

    @field_validator("comment")
    @classmethod
    def validate_comment(cls, value: str | None) -> str | None:
        return _normalize_comment(value)


class RedirectResponse(BaseModel):
    id: UUID
    slug: str
    target_path: str
    comment: str | None = None
    created_at: datetime
    updated_at: datetime


class RedirectListResponse(BaseModel):
    items: list[RedirectResponse]


class RedirectResolveResponse(BaseModel):
    slug: str
    target_path: str
