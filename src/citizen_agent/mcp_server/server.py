"""MCP server exposing the Civitas domain as 17 deterministic tools."""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import WithJsonSchema

from citizen_agent.domain.enums import (
    AppointmentPurpose,
    IssueCategory,
    Office,
    ServiceType,
)
from citizen_agent.domain.errors import DomainError
from citizen_agent.domain.models import (
    ApplicationResult,
    AppointmentResult,
    CancelAppointmentResult,
    CaseStatusResult,
    CitizenProfile,
    EligibilityResult,
    EscalationResult,
    IssueResult,
    PaymentResult,
    PickupDatesResult,
    PickupResult,
    QuoteResult,
    ServiceInfoResult,
    SlotsResult,
    UpdateAddressResult,
    VerifyCitizenResult,
)
from citizen_agent.domain.services import CitizenServices

logger = logging.getLogger("citizen_agent.mcp")

ServiceTypeArg = Annotated[
    ServiceType,
    WithJsonSchema({"type": "string", "enum": [member.value for member in ServiceType]}),
]
IssueCategoryArg = Annotated[
    IssueCategory,
    WithJsonSchema({"type": "string", "enum": [member.value for member in IssueCategory]}),
]
OfficeArg = Annotated[
    Office,
    WithJsonSchema({"type": "string", "enum": [member.value for member in Office]}),
]
AppointmentPurposeArg = Annotated[
    AppointmentPurpose,
    WithJsonSchema({"type": "string", "enum": [member.value for member in AppointmentPurpose]}),
]

READ_ONLY = ToolAnnotations(read_only_hint=True)
IDEMPOTENT_WRITE = ToolAnnotations(read_only_hint=False, idempotent_hint=True)
DESTRUCTIVE_WRITE = ToolAnnotations(
    read_only_hint=False, idempotent_hint=True, destructive_hint=True
)


@contextmanager
def _guard(tool: str) -> Iterator[None]:
    """Translate domain failures into MCP tool errors and log one line per call."""
    started = time.perf_counter()
    try:
        yield
    except DomainError as exc:
        _log_outcome(tool, exc.code.value, started)
        raise ToolError(f"{exc.code.value}: {exc.message}") from exc
    except Exception:
        logger.exception("Tool %r raised an unexpected exception", tool)
        _log_outcome(tool, "INTERNAL_ERROR", started)
        raise ToolError("INTERNAL_ERROR: unexpected server error") from None
    else:
        _log_outcome(tool, "ok", started)


def _log_outcome(tool: str, outcome: str, started: float) -> None:
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    logger.info("tool=%s outcome=%s duration_ms=%.1f", tool, outcome, elapsed_ms)


def build_server(services: CitizenServices) -> MCPServer[Any]:
    """Create a fresh MCP server bound to a service instance."""
    server: MCPServer[Any] = MCPServer(
        name="civitas-citizen-services",
        version="0.1.0",
        instructions=(
            "Deterministic citizen services for the fictional city of Civitas. "
            "Verify identity first, then pass the returned citizen_token to "
            "citizen-scoped tools. All dates use YYYY-MM-DD."
        ),
    )

    # -- identity and profile -------------------------------------------

    @server.tool(
        name="verify_citizen",
        description=(
            "Verify a citizen's identity and mint a signed citizen token. Use before any "
            "citizen-scoped tool when no token is available. Requires full_name, "
            "date_of_birth (YYYY-MM-DD), and postal_code (CV-###). Errors: "
            "INVALID_ARGUMENT for malformed input; VERIFICATION_FAILED when no record matches."
        ),
        annotations=READ_ONLY,
    )
    def verify_citizen(full_name: str, date_of_birth: str, postal_code: str) -> VerifyCitizenResult:
        with _guard("verify_citizen"):
            return services.verify_citizen(full_name, date_of_birth, postal_code)

    @server.tool(
        name="get_citizen_profile",
        description=(
            "Return the citizen's profile, vehicles, applications, booked appointments, and "
            "scheduled pickups. Use after verify_citizen when the citizen asks about their own "
            "record. Requires citizen_token from verify_citizen. Errors: INVALID_TOKEN."
        ),
        annotations=READ_ONLY,
    )
    def get_citizen_profile(citizen_token: str) -> CitizenProfile:
        with _guard("get_citizen_profile"):
            return services.get_citizen_profile(citizen_token)

    @server.tool(
        name="update_address",
        description=(
            "Update the citizen's street address. Use when the citizen reports a move. "
            "Requires citizen_token from verify_citizen; postal_code must be a Civitas code "
            "(CV-###). Repeating the same address returns changed=false. Errors: "
            "INVALID_ARGUMENT, INVALID_TOKEN, INVALID_POSTAL_CODE."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def update_address(
        citizen_token: str, street_address: str, postal_code: str
    ) -> UpdateAddressResult:
        with _guard("update_address"):
            return services.update_address(citizen_token, street_address, postal_code)

    # -- catalog and eligibility ----------------------------------------

    @server.tool(
        name="get_service_info",
        description=(
            "Describe a Civitas service: requirements, fee rules, and processing days. Use "
            "when a citizen asks what a service needs or costs. service_type is one of the six "
            "Civitas service values; the MCP schema rejects unknown values. No citizen token "
            "is needed."
        ),
        annotations=READ_ONLY,
    )
    def get_service_info(service_type: ServiceTypeArg) -> ServiceInfoResult:
        with _guard("get_service_info"):
            return services.get_service_info(service_type)

    @server.tool(
        name="check_eligibility",
        description=(
            "Check whether the citizen is eligible for a service and return every reason "
            "code. Use before quoting or applying. Requires citizen_token from verify_citizen. "
            "service_type is one of the six Civitas service values. Errors: INVALID_TOKEN."
        ),
        annotations=READ_ONLY,
    )
    def check_eligibility(citizen_token: str, service_type: ServiceTypeArg) -> EligibilityResult:
        with _guard("check_eligibility"):
            return services.check_eligibility(citizen_token, service_type)

    # -- fees and payments ----------------------------------------------

    @server.tool(
        name="quote_fee",
        description=(
            "Create or replay a fee quote for a paid service. Use only for parking permits "
            "and birth certificate copies. Requires citizen_token from verify_citizen. "
            "quantity is 1 for parking and 1-5 for birth copies. Repeating the same request "
            "returns created=false. Errors: INVALID_TOKEN, NO_FEE_REQUIRED, INVALID_QUANTITY, "
            "NOT_ELIGIBLE."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def quote_fee(
        citizen_token: str, service_type: ServiceTypeArg, quantity: int = 1
    ) -> QuoteResult:
        with _guard("quote_fee"):
            return services.quote_fee(citizen_token, service_type, quantity)

    @server.tool(
        name="pay_quote",
        description=(
            "Charge the simulated card on file for a quote; never pass card details. Call only "
            "after the citizen explicitly confirmed paying the quoted amount. Requires "
            "citizen_token from verify_citizen and a quote_id from quote_fee. Replays return "
            "the existing payment without a second charge. Errors: INVALID_TOKEN, NOT_FOUND, "
            "NOT_ELIGIBLE."
        ),
        annotations=DESTRUCTIVE_WRITE,
    )
    def pay_quote(citizen_token: str, quote_id: str) -> PaymentResult:
        with _guard("pay_quote"):
            return services.pay_quote(citizen_token, quote_id)

    # -- applications ---------------------------------------------------

    @server.tool(
        name="apply_parking_permit",
        description=(
            "Submit a parking permit application for a paid quote. Requires citizen_token from "
            "verify_citizen, a license plate registered to the citizen, and a parking "
            "payment_id from pay_quote. Quote and pay first. Repeating the same plate replays "
            "the application. Errors: INVALID_ARGUMENT, INVALID_TOKEN, NOT_FOUND, "
            "PAYMENT_INVALID, PAYMENT_ALREADY_USED, PLATE_NOT_REGISTERED, NOT_ELIGIBLE."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def apply_parking_permit(
        citizen_token: str, license_plate: str, payment_id: str
    ) -> ApplicationResult:
        with _guard("apply_parking_permit"):
            return services.apply_parking_permit(citizen_token, license_plate, payment_id)

    @server.tool(
        name="request_birth_certificate",
        description=(
            "Request certified copies of the citizen's Civitas birth certificate. Requires "
            "citizen_token from verify_citizen, copies between 1 and 5, and a birth-certificate "
            "payment_id from pay_quote. Repeating the same copies replays the application. "
            "Errors: INVALID_QUANTITY, INVALID_TOKEN, NOT_FOUND, PAYMENT_INVALID, "
            "PAYMENT_ALREADY_USED, NOT_ELIGIBLE."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def request_birth_certificate(
        citizen_token: str, copies: int, payment_id: str
    ) -> ApplicationResult:
        with _guard("request_birth_certificate"):
            return services.request_birth_certificate(citizen_token, copies, payment_id)

    # -- bulk waste -----------------------------------------------------

    @server.tool(
        name="list_pickup_dates",
        description=(
            "List the next four bulk-waste pickup dates (YYYY-MM-DD) offered in the citizen's "
            "zone. Use before schedule_bulk_pickup. Requires citizen_token from verify_citizen. "
            "Errors: INVALID_TOKEN."
        ),
        annotations=READ_ONLY,
    )
    def list_pickup_dates(citizen_token: str) -> PickupDatesResult:
        with _guard("list_pickup_dates"):
            return services.list_pickup_dates(citizen_token)

    @server.tool(
        name="schedule_bulk_pickup",
        description=(
            "Schedule one bulk-waste pickup. Requires citizen_token from verify_citizen; date "
            "must come from list_pickup_dates (YYYY-MM-DD) and item_count must be 1-5. Only "
            "one scheduled pickup is allowed. Repeating the same request returns created=false. "
            "Errors: INVALID_QUANTITY, INVALID_TOKEN, ALREADY_SCHEDULED, DATE_UNAVAILABLE."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def schedule_bulk_pickup(citizen_token: str, date: str, item_count: int) -> PickupResult:
        with _guard("schedule_bulk_pickup"):
            return services.schedule_bulk_pickup(citizen_token, date, item_count)

    # -- street issues and cases ---------------------------------------

    @server.tool(
        name="report_street_issue",
        description=(
            "Report a street issue without authentication. category is POTHOLE, STREETLIGHT, "
            "GRAFFITI, or MISSED_COLLECTION; street_address is free text; description is 1-500 "
            "characters. Repeating the same report today returns the existing case. Errors: "
            "INVALID_ARGUMENT."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def report_street_issue(
        category: IssueCategoryArg, street_address: str, description: str
    ) -> IssueResult:
        with _guard("report_street_issue"):
            return services.report_street_issue(category, street_address, description)

    @server.tool(
        name="get_case_status",
        description=(
            "Look up an application or street issue by case ID. APP- IDs require citizen_token "
            "from verify_citizen and must belong to that citizen; ISS- IDs are public and ignore "
            "the token. Use when a citizen asks about an existing case. Errors: AUTH_REQUIRED, "
            "INVALID_TOKEN, NOT_FOUND."
        ),
        annotations=READ_ONLY,
    )
    def get_case_status(case_id: str, citizen_token: str | None = None) -> CaseStatusResult:
        with _guard("get_case_status"):
            return services.get_case_status(case_id, citizen_token)

    # -- appointments ---------------------------------------------------

    @server.tool(
        name="list_appointment_slots",
        description=(
            "List free 30-minute appointment slots at an office. office is CITY_HALL or "
            "NORTH_BRANCH; date is YYYY-MM-DD. Use before book_appointment. Returns an empty "
            "list when none are free. Errors: INVALID_ARGUMENT for a malformed date."
        ),
        annotations=READ_ONLY,
    )
    def list_appointment_slots(office: OfficeArg, date: str) -> SlotsResult:
        with _guard("list_appointment_slots"):
            return services.list_appointment_slots(office, date)

    @server.tool(
        name="book_appointment",
        description=(
            "Book a free office appointment using a slot_id from list_appointment_slots. "
            "Requires citizen_token from verify_citizen; purpose is ID_CARD, PERMIT_PICKUP, or "
            "GENERAL_INQUIRY. Repeating a booked slot replays it; rebooking after cancellation "
            "is supported. Errors: INVALID_TOKEN, NOT_FOUND, SLOT_UNAVAILABLE."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def book_appointment(
        citizen_token: str, slot_id: str, purpose: AppointmentPurposeArg
    ) -> AppointmentResult:
        with _guard("book_appointment"):
            return services.book_appointment(citizen_token, slot_id, purpose)

    @server.tool(
        name="cancel_appointment",
        description=(
            "Cancel the citizen's booked appointment and free its slot. Requires citizen_token "
            "from verify_citizen and an appointment_id from get_citizen_profile. Repeating the "
            "cancellation returns changed=false. Errors: INVALID_TOKEN, NOT_FOUND."
        ),
        annotations=DESTRUCTIVE_WRITE,
    )
    def cancel_appointment(citizen_token: str, appointment_id: str) -> CancelAppointmentResult:
        with _guard("cancel_appointment"):
            return services.cancel_appointment(citizen_token, appointment_id)

    # -- escalation -----------------------------------------------------

    @server.tool(
        name="escalate_to_human",
        description=(
            "Create a human-handoff escalation with a 1-1000 character summary. citizen_token "
            "is optional but must be valid when supplied. A citizen's escalation deduplicates "
            "per day; anonymous escalations deduplicate only when the summary text matches. "
            "Errors: INVALID_ARGUMENT, INVALID_TOKEN."
        ),
        annotations=IDEMPOTENT_WRITE,
    )
    def escalate_to_human(summary: str, citizen_token: str | None = None) -> EscalationResult:
        with _guard("escalate_to_human"):
            return services.escalate_to_human(summary, citizen_token)

    return server
