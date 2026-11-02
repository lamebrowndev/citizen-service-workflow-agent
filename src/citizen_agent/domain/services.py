"""Deterministic citizen services: one method per MCP tool."""

from __future__ import annotations

import json
import sqlite3
from datetime import date as Date

from .enums import (
    ApplicationStatus,
    AppointmentPurpose,
    AppointmentStatus,
    ErrorCode,
    IneligibilityReason,
    IssueCategory,
    IssueStatus,
    Office,
    PickupStatus,
    ServiceType,
    Zone,
)
from .errors import DomainError
from .ids import citizen_token, make_id, verify_token
from .models import (
    ApplicationResult,
    ApplicationSummary,
    AppointmentResult,
    AppointmentSummary,
    CancelAppointmentResult,
    CaseStatusResult,
    CitizenProfile,
    EligibilityResult,
    EscalationResult,
    IssueResult,
    PaymentResult,
    PickupDatesResult,
    PickupResult,
    PickupSummary,
    QuoteResult,
    ServiceInfoResult,
    SlotInfo,
    SlotsResult,
    UpdateAddressResult,
    VehicleInfo,
    VerifyCitizenResult,
)
from .normalize import (
    normalize_address,
    normalize_date,
    normalize_id,
    normalize_name,
    normalize_plate,
    normalize_postal_code,
    normalize_text,
)
from .policy import (
    ACTIVE_APPLICATION_STATUSES,
    MAX_BIRTH_CERTIFICATE_COPIES,
    MAX_BULK_ITEMS,
    MAX_ESCALATION_SUMMARY_LENGTH,
    MAX_ISSUE_DESCRIPTION_LENGTH,
    SERVICE_CATALOG,
    eligibility_reasons,
    offered_pickup_dates,
    quote_amount_cents,
)
from .store import Store, fetch_all, fetch_one, insert_row

_ACTIVE_STATUS_VALUES = tuple(status.value for status in ACTIVE_APPLICATION_STATUSES)


class CitizenServices:
    """Business operations behind the MCP tools.

    Each method is one transaction. A ``DomainError`` rolls the transaction
    back, so failed operations leave the database unchanged.
    """

    def __init__(self, store: Store, token_secret: bytes) -> None:
        self._store = store
        self._secret = token_secret

    # -- internals --------------------------------------------------------

    def _verify_citizen(self, conn: sqlite3.Connection, token: str) -> sqlite3.Row:
        citizen_id = verify_token(self._secret, token)
        row = fetch_one(conn, "SELECT * FROM citizens WHERE citizen_id = ?", (citizen_id,))
        if row is None:
            raise DomainError(ErrorCode.INVALID_TOKEN, "Citizen token is invalid.")
        return row

    @staticmethod
    def _today(conn: sqlite3.Connection) -> Date:
        row = fetch_one(conn, "SELECT value FROM meta WHERE key = 'today'")
        if row is None:
            raise DomainError(ErrorCode.INTERNAL_ERROR, "The database clock is not configured.")
        return Date.fromisoformat(str(row["value"]))

    @staticmethod
    def _postal_row(conn: sqlite3.Connection, postal_code: str) -> sqlite3.Row:
        row = fetch_one(conn, "SELECT * FROM postal_codes WHERE postal_code = ?", (postal_code,))
        if row is None:
            raise DomainError(
                ErrorCode.INTERNAL_ERROR, "The citizen postal code is not configured."
            )
        return row

    @staticmethod
    def _vehicle_count(conn: sqlite3.Connection, citizen_id: str) -> int:
        row = fetch_one(
            conn, "SELECT COUNT(*) AS count FROM vehicles WHERE citizen_id = ?", (citizen_id,)
        )
        if row is None:
            return 0
        return int(row["count"])

    @staticmethod
    def _has_active_permit(conn: sqlite3.Connection, citizen_id: str) -> bool:
        placeholders = ", ".join("?" for _ in _ACTIVE_STATUS_VALUES)
        row = fetch_one(
            conn,
            "SELECT 1 FROM applications WHERE citizen_id = ? AND service_type = ? "
            f"AND status IN ({placeholders}) LIMIT 1",
            (citizen_id, ServiceType.PARKING_PERMIT.value, *_ACTIVE_STATUS_VALUES),
        )
        return row is not None

    @staticmethod
    def _has_scheduled_pickup(conn: sqlite3.Connection, citizen_id: str) -> bool:
        row = fetch_one(
            conn,
            "SELECT 1 FROM pickups WHERE citizen_id = ? AND status = ? LIMIT 1",
            (citizen_id, PickupStatus.SCHEDULED.value),
        )
        return row is not None

    def _reasons(
        self, conn: sqlite3.Connection, citizen: sqlite3.Row, service_type: ServiceType
    ) -> list[IneligibilityReason]:
        citizen_id = str(citizen["citizen_id"])
        postal = self._postal_row(conn, str(citizen["postal_code"]))
        return eligibility_reasons(
            service_type,
            postal_permit_area=bool(postal["permit_area"]),
            vehicle_count=self._vehicle_count(conn, citizen_id),
            has_active_permit=self._has_active_permit(conn, citizen_id),
            born_in_city=bool(citizen["born_in_city"]),
            has_scheduled_pickup=self._has_scheduled_pickup(conn, citizen_id),
        )

    @staticmethod
    def _require_reasons(result: list[IneligibilityReason]) -> None:
        if result:
            codes = ", ".join(reason.value for reason in result)
            raise DomainError(
                ErrorCode.NOT_ELIGIBLE,
                f"Service is not available for this citizen: {codes}.",
            )

    @staticmethod
    def _payment_for(conn: sqlite3.Connection, citizen_id: str, payment_id: str) -> sqlite3.Row:
        row = fetch_one(
            conn,
            "SELECT * FROM payments WHERE payment_id = ? AND citizen_id = ?",
            (payment_id, citizen_id),
        )
        if row is None:
            raise DomainError(ErrorCode.NOT_FOUND, "Payment not found.")
        return row

    @staticmethod
    def _application_for(
        conn: sqlite3.Connection, citizen_id: str, service_type: ServiceType, payment_id: str
    ) -> sqlite3.Row | None:
        application_id = make_id("APP", citizen_id, service_type.value, payment_id)
        return fetch_one(
            conn,
            "SELECT * FROM applications WHERE application_id = ? AND citizen_id = ?",
            (application_id, citizen_id),
        )

    # -- reads ------------------------------------------------------------

    def verify_citizen(
        self, full_name: str, date_of_birth: str, postal_code: str
    ) -> VerifyCitizenResult:
        name = normalize_name(full_name)
        dob = normalize_date(date_of_birth)
        postal = normalize_postal_code(postal_code)
        with self._store.read() as conn:
            rows = fetch_all(
                conn,
                "SELECT * FROM citizens WHERE date_of_birth = ? AND postal_code = ? "
                "ORDER BY citizen_id",
                (dob, postal),
            )
            for row in rows:
                if normalize_name(str(row["full_name"])) == name:
                    citizen_id = str(row["citizen_id"])
                    return VerifyCitizenResult(
                        citizen_token=citizen_token(self._secret, citizen_id),
                        full_name=str(row["full_name"]),
                    )
        raise DomainError(ErrorCode.VERIFICATION_FAILED, "Identity verification failed.")

    def get_citizen_profile(self, citizen_token: str) -> CitizenProfile:
        with self._store.read() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            postal = self._postal_row(conn, str(citizen["postal_code"]))

            vehicles = [
                VehicleInfo(license_plate=str(row["license_plate"]))
                for row in fetch_all(
                    conn,
                    "SELECT license_plate FROM vehicles WHERE citizen_id = ? "
                    "ORDER BY license_plate",
                    (citizen_id,),
                )
            ]
            applications = [
                ApplicationSummary(
                    application_id=str(row["application_id"]),
                    service_type=ServiceType(str(row["service_type"])),
                    status=ApplicationStatus(str(row["status"])),
                )
                for row in fetch_all(
                    conn,
                    "SELECT application_id, service_type, status FROM applications "
                    "WHERE citizen_id = ? ORDER BY application_id",
                    (citizen_id,),
                )
            ]
            appointments = [
                AppointmentSummary(
                    appointment_id=str(row["appointment_id"]),
                    slot_id=str(row["slot_id"]),
                    office=Office(str(row["office"])),
                    date=str(row["slot_date"]),
                    time=str(row["time"]),
                    purpose=AppointmentPurpose(str(row["purpose"])),
                )
                for row in fetch_all(
                    conn,
                    "SELECT a.appointment_id, a.slot_id, a.purpose, s.office, "
                    "s.date AS slot_date, s.time "
                    "FROM appointments a JOIN slots s ON s.slot_id = a.slot_id "
                    "WHERE a.citizen_id = ? AND a.status = ? ORDER BY a.appointment_id",
                    (citizen_id, AppointmentStatus.BOOKED.value),
                )
            ]
            pickups = [
                PickupSummary(
                    pickup_id=str(row["pickup_id"]),
                    date=str(row["date"]),
                    item_count=int(row["item_count"]),
                )
                for row in fetch_all(
                    conn,
                    "SELECT pickup_id, date, item_count FROM pickups "
                    "WHERE citizen_id = ? AND status = ? ORDER BY pickup_id",
                    (citizen_id, PickupStatus.SCHEDULED.value),
                )
            ]
            return CitizenProfile(
                citizen_id=citizen_id,
                full_name=str(citizen["full_name"]),
                street_address=str(citizen["street_address"]),
                postal_code=str(citizen["postal_code"]),
                zone=Zone(str(postal["zone"])),
                permit_area=bool(postal["permit_area"]),
                vehicles=vehicles,
                applications=applications,
                appointments=appointments,
                pickups=pickups,
            )

    def get_service_info(self, service_type: ServiceType) -> ServiceInfoResult:
        info = SERVICE_CATALOG[service_type]
        return ServiceInfoResult(
            service_type=service_type,
            title=info.title,
            description=info.description,
            requirements=list(info.requirements),
            fee_rules=info.fee_rules,
            processing_days=info.processing_days,
        )

    def check_eligibility(self, citizen_token: str, service_type: ServiceType) -> EligibilityResult:
        with self._store.read() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            reasons = self._reasons(conn, citizen, service_type)
            return EligibilityResult(
                service_type=service_type,
                eligible=not reasons,
                reasons=reasons,
            )

    def list_pickup_dates(self, citizen_token: str) -> PickupDatesResult:
        with self._store.read() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            postal = self._postal_row(conn, str(citizen["postal_code"]))
            today = self._today(conn)
            zone = Zone(str(postal["zone"]))
            return PickupDatesResult(zone=zone, dates=offered_pickup_dates(zone, today))

    def get_case_status(self, case_id: str, citizen_token: str | None = None) -> CaseStatusResult:
        normalized = normalize_id(case_id)
        with self._store.read() as conn:
            if normalized.startswith("APP-"):
                if citizen_token is None:
                    raise DomainError(
                        ErrorCode.AUTH_REQUIRED, "A citizen token is required for applications."
                    )
                citizen = self._verify_citizen(conn, citizen_token)
                row = fetch_one(
                    conn,
                    "SELECT * FROM applications WHERE application_id = ? AND citizen_id = ?",
                    (normalized, str(citizen["citizen_id"])),
                )
                if row is None:
                    raise DomainError(ErrorCode.NOT_FOUND, "Case not found.")
                return CaseStatusResult(
                    case_id=str(row["application_id"]),
                    case_type="APPLICATION",
                    status=str(row["status"]),
                    subject=str(row["service_type"]),
                    updated_on=str(row["updated_on"]),
                )
            if normalized.startswith("ISS-"):
                row = fetch_one(conn, "SELECT * FROM issues WHERE issue_id = ?", (normalized,))
                if row is None:
                    raise DomainError(ErrorCode.NOT_FOUND, "Case not found.")
                return CaseStatusResult(
                    case_id=str(row["issue_id"]),
                    case_type="ISSUE",
                    status=str(row["status"]),
                    subject=str(row["category"]),
                    updated_on=str(row["updated_on"]),
                )
        raise DomainError(ErrorCode.NOT_FOUND, "Case not found.")

    def list_appointment_slots(self, office: Office, date: str) -> SlotsResult:
        normalized_date = normalize_date(date)
        with self._store.read() as conn:
            rows = fetch_all(
                conn,
                "SELECT s.slot_id, s.time FROM slots s "
                "WHERE s.office = ? AND s.date = ? "
                "AND NOT EXISTS (SELECT 1 FROM appointments a "
                "WHERE a.slot_id = s.slot_id AND a.status = ?) "
                "ORDER BY s.time",
                (office.value, normalized_date, AppointmentStatus.BOOKED.value),
            )
            return SlotsResult(
                office=office,
                date=normalized_date,
                slots=[
                    SlotInfo(slot_id=str(row["slot_id"]), time=str(row["time"])) for row in rows
                ],
            )

    # -- writes -----------------------------------------------------------

    def update_address(
        self, citizen_token: str, street_address: str, postal_code: str
    ) -> UpdateAddressResult:
        address = normalize_address(street_address)
        postal = normalize_postal_code(postal_code)
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            postal_row = fetch_one(
                conn, "SELECT * FROM postal_codes WHERE postal_code = ?", (postal,)
            )
            if postal_row is None:
                raise DomainError(
                    ErrorCode.INVALID_POSTAL_CODE, "Postal code is not served by Civitas."
                )
            citizen_id = str(citizen["citizen_id"])
            changed = address != citizen["street_address"] or postal != citizen["postal_code"]
            if changed:
                conn.execute(
                    "UPDATE citizens SET street_address = ?, postal_code = ? WHERE citizen_id = ?",
                    (address, postal, citizen_id),
                )
            return UpdateAddressResult(
                citizen_id=citizen_id,
                street_address=address,
                postal_code=postal,
                zone=Zone(str(postal_row["zone"])),
                permit_area=bool(postal_row["permit_area"]),
                changed=changed,
            )

    def quote_fee(
        self, citizen_token: str, service_type: ServiceType, quantity: int = 1
    ) -> QuoteResult:
        if isinstance(quantity, bool) or not isinstance(quantity, int):
            raise DomainError(ErrorCode.INVALID_QUANTITY, "Quantity must be an integer.")
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            existing = fetch_one(
                conn,
                "SELECT q.* FROM quotes q "
                "WHERE q.citizen_id = ? AND q.service_type = ? AND q.quantity = ? "
                "AND NOT EXISTS ("
                "SELECT 1 FROM payments p "
                "JOIN applications a ON a.payment_id = p.payment_id "
                "WHERE p.quote_id = q.quote_id"
                ") "
                "ORDER BY q.created_on, q.quote_id LIMIT 1",
                (citizen_id, service_type.value, quantity),
            )
            if existing is not None:
                return QuoteResult(
                    quote_id=str(existing["quote_id"]),
                    service_type=ServiceType(str(existing["service_type"])),
                    quantity=int(existing["quantity"]),
                    amount_cents=int(existing["amount_cents"]),
                    created=False,
                )
            count_row = fetch_one(
                conn,
                "SELECT COUNT(*) AS count FROM quotes "
                "WHERE citizen_id = ? AND service_type = ? AND quantity = ?",
                (citizen_id, service_type.value, quantity),
            )
            previous_quotes = int(count_row["count"]) if count_row is not None else 0
            quote_id = make_id(
                "QTE",
                citizen_id,
                service_type.value,
                str(quantity),
                str(previous_quotes),
            )
            today = self._today(conn)
            amount = quote_amount_cents(
                service_type,
                quantity,
                date_of_birth=Date.fromisoformat(str(citizen["date_of_birth"])),
                today=today,
            )
            self._require_reasons(self._reasons(conn, citizen, service_type))
            insert_row(
                conn,
                "quotes",
                {
                    "quote_id": quote_id,
                    "citizen_id": citizen_id,
                    "service_type": service_type.value,
                    "quantity": quantity,
                    "amount_cents": amount,
                    "created_on": today.isoformat(),
                },
            )
            return QuoteResult(
                quote_id=quote_id,
                service_type=service_type,
                quantity=quantity,
                amount_cents=amount,
                created=True,
            )

    def pay_quote(self, citizen_token: str, quote_id: str) -> PaymentResult:
        normalized_quote = normalize_id(quote_id)
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            quote = fetch_one(
                conn,
                "SELECT * FROM quotes WHERE quote_id = ? AND citizen_id = ?",
                (normalized_quote, citizen_id),
            )
            if quote is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Quote not found.")
            payment_id = make_id("PAY", normalized_quote)
            existing = fetch_one(
                conn,
                "SELECT * FROM payments WHERE payment_id = ? AND citizen_id = ?",
                (payment_id, citizen_id),
            )
            if existing is not None:
                return PaymentResult(
                    payment_id=str(existing["payment_id"]),
                    quote_id=str(existing["quote_id"]),
                    amount_cents=int(existing["amount_cents"]),
                    created=False,
                )
            self._require_reasons(
                self._reasons(conn, citizen, ServiceType(str(quote["service_type"])))
            )
            today = self._today(conn)
            insert_row(
                conn,
                "payments",
                {
                    "payment_id": payment_id,
                    "quote_id": normalized_quote,
                    "citizen_id": citizen_id,
                    "service_type": str(quote["service_type"]),
                    "amount_cents": int(quote["amount_cents"]),
                    "paid_on": today.isoformat(),
                },
            )
            return PaymentResult(
                payment_id=payment_id,
                quote_id=normalized_quote,
                amount_cents=int(quote["amount_cents"]),
                created=True,
            )

    def apply_parking_permit(
        self, citizen_token: str, license_plate: str, payment_id: str
    ) -> ApplicationResult:
        plate = normalize_plate(license_plate)
        normalized_payment = normalize_id(payment_id)
        service_type = ServiceType.PARKING_PERMIT
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            today = self._today(conn)
            existing = self._application_for(conn, citizen_id, service_type, normalized_payment)
            if existing is not None:
                details = json.loads(str(existing["details_json"]))
                if details.get("license_plate") != plate:
                    raise DomainError(
                        ErrorCode.PAYMENT_ALREADY_USED,
                        "This payment has already been used for another application.",
                    )
                return ApplicationResult(
                    application_id=str(existing["application_id"]),
                    service_type=ServiceType(str(existing["service_type"])),
                    status=ApplicationStatus(str(existing["status"])),
                    created=False,
                )

            payment = self._payment_for(conn, citizen_id, normalized_payment)
            if str(payment["service_type"]) != service_type.value:
                raise DomainError(ErrorCode.PAYMENT_INVALID, "Payment is for a different service.")
            registered = fetch_one(
                conn,
                "SELECT 1 FROM vehicles WHERE license_plate = ? AND citizen_id = ?",
                (plate, citizen_id),
            )
            if registered is None:
                raise DomainError(
                    ErrorCode.PLATE_NOT_REGISTERED,
                    "License plate is not registered to this citizen.",
                )
            self._require_reasons(self._reasons(conn, citizen, service_type))

            application_id = make_id("APP", citizen_id, service_type.value, normalized_payment)
            insert_row(
                conn,
                "applications",
                {
                    "application_id": application_id,
                    "citizen_id": citizen_id,
                    "service_type": service_type.value,
                    "status": ApplicationStatus.SUBMITTED.value,
                    "payment_id": normalized_payment,
                    "details_json": json.dumps(
                        {"license_plate": plate}, sort_keys=True, separators=(",", ":")
                    ),
                    "submitted_on": today.isoformat(),
                    "updated_on": today.isoformat(),
                },
            )
            return ApplicationResult(
                application_id=application_id,
                service_type=service_type,
                status=ApplicationStatus.SUBMITTED,
                created=True,
            )

    def request_birth_certificate(
        self, citizen_token: str, copies: int, payment_id: str
    ) -> ApplicationResult:
        if (
            isinstance(copies, bool)
            or not isinstance(copies, int)
            or not 1 <= copies <= MAX_BIRTH_CERTIFICATE_COPIES
        ):
            raise DomainError(
                ErrorCode.INVALID_QUANTITY,
                "Birth certificate copies must be between 1 and 5.",
            )
        normalized_payment = normalize_id(payment_id)
        service_type = ServiceType.BIRTH_CERTIFICATE_COPY
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            today = self._today(conn)
            existing = self._application_for(conn, citizen_id, service_type, normalized_payment)
            if existing is not None:
                details = json.loads(str(existing["details_json"]))
                if details.get("copies") != copies:
                    raise DomainError(
                        ErrorCode.PAYMENT_ALREADY_USED,
                        "This payment has already been used for another application.",
                    )
                return ApplicationResult(
                    application_id=str(existing["application_id"]),
                    service_type=ServiceType(str(existing["service_type"])),
                    status=ApplicationStatus(str(existing["status"])),
                    created=False,
                )

            payment = self._payment_for(conn, citizen_id, normalized_payment)
            if str(payment["service_type"]) != service_type.value:
                raise DomainError(ErrorCode.PAYMENT_INVALID, "Payment is for a different service.")
            quote = fetch_one(
                conn,
                "SELECT quantity FROM quotes WHERE quote_id = ?",
                (str(payment["quote_id"]),),
            )
            if quote is None or int(quote["quantity"]) != copies:
                raise DomainError(
                    ErrorCode.PAYMENT_INVALID,
                    "Payment does not match the requested number of copies.",
                )
            self._require_reasons(self._reasons(conn, citizen, service_type))

            application_id = make_id("APP", citizen_id, service_type.value, normalized_payment)
            insert_row(
                conn,
                "applications",
                {
                    "application_id": application_id,
                    "citizen_id": citizen_id,
                    "service_type": service_type.value,
                    "status": ApplicationStatus.SUBMITTED.value,
                    "payment_id": normalized_payment,
                    "details_json": json.dumps(
                        {"copies": copies}, sort_keys=True, separators=(",", ":")
                    ),
                    "submitted_on": today.isoformat(),
                    "updated_on": today.isoformat(),
                },
            )
            return ApplicationResult(
                application_id=application_id,
                service_type=service_type,
                status=ApplicationStatus.SUBMITTED,
                created=True,
            )

    def schedule_bulk_pickup(self, citizen_token: str, date: str, item_count: int) -> PickupResult:
        if (
            isinstance(item_count, bool)
            or not isinstance(item_count, int)
            or not 1 <= item_count <= MAX_BULK_ITEMS
        ):
            raise DomainError(
                ErrorCode.INVALID_QUANTITY, "Pickup item count must be between 1 and 5."
            )
        pickup_date = normalize_date(date)
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            pickup_id = make_id("PKP", citizen_id, pickup_date)
            existing = fetch_one(
                conn,
                "SELECT * FROM pickups WHERE pickup_id = ? AND citizen_id = ?",
                (pickup_id, citizen_id),
            )
            if existing is not None and str(existing["status"]) == PickupStatus.SCHEDULED.value:
                if int(existing["item_count"]) != item_count:
                    raise DomainError(
                        ErrorCode.ALREADY_SCHEDULED,
                        "A pickup is already scheduled for this citizen.",
                    )
                return PickupResult(
                    pickup_id=str(existing["pickup_id"]),
                    date=str(existing["date"]),
                    item_count=int(existing["item_count"]),
                    status=PickupStatus(str(existing["status"])),
                    created=False,
                )
            if self._has_scheduled_pickup(conn, citizen_id):
                raise DomainError(
                    ErrorCode.ALREADY_SCHEDULED,
                    "A pickup is already scheduled for this citizen.",
                )
            postal = self._postal_row(conn, str(citizen["postal_code"]))
            today = self._today(conn)
            offered = offered_pickup_dates(Zone(str(postal["zone"])), today)
            if pickup_date not in offered:
                raise DomainError(
                    ErrorCode.DATE_UNAVAILABLE,
                    "Date is not available for this citizen's zone.",
                )
            insert_row(
                conn,
                "pickups",
                {
                    "pickup_id": pickup_id,
                    "citizen_id": citizen_id,
                    "date": pickup_date,
                    "item_count": item_count,
                    "status": PickupStatus.SCHEDULED.value,
                },
            )
            return PickupResult(
                pickup_id=pickup_id,
                date=pickup_date,
                item_count=item_count,
                status=PickupStatus.SCHEDULED,
                created=True,
            )

    def report_street_issue(
        self, category: IssueCategory, street_address: str, description: str
    ) -> IssueResult:
        issue_category = category
        address = normalize_address(street_address)
        if (
            not isinstance(description, str)
            or not 1 <= len(description) <= MAX_ISSUE_DESCRIPTION_LENGTH
            or not normalize_text(description)
        ):
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Description must be between 1 and 500 characters.",
            )
        with self._store.write() as conn:
            today = self._today(conn)
            issue_id = make_id("ISS", issue_category.value, address, today.isoformat())
            existing = fetch_one(conn, "SELECT * FROM issues WHERE issue_id = ?", (issue_id,))
            if existing is not None:
                return IssueResult(
                    issue_id=str(existing["issue_id"]),
                    status=IssueStatus(str(existing["status"])),
                    created=False,
                )
            insert_row(
                conn,
                "issues",
                {
                    "issue_id": issue_id,
                    "category": issue_category.value,
                    "street_address": address,
                    "description": description,
                    "status": IssueStatus.OPEN.value,
                    "reported_on": today.isoformat(),
                    "updated_on": today.isoformat(),
                },
            )
            return IssueResult(issue_id=issue_id, status=IssueStatus.OPEN, created=True)

    def book_appointment(
        self, citizen_token: str, slot_id: str, purpose: AppointmentPurpose
    ) -> AppointmentResult:
        normalized_slot = normalize_id(slot_id)
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            citizen_id = str(citizen["citizen_id"])
            appointment_id = make_id("APT", citizen_id, normalized_slot)
            existing = fetch_one(
                conn,
                "SELECT * FROM appointments WHERE appointment_id = ? AND citizen_id = ?",
                (appointment_id, citizen_id),
            )
            if existing is not None and str(existing["status"]) == AppointmentStatus.BOOKED.value:
                return self._appointment_result(conn, existing, created=False)
            slot = fetch_one(conn, "SELECT * FROM slots WHERE slot_id = ?", (normalized_slot,))
            if slot is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Appointment slot not found.")
            other = fetch_one(
                conn,
                "SELECT 1 FROM appointments WHERE slot_id = ? AND status = ? "
                "AND appointment_id != ?",
                (
                    normalized_slot,
                    AppointmentStatus.BOOKED.value,
                    appointment_id,
                ),
            )
            if other is not None:
                raise DomainError(ErrorCode.SLOT_UNAVAILABLE, "That slot is already booked.")
            if existing is not None:
                conn.execute(
                    "UPDATE appointments SET purpose = ?, status = ? WHERE appointment_id = ?",
                    (
                        purpose.value,
                        AppointmentStatus.BOOKED.value,
                        appointment_id,
                    ),
                )
                updated = fetch_one(
                    conn,
                    "SELECT * FROM appointments WHERE appointment_id = ?",
                    (appointment_id,),
                )
                if updated is None:
                    raise DomainError(ErrorCode.INTERNAL_ERROR, "Appointment could not be booked.")
                return self._appointment_result(conn, updated, created=True)
            insert_row(
                conn,
                "appointments",
                {
                    "appointment_id": appointment_id,
                    "citizen_id": citizen_id,
                    "slot_id": normalized_slot,
                    "purpose": purpose.value,
                    "status": AppointmentStatus.BOOKED.value,
                },
            )
            inserted = fetch_one(
                conn,
                "SELECT * FROM appointments WHERE appointment_id = ?",
                (appointment_id,),
            )
            if inserted is None:
                raise DomainError(ErrorCode.INTERNAL_ERROR, "Appointment could not be booked.")
            return self._appointment_result(conn, inserted, created=True)

    @staticmethod
    def _appointment_result(
        conn: sqlite3.Connection, appointment: sqlite3.Row, *, created: bool
    ) -> AppointmentResult:
        slot = fetch_one(
            conn,
            "SELECT * FROM slots WHERE slot_id = ?",
            (str(appointment["slot_id"]),),
        )
        if slot is None:
            raise DomainError(ErrorCode.INTERNAL_ERROR, "Appointment slot is not configured.")
        return AppointmentResult(
            appointment_id=str(appointment["appointment_id"]),
            slot_id=str(appointment["slot_id"]),
            office=Office(str(slot["office"])),
            date=str(slot["date"]),
            time=str(slot["time"]),
            purpose=AppointmentPurpose(str(appointment["purpose"])),
            status=AppointmentStatus(str(appointment["status"])),
            created=created,
        )

    def cancel_appointment(
        self, citizen_token: str, appointment_id: str
    ) -> CancelAppointmentResult:
        normalized_id_value = normalize_id(appointment_id)
        with self._store.write() as conn:
            citizen = self._verify_citizen(conn, citizen_token)
            row = fetch_one(
                conn,
                "SELECT * FROM appointments WHERE appointment_id = ? AND citizen_id = ?",
                (normalized_id_value, str(citizen["citizen_id"])),
            )
            if row is None:
                raise DomainError(ErrorCode.NOT_FOUND, "Appointment not found.")
            if str(row["status"]) == AppointmentStatus.CANCELLED.value:
                return CancelAppointmentResult(appointment_id=normalized_id_value, changed=False)
            conn.execute(
                "UPDATE appointments SET status = ? WHERE appointment_id = ?",
                (AppointmentStatus.CANCELLED.value, normalized_id_value),
            )
            return CancelAppointmentResult(appointment_id=normalized_id_value, changed=True)

    def escalate_to_human(self, summary: str, citizen_token: str | None = None) -> EscalationResult:
        if not isinstance(summary, str) or not 1 <= len(summary) <= MAX_ESCALATION_SUMMARY_LENGTH:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Summary must be between 1 and 1000 characters.",
            )
        normalized_summary = normalize_text(summary)
        if not normalized_summary:
            raise DomainError(
                ErrorCode.INVALID_ARGUMENT,
                "Summary must contain non-whitespace text.",
            )
        with self._store.write() as conn:
            citizen_id: str | None = None
            if citizen_token is not None:
                citizen = self._verify_citizen(conn, citizen_token)
                citizen_id = str(citizen["citizen_id"])
            today = self._today(conn)
            if citizen_id is not None:
                escalation_id = make_id("ESC", citizen_id, today.isoformat())
            else:
                escalation_id = make_id("ESC", "ANONYMOUS", today.isoformat(), normalized_summary)
            existing = fetch_one(
                conn,
                "SELECT * FROM escalations WHERE escalation_id = ?",
                (escalation_id,),
            )
            if existing is not None:
                return EscalationResult(escalation_id=str(existing["escalation_id"]), created=False)
            insert_row(
                conn,
                "escalations",
                {
                    "escalation_id": escalation_id,
                    "citizen_id": citizen_id,
                    "summary": summary,
                    "created_on": today.isoformat(),
                },
            )
            return EscalationResult(escalation_id=escalation_id, created=True)
