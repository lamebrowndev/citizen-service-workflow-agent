"""Shared test fixtures: every test gets a freshly seeded temporary database."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from citizen_agent.domain.models import Fixture
from citizen_agent.domain.seed import load_bundled_fixture
from citizen_agent.domain.services import CitizenServices
from citizen_agent.domain.store import Store

TEST_SECRET = b"test-token-secret"


@pytest.fixture
def fixture() -> Fixture:
    return load_bundled_fixture()


@pytest.fixture
def db_path(tmp_path: Path, fixture: Fixture) -> Path:
    path = tmp_path / "citizen.db"
    Store.create_from_fixture(path, fixture)
    return path


@pytest.fixture
def store(db_path: Path) -> Store:
    return Store(db_path)


@pytest.fixture
def services(store: Store) -> CitizenServices:
    return CitizenServices(store, TEST_SECRET)


@pytest.fixture
def token_for(fixture: Fixture, services: CitizenServices) -> Callable[[str], str]:
    by_id = {citizen.citizen_id: citizen for citizen in fixture.citizens}

    def token(citizen_id: str) -> str:
        citizen = by_id[citizen_id]
        result = services.verify_citizen(
            citizen.full_name, citizen.date_of_birth, citizen.postal_code
        )
        return result.citizen_token

    return token
