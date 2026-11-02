"""Runtime configuration loaded from the environment."""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB_PATH = "var/citizen.db"
DEFAULT_TOKEN_SECRET = "civitas-dev-secret"
DEFAULT_LOG_LEVEL = "INFO"


@dataclass(frozen=True)
class Settings:
    """Resolved process settings. Paths are absolute."""

    db_path: Path
    token_secret: str
    log_level: str


def load_settings() -> Settings:
    """Read settings from the environment, applying documented defaults."""
    raw_db_path = os.environ.get("CSA_DB_PATH", DEFAULT_DB_PATH)
    db_path = Path(raw_db_path).expanduser().resolve()
    token_secret = os.environ.get("CSA_TOKEN_SECRET", DEFAULT_TOKEN_SECRET)
    log_level = os.environ.get("CSA_LOG_LEVEL", DEFAULT_LOG_LEVEL).upper()
    if log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
        log_level = DEFAULT_LOG_LEVEL
    return Settings(db_path=db_path, token_secret=token_secret, log_level=log_level)


def configure(settings: Settings) -> None:
    """Configure stderr logging and announce startup facts."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level, logging.INFO),
        format="%(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
        force=True,
    )
    logger = logging.getLogger("citizen_agent")
    logger.info("Database: %s", settings.db_path)
    if settings.token_secret == DEFAULT_TOKEN_SECRET:
        logger.warning(
            "CSA_TOKEN_SECRET is using the insecure development default; "
            "set a private secret outside local development."
        )
