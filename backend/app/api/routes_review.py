"""Review queue API — powers the three-control review screen
(Resume Track dropdown / Modify / Submit)."""
from fastapi import APIRouter, Body, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.applications import Application, ApplicationPacket, ReviewQueueItem
from app.models.base import ApplicationState as S
from app.models.employers import Employer, EmployerMemoryNote
from app.models.jobs import JobPosting
from app.models.profile import ResumeTrack
from app.models.scoring import ScoringExplanation
from app.models.sources import Source, SourcePolicy
from fastapi.responses import FileResponse
from app.workflow import review as svc
from app.workflow.manual_assist import build_bookmarklet, build_prefill_map
from app.workflow.state_machine import Ctx, TransitionError, transition

router = APIRouter(prefix="/review", tags=["review"])


def _app_or_404(session: Session, app_id: int) -> Application:
    app = session.get(Application, app_id)
    if app is None:
        raise HTTPException(404, "application not found")
    return app


@router.get("")
def queue(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.exec(
        select(ReviewQueueItem, Application)
        .join(Application, Application.id == ReviewQueueItem.application_id)
        .where(ReviewQueueItem.resolved_at == None)  # noqa: E711
        .order_by(ReviewQueueItem.priority.desc())
    )
    out = []
    for item, app in rows:
        posting = session.get(JobPosting, app.posting_id)
        emp = session.get(Employer, posting.employer_id) if posting.employer_id else None
        out.append({
            "queue_id": item.id, "application_id": app.id,
            "title": posting.title, "employer": emp.canonical_name if emp else None,
            "fit_score": app.fit_score, "state": str(app.state),
            "missing_fields": item.missing_fields,
            "url": posting.url, "location": posting.location_raw,
            "is_remote": posting.is_remote,
            "salary_min": posting.salary_min, "salary_max": posting.salary_max,
            "duplicate_confidence": posting.duplicate_confidence,
            "queued_at": item.queued_at.isoformat(),
        })
    return out


@router.get("/{app_id}")
def detail(app_id: int, session: Session = Depends(get_session)) -> dict:
    app = _app_or_404(session, app_id)
    posting = session.get(JobPosting, app.posting_id)
    source = session.get(Source, posting.source_id)
    policy = session.exec(
        select(SourcePolicy).where(SourcePolicy.source_id == posting.source_id)
    ).first()
    explanation = session.exec(
        select(ScoringExplanation).where(ScoringExplanation.posting_id == posting.id)
        .order_by(ScoringExplanation.created_at.desc())
    ).first()
    packet = session.exec(
        select(ApplicationPacket).where(ApplicationPacket.application_id == app.id)
        .order_by(ApplicationPacket.version_no.desc())
    ).first()
    memory = None
    if posting.employer_id:
        note = session.exec(select(EmployerMemoryNote).where(
            EmployerMemoryNote.employer_id == posting.employer_id)).first()
        memory = note.model_dump() if note else None
    tracks = [
        {"slug": t.slug, "name": t.name,
         "score": (explanation.track_scores or {}).get(t.slug) if explanation else None,
         "selected": t.id == app.track_id}
        for t in session.exec(select(ResumeTrack).where(ResumeTrack.enabled == True))  # noqa: E712
    ]
    return {
        "application": app.model_dump(),
        "posting": posting.model_dump(exclude={"raw"}),
        "source": {"slug": source.slug, "name": source.name},
        "policy": {"mode": str(policy.recommended_mode),
                   "auto_submit_allowed": policy.auto_submit_allowed,
                   "browser_automation_allowed": policy.browser_automation_allowed}
        if policy else None,
        "scoring": explanation.model_dump() if explanation else None,
        "track_options": tracks,
        "track_why": explanation.rationale if explanation else "",
        "packet": packet.model_dump() if packet else None,
    }


class TrackBody(BaseModel):
    track_slug: str


@router.post("/{app_id}/track")
def override_track(app_id: int, body: TrackBody,
                   session: Session = Depends(get_session)) -> dict:
    app = _app_or_404(session, app_id)
    try:
        packet = svc.set_track(session, app, body.track_slug)
    except svc.ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return packet.model_dump()


class ModifyBody(BaseModel):
    summary: str | None = None
    cover_note: str | None = None
    answers: list[dict] | None = None


@router.post("/{app_id}/modify")
def modify(app_id: int, body: ModifyBody,
           session: Session = Depends(get_session)) -> dict:
    app = _app_or_404(session, app_id)
    try:
        packet = svc.modify_packet(session, app, body.model_dump(exclude_none=True))
    except svc.ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return packet.model_dump()


@router.post("/{app_id}/submit")
def submit(app_id: int, session: Session = Depends(get_session)) -> dict:
    """One click: approve + policy-routed next step. Never bypasses policy."""
    app = _app_or_404(session, app_id)
    try:
        next_step = svc.approve(session, app)
    except (svc.ReviewError, TransitionError) as exc:
        raise HTTPException(422, str(exc)) from exc
    if next_step.get("mode") == "manual_assist":
        from app.tasks import manual_assist_prefill
        manual_assist_prefill.delay(app.id)
        next_step["assist_dispatched"] = True
    return next_step


class OutcomeBody(BaseModel):
    success: bool
    detail: str = ""


@router.post("/{app_id}/confirm")
def confirm(app_id: int, body: OutcomeBody,
            session: Session = Depends(get_session)) -> dict:
    app = _app_or_404(session, app_id)
    try:
        app = svc.confirm_submitted(session, app, body.success, body.detail)
    except svc.ReviewError as exc:
        raise HTTPException(422, str(exc)) from exc
    return app.model_dump()


@router.post("/{app_id}/rescue")
def rescue_blocked(app_id: int, session: Session = Depends(get_session)) -> dict:
    """Human rescues a blocked_by_policy app into the review queue for a compliant
    handoff (never into automation)."""
    app = _app_or_404(session, app_id)
    if app.state != S.blocked_by_policy:
        raise HTTPException(422, f"state is {app.state}, not blocked_by_policy")
    from app.workflow.packet import build_packet
    build_packet(session, app)
    transition(session, app, S.queued_for_review, Ctx(human_action=True))
    session.commit()
    return app.model_dump()


@router.get("/{app_id}/assist")
def assist_status(app_id: int, session: Session = Depends(get_session)) -> dict:
    """Prefill map + bookmarklet + latest headless prefill report/screenshot."""
    from app.models.applications import ApplicationEvent
    app = _app_or_404(session, app_id)
    pm = build_prefill_map(session, app)
    last = session.exec(
        select(ApplicationEvent).where(
            ApplicationEvent.application_id == app_id,
            ApplicationEvent.event_type == "manual_assist_prefill",
        ).order_by(ApplicationEvent.created_at.desc())
    ).first()
    return {
        "prefill": pm.as_dict(),
        "bookmarklet": build_bookmarklet(pm),
        "report": last.payload if last else None,
        "screenshot_url": f"/review/{app_id}/assist/screenshot" if last else None,
    }


@router.post("/{app_id}/assist")
def assist_trigger(app_id: int, session: Session = Depends(get_session)) -> dict:
    """Manually (re)run the headless prefill for this application."""
    app = _app_or_404(session, app_id)
    from app.tasks import manual_assist_prefill
    manual_assist_prefill.delay(app.id)
    return {"dispatched": app.id}


@router.get("/{app_id}/assist/screenshot")
def assist_screenshot(app_id: int):
    from pathlib import Path
    shot = Path(f"/srv/jobops/exports/assist/app_{app_id}.png")
    if not shot.exists():
        raise HTTPException(404, "no screenshot yet")
    return FileResponse(str(shot), media_type="image/png")
