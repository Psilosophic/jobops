"""SQLite-backed session for workflow integration tests (prod is Postgres; the
JSONVariant column type keeps both happy)."""
import pytest
from sqlmodel import Session, SQLModel, create_engine

import app.models  # noqa: F401 — register tables


@pytest.fixture
def session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        yield s
