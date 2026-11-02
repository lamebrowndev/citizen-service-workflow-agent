"""Deterministic ID and signed-token behavior."""

from __future__ import annotations

import re

import pytest

from citizen_agent.domain.enums import ErrorCode
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.ids import citizen_token, make_id, verify_token

SECRET = b"unit-test-secret"


def test_make_id_is_deterministic_and_formatted() -> None:
    first = make_id("QTE", "CIT-0001", "PARKING_PERMIT", "1")
    second = make_id("QTE", "CIT-0001", "PARKING_PERMIT", "1")
    assert first == second
    assert re.fullmatch(r"QTE-[0-9A-F]{8}", first)


def test_make_id_changes_with_key_parts() -> None:
    assert make_id("APP", "CIT-0001", "PARKING_PERMIT") != make_id(
        "APP", "CIT-0002", "PARKING_PERMIT"
    )


def test_token_round_trip() -> None:
    token = citizen_token(SECRET, "CIT-0001")
    assert token.startswith("CTK.CIT-0001.")
    signature = token.rsplit(".", 1)[1]
    assert re.fullmatch(r"[0-9A-F]{16}", signature)
    assert verify_token(SECRET, token) == "CIT-0001"


def test_token_rejects_tampered_signature() -> None:
    token = citizen_token(SECRET, "CIT-0001")
    tampered = token[:-1] + ("0" if token[-1] != "0" else "1")
    with pytest.raises(DomainError) as excinfo:
        verify_token(SECRET, tampered)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


def test_token_rejects_tampered_citizen() -> None:
    token = citizen_token(SECRET, "CIT-0001")
    tampered = token.replace("CIT-0001", "CIT-0002")
    with pytest.raises(DomainError) as excinfo:
        verify_token(SECRET, tampered)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


@pytest.mark.parametrize(
    "malformed",
    ["", "CTK.CIT-0001", "CTK..ABCD", "XXX.CIT-0001.ABCD", "CTK.CIT-0001.ABCD.EXTRA"],
)
def test_token_rejects_malformed_values(malformed: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        verify_token(SECRET, malformed)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN
