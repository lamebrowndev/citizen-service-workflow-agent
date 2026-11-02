"""Assert every documented property of the bundled fixture, computed from its data."""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from datetime import date
from importlib.resources import files
from pathlib import Path

from citizen_agent.domain.enums import (
    ApplicationStatus,
    AppointmentStatus,
    IssueCategory,
    IssueStatus,
    PickupStatus,
    ServiceType,
    Zone,
)
from citizen_agent.domain.models import Fixture
from citizen_agent.domain.normalize import (
    display_name,
    normalize_address,
    normalize_name,
    normalize_plate,
    normalize_postal_code,
)
from citizen_agent.domain.policy import (
    ACTIVE_APPLICATION_STATUSES,
    age_on,
    offered_pickup_dates,
)
from citizen_agent.domain.store import Store


def _has_active_parking_application(fixture: Fixture, citizen_id: str) -> bool:
    return any(
        application.citizen_id == citizen_id
        and application.service_type is ServiceType.PARKING_PERMIT
        and application.status in ACTIVE_APPLICATION_STATUSES
        for application in fixture.applications
    )


def _raw_fixture() -> dict[str, object]:
    text = files("citizen_agent.fixtures").joinpath("default.json").read_text(encoding="utf-8")
    return json.loads(text)


def test_meta_and_calendar_date(fixture: Fixture) -> None:
    assert fixture.meta.fixture_name == "default"
    assert fixture.meta.today == "2026-03-02"
    assert date.fromisoformat(fixture.meta.today).weekday() == 0  # Monday


def test_postal_codes_cover_the_city(fixture: Fixture) -> None:
    assert [postal.postal_code for postal in fixture.postal_codes] == [
        f"CV-{number}" for number in range(101, 109)
    ]
    zones = {postal.postal_code: postal.zone for postal in fixture.postal_codes}
    assert zones["CV-101"] is Zone.NORTH
    assert zones["CV-102"] is Zone.NORTH
    assert zones["CV-103"] is Zone.SOUTH
    assert zones["CV-104"] is Zone.SOUTH
    assert zones["CV-105"] is Zone.EAST
    assert zones["CV-106"] is Zone.EAST
    assert zones["CV-107"] is Zone.WEST
    assert zones["CV-108"] is Zone.WEST
    for postal in fixture.postal_codes:
        number = int(postal.postal_code.split("-")[1])
        assert postal.permit_area is (number % 2 == 1)


def test_citizen_count_identifiers_and_dates(fixture: Fixture) -> None:
    assert len(fixture.citizens) == 40
    assert [citizen.citizen_id for citizen in fixture.citizens] == [
        f"CIT-{number:04d}" for number in range(1, 41)
    ]
    for citizen in fixture.citizens:
        born = date.fromisoformat(citizen.date_of_birth)
        assert date(1940, 1, 1) <= born <= date(2006, 12, 31)
        assert normalize_postal_code(citizen.postal_code) == citizen.postal_code
        assert normalize_address(citizen.street_address) == citizen.street_address
        assert display_name(citizen.full_name) == citizen.full_name


def test_identity_triples_are_unique_and_names_repeat(fixture: Fixture) -> None:
    triples = {
        (
            normalize_name(citizen.full_name),
            citizen.date_of_birth,
            citizen.postal_code,
        )
        for citizen in fixture.citizens
    }
    assert len(triples) == len(fixture.citizens)

    name_counts = Counter(normalize_name(citizen.full_name) for citizen in fixture.citizens)
    duplicate_groups = [name for name, count in name_counts.items() if count >= 2]
    assert len(duplicate_groups) >= 2
    for name in duplicate_groups:
        group = [c for c in fixture.citizens if normalize_name(c.full_name) == name]
        assert len({(c.date_of_birth, c.postal_code) for c in group}) == len(group)


def test_seniors_and_senior_boundaries(fixture: Fixture) -> None:
    today = date.fromisoformat(fixture.meta.today)
    seniors = [
        c for c in fixture.citizens if age_on(date.fromisoformat(c.date_of_birth), today) >= 65
    ]
    assert len(seniors) >= 5

    by_dob = {c.date_of_birth: c for c in fixture.citizens}
    assert "1961-03-02" in by_dob
    assert "1961-03-03" in by_dob
    assert "1960-02-29" in by_dob
    assert age_on(date(1961, 3, 2), today) == 65
    assert age_on(date(1961, 3, 3), today) == 64
    assert age_on(date(1960, 2, 29), today) == 66


def test_parking_boundary_citizens_are_fully_eligible(fixture: Fixture) -> None:
    postal_areas = {postal.postal_code: postal.permit_area for postal in fixture.postal_codes}
    vehicle_counts = Counter(vehicle.citizen_id for vehicle in fixture.vehicles)
    for citizen in fixture.citizens:
        if citizen.date_of_birth not in {"1961-03-02", "1961-03-03"}:
            continue
        assert postal_areas[citizen.postal_code] is True
        assert vehicle_counts[citizen.citizen_id] >= 1
        assert not _has_active_parking_application(fixture, citizen.citizen_id)


def test_vehicle_and_address_distribution(fixture: Fixture) -> None:
    even_postal = [c for c in fixture.citizens if int(c.postal_code.split("-")[1]) % 2 == 0]
    assert len(even_postal) >= 6

    vehicle_counts = Counter(vehicle.citizen_id for vehicle in fixture.vehicles)
    zero = [c for c in fixture.citizens if vehicle_counts[c.citizen_id] == 0]
    two = [c for c in fixture.citizens if vehicle_counts[c.citizen_id] >= 2]
    assert len(zero) >= 3
    assert len(two) >= 3

    for vehicle in fixture.vehicles:
        assert normalize_plate(vehicle.license_plate) == vehicle.license_plate


def test_application_population(fixture: Fixture) -> None:
    assert len(fixture.applications) >= 15
    ids = [application.application_id for application in fixture.applications]
    assert len(ids) == len(set(ids))
    assert all(re.fullmatch(r"APP-[0-9A-F]{8}", application_id) for application_id in ids)

    today = fixture.meta.today
    for application in fixture.applications:
        assert application.service_type in {
            ServiceType.PARKING_PERMIT,
            ServiceType.BIRTH_CERTIFICATE_COPY,
        }
        assert application.payment_id is None
        assert application.submitted_on < today
        assert application.submitted_on <= application.updated_on <= today

    statuses = {application.status for application in fixture.applications}
    assert statuses == set(ApplicationStatus)


def test_active_and_rejected_permits(fixture: Fixture) -> None:
    active_citizens = {
        application.citizen_id
        for application in fixture.applications
        if application.service_type is ServiceType.PARKING_PERMIT
        and application.status in ACTIVE_APPLICATION_STATUSES
    }
    assert len(active_citizens) >= 3

    only_rejected = []
    for citizen in fixture.citizens:
        parking = [
            application
            for application in fixture.applications
            if application.citizen_id == citizen.citizen_id
            and application.service_type is ServiceType.PARKING_PERMIT
        ]
        if len(parking) == 1 and parking[0].status is ApplicationStatus.REJECTED:
            only_rejected.append(citizen.citizen_id)
    assert only_rejected


def test_birth_and_pickup_population(fixture: Fixture) -> None:
    assert sum(1 for citizen in fixture.citizens if not citizen.born_in_city) >= 5
    assert sum(1 for pickup in fixture.pickups if pickup.status is PickupStatus.SCHEDULED) >= 2


def test_issue_population(fixture: Fixture) -> None:
    assert len(fixture.issues) >= 10
    assert {issue.category for issue in fixture.issues} == set(IssueCategory)
    assert {issue.status for issue in fixture.issues} == set(IssueStatus)
    assert all(issue.reported_on < fixture.meta.today for issue in fixture.issues)
    for issue in fixture.issues:
        assert 1 <= len(issue.description) <= 500
        assert normalize_address(issue.street_address) == issue.street_address


def test_calendar_expands_to_business_day_slots(fixture: Fixture, store: Store) -> None:
    snapshot = store.snapshot()
    slots = snapshot["slots"]
    calendar = fixture.appointment_calendar
    assert len(slots) == calendar.business_days * len(calendar.times) * len(calendar.offices) == 120
    for slot in slots:
        assert re.fullmatch(r"SLOT-(CITY_HALL|NORTH_BRANCH)-\d{8}-\d{4}", slot["slot_id"])
        assert date.fromisoformat(slot["date"]).weekday() < 5
        assert slot["time"] in calendar.times
        assert slot["office"] in {"CITY_HALL", "NORTH_BRANCH"}


def test_appointment_population(fixture: Fixture) -> None:
    booked = [
        appointment
        for appointment in fixture.appointments
        if appointment.status is AppointmentStatus.BOOKED
    ]
    cancelled = [
        appointment
        for appointment in fixture.appointments
        if appointment.status is AppointmentStatus.CANCELLED
    ]
    assert len(booked) >= 30
    assert len(cancelled) >= 3

    slots = [appointment.slot_id for appointment in booked]
    assert len(slots) == len(set(slots))

    city_hall_0503 = {
        appointment.slot_id
        for appointment in booked
        if appointment.slot_id.startswith("SLOT-CITY_HALL-20260305-")
    }
    expected = {
        f"SLOT-CITY_HALL-20260305-{time.replace(':', '')}"
        for time in fixture.appointment_calendar.times
    }
    assert city_hall_0503 == expected


def test_pickups_respect_zone_calendar(fixture: Fixture) -> None:
    today = date.fromisoformat(fixture.meta.today)
    zone_by_postal = {postal.postal_code: postal.zone for postal in fixture.postal_codes}
    citizen_zone = {
        citizen.citizen_id: zone_by_postal[citizen.postal_code] for citizen in fixture.citizens
    }
    for pickup in fixture.pickups:
        if pickup.status is PickupStatus.SCHEDULED:
            offered = offered_pickup_dates(citizen_zone[pickup.citizen_id], today)
            assert pickup.date in offered
    completed = [pickup for pickup in fixture.pickups if pickup.status is PickupStatus.COMPLETED]
    assert len(completed) >= 3
    assert all(pickup.date < fixture.meta.today for pickup in completed)


def test_fixture_omits_computed_ids() -> None:
    raw = _raw_fixture()
    for key, identifier in (
        ("issues", "issue_id"),
        ("appointments", "appointment_id"),
        ("pickups", "pickup_id"),
    ):
        entries = raw[key]
        assert isinstance(entries, list)
        assert all(identifier not in entry for entry in entries)


def test_seeding_is_deterministic(fixture: Fixture, tmp_path: Path) -> None:
    first = Store.create_from_fixture(tmp_path / "first.db", fixture)
    second = Store.create_from_fixture(tmp_path / "second.db", fixture)
    assert first.snapshot() == second.snapshot()


def test_reseeding_requires_overwrite(fixture: Fixture, db_path: Path) -> None:
    before = Store(db_path).snapshot()
    Store.create_from_fixture(db_path, fixture, overwrite=True)
    assert Store(db_path).snapshot() == before


def test_issue_and_pickup_ids_are_computed(fixture: Fixture, store: Store) -> None:
    snapshot = store.snapshot()
    assert all(issue["issue_id"].startswith("ISS-") for issue in snapshot["issues"])
    assert all(pickup["pickup_id"].startswith("PKP-") for pickup in snapshot["pickups"])
    assert all(
        appointment["appointment_id"].startswith("APT-") for appointment in snapshot["appointments"]
    )


def test_snapshot_covers_every_table(store: Store) -> None:
    snapshot = store.snapshot()
    assert set(snapshot) == {
        "applications",
        "appointments",
        "citizens",
        "escalations",
        "issues",
        "meta",
        "payments",
        "pickups",
        "postal_codes",
        "quotes",
        "slots",
        "vehicles",
    }
    for table, rows in snapshot.items():
        if table == "meta":
            assert {row["key"] for row in rows} == {"today", "fixture_name"}
            continue
        primary_keys = [next(iter(row.values())) for row in rows]
        assert primary_keys == sorted(primary_keys)


def test_slot_booked_counts_at_most_one(store: Store) -> None:
    booked_per_slot: dict[str, int] = defaultdict(int)
    for appointment in store.snapshot()["appointments"]:
        if appointment["status"] == AppointmentStatus.BOOKED:
            booked_per_slot[appointment["slot_id"]] += 1
    assert all(count == 1 for count in booked_per_slot.values())
