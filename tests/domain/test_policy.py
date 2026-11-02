"""Policy arithmetic, calendar rules, and eligibility ordering."""

from __future__ import annotations

from datetime import date

import pytest

from citizen_agent.domain.enums import ErrorCode, IneligibilityReason, ServiceType, Zone
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.policy import (
    age_on,
    eligibility_reasons,
    offered_pickup_dates,
    quote_amount_cents,
)

TODAY = date(2026, 3, 2)


def test_age_handles_leap_day_birthdays() -> None:
    assert age_on(date(1960, 2, 29), TODAY) == 66
    assert age_on(date(1961, 3, 2), TODAY) == 65
    assert age_on(date(1961, 3, 3), TODAY) == 64
    assert age_on(date(2006, 3, 3), TODAY) == 19


def test_parking_fee_uses_senior_boundary() -> None:
    assert (
        quote_amount_cents(
            ServiceType.PARKING_PERMIT, 1, date_of_birth=date(1961, 3, 2), today=TODAY
        )
        == 3000
    )
    assert (
        quote_amount_cents(
            ServiceType.PARKING_PERMIT, 1, date_of_birth=date(1961, 3, 3), today=TODAY
        )
        == 6000
    )


def test_birth_copy_fee_per_copy() -> None:
    for copies in range(1, 6):
        assert (
            quote_amount_cents(
                ServiceType.BIRTH_CERTIFICATE_COPY,
                copies,
                date_of_birth=date(1990, 1, 1),
                today=TODAY,
            )
            == 1500 * copies
        )


@pytest.mark.parametrize(
    ("service_type", "quantity", "expected"),
    [
        (ServiceType.PARKING_PERMIT, 2, ErrorCode.INVALID_QUANTITY),
        (ServiceType.BIRTH_CERTIFICATE_COPY, 0, ErrorCode.INVALID_QUANTITY),
        (ServiceType.BIRTH_CERTIFICATE_COPY, 6, ErrorCode.INVALID_QUANTITY),
        (ServiceType.ADDRESS_CHANGE, 1, ErrorCode.NO_FEE_REQUIRED),
        (ServiceType.BULK_WASTE_PICKUP, 1, ErrorCode.NO_FEE_REQUIRED),
        (ServiceType.STREET_ISSUE_REPORT, 1, ErrorCode.NO_FEE_REQUIRED),
        (ServiceType.OFFICE_APPOINTMENT, 1, ErrorCode.NO_FEE_REQUIRED),
    ],
)
def test_quote_amount_rejects_invalid_service_quantities(
    service_type: ServiceType, quantity: int, expected: ErrorCode
) -> None:
    with pytest.raises(DomainError) as excinfo:
        quote_amount_cents(service_type, quantity, date_of_birth=date(1990, 1, 1), today=TODAY)
    assert excinfo.value.code is expected


def test_offered_pickup_dates_north_and_west() -> None:
    assert offered_pickup_dates(Zone.NORTH, TODAY) == [
        "2026-03-03",
        "2026-03-10",
        "2026-03-17",
        "2026-03-24",
    ]
    assert offered_pickup_dates(Zone.WEST, TODAY) == [
        "2026-03-06",
        "2026-03-13",
        "2026-03-20",
        "2026-03-27",
    ]


def test_parking_eligibility_returns_all_reasons_in_order() -> None:
    reasons = eligibility_reasons(
        ServiceType.PARKING_PERMIT,
        postal_permit_area=False,
        vehicle_count=0,
        has_active_permit=True,
        born_in_city=True,
        has_scheduled_pickup=True,
    )
    assert reasons == [
        IneligibilityReason.NOT_IN_PERMIT_AREA,
        IneligibilityReason.NO_REGISTERED_VEHICLE,
        IneligibilityReason.ACTIVE_PERMIT_EXISTS,
    ]


def test_non_parking_eligibility_rules() -> None:
    assert eligibility_reasons(
        ServiceType.BIRTH_CERTIFICATE_COPY,
        postal_permit_area=False,
        vehicle_count=0,
        has_active_permit=True,
        born_in_city=False,
        has_scheduled_pickup=False,
    ) == [IneligibilityReason.NO_BIRTH_RECORD]
    assert eligibility_reasons(
        ServiceType.BULK_WASTE_PICKUP,
        postal_permit_area=False,
        vehicle_count=0,
        has_active_permit=True,
        born_in_city=False,
        has_scheduled_pickup=True,
    ) == [IneligibilityReason.PICKUP_ALREADY_SCHEDULED]
    assert (
        eligibility_reasons(
            ServiceType.ADDRESS_CHANGE,
            postal_permit_area=False,
            vehicle_count=0,
            has_active_permit=True,
            born_in_city=False,
            has_scheduled_pickup=True,
        )
        == []
    )
