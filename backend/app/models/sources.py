from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, HealthEventType, RiskLevel, SourceMode, SourceType, utcnow


class Source(SQLModel, table=True):
    __tablename__ = "sources"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True, index=True)          # "greenhouse", "linkedin_alerts"
    name: str
    source_type: SourceType
    login_required: bool = False
    official_api_available: bool = False
    retrieval_method: str                                # "official_api" | "rss" | "imap" | "user_export"
    enabled: bool = True
    # adapter config, e.g. {"boards": ["companyx"], "poll_minutes": 30}
    config: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class SourcePolicy(SQLModel, table=True):
    __tablename__ = "source_policies"

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", unique=True, index=True)
    scraping_allowed: bool = False
    browser_automation_allowed: bool = False
    auto_submit_allowed: bool = False
    manual_review_required: bool = True
    recommended_mode: SourceMode = SourceMode.discover_only
    risk_level: RiskLevel = RiskLevel.medium
    evidence_notes: str = ""
    last_policy_reviewed_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class SourceHealthEvent(SQLModel, table=True):
    __tablename__ = "source_health_events"

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    event_type: HealthEventType
    detail: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class SourceCredentialsMetadata(SQLModel, table=True):
    """Pointer to a credential, never the credential. credential_ref is an ENV VAR NAME."""
    __tablename__ = "source_credentials_metadata"

    id: int | None = Field(default=None, primary_key=True)
    source_id: int = Field(foreign_key="sources.id", index=True)
    credential_ref: str                                  # e.g. "JOBOPS_IMAP_PASSWORD"
    purpose: str = ""
    last_rotated_at: datetime | None = None
