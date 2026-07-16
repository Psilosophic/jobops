from datetime import datetime

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, ApplicationState, EventActor, SubmissionMode, utcnow


class Application(SQLModel, table=True):
    __tablename__ = "applications"

    id: int | None = Field(default=None, primary_key=True)
    posting_id: int = Field(foreign_key="job_postings.id", unique=True, index=True)
    track_id: int | None = Field(default=None, foreign_key="resume_tracks.id")
    resume_version_id: int | None = Field(default=None, foreign_key="resume_versions.id")
    state: ApplicationState = Field(default=ApplicationState.discovered, index=True)
    submission_mode: SubmissionMode = SubmissionMode.none
    fit_score: float | None = None
    user_modified: bool = False
    submitted_at: datetime | None = None
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


class ApplicationPacket(SQLModel, table=True):
    """Full snapshot of what would be / was sent. New version on every Modify save."""
    __tablename__ = "application_packets"
    __table_args__ = (UniqueConstraint("application_id", "version_no", name="uq_packet_version"),)

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)
    version_no: int
    # {"resume_version_id":..,"track":..,"summary":..,"cover_note":..,
    #  "answers":[{"variant_id":..,"question":..,"text":..,"user_edited":bool}], ...}
    snapshot: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    created_by: EventActor = EventActor.system
    created_at: datetime = Field(default_factory=utcnow)


class ApplicationEvent(SQLModel, table=True):
    __tablename__ = "application_events"

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", index=True)
    event_type: str                                      # "state_change","track_override",...
    actor: EventActor = EventActor.system
    payload: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    created_at: datetime = Field(default_factory=utcnow, index=True)


class ReviewQueueItem(SQLModel, table=True):
    __tablename__ = "review_queue"

    id: int | None = Field(default=None, primary_key=True)
    application_id: int = Field(foreign_key="applications.id", unique=True, index=True)
    priority: float = 0.0                                # usually fit score
    missing_fields: list = Field(default_factory=list, sa_column=Column(JSONVariant, nullable=False))
    queued_at: datetime = Field(default_factory=utcnow)
    resolved_at: datetime | None = None
