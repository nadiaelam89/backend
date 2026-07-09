from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import secrets
import time

from fastapi import HTTPException, status

from app.core.config import settings

logger = logging.getLogger(__name__)

_TOKEN_TTL_SECONDS = 60 * 60 * 12  # 12 hours
TOKEN_TTL_SECONDS = _TOKEN_TTL_SECONDS
_REDIRECT_AUDIENCE = "redirectnadia"


def _session_secret() -> bytes:
    secret = settings.REDIRECT_SESSION_SECRET or settings.ADMIN_SESSION_SECRET
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redirect session secret is not configured",
        )
    return secret.encode("utf-8")


def _sign_payload(payload_b64: str) -> str:
    return hmac.new(_session_secret(), payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()


def create_redirect_token() -> tuple[str, int]:
    payload = {
        "sub": "redirectnadia",
        "aud": _REDIRECT_AUDIENCE,
        "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    signature = _sign_payload(payload_b64)
    return f"{payload_b64}.{signature}", _TOKEN_TTL_SECONDS


def verify_redirect_token(token: str) -> None:
    if not token or "." not in token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    payload_b64, signature = token.rsplit(".", 1)
    expected = _sign_payload(payload_b64)
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    try:
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("utf-8")).decode("utf-8"))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc

    exp = payload.get("exp")
    if not isinstance(exp, int) or exp < int(time.time()):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")

    if payload.get("aud") != _REDIRECT_AUDIENCE:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def authenticate_redirect_admin(password: str) -> str:
    if not settings.REDIRECT_ADMIN_PASSWORD:
        logger.error("REDIRECT_ADMIN_PASSWORD is not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Redirect admin login is not configured",
        )

    if not secrets.compare_digest(password, settings.REDIRECT_ADMIN_PASSWORD):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token, _ = create_redirect_token()
    return token
