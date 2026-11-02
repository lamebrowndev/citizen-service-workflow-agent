"""Pure normalization helpers used by tools, the seeder, and evaluators.

Every helper raises ``DomainError(INVALID_ARGUMENT)`` for malformed input and
returns the canonical stored form.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date

from .enums import ErrorCode
from .errors import DomainError

_WHITESPACE = re.compile(r"\s+")
_STREET_TOKENS = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "ROAD": "RD",
    "BOULEVARD": "BLVD",
    "DRIVE": "DR",
    "LANE": "LN",
    "COURT": "CT",
    "PLACE": "PL",
}
_POSTAL_CODE = re.compile(r"^CV-\d{3}$")
_LICENSE_PLATE = re.compile(r"^[A-Z0-9]{2,8}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_text(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise DomainError(ErrorCode.INVALID_ARGUMENT, f"{field} must be text.")
    return value


def normalize_name(value: str) -> str:
    """NFKC, trim, collapse whitespace, and casefold a personal name."""
    text = _require_text(value, "Name")
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).strip())
    normalized = normalized.casefold()
    if not normalized:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Name must not be empty.")
    return normalized


def display_name(value: str) -> str:
    """NFKC, trim, and collapse whitespace while preserving display casing."""
    text = _require_text(value, "Name")
    normalized = _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).strip())
    if not normalized:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Name must not be empty.")
    return normalized


def normalize_text(value: str) -> str:
    """NFKC, trim, collapse internal whitespace, and casefold arbitrary text."""
    text = _require_text(value, "Text")
    return _WHITESPACE.sub(" ", unicodedata.normalize("NFKC", text).strip()).casefold()


def normalize_address(value: str) -> str:
    """Canonical uppercase street address with standard token abbreviations."""
    text = _require_text(value, "Street address")
    cleaned = unicodedata.normalize("NFKC", text).upper()
    cleaned = cleaned.replace(".", "").replace(",", "")
    tokens = _WHITESPACE.sub(" ", cleaned).strip().split(" ")
    if not tokens or tokens == [""]:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Street address must not be empty.")
    expanded = [_STREET_TOKENS.get(token, token) for token in tokens]
    normalized = " ".join(expanded)
    if not normalized:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Street address must not be empty.")
    return normalized


def normalize_plate(value: str) -> str:
    """Uppercase plate with spaces and hyphens removed; 2-8 alphanumerics."""
    text = _require_text(value, "License plate")
    normalized = _WHITESPACE.sub("", text.upper()).replace("-", "")
    if not _LICENSE_PLATE.fullmatch(normalized):
        raise DomainError(
            ErrorCode.INVALID_ARGUMENT,
            "License plate must contain 2-8 letters or digits.",
        )
    return normalized


def normalize_postal_code(value: str) -> str:
    """Canonical Civitas postal code (CV-###)."""
    text = _require_text(value, "Postal code")
    normalized = text.strip().upper()
    if not _POSTAL_CODE.fullmatch(normalized):
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Postal code must match CV-###.")
    return normalized


def normalize_date(value: str) -> str:
    """Validate a real calendar date in YYYY-MM-DD form."""
    text = _require_text(value, "Date")
    normalized = text.strip()
    if not _DATE.fullmatch(normalized):
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Date must use YYYY-MM-DD.")
    try:
        date.fromisoformat(normalized)
    except ValueError as exc:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Date is not a real calendar date.") from exc
    return normalized


def normalize_id(value: str) -> str:
    """Canonical record identifier: trimmed and uppercase."""
    text = _require_text(value, "Record ID")
    normalized = text.strip().upper()
    if not normalized:
        raise DomainError(ErrorCode.INVALID_ARGUMENT, "Record ID must not be empty.")
    return normalized
