from datetime import datetime

from sqlalchemy import Column
from sqlmodel import Field, SQLModel

from app.models.base import JSONVariant, utcnow


class KeywordPack(SQLModel, table=True):
    """Per-track search targeting. include/exclude shapes:
    include = {"titles": [...], "required_tech": [...], "preferred_tech": [...]}
    exclude = {"titles": [...], "keywords": [...], "tech": [...]}
    """
    __tablename__ = "keyword_packs"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    track_slug: str = Field(index=True)                  # "iam" | "support_enablement" | ...
    include: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    exclude: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    enabled: bool = True
    updated_at: datetime = Field(default_factory=utcnow)


class ScoringProfile(SQLModel, table=True):
    __tablename__ = "scoring_profiles"

    id: int | None = Field(default=None, primary_key=True)
    name: str = Field(unique=True)
    is_active: bool = False
    # weights (0..1 fractions of a 100-pt scale)
    w_title: float = 0.25
    w_skill: float = 0.30
    w_location: float = 0.15
    w_comp: float = 0.10
    w_recency: float = 0.08
    w_employer_pref: float = 0.05
    w_track_fit: float = 0.07
    # penalties (absolute points off 100)
    p_missing_salary: float = 3.0
    p_recruiter: float = 8.0
    p_contract: float = 5.0
    p_poor_title: float = 4.0
    # thresholds (0..100)
    min_fit_threshold: float = 55.0
    manual_review_threshold: float = 65.0
    auto_queue_threshold: float = 75.0
    auto_submit_threshold: float = 90.0
    max_job_age_days: int = 21
    updated_at: datetime = Field(default_factory=utcnow)


class ScoringExplanation(SQLModel, table=True):
    """One row per scoring pass. Columns, not a blob, so SQL can aggregate components."""
    __tablename__ = "scoring_explanations"

    id: int | None = Field(default=None, primary_key=True)
    posting_id: int = Field(foreign_key="job_postings.id", index=True)
    profile_id: int = Field(foreign_key="scoring_profiles.id")
    title_match: float = 0.0
    skill_match: float = 0.0
    location_match: float = 0.0
    comp_match: float = 0.0
    recency: float = 0.0
    employer_pref: float = 0.0
    track_fit: float = 0.0
    negative_penalty: float = 0.0
    recruiter_penalty: float = 0.0
    contract_penalty: float = 0.0
    missing_salary_penalty: float = 0.0
    duplicate_confidence: float = 0.0
    policy_gate_result: str = ""                         # serialized PolicyDecision
    total: float = 0.0
    chosen_track: str | None = None
    track_scores: dict = Field(default_factory=dict, sa_column=Column(JSONVariant, nullable=False))
    rationale: str = ""                                  # template or Ollama prose
    created_at: datetime = Field(default_factory=utcnow, index=True)
