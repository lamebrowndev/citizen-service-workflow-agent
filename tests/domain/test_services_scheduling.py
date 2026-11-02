"""Write tools for pickups, issues, appointments, and human escalation."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from citizen_agent.domain.enums import (
    AppointmentPurpose,
    AppointmentStatus,
    ErrorCode,
    IssueCategory,
    IssueStatus,
    Office,
    PickupStatus,
)
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.models import Fixture
from citizen_agent.domain.services import CitizenServices
from citizen_agent.domain.store import Store

TODAY = "2026-03-02"


# -- schedule_bulk_pickup -------------------------------------------------


def test_schedule_bulk_pickup_and_replay(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    result = services.schedule_bulk_pickup(token, "2026-03-03", 3)
    assert result.status is PickupStatus.SCHEDULED
    assert result.created is True
    assert result.item_count == 3

    profile = services.get_citizen_profile(token)
    assert [pickup.pickup_id for pickup in profile.pickups] == [result.pickup_id]

    before = store.snapshot()
    replay = services.schedule_bulk_pickup(token, "2026-03-03", 3)
    assert replay.pickup_id == result.pickup_id
    assert replay.created is False
    assert store.snapshot() == before


def test_schedule_bulk_pickup_rejects_second_pickup(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    services.schedule_bulk_pickup(token, "2026-03-03", 3)

    with pytest.raises(DomainError) as same_date:
        services.schedule_bulk_pickup(token, "2026-03-03", 4)
    assert same_date.value.code is ErrorCode.ALREADY_SCHEDULED

    before = store.snapshot()
    with pytest.raises(DomainError) as other_date:
        services.schedule_bulk_pickup(token, "2026-03-10", 2)
    assert other_date.value.code is ErrorCode.ALREADY_SCHEDULED
    assert store.snapshot() == before


def test_schedule_bulk_pickup_rejects_date_outside_zone_calendar(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.schedule_bulk_pickup(token_for("CIT-0001"), "2026-03-04", 2)
    assert excinfo.value.code is ErrorCode.DATE_UNAVAILABLE
    assert store.snapshot() == before


def test_schedule_bulk_pickup_allows_completed_history(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    result = services.schedule_bulk_pickup(token_for("CIT-0008"), "2026-03-04", 2)
    assert result.created is True
    assert result.status is PickupStatus.SCHEDULED


def test_schedule_bulk_pickup_does_not_replay_completed_pickup(
    services: CitizenServices,
    token_for: Callable[[str], str],
    store: Store,
    fixture: Fixture,
) -> None:
    completed = next(
        pickup for pickup in fixture.pickups if pickup.status is PickupStatus.COMPLETED
    )
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.schedule_bulk_pickup(
            token_for(completed.citizen_id), completed.date, completed.item_count
        )
    assert excinfo.value.code is ErrorCode.DATE_UNAVAILABLE
    assert store.snapshot() == before


@pytest.mark.parametrize("item_count", [0, 6])
def test_schedule_bulk_pickup_rejects_bad_counts(
    services: CitizenServices, token_for: Callable[[str], str], item_count: int
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.schedule_bulk_pickup(token_for("CIT-0001"), "2026-03-03", item_count)
    assert excinfo.value.code is ErrorCode.INVALID_QUANTITY


def test_schedule_bulk_pickup_rejects_invalid_token(
    services: CitizenServices,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.schedule_bulk_pickup("nope", "2026-03-03", 2)
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


# -- report_street_issue --------------------------------------------------


def test_report_street_issue_creates_open_case(services: CitizenServices, store: Store) -> None:
    result = services.report_street_issue(
        IssueCategory.POTHOLE, "12 Maple Street", "A deep pothole."
    )
    assert result.status is IssueStatus.OPEN
    assert result.created is True

    row = next(row for row in store.snapshot()["issues"] if row["issue_id"] == result.issue_id)
    assert row["street_address"] == "12 MAPLE ST"
    assert row["reported_on"] == TODAY
    assert row["updated_on"] == TODAY
    assert row["category"] == IssueCategory.POTHOLE.value


def test_report_street_issue_replay_ignores_description(
    services: CitizenServices, store: Store
) -> None:
    first = services.report_street_issue(
        IssueCategory.GRAFFITI, "7 Elm Place", "First description."
    )
    before = store.snapshot()
    replay = services.report_street_issue(
        IssueCategory.GRAFFITI, "7 Elm Place.", "A different description."
    )
    assert replay.issue_id == first.issue_id
    assert replay.created is False
    assert store.snapshot() == before


def test_report_street_issue_different_category_is_distinct(
    services: CitizenServices,
) -> None:
    first = services.report_street_issue(
        IssueCategory.POTHOLE, "12 Maple Street", "A deep pothole."
    )
    second = services.report_street_issue(
        IssueCategory.STREETLIGHT, "12 Maple Street", "A dark streetlight."
    )
    assert first.issue_id != second.issue_id


@pytest.mark.parametrize("description", ["", "x" * 501])
def test_report_street_issue_rejects_bad_descriptions(
    services: CitizenServices, description: str, store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.report_street_issue(IssueCategory.POTHOLE, "12 Maple Street", description)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert store.snapshot() == before


def test_report_street_issue_rejects_bad_address(
    services: CitizenServices,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.report_street_issue(IssueCategory.POTHOLE, " . ", "A deep pothole.")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_report_street_issue_rejects_whitespace_description(
    services: CitizenServices, store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.report_street_issue(IssueCategory.POTHOLE, "12 MAPLE ST", " \t\n ")
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT
    assert store.snapshot() == before


# -- book_appointment -----------------------------------------------------


def test_book_appointment_new_slot_and_replay(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    booking = services.book_appointment(
        token, "slot-north_branch-20260310-0900", AppointmentPurpose.ID_CARD
    )
    assert booking.created is True
    assert booking.office is Office.NORTH_BRANCH
    assert booking.date == "2026-03-10"
    assert booking.time == "09:00"
    assert booking.status is AppointmentStatus.BOOKED

    before = store.snapshot()
    replay = services.book_appointment(token, booking.slot_id, AppointmentPurpose.GENERAL_INQUIRY)
    assert replay.appointment_id == booking.appointment_id
    assert replay.created is False
    assert replay.purpose is AppointmentPurpose.ID_CARD
    assert store.snapshot() == before


def test_book_appointment_rejects_slot_booked_by_someone_else(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.book_appointment(
            token_for("CIT-0002"),
            "SLOT-CITY_HALL-20260305-0900",
            AppointmentPurpose.ID_CARD,
        )
    assert excinfo.value.code is ErrorCode.SLOT_UNAVAILABLE
    assert store.snapshot() == before


def test_book_appointment_missing_slot(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.book_appointment(
            token_for("CIT-0001"),
            "SLOT-CITY_HALL-20990101-0900",
            AppointmentPurpose.ID_CARD,
        )
    assert excinfo.value.code is ErrorCode.NOT_FOUND


def test_cancel_then_rebook_same_slot(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    token = token_for("CIT-0001")
    slot_id = "SLOT-CITY_HALL-20260305-0900"
    profile = services.get_citizen_profile(token)
    appointment_id = next(
        appointment.appointment_id
        for appointment in profile.appointments
        if appointment.slot_id == slot_id
    )
    cancelled = services.cancel_appointment(token, appointment_id)
    assert cancelled.changed is True
    assert cancelled.status is AppointmentStatus.CANCELLED

    rebooked = services.book_appointment(token, slot_id, AppointmentPurpose.GENERAL_INQUIRY)
    assert rebooked.created is True
    assert rebooked.appointment_id == appointment_id
    assert rebooked.purpose is AppointmentPurpose.GENERAL_INQUIRY
    assert rebooked.status is AppointmentStatus.BOOKED


def test_book_appointment_rejects_invalid_token(
    services: CitizenServices,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.book_appointment(
            "nope", "SLOT-CITY_HALL-20260305-0900", AppointmentPurpose.ID_CARD
        )
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


# -- cancel_appointment ---------------------------------------------------


def test_cancel_appointment_is_idempotent(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    profile = services.get_citizen_profile(token)
    appointment_id = profile.appointments[0].appointment_id

    first = services.cancel_appointment(token, appointment_id)
    assert first.changed is True

    before = store.snapshot()
    second = services.cancel_appointment(token, appointment_id)
    assert second.changed is False
    assert second.status is AppointmentStatus.CANCELLED
    assert store.snapshot() == before


def test_cancel_appointment_frees_the_slot(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    token = token_for("CIT-0001")
    profile = services.get_citizen_profile(token)
    appointment = next(
        appointment for appointment in profile.appointments if appointment.date == "2026-03-05"
    )
    services.cancel_appointment(token, appointment.appointment_id)
    slots = services.list_appointment_slots(Office.CITY_HALL, "2026-03-05")
    assert len(slots.slots) == 1
    assert slots.slots[0].slot_id == appointment.slot_id


def test_cancel_appointment_missing_or_cross_citizen(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    appointment_id = services.get_citizen_profile(token).appointments[0].appointment_id
    before = store.snapshot()
    for caller, candidate in (
        (token_for("CIT-0002"), appointment_id),
        (token, "APT-00000000"),
    ):
        with pytest.raises(DomainError) as excinfo:
            services.cancel_appointment(caller, candidate)
        assert excinfo.value.code is ErrorCode.NOT_FOUND
    assert store.snapshot() == before


def test_cancel_appointment_rejects_invalid_token(
    services: CitizenServices,
) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.cancel_appointment("nope", "APT-00000000")
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN


# -- escalate_to_human ----------------------------------------------------


def test_anonymous_escalations_deduplicate_on_normalized_summary(
    services: CitizenServices, store: Store
) -> None:
    first = services.escalate_to_human("Streetlight outage unresolved after two weeks.")
    second = services.escalate_to_human("A different summary is ignored.")
    assert first.created is True
    assert second.created is True
    assert second.escalation_id != first.escalation_id

    row = next(
        row
        for row in store.snapshot()["escalations"]
        if row["escalation_id"] == first.escalation_id
    )
    assert row["citizen_id"] is None
    assert row["summary"] == "Streetlight outage unresolved after two weeks."
    assert row["created_on"] == TODAY

    before = store.snapshot()
    replay = services.escalate_to_human("  STREETLIGHT   outage unresolved AFTER two weeks. ")
    assert replay.escalation_id == first.escalation_id
    assert replay.created is False
    assert store.snapshot() == before
    assert len(store.snapshot()["escalations"]) == 2


def test_citizen_escalations_deduplicate_per_day(
    services: CitizenServices, token_for: Callable[[str], str], store: Store
) -> None:
    token = token_for("CIT-0001")
    first = services.escalate_to_human("First citizen summary.", token)
    second = services.escalate_to_human("Second citizen summary.", token)
    assert first.created is True
    assert second.created is False
    assert second.escalation_id == first.escalation_id

    row = next(
        row
        for row in store.snapshot()["escalations"]
        if row["escalation_id"] == first.escalation_id
    )
    assert row["summary"] == "First citizen summary."


@pytest.mark.parametrize("with_token", [False, True])
def test_escalate_rejects_whitespace_only_summary(
    services: CitizenServices,
    token_for: Callable[[str], str],
    with_token: bool,
) -> None:
    token = token_for("CIT-0001") if with_token else None
    with pytest.raises(DomainError) as excinfo:
        services.escalate_to_human(" \t\n ", token)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


def test_escalate_for_citizen_and_anonymous_are_distinct(
    services: CitizenServices, token_for: Callable[[str], str]
) -> None:
    anonymous = services.escalate_to_human("Anonymous request.")
    identified = services.escalate_to_human("Identified request.", token_for("CIT-0001"))
    assert identified.created is True
    assert identified.escalation_id != anonymous.escalation_id


def test_escalate_rejects_invalid_token(services: CitizenServices, store: Store) -> None:
    before = store.snapshot()
    with pytest.raises(DomainError) as excinfo:
        services.escalate_to_human("Needs help.", "nope")
    assert excinfo.value.code is ErrorCode.INVALID_TOKEN
    assert store.snapshot() == before


@pytest.mark.parametrize("summary", ["", "x" * 1001])
def test_escalate_rejects_bad_summaries(services: CitizenServices, summary: str) -> None:
    with pytest.raises(DomainError) as excinfo:
        services.escalate_to_human(summary)
    assert excinfo.value.code is ErrorCode.INVALID_ARGUMENT


# -- shared guardrails ----------------------------------------------------
