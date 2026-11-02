PRAGMA foreign_keys = ON;

CREATE TABLE meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE postal_codes (
    postal_code TEXT PRIMARY KEY,
    zone TEXT NOT NULL,
    permit_area INTEGER NOT NULL CHECK (permit_area IN (0, 1))
);

CREATE TABLE citizens (
    citizen_id TEXT PRIMARY KEY,
    full_name TEXT NOT NULL,
    date_of_birth TEXT NOT NULL,
    street_address TEXT NOT NULL,
    postal_code TEXT NOT NULL REFERENCES postal_codes(postal_code),
    born_in_city INTEGER NOT NULL CHECK (born_in_city IN (0, 1))
);

CREATE TABLE vehicles (
    license_plate TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL REFERENCES citizens(citizen_id)
);

CREATE TABLE quotes (
    quote_id TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL REFERENCES citizens(citizen_id),
    service_type TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    created_on TEXT NOT NULL
);

CREATE TABLE payments (
    payment_id TEXT PRIMARY KEY,
    quote_id TEXT NOT NULL UNIQUE REFERENCES quotes(quote_id),
    citizen_id TEXT NOT NULL REFERENCES citizens(citizen_id),
    service_type TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    paid_on TEXT NOT NULL
);

CREATE TABLE applications (
    application_id TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL REFERENCES citizens(citizen_id),
    service_type TEXT NOT NULL,
    status TEXT NOT NULL,
    payment_id TEXT UNIQUE REFERENCES payments(payment_id),
    details_json TEXT NOT NULL,
    submitted_on TEXT NOT NULL,
    updated_on TEXT NOT NULL
);

CREATE TABLE issues (
    issue_id TEXT PRIMARY KEY,
    category TEXT NOT NULL,
    street_address TEXT NOT NULL,
    description TEXT NOT NULL,
    status TEXT NOT NULL,
    reported_on TEXT NOT NULL,
    updated_on TEXT NOT NULL
);

CREATE TABLE slots (
    slot_id TEXT PRIMARY KEY,
    office TEXT NOT NULL,
    date TEXT NOT NULL,
    time TEXT NOT NULL
);

CREATE TABLE appointments (
    appointment_id TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL REFERENCES citizens(citizen_id),
    slot_id TEXT NOT NULL REFERENCES slots(slot_id),
    purpose TEXT NOT NULL,
    status TEXT NOT NULL
);

CREATE UNIQUE INDEX appointments_one_booked_per_slot
    ON appointments (slot_id) WHERE status = 'BOOKED';

CREATE TABLE pickups (
    pickup_id TEXT PRIMARY KEY,
    citizen_id TEXT NOT NULL REFERENCES citizens(citizen_id),
    date TEXT NOT NULL,
    item_count INTEGER NOT NULL,
    status TEXT NOT NULL
);

CREATE TABLE escalations (
    escalation_id TEXT PRIMARY KEY,
    citizen_id TEXT REFERENCES citizens(citizen_id),
    summary TEXT NOT NULL,
    created_on TEXT NOT NULL
);
