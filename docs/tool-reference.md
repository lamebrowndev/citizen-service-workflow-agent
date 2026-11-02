# Tool Reference

All 17 tools served by `csa-mcp`. Names and arguments are identical in `CitizenServices` (`src/citizen_agent/domain/services.py`) and over MCP. For how the system works as a whole, see the [Project guide](project-guide.md).

## Conventions

- **Formats.** Dates are `YYYY-MM-DD`. Postal codes are `CV-` followed by three digits. License plates are 2 to 8 letters or digits; spaces and hyphens are ignored. IDs are case-insensitive and stored in uppercase. Money is integer cents in USD.
- **Tokens.** `citizen_token` always means the token returned by `verify_citizen`.
- **Results.** Each tool returns a JSON object (MCP `structuredContent`) with the fields listed.
- **Errors.** A failed call returns `isError: true` with text of the form `Error executing tool <name>: <CODE>: <message>`. All codes are explained in [section 11 of the guide](project-guide.md#11-error-codes). Unknown enum values are rejected by the schema before a tool runs.
- **Retries.** Write tools are idempotent. A repeated call returns the existing record with `created: false` (or `changed: false`) and writes nothing. See [section 9 of the guide](project-guide.md#9-idempotency-and-safe-retries).
- **Annotations.** Read tools are marked `readOnlyHint`; write tools `idempotentHint`; `pay_quote` and `cancel_appointment` are also marked `destructiveHint`.
- **Examples.** Every example was produced on a freshly seeded database with the default development secret, so it can be reproduced exactly. `<token>` stands for the token of the citizen named in the example.

## Index

| # | Tool | Type |
| --- | --- | --- |
| 1 | [`verify_citizen`](#1-verify_citizen) | Read |
| 2 | [`get_citizen_profile`](#2-get_citizen_profile) | Read |
| 3 | [`update_address`](#3-update_address) | Write |
| 4 | [`get_service_info`](#4-get_service_info) | Read |
| 5 | [`check_eligibility`](#5-check_eligibility) | Read |
| 6 | [`quote_fee`](#6-quote_fee) | Write |
| 7 | [`pay_quote`](#7-pay_quote) | Write |
| 8 | [`apply_parking_permit`](#8-apply_parking_permit) | Write |
| 9 | [`request_birth_certificate`](#9-request_birth_certificate) | Write |
| 10 | [`list_pickup_dates`](#10-list_pickup_dates) | Read |
| 11 | [`schedule_bulk_pickup`](#11-schedule_bulk_pickup) | Write |
| 12 | [`report_street_issue`](#12-report_street_issue) | Write |
| 13 | [`get_case_status`](#13-get_case_status) | Read |
| 14 | [`list_appointment_slots`](#14-list_appointment_slots) | Read |
| 15 | [`book_appointment`](#15-book_appointment) | Write |
| 16 | [`cancel_appointment`](#16-cancel_appointment) | Write |
| 17 | [`escalate_to_human`](#17-escalate_to_human) | Write |

## 1. verify_citizen

Confirms a citizen's identity and issues the signed token that every citizen-scoped tool requires.
**Use when:** the request concerns the citizen's own records or services. This is the first step of most workflows.

| Argument | Type | Notes |
| --- | --- | --- |
| `full_name` | string | Compared ignoring case and extra spaces |
| `date_of_birth` | string | `YYYY-MM-DD` |
| `postal_code` | string | `CV-###` |

**Returns:** `citizen_token`, `full_name` (display form).
**Errors:** `INVALID_ARGUMENT` (malformed input, such as a date in another format), `VERIFICATION_FAILED` (no citizen matches all three fields; the message never says which one was wrong).
**Note:** all three fields must match. Names alone are not unique in Civitas.

```text
arguments: {"full_name": "Amara Okafor", "date_of_birth": "1961-03-02", "postal_code": "CV-101"}
result:    {"citizen_token": "CTK.CIT-0001.C3D580D6ACEC6E3F", "full_name": "Amara Okafor"}
```

## 2. get_citizen_profile

Returns the verified citizen's record.
**Use when:** you need the citizen's plate, current address or zone, an existing application, or an appointment ID to cancel.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |

**Returns:** `citizen_id`, `full_name`, `street_address`, `postal_code`, `zone`, `permit_area`, `vehicles` (each with `license_plate`), `applications` (each with `application_id`, `service_type`, `status`), `appointments` (booked only: `appointment_id`, `slot_id`, `office`, `date`, `time`, `purpose`), `pickups` (scheduled only: `pickup_id`, `date`, `item_count`).
**Errors:** `INVALID_TOKEN`.
**Note:** never returns a date of birth.

```text
arguments: {"citizen_token": "<token for CIT-0001>"}
result:    {"citizen_id": "CIT-0001", "full_name": "Amara Okafor", "street_address": "12 MAPLE ST", "postal_code": "CV-101",
            "zone": "NORTH", "permit_area": true, "vehicles": [{"license_plate": "CVX1234"}], "applications": [],
            "appointments": [{"appointment_id": "APT-073C673B", "slot_id": "SLOT-CITY_HALL-20260305-0900", "office": "CITY_HALL",
                              "date": "2026-03-05", "time": "09:00", "purpose": "PERMIT_PICKUP"}],
            "pickups": []}
```

## 3. update_address

Changes the citizen's registered street address and postal code.
**Use when:** the citizen reports a move.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `street_address` | string | Stored normalized: uppercase, punctuation removed, and STREET, AVENUE, ROAD, BOULEVARD, DRIVE, LANE, COURT, PLACE abbreviated to ST, AVE, RD, BLVD, DR, LN, CT, PL |
| `postal_code` | string | Must be one of CV-101 to CV-108 |

**Returns:** `citizen_id`, `street_address`, `postal_code`, `zone`, `permit_area`, `changed`.
**Errors:** `INVALID_ARGUMENT`, `INVALID_TOKEN`, `INVALID_POSTAL_CODE`.
**Retries:** the same address again returns `changed: false`.
**Note:** the new zone and permit area take effect immediately for pickup dates and parking eligibility; existing records are not modified.

```text
arguments: {"citizen_token": "<token for CIT-0002>", "street_address": "45 Oak Avenue", "postal_code": "cv-105"}
result:    {"citizen_id": "CIT-0002", "street_address": "45 OAK AVE", "postal_code": "CV-105", "zone": "EAST", "permit_area": true, "changed": true}
```

## 4. get_service_info

Describes a service's requirements, fee rules, and processing time. Takes no action.
**Use when:** the citizen asks what a service needs or costs. No token is needed.

| Argument | Type | Notes |
| --- | --- | --- |
| `service_type` | enum | `PARKING_PERMIT`, `BIRTH_CERTIFICATE_COPY`, `BULK_WASTE_PICKUP`, `ADDRESS_CHANGE`, `STREET_ISSUE_REPORT`, `OFFICE_APPOINTMENT` |

**Returns:** `service_type`, `title`, `description`, `requirements`, `fee_rules`, `processing_days`.
**Errors:** none raised by the tool; unknown service values are rejected by the schema.

```text
arguments: {"service_type": "BIRTH_CERTIFICATE_COPY"}
result:    {"service_type": "BIRTH_CERTIFICATE_COPY", "title": "Birth Certificate Copy",
            "description": "Certified copy of the applicant's own Civitas birth certificate.",
            "requirements": ["Verified identity", "Birth registered in Civitas"],
            "fee_rules": "$15.00 per copy, 1–5 copies", "processing_days": 7}
```

## 5. check_eligibility

Reports whether the citizen qualifies for a service, with every reason if not.
**Use when:** before quoting or applying.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `service_type` | enum | Any of the six services |

**Returns:** `service_type`, `eligible`, `reasons` (codes in a fixed order: `NOT_IN_PERMIT_AREA`, `NO_REGISTERED_VEHICLE`, `ACTIVE_PERMIT_EXISTS`, `NO_BIRTH_RECORD`, `PICKUP_ALREADY_SCHEDULED`).
**Errors:** `INVALID_TOKEN`.
**Note:** services without rules (`ADDRESS_CHANGE`, `STREET_ISSUE_REPORT`, `OFFICE_APPOINTMENT`) always return `eligible: true`.

```text
arguments: {"citizen_token": "<token for CIT-0006, Hiroshi Tanaka>", "service_type": "PARKING_PERMIT"}
result:    {"service_type": "PARKING_PERMIT", "eligible": false, "reasons": ["NOT_IN_PERMIT_AREA"]}
```

## 6. quote_fee

Creates a fee quote for a paid service, or returns the citizen's open quote for the same service and quantity.
**Use when:** eligibility is confirmed, before asking the citizen to approve the amount.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `service_type` | enum | Only `PARKING_PERMIT` and `BIRTH_CERTIFICATE_COPY` carry fees |
| `quantity` | integer, default 1 | Parking: exactly 1. Birth certificate copies: 1 to 5 |

**Returns:** `quote_id`, `service_type`, `quantity`, `amount_cents`, `currency` (`"USD"`), `created`.
**Errors:** `INVALID_TOKEN`, `NO_FEE_REQUIRED`, `INVALID_QUANTITY`, `NOT_ELIGIBLE`.
**Retries:** returns the open quote (not yet used by an application, even if paid) with `created: false`. A new quote is created only after the previous one has been used by an application.

```text
arguments: {"citizen_token": "<token for CIT-0001>", "service_type": "PARKING_PERMIT"}
result:    {"quote_id": "QTE-3DA94D2B", "service_type": "PARKING_PERMIT", "quantity": 1, "amount_cents": 3000, "currency": "USD", "created": true}
```

## 7. pay_quote

Charges the simulated card on file for a quote, exactly once.
**Use when:** only after the citizen has explicitly agreed to the quoted amount.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `quote_id` | string | From `quote_fee` |

**Returns:** `payment_id`, `quote_id`, `amount_cents`, `status` (`"PAID"`), `created`.
**Errors:** `INVALID_TOKEN`, `NOT_FOUND` (the quote does not exist or belongs to someone else), `NOT_ELIGIBLE` (eligibility is re-checked before charging).
**Retries:** the same quote returns the same payment with `created: false`; there is never a second charge.
**Note:** no tool accepts card details.

```text
arguments: {"citizen_token": "<token for CIT-0001>", "quote_id": "QTE-3DA94D2B"}     (after the quote_fee example)
result:    {"payment_id": "PAY-0ECB7B2E", "quote_id": "QTE-3DA94D2B", "amount_cents": 3000, "status": "PAID", "created": true}
```

## 8. apply_parking_permit

Submits a residential parking permit application funded by a parking payment.
**Use when:** `pay_quote` has succeeded for a `PARKING_PERMIT` quote.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `license_plate` | string | Must be registered to this citizen; spaces and hyphens are ignored |
| `payment_id` | string | From `pay_quote` |

**Returns:** `application_id`, `service_type`, `status` (`"SUBMITTED"`), `created`.
**Errors:** `INVALID_ARGUMENT`, `INVALID_TOKEN`, `NOT_FOUND` (payment), `PAYMENT_INVALID` (payment for another service), `PAYMENT_ALREADY_USED` (payment already funds an application for another plate), `PLATE_NOT_REGISTERED`, `NOT_ELIGIBLE`.
**Retries:** the same payment and plate return the existing application with `created: false`.

```text
arguments: {"citizen_token": "<token for CIT-0001>", "license_plate": "cvx-1234", "payment_id": "PAY-0ECB7B2E"}     (after the pay_quote example)
result:    {"application_id": "APP-8378276D", "service_type": "PARKING_PERMIT", "status": "SUBMITTED", "created": true}
```

## 9. request_birth_certificate

Requests certified copies of the citizen's own Civitas birth certificate, funded by a payment.
**Use when:** `pay_quote` has succeeded for a `BIRTH_CERTIFICATE_COPY` quote with the same quantity.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `copies` | integer | 1 to 5; must equal the quote's quantity |
| `payment_id` | string | From `pay_quote` |

**Returns:** `application_id`, `service_type`, `status` (`"SUBMITTED"`), `created`.
**Errors:** `INVALID_QUANTITY`, `INVALID_TOKEN`, `NOT_FOUND`, `PAYMENT_INVALID` (wrong service, or the quote quantity differs from `copies`), `PAYMENT_ALREADY_USED`, `NOT_ELIGIBLE`.
**Retries:** the same payment and copies return the existing application; different copies give `PAYMENT_ALREADY_USED`.

```text
sequence for CIT-0002 (Ravi Chandrasekaran):
  quote_fee(<token>, "BIRTH_CERTIFICATE_COPY", 2)
    -> {"quote_id": "QTE-D090E037", "service_type": "BIRTH_CERTIFICATE_COPY", "quantity": 2, "amount_cents": 3000, "currency": "USD", "created": true}
  pay_quote(<token>, "QTE-D090E037")
    -> {"payment_id": "PAY-8B5B6E1F", "quote_id": "QTE-D090E037", "amount_cents": 3000, "status": "PAID", "created": true}
  request_birth_certificate(<token>, 2, "PAY-8B5B6E1F")
    -> {"application_id": "APP-F6B83C39", "service_type": "BIRTH_CERTIFICATE_COPY", "status": "SUBMITTED", "created": true}
```

## 10. list_pickup_dates

Lists the next four bulk-waste pickup dates for the citizen's zone.
**Use when:** before `schedule_bulk_pickup`.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |

**Returns:** `zone`, `dates` (four dates, strictly after the simulated date).
**Errors:** `INVALID_TOKEN`.

```text
arguments: {"citizen_token": "<token for CIT-0001>"}
result:    {"zone": "NORTH", "dates": ["2026-03-03", "2026-03-10", "2026-03-17", "2026-03-24"]}
```

## 11. schedule_bulk_pickup

Schedules one curbside pickup of up to five items.
**Use when:** the citizen has chosen one of the offered dates.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `date` | string | One of the dates from `list_pickup_dates` |
| `item_count` | integer | 1 to 5 |

**Returns:** `pickup_id`, `date`, `item_count`, `status` (`"SCHEDULED"`), `created`.
**Errors:** `INVALID_ARGUMENT`, `INVALID_QUANTITY`, `INVALID_TOKEN`, `ALREADY_SCHEDULED`, `DATE_UNAVAILABLE`.
**Retries:** the same date and item count return the existing pickup with `created: false`; a different count while one is scheduled gives `ALREADY_SCHEDULED`. Completed pickups are never replayed.

```text
arguments: {"citizen_token": "<token for CIT-0001>", "date": "2026-03-03", "item_count": 3}
result:    {"pickup_id": "PKP-06D240CC", "date": "2026-03-03", "item_count": 3, "status": "SCHEDULED", "created": true}
```

## 12. report_street_issue

Reports a street problem. No identity is needed.
**Use when:** the citizen reports a problem at a location.

| Argument | Type | Notes |
| --- | --- | --- |
| `category` | enum | `POTHOLE`, `STREETLIGHT`, `GRAFFITI`, `MISSED_COLLECTION` |
| `street_address` | string | Stored normalized, as in `update_address` |
| `description` | string | 1 to 500 characters, not blank |

**Returns:** `issue_id`, `status` (`"OPEN"` for new issues), `created`.
**Errors:** `INVALID_ARGUMENT`.
**Retries:** the same category at the same address on the same day returns the existing issue with `created: false`; the first description is kept.

```text
arguments: {"category": "STREETLIGHT", "street_address": "40 Elm Street", "description": "Streetlight flickers all night."}
result:    {"issue_id": "ISS-9D8F1DC1", "status": "OPEN", "created": true}
```

## 13. get_case_status

Looks up the status of an application (`APP-` IDs) or a street issue (`ISS-` IDs).
**Use when:** the citizen asks about an existing case.

| Argument | Type | Notes |
| --- | --- | --- |
| `case_id` | string | An `APP-` or `ISS-` ID |
| `citizen_token` | string, optional | Required for `APP-` cases; ignored for `ISS-` cases |

**Returns:** `case_id`, `case_type` (`"APPLICATION"` or `"ISSUE"`), `status`, `subject` (the service type or the issue category), `updated_on`.
**Errors:** `AUTH_REQUIRED` (an `APP-` case without a token), `INVALID_TOKEN`, `NOT_FOUND` (missing, belonging to someone else, or an unknown prefix).

```text
arguments: {"case_id": "ISS-4C0406B3"}
result:    {"case_id": "ISS-4C0406B3", "case_type": "ISSUE", "status": "OPEN", "subject": "POTHOLE", "updated_on": "2026-02-10"}

arguments: {"case_id": "APP-1A2B3C4D", "citizen_token": "<token for the application's owner>"}
result:    {"case_id": "APP-1A2B3C4D", "case_type": "APPLICATION", "status": "APPROVED", "subject": "PARKING_PERMIT", "updated_on": "2025-11-10"}
```

## 14. list_appointment_slots

Lists free 30-minute appointment slots at an office on a date. No token is needed.
**Use when:** before `book_appointment`.

| Argument | Type | Notes |
| --- | --- | --- |
| `office` | enum | `CITY_HALL`, `NORTH_BRANCH` |
| `date` | string | `YYYY-MM-DD` |

**Returns:** `office`, `date`, `slots` (each with `slot_id` and `time`, sorted by time; empty when nothing is free).
**Errors:** `INVALID_ARGUMENT`.

```text
arguments: {"office": "NORTH_BRANCH", "date": "2026-03-03"}
result:    {"office": "NORTH_BRANCH", "date": "2026-03-03", "slots": [{"slot_id": "SLOT-NORTH_BRANCH-20260303-1100", "time": "11:00"},
                                                                        {"slot_id": "SLOT-NORTH_BRANCH-20260303-1130", "time": "11:30"}]}

arguments: {"office": "CITY_HALL", "date": "2026-03-05"}
result:    {"office": "CITY_HALL", "date": "2026-03-05", "slots": []}      (fully booked)
```

## 15. book_appointment

Books a free slot for the citizen.
**Use when:** the citizen has chosen a slot from `list_appointment_slots`.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `slot_id` | string | From `list_appointment_slots` |
| `purpose` | enum | `ID_CARD`, `PERMIT_PICKUP`, `GENERAL_INQUIRY` |

**Returns:** `appointment_id`, `slot_id`, `office`, `date`, `time`, `purpose`, `status` (`"BOOKED"`), `created`.
**Errors:** `INVALID_TOKEN`, `NOT_FOUND` (no such slot), `SLOT_UNAVAILABLE`.
**Retries:** a slot the citizen already holds returns the existing booking with `created: false`; a slot the citizen cancelled earlier is booked again with `created: true`.
**Note:** to reschedule, book the new slot first, then cancel the old one, so a failed booking never loses the existing appointment.

```text
arguments: {"citizen_token": "<token for CIT-0001>", "slot_id": "SLOT-NORTH_BRANCH-20260303-1100", "purpose": "GENERAL_INQUIRY"}
result:    {"appointment_id": "APT-30D8C24F", "slot_id": "SLOT-NORTH_BRANCH-20260303-1100", "office": "NORTH_BRANCH", "date": "2026-03-03",
            "time": "11:00", "purpose": "GENERAL_INQUIRY", "status": "BOOKED", "created": true}
```

## 16. cancel_appointment

Cancels one of the citizen's booked appointments and frees the slot.
**Use when:** the citizen cancels, or after the new booking in a reschedule has succeeded.

| Argument | Type | Notes |
| --- | --- | --- |
| `citizen_token` | string | From `verify_citizen` |
| `appointment_id` | string | From `get_citizen_profile` or `book_appointment` |

**Returns:** `appointment_id`, `status` (`"CANCELLED"`), `changed`.
**Errors:** `INVALID_TOKEN`, `NOT_FOUND` (missing or belonging to someone else).
**Retries:** an already cancelled appointment returns `changed: false`.

```text
arguments: {"citizen_token": "<token for CIT-0001>", "appointment_id": "APT-30D8C24F"}     (after the book_appointment example)
result:    {"appointment_id": "APT-30D8C24F", "status": "CANCELLED", "changed": true}
repeated:  {"appointment_id": "APT-30D8C24F", "status": "CANCELLED", "changed": false}
```

## 17. escalate_to_human

Hands the request to a human staff member.
**Use when:** the request is out of scope, the citizen asks for a person, or the workflow cannot proceed.

| Argument | Type | Notes |
| --- | --- | --- |
| `summary` | string | 1 to 1000 characters, not blank |
| `citizen_token` | string, optional | Must be valid if supplied |

**Returns:** `escalation_id`, `created`.
**Errors:** `INVALID_ARGUMENT`, `INVALID_TOKEN`.
**Retries:** one escalation per verified citizen per day (later calls return it with `created: false`, keeping the first summary). Anonymous escalations are deduplicated only when the summary text is the same, ignoring case and spacing.

```text
arguments: {"summary": "Caller wants to dispute a parking fine."}
result:    {"escalation_id": "ESC-7B4884E0", "created": true}

arguments: {"summary": "Citizen asks to speak with a permit officer.", "citizen_token": "<token for CIT-0001>"}
result:    {"escalation_id": "ESC-B623B2C1", "created": true}
```
