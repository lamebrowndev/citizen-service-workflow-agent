"""Deterministic identifiers and signed citizen tokens."""

from __future__ import annotations

import hashlib
import hmac

from .enums import ErrorCode
from .errors import DomainError

TOKEN_PREFIX = "CTK"


def make_id(prefix: str, *parts: str) -> str:
    """Construct a stable identifier from normalized key parts."""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:8].upper()
    return f"{prefix}-{digest}"


def _signature(secret: bytes, citizen_id: str) -> str:
    return hmac.new(secret, citizen_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16].upper()


def citizen_token(secret: bytes, citizen_id: str) -> str:
    """Mint a signed token for a citizen."""
    return f"{TOKEN_PREFIX}.{citizen_id}.{_signature(secret, citizen_id)}"


def verify_token(secret: bytes, token: str) -> str:
    """Return the citizen id from a well-formed, correctly signed token.

    Existence of the citizen is checked by the service layer, which owns the
    database connection.
    """
    if not isinstance(token, str):
        raise DomainError(ErrorCode.INVALID_TOKEN, "Citizen token is invalid.")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise DomainError(ErrorCode.INVALID_TOKEN, "Citizen token is invalid.")
    _, citizen_id, signature = parts
    if not citizen_id or not signature:
        raise DomainError(ErrorCode.INVALID_TOKEN, "Citizen token is invalid.")
    expected = _signature(secret, citizen_id)
    if not hmac.compare_digest(expected, signature):
        raise DomainError(ErrorCode.INVALID_TOKEN, "Citizen token is invalid.")
    return citizen_id
