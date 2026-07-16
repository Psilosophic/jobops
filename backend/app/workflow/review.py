"""Review queue workflow service: Modify / Submit / track override — the exact
three-control interaction model, minus pixels (API layer renders it)."""
from sqlmodel import Session, select

from app.models.applications import (
    Application, ApplicationEvent, ApplicationPacket, ReviewQueueItem,
)
from app.models.base import ApplicationState as S
from app.models.base import EventActor, SubmissionMode, utcnow
from app.models.jobs import JobPosting
from app.models.ops import PanicState
from app.models.profile import Resume, ResumeTrack, ResumeVersion
from app.models.sources import SourcePolicy
from app.panic.service import log_prevented
from app.policy.engine import Action, gate
from app.workflow.state_machine import Ctx, TransitionError, transition


class ReviewError(Exception):
    pass


def _latest_packet(session: Session, app_id: int) -> ApplicationPacket | None:
    return session.exec(
        select(ApplicationPacket).where(ApplicationPacket.application_id == app_id)
        .order_by(ApplicationPacket.version_no.desc())
    ).first()


def set_track(session: Session, app: Application, track_slug: str) -> ApplicationPacket:
    """Manual track override from the dropdown. Logged; rebuilds resume linkage."""
    track = session.exec(select(ResumeTrack).where(ResumeTrack.slug == track_slug)).first()
    if track is None:
        raise ReviewError(f"unknown track: {track_slug}")
    old = app.track_id
    app.track_id = track.id
    resume = session.exec(select(Resume).where(Resume.track_id == track.id)).first()
    rv = None
    if resume:
        rv = session.exec(
            select(ResumeVersion).where(ResumeVersion.resume_id == resume.id)
            .order_by(ResumeVersion.version_no.desc())
        ).first()
    app.resume_version_id = rv.id if rv else None
    session.add(app)
    session.add(ApplicationEvent(
        application_id=app.id, event_type="track_override", actor=EventActor.user,
        payload={"from_track_id": old, "to_track": track_slug,
                 "resume_version_id": app.resume_version_id},
    ))
    packet = _latest_packet(session, app.id)
    snap = dict(packet.snapshot)
    snap["track"] = track_slug
    snap["resume_version_id"] = app.resume_version_id
    snap["resume_file"] = rv.file_path if rv else None
    new = ApplicationPacket(application_id=app.id, version_no=packet.version_no + 1,
                            snapshot=snap, created_by=EventActor.user)
    session.add(new)
    session.commit()
    session.refresh(new)
    return new


def modify_packet(session: Session, app: Application, edits: dict) -> ApplicationPacket:
    """Modify button: saves edited fields into a NEW packet version with user-edited
    flags. Submits nothing."""
    packet = _latest_packet(session, app.id)
    if packet is None:
        raise ReviewError("no packet to modify")
    snap = dict(packet.snapshot)
    edited_fields: list[str] = []
    for key in ("summary", "cover_note"):
        if key in edits and edits[key] != snap.get(key):
            snap[key] = edits[key]
            edited_fields.append(key)
    if "answers" in edits:
        by_name = {a["answer_name"]: a for a in snap.get("answers", [])}
        for edit in edits["answers"]:
            row = by_name.get(edit.get("answer_name"))
            if row is not None and edit.get("text") is not None:
                row["original_text"] = row.get("text")
                row["text"] = edit["text"]
                row["user_edited"] = True
                row["status"] = "user_edited"
                edited_fields.append(f"answer:{edit['answer_name']}")
    if not edited_fields:
        raise ReviewError("no changes supplied")
    new = ApplicationPacket(application_id=app.id, version_no=packet.version_no + 1,
                            snapshot=snap, created_by=EventActor.user)
    app.user_modified = True
    session.add(new)
    session.add(app)
    session.add(ApplicationEvent(
        application_id=app.id, event_type="packet_modified", actor=EventActor.user,
        payload={"fields": edited_fields, "packet_version": new.version_no},
    ))
    if app.state == S.queued_for_review:
        transition(session, app, S.modified_by_user, Ctx(human_action=True),
                   actor=EventActor.user)
        transition(session, app, S.queued_for_review, Ctx(human_action=True),
                   actor=EventActor.user)
    session.commit()
    session.refresh(new)
    return new


def approve(session: Session, app: Application) -> dict:
    """Submit button, step 1: approve + route by policy. Returns what the UI should
    do next: auto submission task, manual-assist task, or handoff launch."""
    queue = session.exec(
        select(ReviewQueueItem).where(ReviewQueueItem.application_id == app.id)
    ).first()
    missing = list(queue.missing_fields) if queue else []
    # recompute missing against the LATEST packet (user may have filled answers)
    packet = _latest_packet(session, app.id)
    if packet:
        still_missing = [a["answer_name"] for a in packet.snapshot.get("answers", [])
                         if a.get("status") == "missing"]
        missing = [m for m in missing if not m.startswith("answer:")] \
            + [f"answer:{n}" for n in still_missing]
        if packet.snapshot.get("resume_version_id") is None:
            if not any(m.startswith("resume_file") for m in missing):
                missing.append("resume_file")
        else:
            missing = [m for m in missing if not m.startswith("resume_file")]
    if missing:
        raise ReviewError(f"cannot submit — missing: {', '.join(sorted(set(missing)))}")

    posting = session.get(JobPosting, app.posting_id)
    policy = session.exec(
        select(SourcePolicy).where(SourcePolicy.source_id == posting.source_id)
    ).first()
    panic = session.get(PanicState, 1) or PanicState(id=1)

    auto = gate(Action.AUTO_SUBMIT, policy, panic, posting.source_id)
    assist = gate(Action.BROWSER_ASSIST, policy, panic, posting.source_id)

    transition(session, app, S.approved_for_submission,
               Ctx(human_action=True, missing_fields=[]), actor=EventActor.user)

    if auto.allowed:
        transition(session, app, S.ready_to_submit, Ctx(policy_allows_submit=True),
                   actor=EventActor.system, detail={"policy": auto.serialize()})
        app.submission_mode = SubmissionMode.auto_submit
        next_step = {"mode": "auto_submit", "policy": auto.serialize()}
    elif assist.allowed:
        transition(session, app, S.manual_assist_in_progress,
                   Ctx(policy_allows_browser_assist=True), actor=EventActor.system,
                   detail={"policy": assist.serialize()})
        app.submission_mode = SubmissionMode.manual_assist
        next_step = {"mode": "manual_assist", "launch_url": posting.url,
                     "policy": assist.serialize()}
    else:
        # Compliant handoff: open official page, show packet side panel.
        if not auto.allowed:
            log_prevented(session, "auto_submit", {"application_id": app.id,
                                                   "reasons": list(auto.reasons)})
        app.submission_mode = SubmissionMode.handoff_launch
        next_step = {"mode": "handoff_launch", "launch_url": posting.url,
                     "packet_version": packet.version_no if packet else None,
                     "denied_because": list(auto.reasons)}
    session.add(app)
    if queue:
        queue.resolved_at = utcnow()
        session.add(queue)
    session.commit()
    return next_step


def confirm_submitted(session: Session, app: Application, success: bool,
                      detail: str = "") -> Application:
    """Human (or Phase 4 automation) confirms the final outcome."""
    packet = _latest_packet(session, app.id)
    try:
        if success:
            transition(session, app, S.submitted, Ctx(human_action=True),
                       actor=EventActor.user, detail={
                           "packet_version": packet.version_no if packet else None,
                           "submission_mode": str(app.submission_mode),
                           "user_modified": app.user_modified, "detail": detail,
                       })
            app.submitted_at = utcnow()
        else:
            transition(session, app, S.failed_submission, Ctx(human_action=True),
                       actor=EventActor.user, detail={"detail": detail})
    except TransitionError as exc:
        raise ReviewError(str(exc)) from exc
    session.add(app)
    session.commit()
    return app
