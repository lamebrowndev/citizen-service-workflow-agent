"""Pydantic models for fixture validation and tool results."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from .enums import (
    ApplicationStatus,
    AppointmentPurpose,
    AppointmentStatus,
    IneligibilityReason,
    IssueCategory,
    IssueStatus,
    Office,
    PickupStatus,
    ServiceType,
    Zone,
)

# ---------------------------------------------------------------------------
# Fixture models (strict: unknown keys are rejected)
# ---------------------------------------------------------------------------


class _FixtureModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class FixtureMeta(_FixtureModel):
    today: str
    fixture_name: str


class FixturePostalCode(_FixtureModel):
    postal_code: str
    zone: Zone
    permit_area: bool


class FixtureCitizen(_FixtureModel):
    citizen_id: str
    full_name: str
    date_of_birth: str
    street_address: str
    postal_code: str
    born_in_city: bool


class FixtureVehicle(_FixtureModel):
    license_plate: str
    citizen_id: str


class FixtureApplication(_FixtureModel):
    application_id: str
    citizen_id: str
    service_type: ServiceType
    status: ApplicationStatus
    payment_id: str | None = None
    submitted_on: str
    updated_on: str


class FixtureIssue(_FixtureModel):
    category: IssueCategory
    street_address: str
    description: str
    status: IssueStatus
    reported_on: str


class AppointmentCalendar(_FixtureModel):
    start_date: str
    business_days: int
    times: list[str]
    offices: list[Office]


class FixtureAppointment(_FixtureModel):
    citizen_id: str
    slot_id: str
    purpose: AppointmentPurpose
    status: AppointmentStatus


class FixturePickup(_FixtureModel):
    citizen_id: str
    date: str
    item_count: int
    status: PickupStatus


class Fixture(_FixtureModel):
    meta: FixtureMeta
    postal_codes: list[FixturePostalCode]
    citizens: list[FixtureCitizen]
    vehicles: list[FixtureVehicle]
    applications: list[FixtureApplication]
    issues: list[FixtureIssue]
    appointment_calendar: AppointmentCalendar
    appointments: list[FixtureAppointment]
    pickups: list[FixturePickup]


# ---------------------------------------------------------------------------
# Tool results
# ---------------------------------------------------------------------------


class VerifyCitizenResult(BaseModel):
    citizen_token: str
    full_name: str


class VehicleInfo(BaseModel):
    license_plate: str


class ApplicationSummary(BaseModel):
    application_id: str
    service_type: ServiceType
    status: ApplicationStatus


class AppointmentSummary(BaseModel):
    appointment_id: str
    slot_id: str
    office: Office
    date: str
    time: str
    purpose: AppointmentPurpose


class PickupSummary(BaseModel):
    pickup_id: str
    date: str
    item_count: int


class CitizenProfile(BaseModel):
    citizen_id: str
    full_name: str
    street_address: str
    postal_code: str
    zone: Zone
    permit_area: bool
    vehicles: list[VehicleInfo]
    applications: list[ApplicationSummary]
    appointments: list[AppointmentSummary]
    pickups: list[PickupSummary]


class UpdateAddressResult(BaseModel):
    citizen_id: str
    street_address: str
    postal_code: str
    zone: Zone
    permit_area: bool
    changed: bool


class ServiceInfoResult(BaseModel):
    service_type: ServiceType
    title: str
    description: str
    requirements: list[str]
    fee_rules: str
    processing_days: int


class EligibilityResult(BaseModel):
    service_type: ServiceType
    eligible: bool
    reasons: list[IneligibilityReason]


class QuoteResult(BaseModel):
    quote_id: str
    service_type: ServiceType
    quantity: int
    amount_cents: int
    currency: Literal["USD"] = "USD"
    created: bool


class PaymentResult(BaseModel):
    payment_id: str
    quote_id: str
    amount_cents: int
    status: Literal["PAID"] = "PAID"
    created: bool


class ApplicationResult(BaseModel):
    application_id: str
    service_type: ServiceType
    status: ApplicationStatus
    created: bool


class PickupDatesResult(BaseModel):
    zone: Zone
    dates: list[str]


class PickupResult(BaseModel):
    pickup_id: str
    date: str
    item_count: int
    status: PickupStatus
    created: bool


class IssueResult(BaseModel):
    issue_id: str
    status: IssueStatus
    created: bool


class CaseStatusResult(BaseModel):
    case_id: str
    case_type: Literal["APPLICATION", "ISSUE"]
    status: str
    subject: str
    updated_on: str


class SlotInfo(BaseModel):
    slot_id: str
    time: str


class SlotsResult(BaseModel):
    office: Office
    date: str
    slots: list[SlotInfo]


class AppointmentResult(BaseModel):
    appointment_id: str
    slot_id: str
    office: Office
    date: str
    time: str
    purpose: AppointmentPurpose
    status: AppointmentStatus
    created: bool


class CancelAppointmentResult(BaseModel):
    appointment_id: str
    status: Literal[AppointmentStatus.CANCELLED] = AppointmentStatus.CANCELLED
    changed: bool


class EscalationResult(BaseModel):
    escalation_id: str
    created: bool
