from __future__ import annotations

import hashlib


def sha256_lower(value: str) -> str:
    """Return the SHA-256 hex digest of the lowercased, stripped value."""
    return hashlib.sha256(value.strip().lower().encode("utf-8")).hexdigest()
