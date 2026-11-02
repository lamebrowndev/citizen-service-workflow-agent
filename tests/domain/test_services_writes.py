"""Write tools for addresses, quotes, payments, and applications."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from citizen_agent.domain.enums import ApplicationStatus, ErrorCode, ServiceType
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.ids import make_id
from citizen_agent.domain.models import Fixture
from citizen_agent.domain.services import CitizenServices
from citizen_agent.domain.store import Store, insert_row
from tests.conftest import TEST_SECRET

TODAY = "2026-03-02"


def _force_quote_and_payment(
    store: Store, citizen_id: str, service_type: ServiceType, quantity: int, amount: int
) -> str:
    quote_id = make_id("QTE", citizen_id, service_type.value, str(quantity), "0")
    payment_id = make_id("PAY", quote_id)
    with store.write() as conn:
        insert_row(
            conn,
            "quotes",
            {
                "quote_id": quote_id,
                "citizen_id": citizen_id,
                "service_type": service_type.value,
                "quantity": quantity,
                "amount_cents": amount,
                "created_on": TODAY,
            },
        )
        insert_row(
            conn,
            "payments",
            {
                "payment_id": payment_id,
                "quote_id": quote_id,
                "citizen_id": citizen_id,
                "service_type": service_type.value,
                "amount_cents": amount,
                "paid_on": TODAY,
            },
        )
    return payment_id


def _force_active_permit(store: Store, citizen_id: str) -> None:
    with store.write() as conn:
        insert_row(
            conn,
            "applications",
            {
                "application_id": "APP-DEADBEEF",
                "citizen_id": citizen_id,
                "service_type": ServiceType.PARKING_PERMIT.value,
                "status": ApplicationStatus.IN_REVIEW.value,
                "payment_id": None,
                "details_json": "{}",
                "submitted_on": TODAY,
                "updated_on": TODAY,
            },
        )


# -- update_address -------------------------------------------------------


def test_update_address_normalizes_and_reports_change(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    token = token_for("CIT-0001")
    result = services.update_address(token, "99 new street.", "cv-102")
    assert result.street_address == "99 NEW ST"
    assert result.postal_code == "CV-102"
    assert result.zone.value == "NORTH"
    assert result.permit_area is False
    assert result.changed is True

    profile = services.get_citizen_profile(token)
    assert profile.street_address == "99 NEW ST"
    assert profile.postal_code == "CV-102"


def test_update_address_identical_input_is_unchanged(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    before = store.snapshot()
    result = services.update_address(token, "12 Maple Street", "cv-101")
    assert result.changed is False
    assert store.snapshot() == before


def test_update_address_unknown_postal_code(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.update_address(token_for("CIT-0001"), "1 A ST", "CV-999")
    assert excinfo.value.code is ErrorCode.INVALID_POSTAL_CODE
    assert store.snapshot() == before


@pytest.mark.parametrize("token", ["nope", "CTK.CIT-9999.0000000000000000"])
def test_update_address_rejects_bad_tokens(services: CitizenServices, token: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.update_address(token, "1 A ST", "CV-101")
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


# -- quote_fee ------------------------------------------------------------


def test_quote_fee_exact_senior_and_standard_parking_prices(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    senior = services.quote_fee(token_for("CIT-0001"), ServiceType.PARKING_PERMIT)
    standard = services.quote_fee(token_for("CIT-0002"), ServiceType.PARKING_PERMIT)
    assert senior.amount_cents == 3000
    assert standard.amount_cents == 6000
    assert senior.currency == "USD"
    assert senior.quantity == 1
    assert senior.created is True


def test_quote_fee_birth_copies_price(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    quote = services.quote_fee(token_for("CIT-0001"), ServiceType.BIRTH_CERTIFICATE_COPY, 3)
    assert quote.amount_cents == 4500
    assert quote.quantity == 3


@pytest.mark.parametrize(
    "service_type",
    [
        ServiceType.BULK_WASTE_PICKUP,
        ServiceType.ADDRESS_CHANGE,
        ServiceType.STREET_ISSUE_REPORT,
        ServiceType.OFFICE_APPOINTMENT,
    ],
)
def test_quote_fee_rejects_free_services(
    services: CitizenServices, token_for: Callable[[str], str], service_type: ServiceType
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.quote_fee(token_for("CIT-0001"), service_type)
    assert excinfo.value.code is ErrorCode.NO_FEE_REQUIRED


@pytest.mark.parametrize(
    ("service_type", "quantity"),
    [
        (ServiceType.PARKING_PERMIT, 2),
        (ServiceType.BIRTH_CERTIFICATE_COPY, 0),
        (ServiceType.BIRTH_CERTIFICATE_COPY, 6),
    ],
)
def test_quote_fee_rejects_bad_quantities(
    services: CitizenServices,
    token_for: Callable[[str], str],
    service_type: ServiceType,
    quantity: int,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.quote_fee(token_for("CIT-0001"), service_type, quantity)
    assert excinfo.value.code is ErrorCode.INVALID_QUANTITY


def test_quote_fee_is_idempotent(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    first = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    before = store.snapshot()
    second = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    assert second.quote_id == first.quote_id
    assert second.created is False
    assert store.snapshot() == before


def test_quote_and_payment_retries_are_stable(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    first_quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    assert first_quote.created is True

    second_quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    assert second_quote.quote_id == first_quote.quote_id
    assert second_quote.created is False

    first_payment = services.pay_quote(token, first_quote.quote_id)
    assert first_payment.created is True

    before = store.snapshot()
    third_quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    second_payment = services.pay_quote(token, first_quote.quote_id)
    assert third_quote.quote_id == first_quote.quote_id
    assert third_quote.created is False
    assert second_payment.payment_id == first_payment.payment_id
    assert second_payment.created is False
    assert store.snapshot() == before


def test_quote_fee_rejects_ineligible_service(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.quote_fee(token_for("CIT-0006"), ServiceType.BIRTH_CERTIFICATE_COPY)
    assert excinfo.value.code is ErrorCode.NOT_ELIGIBLE
    assert "NO_BIRTH_RECORD" in excinfo.value.message
    assert store.snapshot() == before


def test_quote_fee_rejects_invalid_token(services: CitizenServices) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.quote_fee("nope", ServiceType.PARKING_PERMIT)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


# -- pay_quote ------------------------------------------------------------


def test_pay_quote_creates_one_payment_and_replays(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    payment = services.pay_quote(token, quote.quote_id)
    assert payment.status == "PAID"
    assert payment.amount_cents == 3000
    assert payment.created is True

    before = store.snapshot()
    replay = services.pay_quote(token, quote.quote_id)
    assert replay.payment_id == payment.payment_id
    assert replay.created is False
    assert store.snapshot() == before


def test_pay_quote_missing_or_cross_citizen_quote(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    quote = services.quote_fee(token_for("CIT-0001"), ServiceType.PARKING_PERMIT)
    for token, quote_id in (
        (token_for("CIT-0001"), "QTE-00000000"),
        (token_for("CIT-0002"), quote.quote_id),
    ):
        with pytest.raises(DomainError) as excinfo:
            services.pay_quote(token, quote_id)
        assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_pay_quote_rejects_invalid_token(services: CitizenServices) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.pay_quote("nope", "QTE-00000000")
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


def test_pay_quote_rechecks_eligibility(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    services.update_address(token, "1 A ST", "CV-102")

    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.pay_quote(token, quote.quote_id)
    assert excinfo.value.code is ErrorCode.NOT_ELIGIBLE
    assert "NOT_IN_PERMIT_AREA" in excinfo.value.message
    assert store.snapshot() == before


# -- apply_parking_permit -------------------------------------------------


def test_parking_flow_and_replay(
    services: CitizenServices,
    token_for: Callable[[str], str],
    store: Store,
) -> None:
    token = token_for("CIT-0001")
    eligibility = services.check_eligibility(token, ServiceType.PARKING_PERMIT)
    assert eligibility.eligible is True
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    payment = services.pay_quote(token, quote.quote_id)
    application = services.apply_parking_permit(token, "CVX-1234", payment.payment_id)
    assert application.status is ApplicationStatus.SUBMITTED
    assert application.created is True

    before = store.snapshot()
    replay = services.apply_parking_permit(token, "cvx1234", payment.payment_id)
    assert replay.application_id == application.application_id
    assert replay.created is False
    assert store.snapshot() == before

    row = next(
        row
        for row in store.snapshot()["applications"]
        if row["application_id"] == application.application_id
    )
    assert json.loads(row["details_json"]) == {"license_plate": "CVX1234"}
    assert row["payment_id"] == payment.payment_id


def test_parking_payment_reuse_with_different_plate(
    services: CitizenServices,
    token_for: Callable[[str], str],
    store: Store,
) -> None:
    token = token_for("CIT-0009")
    payment = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    paid = services.pay_quote(token, payment.quote_id)
    services.apply_parking_permit(token, "PRK1111", paid.payment_id)
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.apply_parking_permit(token, "PRK2222", paid.payment_id)
    assert excinfo.value.code is ErrorCode.PAYMENT_ALREADY_USED
    assert store.snapshot() == before


def test_parking_rejects_missing_or_cross_citizen_payment(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    payment = services.quote_fee(token_for("CIT-0001"), ServiceType.PARKING_PERMIT)
    paid = services.pay_quote(token_for("CIT-0001"), payment.quote_id)
    for token, payment_id in (
        (token_for("CIT-0001"), "PAY-00000000"),
        (token_for("CIT-0002"), paid.payment_id),
    ):
        with pytest.raises(DomainError) as excinfo:
            services.apply_parking_permit(token, "CVX1234", payment_id)
        assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_parking_rejects_payment_for_another_service(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 1)
    payment = services.pay_quote(token, quote.quote_id)
    with pytest.raises(DomainError) as excinfo:
        services.apply_parking_permit(token, "CVX1234", payment.payment_id)
    assert excinfo.value.code is ErrorCode.PAYMENT_INVALID


def test_parking_rejects_unregistered_plate(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    payment = services.pay_quote(token, quote.quote_id)
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.apply_parking_permit(token, "ZZZ999", payment.payment_id)
    assert excinfo.value.code is ErrorCode.PLATE_NOT_REGISTERED
    assert store.snapshot() == before


def test_parking_rejects_ineligible_citizen(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    payment = services.pay_quote(token, quote.quote_id)
    _force_active_permit(store, "CIT-0001")
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.apply_parking_permit(token, "CVX1234", payment.payment_id)
    assert excinfo.value.code is ErrorCode.NOT_ELIGIBLE
    assert "ACTIVE_PERMIT_EXISTS" in excinfo.value.message
    assert store.snapshot() == before


def test_paid_but_unused_quote_remains_open(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    payment = services.pay_quote(token, quote.quote_id)

    services.update_address(token, "1 A ST", "CV-102")
    with pytest.raises(DomainError) as excinfo:
        services.apply_parking_permit(token, "CVX1234", payment.payment_id)
    assert excinfo.value.code is ErrorCode.NOT_ELIGIBLE

    services.update_address(token, "12 MAPLE ST", "CV-101")
    replay = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    assert replay.quote_id == quote.quote_id
    assert replay.created is False

    application = services.apply_parking_permit(token, "CVX1234", payment.payment_id)
    assert application.created is True

    payments = [row for row in store.snapshot()["payments"] if row["citizen_id"] == "CIT-0001"]
    assert len(payments) == 1


def test_parking_rejects_invalid_plate_and_token(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    with pytest.raises(DomainError) as invalid_plate:
        services.apply_parking_permit(token_for("CIT-0001"), "A", "PAY-00000000")
    assert invalid_plate.value.code is ErrorCode.INVALID_ARGUMENT

    with pytest.raises(DomainError) as invalid_token:
        services.apply_parking_permit("nope", "CVX1234", "PAY-00000000")
    assert invalid_token.value.code is ErrorCode.INVALID_TOKEN


# -- request_birth_certificate -------------------------------------------


def test_birth_certificate_flow_and_replay(
    services: CitizenServices,
    token_for: Callable[[str], str],
    store: Store,
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    payment = services.pay_quote(token, quote.quote_id)
    application = services.request_birth_certificate(token, 2, payment.payment_id)
    assert application.status is ApplicationStatus.SUBMITTED
    assert application.created is True

    before = store.snapshot()
    replay = services.request_birth_certificate(token, 2, payment.payment_id)
    assert replay.application_id == application.application_id
    assert replay.created is False
    assert store.snapshot() == before

    row = next(
        row
        for row in store.snapshot()["applications"]
        if row["application_id"] == application.application_id
    )
    assert json.loads(row["details_json"]) == {"copies": 2}


def test_two_birth_certificate_orders_create_new_records(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    first_quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    first_payment = services.pay_quote(token, first_quote.quote_id)
    first_application = services.request_birth_certificate(token, 2, first_payment.payment_id)

    second_quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    assert second_quote.created is True
    assert second_quote.quote_id != first_quote.quote_id

    second_payment = services.pay_quote(token, second_quote.quote_id)
    assert second_payment.created is True
    assert second_payment.payment_id != first_payment.payment_id

    second_application = services.request_birth_certificate(token, 2, second_payment.payment_id)
    assert second_application.created is True
    assert second_application.application_id != first_application.application_id

    applications = [
        row for row in store.snapshot()["applications"] if row["citizen_id"] == "CIT-0001"
    ]
    assert len(applications) == 2
    assert len({row["payment_id"] for row in applications}) == 2


def test_birth_certificate_reuses_payment_for_other_copies(
    services: CitizenServices,
    token_for: Callable[[str], str],
    store: Store,
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    payment = services.pay_quote(token, quote.quote_id)
    services.request_birth_certificate(token, 2, payment.payment_id)
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.request_birth_certificate(token, 3, payment.payment_id)
    assert excinfo.value.code is ErrorCode.PAYMENT_ALREADY_USED
    assert store.snapshot() == before


def test_birth_certificate_payment_quantity_mismatch(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
    payment = services.pay_quote(token, quote.quote_id)
    with pytest.raises(DomainError) as excinfo:
        services.request_birth_certificate(token, 3, payment.payment_id)
    assert excinfo.value.code is ErrorCode.PAYMENT_INVALID


def test_birth_certificate_rejects_wrong_service_and_missing_payment(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    payment = services.pay_quote(token, quote.quote_id)

    with pytest.raises(DomainError) as wrong_service:
        services.request_birth_certificate(token, 1, payment.payment_id)
    assert wrong_service.value.code is ErrorCode.PAYMENT_INVALID

    with pytest.raises(DomainError) as missing:
        services.request_birth_certificate(token, 1, "PAY-00000000")
    assert missing.value.code is ErrorCode.NOT_FOUND

    other_token = token_for("CIT-0002")
    with pytest.raises(DomainError) as other:
        services.request_birth_certificate(other_token, 1, payment.payment_id)
    assert other.value.code is ErrorCode.NOT_FOUND


def test_birth_certificate_ineligible_after_direct_payment_setup(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    payment_id = _force_quote_and_payment(
        store, "CIT-0006", ServiceType.BIRTH_CERTIFICATE_COPY, 1, 1500
    )
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.request_birth_certificate(token_for("CIT-0006"), 1, payment_id)
    assert excinfo.value.code is ErrorCode.NOT_ELIGIBLE
    assert "NO_BIRTH_RECORD" in excinfo.value.message
    assert store.snapshot() == before


@pytest.mark.parametrize("copies", [0, 6])
def test_birth_certificate_rejects_bad_copies(
    services: CitizenServices, token_for: Callable[[str], str], copies: int
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.request_birth_certificate(token_for("CIT-0001"), copies, "PAY-00000000")
    assert excinfo.value.code is ErrorCode.INVALID_QUANTITY


def test_birth_certificate_rejects_invalid_token(services: CitizenServices) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.request_birth_certificate("nope", 1, "PAY-00000000")
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


def test_payment_is_only_charged_once(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    quote = services.quote_fee(token, ServiceType.PARKING_PERMIT)
    services.pay_quote(token, quote.quote_id)
    payments = [row for row in store.snapshot()["payments"] if row["quote_id"] == quote.quote_id]
    assert len(payments) == 1
    assert payments[0]["amount_cents"] == 3000


def test_repeat_birth_orders_are_deterministic(fixture: Fixture, tmp_path: Path) -> None:
    citizen = next(c for c in fixture.citizens if c.citizen_id == "CIT-0001")

    def run(name: str) -> dict[str, list[dict[str, object]]]:
        store = Store.create_from_fixture(tmp_path / name, fixture)
        services = CitizenServices(store, TEST_SECRET)
        token = services.verify_citizen(
            citizen.full_name, citizen.date_of_birth, citizen.postal_code
        ).citizen_token
        for _ in range(2):
            quote = services.quote_fee(token, ServiceType.BIRTH_CERTIFICATE_COPY, 2)
            payment = services.pay_quote(token, quote.quote_id)
            services.request_birth_certificate(token, 2, payment.payment_id)
        return store.snapshot()

    assert run("first.db") == run("second.db")
