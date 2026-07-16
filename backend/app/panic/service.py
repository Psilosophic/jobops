"""Panic Control Layer. All changes logged with operator intent; enforcement happens
in policy.gate() which reads PanicState on every decision."""
from sqlmodel import Session

from app.models.base import utcnow
from app.models.ops import PanicPanelEvent, PanicState

MUTABLE_FLAGS = {
    "submissions_paused", "discover_only_all", "browser_automation_paused",
    "outbound_email_paused", "review_required_all",
}


def get_state(session: Session) -> PanicState:
    state = session.get(PanicState, 1)
    if state is None:
        state = PanicState(id=1)
        session.add(state)
        session.commit()
        session.refresh(state)
    return state


def set_flag(session: Session, flag: str, value: bool, operator_intent: str) -> PanicState:
    if flag not in MUTABLE_FLAGS:
        raise ValueError(f"unknown panic flag: {flag}")
    state = get_state(session)
    setattr(state, flag, value)
    state.updated_at = utcnow()
    session.add(state)
    session.add(PanicPanelEvent(action=f"set:{flag}={value}", operator_intent=operator_intent))
    session.commit()
    session.refresh(state)
    return state


def set_min_fit_override(session: Session, value: float | None, intent: str) -> PanicState:
    state = get_state(session)
    state.min_fit_override = value
    state.updated_at = utcnow()
    session.add(state)
    session.add(PanicPanelEvent(action=f"set:min_fit_override={value}", operator_intent=intent))
    session.commit()
    session.refresh(state)
    return state


def set_list(session: Session, which: str, values: list, intent: str) -> PanicState:
    if which not in ("paused_sources", "disabled_tracks", "disabled_answer_variants"):
        raise ValueError(f"unknown panic list: {which}")
    state = get_state(session)
    setattr(state, which, values)
    state.updated_at = utcnow()
    session.add(state)
    session.add(PanicPanelEvent(action=f"set:{which}", scope=str(values),
                                operator_intent=intent))
    session.commit()
    session.refresh(state)
    return state


def emergency_stop(session: Session, intent: str) -> PanicState:
    """The big red button: stop everything outbound, keep discovery alive."""
    state = get_state(session)
    state.submissions_paused = True
    state.discover_only_all = True
    state.browser_automation_paused = True
    state.outbound_email_paused = True
    state.review_required_all = True
    state.updated_at = utcnow()
    session.add(state)
    session.add(PanicPanelEvent(action="emergency_stop", operator_intent=intent))
    session.commit()
    session.refresh(state)
    return state


def log_prevented(session: Session, action: str, detail: dict) -> None:
    session.add(PanicPanelEvent(action="prevented", scope=action, prevented_action=detail))
    session.commit()
