"""Shared enums and base helpers for all models."""
from datetime import datetime, timezone

from sqlalchemy import JSON
from sqlalchemy.dialects.postgresql import JSONB

# Portable JSON column: JSONB on Postgres (prod), plain JSON elsewhere (tests).
JSONVariant = JSON().with_variant(JSONB(), "postgresql")

try:
    from enum import StrEnum
except ImportError:  # pragma: no cover — py<3.11 fallback, prod image is 3.12
    from enum import Enum

    class StrEnum(str, Enum):
        def __str__(self) -> str:
            return str(self.value)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class SourceMode(StrEnum):
    """Policy-assigned workflow mode for a source. Order = restrictiveness."""
    discover_only = "discover_only"
    qualify_only = "qualify_only"
    packet_only = "packet_only"
    queued_for_review = "queued_for_review"
    manual_assist = "manual_assist"
    auto_submit_allowed = "auto_submit_allowed"


class SourceType(StrEnum):
    board = "board"
    ats = "ats"
    employer_page = "employer_page"
    mailbox = "mailbox"


class RiskLevel(StrEnum):
    low = "low"
    medium = "medium"
    med_high = "med_high"
    high = "high"


class HealthEventType(StrEnum):
    ok = "ok"
    error = "error"
    rate_limited = "rate_limited"
    policy_drift = "policy_drift"


class PostingStatus(StrEnum):
    active = "active"
    closed = "closed"
    stale = "stale"


class AnswerSafety(StrEnum):
    safe_for_auto_use = "safe_for_auto_use"
    requires_review = "requires_review"
    forbidden_for_auto_use = "forbidden_for_auto_use"


class AnswerCategory(StrEnum):
    work_authorization = "work_authorization"
    sponsorship = "sponsorship"
    experience_years = "experience_years"
    work_setup = "work_setup"
    compensation = "compensation"
    relocation = "relocation"
    travel = "travel"
    certifications = "certifications"
    notice_period = "notice_period"
    technology = "technology"
    yes_no = "yes_no"
    custom = "custom"


class ApplicationState(StrEnum):
    discovered = "discovered"
    normalized = "normalized"
    deduped = "deduped"
    scored = "scored"
    rejected_low_fit = "rejected_low_fit"
    blocked_by_policy = "blocked_by_policy"
    packet_ready = "packet_ready"
    queued_for_review = "queued_for_review"
    modified_by_user = "modified_by_user"
    approved_for_submission = "approved_for_submission"
    manual_assist_in_progress = "manual_assist_in_progress"
    ready_to_submit = "ready_to_submit"
    submitted = "submitted"
    followup_needed = "followup_needed"
    failed_submission = "failed_submission"
    errored = "errored"
    archived = "archived"


class SubmissionMode(StrEnum):
    none = "none"
    handoff_launch = "handoff_launch"     # open official page + copy panel
    manual_assist = "manual_assist"       # policy-allowed prefill, human confirms
    auto_submit = "auto_submit"           # policy-allowed full submission


class EventActor(StrEnum):
    system = "system"
    user = "user"


class ListKind(StrEnum):
    employer = "employer"
    industry = "industry"
    title = "title"
    keyword = "keyword"
    source = "source"
