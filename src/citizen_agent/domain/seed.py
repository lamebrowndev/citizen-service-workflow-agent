"""``csa-seed`` — create and populate a Civitas database from a fixture."""

from __future__ import annotations

import argparse
import json
import logging
import sys
from collections.abc import Sequence
from importlib.resources import files
from pathlib import Path

from pydantic import ValidationError

from citizen_agent.config import configure, load_settings

from .models import Fixture
from .store import Store, StoreError

logger = logging.getLogger("citizen_agent.seed")


def load_bundled_fixture() -> Fixture:
    text = files("citizen_agent.fixtures").joinpath("default.json").read_text(encoding="utf-8")
    return Fixture.model_validate_json(text)


def load_fixture(path: Path | None) -> Fixture:
    if path is None:
        return load_bundled_fixture()
    return Fixture.model_validate(json.loads(path.read_text(encoding="utf-8")))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="csa-seed",
        description="Create a Civitas database from a fixture.",
    )
    parser.add_argument("--db", required=True, type=Path, help="SQLite database path.")
    parser.add_argument(
        "--fixture",
        type=Path,
        default=None,
        help="Fixture JSON path (defaults to the bundled fixture).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Replace an existing database.",
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    configure(settings)
    logger.info("Seeding database: %s", args.db.expanduser().resolve())

    try:
        fixture = load_fixture(args.fixture)
    except (OSError, json.JSONDecodeError, ValidationError) as exc:
        print(f"Failed to load fixture: {exc}", file=sys.stderr)
        return 1

    try:
        Store.create_from_fixture(args.db, fixture, overwrite=args.force)
    except StoreError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    logger.info(
        "Seeded %d citizens, %d applications, %d issues, %d slots, %d appointments.",
        len(fixture.citizens),
        len(fixture.applications),
        len(fixture.issues),
        fixture.appointment_calendar.business_days
        * len(fixture.appointment_calendar.times)
        * len(fixture.appointment_calendar.offices),
        len(fixture.appointments),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
