"""Business constants and pure policy rules for Civitas services."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from .enums import ApplicationStatus, ErrorCode, IneligibilityReason, ServiceType, Zone
from .errors import DomainError

PARKING_PERMIT_FEE_CENTS = 6000
PARKING_PERMIT_QUANTITY = 1
PARKING_PERMIT_SENIOR_FEE_CENTS = 3000
BIRTH_CERTIFICATE_COPY_FEE_CENTS = 1500
SENIOR_AGE = 65
MAX_BIRTH_CERTIFICATE_COPIES = 5
MAX_BULK_ITEMS = 5
MAX_ISSUE_DESCRIPTION_LENGTH = 500
MAX_ESCALATION_SUMMARY_LENGTH = 1000
OFFERED_PICKUP_DATES = 4

ZONE_PICKUP_WEEKDAY: dict[Zone, int] = {
    Zone.NORTH: 1,  # Tuesday
    Zone.SOUTH: 2,  # Wednesday
    Zone.EAST: 3,  # Thursday
    Zone.WEST: 4,  # Friday
}

ACTIVE_APPLICATION_STATUSES: frozenset[ApplicationStatus] = frozenset(
    {
        ApplicationStatus.SUBMITTED,
        ApplicationStatus.IN_REVIEW,
        ApplicationStatus.APPROVED,
    }
)


@dataclass(frozen=True)
class ServiceInfo:
    title: str
    description: str
    requirements: tuple[str, ...]
    fee_rules: str
    processing_days: int


SERVICE_CATALOG: dict[ServiceType, ServiceInfo] = {
    ServiceType.PARKING_PERMIT: ServiceInfo(
        title="Residential Parking Permit",
        description="Annual residential parking permit for a registered vehicle.",
        requirements=(
            "Verified identity",
            "Address in a permit-area postal code",
            "Vehicle registered to the applicant",
            "No active permit",
        ),
        fee_rules="$60.00 per year; $30.00 for residents aged 65+",
        processing_days=5,
    ),
    ServiceType.BIRTH_CERTIFICATE_COPY: ServiceInfo(
        title="Birth Certificate Copy",
        description="Certified copy of the applicant's own Civitas birth certificate.",
        requirements=(
            "Verified identity",
            "Birth registered in Civitas",
        ),
        fee_rules="$15.00 per copy, 1\u20135 copies",
        processing_days=7,
    ),
    ServiceType.BULK_WASTE_PICKUP: ServiceInfo(
        title="Bulk Waste Pickup",
        description="Curbside pickup for up to five bulky household items.",
        requirements=(
            "Verified identity",
            "Up to 5 items",
            "One scheduled pickup at a time",
        ),
        fee_rules="Free",
        processing_days=0,
    ),
    ServiceType.ADDRESS_CHANGE: ServiceInfo(
        title="Address Change",
        description="Update the address on a citizen record.",
        requirements=(
            "Verified identity",
            "New address with a Civitas postal code (CV-101..CV-108)",
        ),
        fee_rules="Free",
        processing_days=0,
    ),
    ServiceType.STREET_ISSUE_REPORT: ServiceInfo(
        title="Street Issue Report",
        description="Report a pothole, streetlight problem, graffiti, or missed collection.",
        requirements=(
            "Issue category",
            "Street address",
            "Short description",
            "No identity needed",
        ),
        fee_rules="Free",
        processing_days=3,
    ),
    ServiceType.OFFICE_APPOINTMENT: ServiceInfo(
        title="Office Appointment",
        description="Book a 30-minute in-person appointment at a Civitas office.",
        requirements=(
            "Verified identity",
            "Offices CITY_HALL and NORTH_BRANCH",
            "30-minute slots 09:00\u201311:30 on business days",
        ),
        fee_rules="Free",
        processing_days=0,
    ),
}


def age_on(date_of_birth: date, today: date) -> int:
    """Calendar age in whole years, safe for February 29 births."""
    return (
        today.year
        - date_of_birth.year
        - ((today.month, today.day) < (date_of_birth.month, date_of_birth.day))
    )


def is_senior(date_of_birth: date, today: date) -> bool:
    return age_on(date_of_birth, today) >= SENIOR_AGE


def parking_fee_cents(date_of_birth: date, today: date) -> int:
    if is_senior(date_of_birth, today):
        return PARKING_PERMIT_SENIOR_FEE_CENTS
    return PARKING_PERMIT_FEE_CENTS


def quote_amount_cents(
    service_type: ServiceType,
    quantity: int,
    *,
    date_of_birth: date,
    today: date,
) -> int:
    """Price a quote, enforcing service-specific quantity rules."""
    if service_type is ServiceType.PARKING_PERMIT:
        if quantity != PARKING_PERMIT_QUANTITY:
            raise DomainError(
                ErrorCode.INVALID_QUANTITY,
                "Parking permits require a quantity of 1.",
            )
        return parking_fee_cents(date_of_birth, today)
    if service_type is ServiceType.BIRTH_CERTIFICATE_COPY:
        if quantity < 1 or quantity > MAX_BIRTH_CERTIFICATE_COPIES:
            raise DomainError(
                ErrorCode.INVALID_QUANTITY,
                "Birth certificate copies must be between 1 and 5.",
            )
        return BIRTH_CERTIFICATE_COPY_FEE_CENTS * quantity
    raise DomainError(ErrorCode.NO_FEE_REQUIRED, "This service does not require a fee.")


def pickup_weekday(zone: Zone) -> int:
    return ZONE_PICKUP_WEEKDAY[zone]


def offered_pickup_dates(zone: Zone, today: date) -> list[str]:
    """The next four zone pickup weekdays strictly after today."""
    weekday = pickup_weekday(zone)
    dates: list[str] = []
    candidate = today + timedelta(days=1)
    while len(dates) < OFFERED_PICKUP_DATES:
        if candidate.weekday() == weekday:
            dates.append(candidate.isoformat())
        candidate += timedelta(days=1)
    return dates


def eligibility_reasons(
    service_type: ServiceType,
    *,
    postal_permit_area: bool,
    vehicle_count: int,
    has_active_permit: bool,
    born_in_city: bool,
    has_scheduled_pickup: bool,
) -> list[IneligibilityReason]:
    """Return every applicable reason, in the documented order."""
    reasons: list[IneligibilityReason] = []
    if service_type is ServiceType.PARKING_PERMIT:
        if not postal_permit_area:
            reasons.append(IneligibilityReason.NOT_IN_PERMIT_AREA)
        if vehicle_count < 1:
            reasons.append(IneligibilityReason.NO_REGISTERED_VEHICLE)
        if has_active_permit:
            reasons.append(IneligibilityReason.ACTIVE_PERMIT_EXISTS)
    elif service_type is ServiceType.BIRTH_CERTIFICATE_COPY:
        if not born_in_city:
            reasons.append(IneligibilityReason.NO_BIRTH_RECORD)
    elif service_type is ServiceType.BULK_WASTE_PICKUP:
        if has_scheduled_pickup:
            reasons.append(IneligibilityReason.PICKUP_ALREADY_SCHEDULED)
    return reasons
