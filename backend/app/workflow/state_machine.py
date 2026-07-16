"""Application lifecycle state machine.

Transitions are data, guards are named functions, and the ONLY way to move an
application between states is `transition()`, which also writes the audit event.
"""
from collections.abc import Callable
from dataclasses import dataclass

from sqlmodel import Session

from app.models.applications import Application, ApplicationEvent
from app.models.base import ApplicationState as S
from app.models.base import EventActor, utcnow


class TransitionError(Exception):
    pass


@dataclass
class Ctx:
    """Everything a guard might need. Populated by the caller."""
    fit_score: float | None = None
    min_fit_threshold: float | None = None
    policy_allows_packet: bool = False
    policy_allows_submit: bool = False
    policy_allows_browser_assist: bool = False
    missing_fields: list[str] | None = None
    human_action: bool = False
    forbidden_answers_needed: bool = False


Guard = Callable[[Ctx], tuple[bool, str]]


def _ok(_: Ctx) -> tuple[bool, str]:
    return True, ""


def g_fit_meets_threshold(c: Ctx) -> tuple[bool, str]:
    if c.fit_score is None or c.min_fit_threshold is None:
        return False, "fit score or threshold missing"
    if c.fit_score < c.min_fit_threshold:
        return False, f"fit {c.fit_score:.1f} below threshold {c.min_fit_threshold:.1f}"
    return True, ""


def g_packet_allowed(c: Ctx) -> tuple[bool, str]:
    if c.forbidden_answers_needed:
        return False, "packet requires forbidden-for-auto-use answers"
    if not c.policy_allows_packet:
        return False, "source policy does not allow packet generation"
    return True, ""


def g_human_approved(c: Ctx) -> tuple[bool, str]:
    if not c.human_action:
        return False, "requires explicit human action"
    if c.missing_fields:
        return False, f"missing required fields: {', '.join(c.missing_fields)}"
    return True, ""


def g_submit_allowed(c: Ctx) -> tuple[bool, str]:
    if not c.policy_allows_submit:
        return False, "policy gate denied submission"
    return True, ""


def g_browser_assist_allowed(c: Ctx) -> tuple[bool, str]:
    if not c.policy_allows_browser_assist:
        return False, "policy gate denied browser assist"
    return True, ""


# (from, to) -> guard
TRANSITIONS: dict[tuple[S, S], Guard] = {
    (S.discovered, S.normalized): _ok,
    (S.normalized, S.deduped): _ok,
    (S.deduped, S.scored): _ok,
    (S.scored, S.rejected_low_fit): _ok,
    (S.scored, S.blocked_by_policy): _ok,
    (S.scored, S.packet_ready): lambda c: _and(g_fit_meets_threshold(c), g_packet_allowed(c)),
    (S.packet_ready, S.queued_for_review): _ok,
    (S.packet_ready, S.blocked_by_policy): _ok,
    (S.queued_for_review, S.modified_by_user): lambda c: (c.human_action, "requires human"),
    (S.modified_by_user, S.queued_for_review): _ok,
    (S.queued_for_review, S.approved_for_submission): g_human_approved,
    (S.modified_by_user, S.approved_for_submission): g_human_approved,
    (S.approved_for_submission, S.ready_to_submit): g_submit_allowed,
    (S.approved_for_submission, S.manual_assist_in_progress): g_browser_assist_allowed,
    (S.approved_for_submission, S.submitted): lambda c: (
        c.human_action, "handoff completion must be confirmed by human",
    ),
    (S.manual_assist_in_progress, S.submitted): lambda c: (c.human_action, "requires human"),
    (S.manual_assist_in_progress, S.failed_submission): _ok,
    (S.ready_to_submit, S.submitted): _ok,
    (S.ready_to_submit, S.failed_submission): _ok,
    (S.failed_submission, S.queued_for_review): _ok,
    (S.submitted, S.followup_needed): _ok,
    (S.submitted, S.archived): _ok,
    (S.followup_needed, S.archived): _ok,
    (S.rejected_low_fit, S.archived): _ok,
    (S.blocked_by_policy, S.archived): _ok,
    (S.blocked_by_policy, S.queued_for_review): g_human_approved,  # human can rescue w/ handoff
}

_TERMINAL = {S.archived}
_ERROR_ELIGIBLE = {
    S.discovered, S.normalized, S.deduped, S.scored, S.packet_ready,
    S.queued_for_review, S.approved_for_submission, S.manual_assist_in_progress,
    S.ready_to_submit,
}


def _and(a: tuple[bool, str], b: tuple[bool, str]) -> tuple[bool, str]:
    if not a[0]:
        return a
    return b


def can_transition(frm: S, to: S, ctx: Ctx) -> tuple[bool, str]:
    if frm in _TERMINAL:
        return False, f"{frm} is terminal"
    if to == S.errored:
        return (frm in _ERROR_ELIGIBLE), "" if frm in _ERROR_ELIGIBLE else f"{frm} cannot error"
    if to == frm:
        return False, "no-op transition"
    guard = TRANSITIONS.get((frm, to))
    if guard is None:
        return False, f"illegal transition {frm} -> {to}"
    return guard(ctx)


def transition(
    session: Session,
    app: Application,
    to: S,
    ctx: Ctx,
    actor: EventActor = EventActor.system,
    detail: dict | None = None,
) -> Application:
    allowed, why = can_transition(app.state, to, ctx)
    if not allowed:
        raise TransitionError(f"{app.state} -> {to} denied: {why}")
    frm = app.state
    app.state = to
    app.updated_at = utcnow()
    session.add(app)
    session.add(ApplicationEvent(
        application_id=app.id,
        event_type="state_change",
        actor=actor,
        payload={"from": frm, "to": to, **(detail or {})},
    ))
    return app
