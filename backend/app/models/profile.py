from datetime import datetime

from sqlalchemy import Column, UniqueConstraint
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, AnswerCategory, AnswerSafety, utcnow


class ResumeTrack(SQLModel, table=True):
    __tablename__ = "resume_tracks"

    id: int | None = Field(default=None, primary_key=True)
    slug: str = Field(unique=True)                       # "iam", "support_enablement"
    name: str
    priority: int = 1
    enabled: bool = True
    summary: str = ""


class Resume(SQLModel, table=True):
    __tablename__ = "resumes"

    id: int | None = Field(default=None, primary_key=True)
    track_id: int = Field(foreign_key="resume_tracks.id", index=True)
    name: str
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class ResumeVersion(SQLModel, table=True):
    """Immutable. Applications reference a version id, never 'latest'."""
    __tablename__ = "resume_versions"
    __table_args__ = (UniqueConstraint("resume_id", "version_no", name="uq_resume_version"),)

    id: int | None = Field(default=None, primary_key=True)
    resume_id: int = Field(foreign_key="resumes.id", index=True)
    version_no: int
    file_path: str                                       # inside the exports/files volume
    content_hash: str
    created_at: datetime = Field(default_factory=utcnow)


class AnswerBankItem(SQLModel, table=True):
    __tablename__ = "answer_bank"

    id: int | None = Field(default=None, primary_key=True)
    category: AnswerCategory
    name: str = Field(unique=True)                       # "work_auth_us"
    question_pattern: str                                # regex/substring the question matches
    notes: str = ""
    created_at: datetime = Field(default_factory=utcnow)


class AnswerBankVariant(SQLModel, table=True):
    __tablename__ = "answer_bank_variants"

    id: int | None = Field(default=None, primary_key=True)
    answer_id: int = Field(foreign_key="answer_bank.id", index=True)
    track_id: int | None = Field(default=None, foreign_key="resume_tracks.id")
    answer_text: str
    safety: AnswerSafety = AnswerSafety.requires_review
    enabled: bool = True
    last_verified_at: datetime | None = None
    meta: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
