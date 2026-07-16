from datetime import datetime

from sqlalchemy import Column, Index, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, PostingStatus, utcnow


class DedupeGroup(SQLModel, table=True):
    __tablename__ = "dedupe_groups"

    id: int | None = Field(default=None, primary_key=True)
    primary_posting_id: int | None = None                # set once a canonical member exists
    created_at: datetime = Field(default_factory=utcnow)


class JobPosting(SQLModel, table=True):
    __tablename__ = "job_postings"
    __table_args__ = (
        UniqueConstraint("source_id", "external_id", name="uq_posting_source_external"),
        Index("ix_postings_fingerprint", "dedupe_fingerprint"),
    )

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    employer_id: int | None = Field(default=None, foreign_key="employers.id", index=True)
    dedupe_group_id: int | None = Field(default=None, foreign_key="dedupe_groups.id", index=True)
    external_id: str                                     # id within the source
    dedupe_fingerprint: str                              # sha256(normalized title|employer|loc)
    duplicate_confidence: float = 0.0
    url: str
    title: str = Field(index=True)
    description_text: str = ""
    location_raw: str = ""
    is_remote: bool = False
    remote_scope: str | None = None                      # "us", "co", "global", None
    salary_raw: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_currency: str = "USD"
    salary_interval: str = "year"                        # "year" | "hour"
    employment_type: str | None = None                   # "full_time", "contract", ...
    posted_at: datetime | None = None
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)
    status: PostingStatus = PostingStatus.active
    raw: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))


class JobPostingVersion(SQLModel, table=True):
    __tablename__ = "job_posting_versions"
    __table_args__ = (
        UniqueConstraint("posting_id", "version_no", name="uq_posting_version"),
    )

    id: int | None = Field(default=None, primary_key=True)
    posting_id: int = Field(foreign_key="job_postings.id", index=True)
    version_no: int
    content_hash: str
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class SearchRun(SQLModel, table=True):
    __tablename__ = "search_runs"

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    status: str = "running"                              # running | ok | error
    fetched: int = 0
    new: int = 0
    updated: int = 0
    errors: int = 0
    error_detail: str | None = None
