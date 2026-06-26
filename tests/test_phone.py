"""Tests for Saudi phone normalization."""
from __future__ import annotations

import pytest

from app.services.phone import normalize_saudi_phone


# ---------------------------------------------------------------------------
# Valid formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,expected_local,expected_e164,expected_digits",
    [
        # Local with leading zero
        ("0512345678", "0512345678", "+966512345678", "966512345678"),
        # Local without leading zero
        ("512345678", "0512345678", "+966512345678", "966512345678"),
        # International without plus
        ("966512345678", "0512345678", "+966512345678", "966512345678"),
        # E.164 with plus
        ("+966512345678", "0512345678", "+966512345678", "966512345678"),
        # With spaces
        ("051 234 5678", "0512345678", "+966512345678", "966512345678"),
        # With dashes
        ("051-234-5678", "0512345678", "+966512345678", "966512345678"),
        # With parens and spaces
        ("(051) 234 5678", "0512345678", "+966512345678", "966512345678"),
        # Different Saudi mobile operator prefixes
        ("0551234567", "0551234567", "+966551234567", "966551234567"),
        ("0561234567", "0561234567", "+966561234567", "966561234567"),
        ("0571234567", "0571234567", "+966571234567", "966571234567"),
        # International format different operator
        ("+966551234567", "0551234567", "+966551234567", "966551234567"),
        ("966551234567", "0551234567", "+966551234567", "966551234567"),
    ],
)
def test_valid_phones(
    raw: str, expected_local: str, expected_e164: str, expected_digits: str
) -> None:
    result = normalize_saudi_phone(raw)
    assert result.is_valid is True, f"Expected valid for {raw!r}, got error: {result.error}"
    assert result.phone_local == expected_local
    assert result.phone_e164 == expected_e164
    assert result.phone_digits == expected_digits


# ---------------------------------------------------------------------------
# Invalid formats
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw,description",
    [
        ("", "empty string"),
        ("   ", "whitespace only"),
        ("123456789", "9 digits not starting with 5"),
        ("04123456789", "landline-style 04 prefix"),
        ("0512345", "too short"),
        ("051234567890", "too long"),
        ("abcdefghij", "letters only"),
        ("05abc12345", "mixed letters and digits"),
        ("+1234567890", "non-Saudi country code"),
        ("+44712345678", "UK number"),
        ("0712345678", "starts with 07, not valid Saudi mobile"),
        ("0612345678", "starts with 06, not valid Saudi mobile"),
    ],
)
def test_invalid_phones(raw: str, description: str) -> None:
    result = normalize_saudi_phone(raw)
    assert result.is_valid is False, f"Expected INVALID for {raw!r} ({description})"
    assert result.error != ""


def test_none_input() -> None:
    result = normalize_saudi_phone(None)  # type: ignore[arg-type]
    assert result.is_valid is False


def test_hash_consistency() -> None:
    """The same number in different formats should produce the same hash."""
    from app.services.hashing import sha256_lower

    formats = ["0512345678", "512345678", "966512345678", "+966512345678"]
    hashes = set()
    for fmt in formats:
        r = normalize_saudi_phone(fmt)
        assert r.is_valid, f"Expected valid: {fmt}"
        hashes.add(sha256_lower(r.phone_digits))

    assert len(hashes) == 1, "All formats of the same number must produce the same hash"
