from __future__ import annotations

import logging
import sys
from typing import Any


class MaskedPhoneFilter(logging.Filter):
    """Replace full phone numbers with masked versions (****XXXX) in log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = _mask_phone(record.msg)
        if record.args:
            if isinstance(record.args, dict):
                record.args = {k: _mask_phone(str(v)) if "phone" in k.lower() else v
                               for k, v in record.args.items()}
            elif isinstance(record.args, tuple):
                record.args = tuple(
                    _mask_phone(str(a)) if isinstance(a, str) else a for a in record.args
                )
        return True


def _mask_phone(text: str) -> str:
    """Mask Saudi phone numbers in a string, keeping only the last 4 digits."""
    import re
    # Matches +966XXXXXXXX or 05XXXXXXXX or 9665XXXXXXXX patterns
    pattern = r"(\+?966|0)5\d{8}"

    def _replace(m: re.Match[str]) -> str:
        full = m.group(0)
        return "****" + full[-4:]

    return re.sub(pattern, _replace, text)


def setup_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(level)

    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    handler.setFormatter(formatter)
    handler.addFilter(MaskedPhoneFilter())

    root.handlers.clear()
    root.addHandler(handler)

    # Quieten noisy libraries
    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
