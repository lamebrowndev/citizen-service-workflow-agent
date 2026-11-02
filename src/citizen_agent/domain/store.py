"""SQLite persistence: schema creation, fixture seeding, and snapshots.

Every public operation opens its own connection and runs a single transaction.
Connections are never shared across threads.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Iterator, Mapping
from contextlib import contextmanager, suppress
from datetime import date, timedelta
from importlib.resources import files
from pathlib import Path
from typing import Any, Self, cast

from .enums import ErrorCode
from .errors import DomainError
from .ids import make_id
from .models import Fixture
from .normalize import (
    display_name,
    normalize_address,
    normalize_date,
    normalize_id,
    normalize_plate,
    normalize_postal_code,
)


class StoreError(Exception):
    """A storage-level failure that is not a domain rule violation."""


def _load_schema() -> str:
    return files("citizen_agent.domain").joinpath("schema.sql").read_text(encoding="utf-8")


def schema_statements() -> list[str]:
    return [statement.strip() for statement in _load_schema().split(";") if statement.strip()]


def insert_row(conn: sqlite3.Connection, table: str, values: Mapping[str, object]) -> None:
    """Insert one row, never overwriting an existing primary key."""
    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)
    try:
        conn.execute(
            f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
            tuple(values.values()),
        )
    except sqlite3.IntegrityError as exc:
        logging.getLogger("citizen_agent.store").error(
            "Integrity error inserting into %s", table, exc_info=True
        )
        raise DomainError(ErrorCode.INTERNAL_ERROR, "The record could not be created.") from exc


def fetch_one(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> sqlite3.Row | None:
    return cast(sqlite3.Row | None, conn.execute(sql, params).fetchone())


def fetch_all(
    conn: sqlite3.Connection, sql: str, params: tuple[object, ...] = ()
) -> list[sqlite3.Row]:
    return cast(list[sqlite3.Row], conn.execute(sql, params).fetchall())


def _rollback(conn: sqlite3.Connection) -> None:
    with suppress(sqlite3.OperationalError):
        conn.execute("ROLLBACK")


def _slot_id(office: str, day: date, time_text: str) -> str:
    return f"SLOT-{office}-{day:%Y%m%d}-{time_text.replace(':', '')}"


def _business_days(start: date, count: int) -> list[date]:
    days: list[date] = []
    candidate = start
    while len(days) < count:
        if candidate.weekday() < 5:
            days.append(candidate)
        candidate += timedelta(days=1)
    return days


class Store:
    """Connection and transaction boundary for the Civitas database."""

    def __init__(self, db_path: str | Path) -> None:
        self.db_path = Path(db_path).expanduser().resolve()

    # -- transactions -----------------------------------------------------

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise
        finally:
            conn.close()

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            raise
        finally:
            conn.close()

    # -- snapshots --------------------------------------------------------

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        """Every user table, ordered by table name and then primary key."""
        with self.read() as conn:
            tables = [
                str(row["name"])
                for row in fetch_all(
                    conn,
                    "SELECT name FROM sqlite_master "
                    "WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name",
                )
            ]
            snapshot: dict[str, list[dict[str, Any]]] = {}
            for table in tables:
                rows = fetch_all(conn, f'SELECT * FROM "{table}" ORDER BY 1')
                snapshot[table] = [dict(row) for row in rows]
            return snapshot

    # -- fixture seeding --------------------------------------------------

    @classmethod
    def create_from_fixture(
        cls,
        db_path: str | Path,
        fixture: Fixture | Mapping[str, Any],
        overwrite: bool = False,
    ) -> Self:
        """Validate and seed a new database in one transaction."""
        path = Path(db_path).expanduser().resolve()
        data = Fixture.model_validate(fixture)

        if path.exists():
            if not overwrite:
                raise StoreError(f"Database already exists at {path}")
            for suffix in ("", "-wal", "-shm"):
                candidate = Path(f"{path}{suffix}")
                candidate.unlink(missing_ok=True)

        path.parent.mkdir(parents=True, exist_ok=True)

        store = cls(path)
        conn = store._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            for statement in schema_statements():
                conn.execute(statement)

            insert_row(conn, "meta", {"key": "fixture_name", "value": data.meta.fixture_name})
            insert_row(conn, "meta", {"key": "today", "value": normalize_date(data.meta.today)})

            for postal in data.postal_codes:
                insert_row(
                    conn,
                    "postal_codes",
                    {
                        "postal_code": normalize_postal_code(postal.postal_code),
                        "zone": postal.zone.value,
                        "permit_area": int(postal.permit_area),
                    },
                )

            for citizen in data.citizens:
                insert_row(
                    conn,
                    "citizens",
                    {
                        "citizen_id": normalize_id(citizen.citizen_id),
                        "full_name": display_name(citizen.full_name),
                        "date_of_birth": normalize_date(citizen.date_of_birth),
                        "street_address": normalize_address(citizen.street_address),
                        "postal_code": normalize_postal_code(citizen.postal_code),
                        "born_in_city": int(citizen.born_in_city),
                    },
                )

            for vehicle in data.vehicles:
                insert_row(
                    conn,
                    "vehicles",
                    {
                        "license_plate": normalize_plate(vehicle.license_plate),
                        "citizen_id": normalize_id(vehicle.citizen_id),
                    },
                )

            for application in data.applications:
                insert_row(
                    conn,
                    "applications",
                    {
                        "application_id": normalize_id(application.application_id),
                        "citizen_id": normalize_id(application.citizen_id),
                        "service_type": application.service_type.value,
                        "status": application.status.value,
                        "payment_id": (
                            normalize_id(application.payment_id)
                            if application.payment_id is not None
                            else None
                        ),
                        "details_json": "{}",
                        "submitted_on": normalize_date(application.submitted_on),
                        "updated_on": normalize_date(application.updated_on),
                    },
                )

            for issue in data.issues:
                address = normalize_address(issue.street_address)
                reported_on = normalize_date(issue.reported_on)
                issue_id = make_id("ISS", issue.category.value, address, reported_on)
                insert_row(
                    conn,
                    "issues",
                    {
                        "issue_id": issue_id,
                        "category": issue.category.value,
                        "street_address": address,
                        "description": issue.description,
                        "status": issue.status.value,
                        "reported_on": reported_on,
                        "updated_on": reported_on,
                    },
                )

            calendar = data.appointment_calendar
            start = date.fromisoformat(normalize_date(calendar.start_date))
            for day in _business_days(start, calendar.business_days):
                for office in calendar.offices:
                    for time_text in calendar.times:
                        insert_row(
                            conn,
                            "slots",
                            {
                                "slot_id": _slot_id(office.value, day, time_text),
                                "office": office.value,
                                "date": day.isoformat(),
                                "time": time_text,
                            },
                        )

            for appointment in data.appointments:
                citizen_id = normalize_id(appointment.citizen_id)
                slot_id = normalize_id(appointment.slot_id)
                insert_row(
                    conn,
                    "appointments",
                    {
                        "appointment_id": make_id("APT", citizen_id, slot_id),
                        "citizen_id": citizen_id,
                        "slot_id": slot_id,
                        "purpose": appointment.purpose.value,
                        "status": appointment.status.value,
                    },
                )

            for pickup in data.pickups:
                citizen_id = normalize_id(pickup.citizen_id)
                pickup_date = normalize_date(pickup.date)
                insert_row(
                    conn,
                    "pickups",
                    {
                        "pickup_id": make_id("PKP", citizen_id, pickup_date),
                        "citizen_id": citizen_id,
                        "date": pickup_date,
                        "item_count": pickup.item_count,
                        "status": pickup.status.value,
                    },
                )

            conn.execute("COMMIT")
        except BaseException:
            _rollback(conn)
            conn.close()
            raise
        conn.close()
        return store
