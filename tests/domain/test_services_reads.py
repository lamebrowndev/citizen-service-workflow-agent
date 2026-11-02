"""Read-only tool behavior: verification, profile, catalog, eligibility, slots, cases."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from citizen_agent.domain.enums import (
    ApplicationStatus,
    ErrorCode,
    IneligibilityReason,
    IssueCategory,
    IssueStatus,
    Office,
    ServiceType,
    Zone,
)
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.ids import citizen_token
from citizen_agent.domain.policy import SERVICE_CATALOG
from citizen_agent.domain.services import CitizenServices
from tests.conftest import TEST_SECRET


def test_verify_citizen_returns_token_and_display_name(
    services: CitizenServices,
) -> None:
    result = services.verify_citizen("  amara   OKAFOR ", "1961-03-02", " cv-101 ")
    assert result.full_name == "Amara Okafor"
    assert result.citizen_token.startswith("CTK.CIT-0001.")
    profile = services.get_citizen_profile(result.citizen_token)
    assert profile.citizen_id == "CIT-0001"


@pytest.mark.parametrize(
    ("name", "dob", "postal"),
    [
        ("Amara Okafor", "1961-03-03", "CV-101"),
        ("Amara Okafor", "1961-03-02", "CV-102"),
        ("Someone Else", "1961-03-02", "CV-101"),
    ],
)
def test_verify_citizen_mismatch_never_reveals_the_field(
    services: CitizenServices, name: str, dob: str, postal: str
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.verify_citizen(name, dob, postal)
    assert excinfo.value.code is ErrorCode.VERIFICATION_FAILED
    assert excinfo.value.message == "Identity verification failed."


@pytest.mark.parametrize(
    ("name", "dob", "postal"),
    [
        ("   ", "1961-03-02", "CV-101"),
        ("Amara Okafor", "1961-02-30", "CV-101"),
        ("Amara Okafor", "1961-03-02", "CV-9999"),
    ],
)
def test_verify_citizen_rejects_malformed_input(
    services: CitizenServices, name: str, dob: str, postal: str
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.verify_citizen(name, dob, postal)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_get_profile_never_exposes_date_of_birth(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    profile = services.get_citizen_profile(token_for("CIT-0001"))
    dumped = profile.model_dump()
    assert "date_of_birth" not in dumped
    assert profile.full_name == "Amara Okafor"
    assert profile.zone is Zone.NORTH
    assert profile.permit_area is True
    assert [vehicle.license_plate for vehicle in profile.vehicles] == ["CVX1234"]
    assert all(
        appointment.appointment_id.startswith("APT-") for appointment in profile.appointments
    )


def test_get_profile_reports_only_booked_appointments_and_scheduled_pickups(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    profile = services.get_citizen_profile(token_for("CIT-0007"))
    assert len(profile.pickups) == 1
    assert profile.pickups[0].date == "2026-03-03"
    assert profile.applications[0].status is ApplicationStatus.APPROVED
    assert len(profile.appointments) == 1
    assert profile.appointments[0].office is Office.CITY_HALL


def test_get_profile_rejects_unknown_and_invalid_tokens(
    services: CitizenServices,
) -> None:
    for token in ("garbage", citizen_token(TEST_SECRET, "CIT-9999")):
        with pytest.raises(DomainError) as excinfo:
            services.get_citizen_profile(token)
        assert excinfo.value.code is ErrorCode.INVALID_TOKEN


@pytest.mark.parametrize("service_type", list(ServiceType))
def test_service_catalog_is_fully_exposed(
    services: CitizenServices, service_type: ServiceType
) -> None:
    info = services.get_service_info(service_type)
    expected = SERVICE_CATALOG[service_type]
    assert info.service_type is service_type
    assert info.title == expected.title
    assert info.fee_rules == expected.fee_rules
    assert info.processing_days == expected.processing_days
    assert info.requirements == list(expected.requirements)


def test_parking_eligibility_for_boundary_citizens(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    senior = services.check_eligibility(token_for("CIT-0001"), ServiceType.PARKING_PERMIT)
    non_senior = services.check_eligibility(token_for("CIT-0002"), ServiceType.PARKING_PERMIT)
    assert senior.eligible is True
    assert senior.reasons == []
    assert non_senior.eligible is True


def test_eligibility_returns_every_reason_in_order(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    result = services.check_eligibility(token_for("CIT-0021"), ServiceType.PARKING_PERMIT)
    assert result.reasons == [
        IneligibilityReason.NOT_IN_PERMIT_AREA,
        IneligibilityReason.NO_REGISTERED_VEHICLE,
    ]


def test_eligibility_specific_rules(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    active = services.check_eligibility(token_for("CIT-0010"), ServiceType.PARKING_PERMIT)
    assert active.reasons == [IneligibilityReason.ACTIVE_PERMIT_EXISTS]

    no_birth_record = services.check_eligibility(
        token_for("CIT-0006"), ServiceType.BIRTH_CERTIFICATE_COPY
    )
    assert no_birth_record.reasons == [IneligibilityReason.NO_BIRTH_RECORD]

    pickup = services.check_eligibility(token_for("CIT-0007"), ServiceType.BULK_WASTE_PICKUP)
    assert pickup.reasons == [IneligibilityReason.PICKUP_ALREADY_SCHEDULED]

    for service_type in (
        ServiceType.ADDRESS_CHANGE,
        ServiceType.STREET_ISSUE_REPORT,
        ServiceType.OFFICE_APPOINTMENT,
    ):
        assert services.check_eligibility(token_for("CIT-0021"), service_type).eligible


def test_eligibility_rejects_invalid_token(services: CitizenServices) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.check_eligibility("nope", ServiceType.PARKING_PERMIT)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


def test_list_pickup_dates_exact_zone_calendars(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    assert services.list_pickup_dates(token_for("CIT-0001")).dates == [
        "2026-03-03",
        "2026-03-10",
        "2026-03-17",
        "2026-03-24",
    ]
    assert services.list_pickup_dates(token_for("CIT-0004")).dates == [
        "2026-03-06",
        "2026-03-13",
        "2026-03-20",
        "2026-03-27",
    ]


def test_list_pickup_dates_rejects_invalid_token(services: CitizenServices) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.list_pickup_dates("nope")
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


def test_list_appointment_slots_returns_free_sorted_slots(
    services: CitizenServices,
) -> None:
    result = services.list_appointment_slots(Office.CITY_HALL, "2026-03-09")
    assert result.date == "2026-03-09"
    assert [slot.time for slot in result.slots] == [
        "09:00",
        "09:30",
        "10:00",
        "10:30",
        "11:00",
        "11:30",
    ]


def test_list_appointment_slots_exact_fully_booked_day(
    services: CitizenServices,
) -> None:
    result = services.list_appointment_slots(Office.CITY_HALL, "2026-03-05")
    assert result.slots == []


def test_list_appointment_slots_unknown_day_is_empty(
    services: CitizenServices,
) -> None:
    result = services.list_appointment_slots(Office.CITY_HALL, "2026-03-07")
    assert result.slots == []


def test_list_appointment_slots_rejects_malformed_date(
    services: CitizenServices,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.list_appointment_slots(Office.CITY_HALL, "05/03/2026")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_get_case_status_application_requires_owner(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    result = services.get_case_status("app-1a2b3c4d", token_for("CIT-0010"))
    assert result.case_id == "APP-1A2B3C4D"
    assert result.case_type == "APPLICATION"
    assert result.status == "APPROVED"
    assert result.subject == "PARKING_PERMIT"
    assert result.updated_on == "2025-11-10"

    with pytest.raises(DomainError) as missing:
        services.get_case_status("APP-1A2B3C4D")
    assert missing.value.code is ErrorCode.AUTH_REQUIRED

    with pytest.raises(DomainError) as not_owned:
        services.get_case_status("APP-1A2B3C4D", token_for("CIT-0011"))
    assert not_owned.value.code is ErrorCode.NOT_FOUND

    with pytest.raises(DomainError) as invalid:
        services.get_case_status("APP-1A2B3C4D", "nope")
    assert invalid.value.code is ErrorCode.INVALID_TOKEN


def test_get_case_status_issue_is_public(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    created = services.report_street_issue(
        IssueCategory.POTHOLE, "12 Maple Street", "A hole in the road."
    )
    for token in (None, "nope", token_for("CIT-0001")):
        result = services.get_case_status(created.issue_id, token)
        assert result.case_type == "ISSUE"
        assert result.subject == "POTHOLE"
        assert result.status == IssueStatus.OPEN.value
        assert result.updated_on == "2026-03-02"


def test_get_case_status_unknown_prefix_or_missing_case(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    for case_id in ("XYZ-12345678", "APP-00000000", "ISS-00000000"):
        with pytest.raises(DomainError) as excinfo:
            services.get_case_status(case_id, token_for("CIT-0001"))
        assert excinfo.value.code is ErrorCode.NOT_FOUND
