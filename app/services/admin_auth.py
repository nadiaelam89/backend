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


def _sign_payload(payload_b64: str) -> str:
    if not settings.ADMIN_SESSION_SECRET:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin session secret is not configured",
        )
    secret = settings.ADMIN_SESSION_SECRET.encode("utf-8")
    return hmac.new(secret, payload_b64.encode("utf-8"), hashlib.sha256).hexdigest()


def create_admin_token(username: str) -> tuple[str, int]:
    payload = {
        "sub": username,
        "exp": int(time.time()) + _TOKEN_TTL_SECONDS,
    }
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode("utf-8")).decode("utf-8")
    signature = _sign_payload(payload_b64)
    return f"{payload_b64}.{signature}", _TOKEN_TTL_SECONDS


def verify_admin_token(token: str) -> str:
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

    username = payload.get("sub")
    if not isinstance(username, str) or not username:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")

    return username


def authenticate_admin(username: str, password: str) -> str:
    if not settings.ADMIN_USERNAME or not settings.ADMIN_PASSWORD:
        logger.error("Admin credentials are not configured")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Admin login is not configured",
        )

    valid_user = secrets.compare_digest(username, settings.ADMIN_USERNAME)
    valid_pass = secrets.compare_digest(password, settings.ADMIN_PASSWORD)
    if not (valid_user and valid_pass):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token, _ = create_admin_token(username)
    return token
