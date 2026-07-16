from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, utcnow


class Employer(SQLModel, table=True):
    __tablename__ = "employers"

    id: int | None = Field(default=None, primary_key=True)
    canonical_name: str = Field(index=True)
    industry: str | None = None
    website: str | None = None
    preferred: bool = False
    blacklisted: bool = False
    first_seen_at: datetime = Field(default_factory=utcnow)


class EmployerAlias(SQLModel, table=True):
    __tablename__ = "employer_aliases"

    id: int | None = Field(default=None, primary_key=True)
    employer_id: int = Field(foreign_key="employers.id", index=True)
    alias: str = Field(unique=True, index=True)


class EmployerMemoryNote(SQLModel, table=True):
    __tablename__ = "employer_memory_notes"

    id: int | None = Field(default=None, primary_key=True)
    employer_id: int = Field(foreign_key="employers.id", index=True)
    role_family: str | None = None
    note_md: str = ""                                    # human-readable memory card body
    talking_points: list = Field(default_factory=list, sa_column=Column(JSONVariant, nullable=False))
    keywords: list = Field(default_factory=list, sa_column=Column(JSONVariant, nullable=False))
    status_history: list = Field(default_factory=list, sa_column=Column(JSONVariant, nullable=False))
    date_applied: datetime | None = None
    updated_at: datetime = Field(default_factory=utcnow)
