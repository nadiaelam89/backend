from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

_MAX_LOG_CHARS = 4000


def _truncate(value: str) -> str:
    if len(value) <= _MAX_LOG_CHARS:
        return value
    return f"{value[:_MAX_LOG_CHARS]}…(truncated)"


def log_capi_result(
    platform: str,
    *,
    order_number: str,
    event_id: str,
    event_name: str,
    request_summary: dict[str, Any],
    result: dict[str, Any],
) -> None:
    """Log CAPI request summary and full platform response at INFO level."""
    status = result.get("status")
    success = result.get("success")
    body = result.get("body")
    body_text = _truncate(json.dumps(body, ensure_ascii=False)) if body else "null"
    request_text = _truncate(json.dumps(request_summary, ensure_ascii=False))

    logger.info(
        "CAPI [%s] %s order=%s event_id=%s status=%s success=%s",
        platform,
        event_name,
        order_number,
        event_id,
        status,
        success,
    )
    logger.info("CAPI [%s] order=%s request=%s", platform, order_number, request_text)
    logger.info("CAPI [%s] order=%s response=%s", platform, order_number, body_text)

    if not success:
        logger.warning(
            "CAPI [%s] order=%s event_id=%s failed status=%s",
            platform,
            order_number,
            event_id,
            status,
        )
