from datetime import date, datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, ListKind, utcnow


class PanicState(SQLModel, table=True):
    """Singleton row (id=1). Read by the policy gate on EVERY decision."""
    __tablename__ = "panic_state"

    id: int | None = Field(default=None, primary_key=True)
    submissions_paused: bool = False
    discover_only_all: bool = False
    browser_automation_paused: bool = False
    outbound_email_paused: bool = False
    review_required_all: bool = True                     # ships ON: everything starts reviewed
    min_fit_override: float | None = None
    paused_sources: list = Field(default_factory=list, sa_column=Column(JSONVariant, nullable=False))
    disabled_tracks: list = Field(default_factory=list, sa_column=Column(JSONVariant, nullable=False))
    disabled_answer_variants: list = Field(
        default_factory=list, sa_column=Column(JSONVariant, nullable=False)
    )
    updated_at: datetime = Field(default_factory=utcnow)


class PanicPanelEvent(SQLModel, table=True):
    __tablename__ = "panic_panel_events"

    id: int | None = Field(default=None, primary_key=True)
    action: str                                          # "pause_submissions", ...
    scope: str = "global"
    operator_intent: str = ""
    prevented_action: dict | None = Field(default=None, sa_column=Column(JSONVariant, nullable=True))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ExportRecord(SQLModel, table=True):
    __tablename__ = "exports"

    id: int | None = Field(default=None, primary_key=True)
    export_type: str                                     # "daily_full", "call_cheat_sheet", ...
    file_format: str                                     # "csv" | "json" | "html" | "pdf"
    file_path: str
    row_counts: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    created_at: datetime = Field(default_factory=utcnow)


class DailyReport(SQLModel, table=True):
    __tablename__ = "daily_reports"

    id: int | None = Field(default=None, primary_key=True)
    report_date: date = Field(unique=True, index=True)
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    generated_at: datetime = Field(default_factory=utcnow)


class UserSetting(SQLModel, table=True):
    __tablename__ = "user_settings"

    id: int | None = Field(default=None, primary_key=True)
    key: str = Field(unique=True, index=True)
    value: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    updated_at: datetime = Field(default_factory=utcnow)


class ListEntry(SQLModel, table=True):
    """Blacklists and allowlists share a shape; is_allow distinguishes."""
    __tablename__ = "list_entries"

    id: int | None = Field(default=None, primary_key=True)
    kind: ListKind
    is_allow: bool = False
    value: str = Field(index=True)
    reason: str = ""
    created_at: datetime = Field(default_factory=utcnow)
