"""First-boot schema bootstrap.

v0.1 ships without a committed initial migration; create_all() builds the schema
idempotently, and `alembic stamp head` marks the DB current so FUTURE revisions
apply cleanly via `alembic upgrade head`.
"""
from alembic import command
from alembic.config import Config
from sqlmodel import SQLModel

import app.models  # noqa: F401 - registers all tables on the metadata
from app.db import engine
from app.logging import configure_logging, get_logger

configure_logging()
log = get_logger("bootstrap")


def bootstrap() -> None:
    SQLModel.metadata.create_all(engine)
    command.stamp(Config("alembic.ini"), "head")
    log.info("schema_bootstrap_complete")


if __name__ == "__main__":
    bootstrap()
