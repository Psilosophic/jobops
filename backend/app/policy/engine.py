"""Source Policy Engine.

Every action that touches the outside world (or a submission) is gated HERE and only
here. Workflow code calls `gate(...)` immediately before acting; a DENY is final and
gets logged as a prevented action when panic caused it.

This is deliberately a pure function over (action, policy, panic) so it is trivially
testable and cannot rot into scattered if-statements.
"""
from dataclasses import dataclass, field
from app.models.base import StrEnum  # shimmed StrEnum (py3.12 native, py3.10 fallback)

from app.models.base import SourceMode
from app.models.ops import PanicState
from app.models.sources import SourcePolicy


class Action(StrEnum):
    FETCH_OFFICIAL = "fetch_official"        # official API / RSS / IMAP retrieval
    FETCH_SCRAPE = "fetch_scrape"            # any HTML retrieval outside official surfaces
    GENERATE_PACKET = "generate_packet"
    QUEUE_FOR_REVIEW = "queue_for_review"
    BROWSER_ASSIST = "browser_assist"        # Playwright prefill, human confirms
    AUTO_SUBMIT = "auto_submit"
    SEND_EMAIL = "send_email"


class Verdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyDecision:
    verdict: Verdict
    action: Action
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def allowed(self) -> bool:
        return self.verdict == Verdict.ALLOW

    def serialize(self) -> str:
        return f"{self.verdict}:{self.action}:{';'.join(self.reasons)}"


# Minimum mode required for each action (ordering = SourceMode declaration order).
_MODE_ORDER = list(SourceMode)
_MIN_MODE_FOR_ACTION: dict[Action, SourceMode] = {
    Action.FETCH_OFFICIAL: SourceMode.discover_only,
    Action.GENERATE_PACKET: SourceMode.packet_only,
    Action.QUEUE_FOR_REVIEW: SourceMode.queued_for_review,
    Action.BROWSER_ASSIST: SourceMode.manual_assist,
    Action.AUTO_SUBMIT: SourceMode.auto_submit_allowed,
}


def _mode_at_least(mode: SourceMode, minimum: SourceMode) -> bool:
    return _MODE_ORDER.index(mode) >= _MODE_ORDER.index(minimum)


def gate(
    action: Action,
    policy: SourcePolicy | None,
    panic: PanicState,
    source_id: int | None = None,
) -> PolicyDecision:
    """Decide whether `action` is permitted right now. DENY reasons are exhaustive so
    the UI can show the user exactly why a button is disabled."""
    reasons: list[str] = []

    # ---- Panic layer: checked first, overrides everything ----
    if source_id is not None and source_id in (panic.paused_sources or []):
        reasons.append(f"panic: source {source_id} is paused")
    if panic.discover_only_all and action not in (Action.FETCH_OFFICIAL,):
        reasons.append("panic: all sources forced to discover-only")
    if panic.submissions_paused and action == Action.AUTO_SUBMIT:
        reasons.append("panic: all submissions paused")
    if panic.browser_automation_paused and action == Action.BROWSER_ASSIST:
        reasons.append("panic: browser automation paused")
    if panic.outbound_email_paused and action == Action.SEND_EMAIL:
        reasons.append("panic: outbound email paused")
    if panic.review_required_all and action == Action.AUTO_SUBMIT:
        reasons.append("panic/default: review required for all applications")

    # ---- Source policy layer ----
    if action == Action.SEND_EMAIL:
        # Email needs no source policy; only panic gates it.
        pass
    elif policy is None:
        reasons.append("no policy record for source: default deny")
    else:
        if action == Action.FETCH_SCRAPE:
            # Scraping requires BOTH the explicit flag and a non-restricted mode.
            if not policy.scraping_allowed:
                reasons.append("source policy: scraping not allowed")
        elif action == Action.BROWSER_ASSIST:
            if not policy.browser_automation_allowed:
                reasons.append("source policy: browser automation not allowed")
            if not _mode_at_least(policy.recommended_mode, SourceMode.manual_assist):
                reasons.append(f"source mode '{policy.recommended_mode}' below manual_assist")
        elif action == Action.AUTO_SUBMIT:
            if not policy.auto_submit_allowed:
                reasons.append("source policy: auto-submit not allowed")
            if policy.manual_review_required:
                reasons.append("source policy: manual review required")
            if policy.recommended_mode != SourceMode.auto_submit_allowed:
                reasons.append(f"source mode '{policy.recommended_mode}' != auto_submit_allowed")
        else:
            minimum = _MIN_MODE_FOR_ACTION[action]
            if not _mode_at_least(policy.recommended_mode, minimum):
                reasons.append(
                    f"source mode '{policy.recommended_mode}' below required '{minimum}'"
                )

    if reasons:
        return PolicyDecision(Verdict.DENY, action, tuple(reasons))
    return PolicyDecision(Verdict.ALLOW, action)
