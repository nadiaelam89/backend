from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class PhoneResult:
    is_valid: bool
    phone_local: str = ""
    phone_e164: str = ""
    phone_digits: str = ""
    error: str = ""


def normalize_saudi_phone(raw: str) -> PhoneResult:
    """Normalize a Saudi mobile phone number to multiple formats.

    Accepted input formats:
    - 05xxxxxxxx   (local with leading zero)
    - 5xxxxxxxx    (local without leading zero)
    - 9665xxxxxxxx (international without plus)
    - +9665xxxxxxxx (E.164)
    - Spaces, dashes, and parentheses are stripped.

    Returns PhoneResult with is_valid flag and formatted variants.
    """
    if not raw or not isinstance(raw, str):
        return PhoneResult(is_valid=False, error="Phone number is required")

    # Strip whitespace, dashes, dots, parentheses
    cleaned = re.sub(r"[\s\-\.\(\)]+", "", raw.strip())

    # Strip a leading +
    if cleaned.startswith("+"):
        cleaned = cleaned[1:]

    # Now cleaned is digits only (possibly with leading 966 or 0)
    if not cleaned.isdigit():
        return PhoneResult(is_valid=False, error="Phone number must contain only digits")

    # Normalise to 9-digit local suffix (5XXXXXXXX)
    if cleaned.startswith("9665"):
        suffix = cleaned[3:]  # remove 966 → 5XXXXXXXX (9 digits)
    elif cleaned.startswith("05"):
        suffix = cleaned[1:]  # remove 0 → 5XXXXXXXX (9 digits)
    elif cleaned.startswith("5"):
        suffix = cleaned
    else:
        return PhoneResult(
            is_valid=False,
            error="Not a valid Saudi mobile number (must start with 05, 5, 966, or +966)",
        )

    # Saudi mobiles: 5 followed by 8 digits (total 9 digits)
    if not re.fullmatch(r"5[0-9]{8}", suffix):
        return PhoneResult(
            is_valid=False,
            error="Invalid Saudi mobile number format (expected 05XXXXXXXX)",
        )

    phone_local = "0" + suffix          # 05XXXXXXXX
    phone_e164 = "+966" + suffix         # +9665XXXXXXXX
    phone_digits = "966" + suffix        # 9665XXXXXXXX (no +)

    return PhoneResult(
        is_valid=True,
        phone_local=phone_local,
        phone_e164=phone_e164,
        phone_digits=phone_digits,
    )
