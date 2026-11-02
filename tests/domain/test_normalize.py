"""Table-driven tests for the pure normalizers."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest

from citizen_agent.domain.enums import ErrorCode
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.normalize import (
    display_name,
    normalize_address,
    normalize_date,
    normalize_id,
    normalize_name,
    normalize_plate,
    normalize_postal_code,
    normalize_text,
)

Normalizer = Callable[[str], str]

VALID_CASES: list[tuple[Normalizer, str, str]] = [
    (normalize_name, "  Am\u00e9lie   O'Connor ", "am\u00e9lie o'connor"),
    (normalize_name, "JOS\u00c9\tDE   LA CRUZ", "jos\u00e9 de la cruz"),
    (normalize_name, "Sofia Marchetti", "sofia marchetti"),
    (normalize_text, "  Hello   WORLD ", "hello world"),
    (normalize_text, "\tCAF\u00c9\nMen\u00fc ", "caf\u00e9 men\u00fc"),
    (normalize_text, "   ", ""),
    (display_name, "  Sofia   Marchetti ", "Sofia Marchetti"),
    (normalize_address, "12 maple street.", "12 MAPLE ST"),
    (normalize_address, "  45  north avenue, apt 3 ", "45 NORTH AVE APT 3"),
    (normalize_address, "7 elm blvd", "7 ELM BLVD"),
    (normalize_address, "9 STREETVIEW road", "9 STREETVIEW RD"),
    (normalize_address, "3 oak drive", "3 OAK DR"),
    (normalize_address, "4 pine lane", "4 PINE LN"),
    (normalize_address, "5 cedar court", "5 CEDAR CT"),
    (normalize_address, "6 birch place", "6 BIRCH PL"),
    (normalize_plate, "ab 12-cd", "AB12CD"),
    (normalize_plate, " cvx-123 ", "CVX123"),
    (normalize_postal_code, " cv-101 ", "CV-101"),
    (normalize_date, " 2024-02-29 ", "2024-02-29"),
    (normalize_date, "2026-03-02", "2026-03-02"),
    (normalize_id, " app-1a2b3c4d ", "APP-1A2B3C4D"),
]

INVALID_CASES: list[tuple[Normalizer, str]] = [
    (normalize_name, ""),
    (normalize_name, "   "),
    (display_name, " "),
    (normalize_address, ""),
    (normalize_address, "."),
    (normalize_address, " , . "),
    (normalize_plate, "A"),
    (normalize_plate, "ABCDEFGHI"),
    (normalize_plate, "AB_CD"),
    (normalize_plate, ""),
    (normalize_postal_code, "CV-10"),
    (normalize_postal_code, "CV-1000"),
    (normalize_postal_code, "XX-101"),
    (normalize_postal_code, "CV101"),
    (normalize_date, "2023-02-29"),
    (normalize_date, "2026-13-01"),
    (normalize_date, "2026-3-2"),
    (normalize_date, "not-a-date"),
    (normalize_id, ""),
    (normalize_id, "   "),
]


@pytest.mark.parametrize(("normalizer", "raw", "expected"), VALID_CASES)
def test_normalizer_accepts_and_canonicalizes(
    normalizer: Normalizer, raw: str, expected: str
) -> None:
    assert normalizer(raw) == expected


@pytest.mark.parametrize(("normalizer", "raw"), INVALID_CASES)
def test_normalizer_rejects_bad_input(normalizer: Normalizer, raw: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        normalizer(raw)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


@pytest.mark.parametrize(
    "normalizer", [normalize_name, normalize_address, normalize_plate, normalize_text]
)
def test_normalizer_rejects_non_text(normalizer: Normalizer) -> None:
    untyped: Any = normalizer
    with pytest.raises(DomainError) as excinfo:
        untyped(123)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
