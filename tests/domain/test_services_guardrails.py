"""Cross-cutting guardrails: token handling, atomicity, and ID collisions."""

from __future__ import annotations

import logging
from collections.abc import Callable

import pytest

from citizen_agent.domain.enums import ErrorCode, Office, ServiceType
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.ids import citizen_token, make_id
from citizen_agent.domain.services import CitizenServices
from citizen_agent.domain.store import Store, insert_row
from tests.conftest import TEST_SECRET

TODAY = "2026-03-02"


def _call(services: CitizenServices, token: str, tool: str) -> object:
    if tool == "get_citizen_profile":
        return services.get_citizen_profile(token)
    if tool == "update_address":
        return services.update_address(token, "1 A ST", "CV-101")
    if tool == "check_eligibility":
        return services.check_eligibility(token, ServiceType.PARKING_PERMIT)
    if tool == "quote_fee":
        return services.quote_fee(token, ServiceType.PARKING_PERMIT)
    if tool == "pay_quote":
        return services.pay_quote(token, "QTE-00000000")
    if tool == "apply_parking_permit":
        return services.apply_parking_permit(token, "CVX1234", "PAY-00000000")
    if tool == "request_birth_certificate":
        return services.request_birth_certificate(token, 1, "PAY-00000000")
    if tool == "list_pickup_dates":
        return services.list_pickup_dates(token)
    if tool == "schedule_bulk_pickup":
        return services.schedule_bulk_pickup(token, "2026-03-03", 1)
    if tool == "book_appointment":
        return services.book_appointment(token, "SLOT-CITY_HALL-20260305-0900", "ID_CARD")
    if tool == "cancel_appointment":
        return services.cancel_appointment(token, "APT-00000000")
    if tool == "escalate_to_human":
        return services.escalate_to_human("Needs help.", token)
    if tool == "get_case_status":
        return services.get_case_status("APP-1A2B3C4D", token)
    raise AssertionError(f"Unknown tool {tool}")


CITIZEN_SCOPED_TOOLS = [
    "get_citizen_profile",
    "update_address",
    "check_eligibility",
    "quote_fee",
    "pay_quote",
    "apply_parking_permit",
    "request_birth_certificate",
    "list_pickup_dates",
    "schedule_bulk_pickup",
    "book_appointment",
    "cancel_appointment",
    "escalate_to_human",
    "get_case_status",
]


@pytest.mark.parametrize("tool", CITIZEN_SCOPED_TOOLS)
def test_invalid_token_is_rejected_everywhere(services: CitizenServices, tool: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        _call(services, "not-a-token", tool)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


@pytest.mark.parametrize("tool", CITIZEN_SCOPED_TOOLS)
def test_correctly_signed_unknown_citizen_is_rejected(services: CitizenServices, tool: str) -> None:
    ghost = citizen_token(TEST_SECRET, "CIT-9999")
    with pytest.raises(DomainError) as excinfo:
        _call(services, ghost, tool)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


def test_id_collision_raises_internal_error_and_rolls_back(
    services: CitizenServices,
    token_for: Callable[[str], str],
    store: Store,
    caplog: pytest.LogCaptureFixture,
) -> None:
    quote_id = make_id("QTE", "CIT-0001", ServiceType.PARKING_PERMIT.value, "1", "0")
    with store.write() as conn:
        insert_row(
            conn,
            "quotes",
            {
                "quote_id": quote_id,
                "citizen_id": "CIT-0002",
                "service_type": ServiceType.PARKING_PERMIT.value,
                "quantity": 1,
                "amount_cents": 9999,
                "created_on": TODAY,
            },
        )
    before = store.snapshot()
    with (
        caplog.at_level(logging.ERROR, logger="citizen_agent.store"),
        pytest.raises(DomainError) as excinfo,
    ):
        services.quote_fee(token_for("CIT-0001"), ServiceType.PARKING_PERMIT)
    assert excinfo.value.code is ErrorCode.INTERNAL_ERROR
    assert store.snapshot() == before

    error_records = [
        record
        for record in caplog.records
        if record.name == "citizen_agent.store" and record.levelno == logging.ERROR
    ]
    assert len(error_records) == 1
    assert "quotes" in error_records[0].getMessage()


def test_domain_error_mid_write_leaves_database_unchanged(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError):
        services.update_address(token_for("CIT-0001"), "1 A ST", "CV-999")
    with pytest.raises(DomainError):
        services.quote_fee(token_for("CIT-0006"), ServiceType.BIRTH_CERTIFICATE_COPY)
    with pytest.raises(DomainError):
        services.schedule_bulk_pickup(token_for("CIT-0001"), "2026-03-04", 2)
    with pytest.raises(DomainError):
        services.book_appointment(token_for("CIT-0002"), "SLOT-CITY_HALL-20260305-0900", "ID_CARD")
    assert store.snapshot() == before


def test_every_read_tool_is_side_effect_free(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    before = store.snapshot()
    services.get_citizen_profile(token)
    services.get_service_info(ServiceType.PARKING_PERMIT)
    services.check_eligibility(token, ServiceType.PARKING_PERMIT)
    services.list_pickup_dates(token)
    services.list_appointment_slots(Office.CITY_HALL, "2026-03-09")
    services.get_case_status("APP-1A2B3C4D", token_for("CIT-0010"))
    assert store.snapshot() == before
