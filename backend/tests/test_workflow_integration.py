"""End-to-end on SQLite: posting -> score/stage -> packet -> queue -> modify ->
submit routing -> confirm. Asserts the audit chain and the policy guardrails."""
from sqlmodel import select

from app.models.applications import Application, ApplicationEvent, ReviewQueueItem
from app.models.base import (
    AnswerCategory, AnswerSafety, ApplicationState as S, RiskLevel, SourceMode,
    SourceType,
)
from app.models.employers import Employer, EmployerMemoryNote
from app.models.jobs import JobPosting
from app.models.ops import PanicState
from app.models.profile import (
    AnswerBankItem, AnswerBankVariant, Resume, ResumeTrack, ResumeVersion,
)
from app.models.scoring import KeywordPack, ScoringProfile
from app.models.sources import Source, SourcePolicy
from app.pipeline.ingest import score_and_stage
from app.workflow import review as svc


def seed_world(session, mode=SourceMode.manual_assist, browser=True,
               with_resume=True, safe_answers=True):
    session.add(PanicState(id=1, review_required_all=True))
    src = Source(slug="greenhouse", name="GH", source_type=SourceType.ats,
                 retrieval_method="official_api", config={})
    session.add(src)
    session.commit()
    session.add(SourcePolicy(source_id=src.id, browser_automation_allowed=browser,
                             recommended_mode=mode, risk_level=RiskLevel.low))
    track = ResumeTrack(slug="iam", name="IAM")
    session.add(track)
    session.commit()
    if with_resume:
        resume = Resume(track_id=track.id, name="IAM resume")
        session.add(resume)
        session.commit()
        session.add(ResumeVersion(resume_id=resume.id, version_no=1,
                                  file_path="/files/iam_v1.pdf", content_hash="h"))
    session.add(ScoringProfile(name="default", is_active=True))
    session.add(KeywordPack(
        name="iam", track_slug="iam",
        include={"titles": ["iam engineer"],
                 "required_tech": ["saml", "oauth"],
                 "preferred_tech": ["pingfederate", "entra", "mfa", "oidc",
                                    "active directory"]},
        exclude={"titles": [], "tech": []},
    ))
    safety = AnswerSafety.safe_for_auto_use if safe_answers else \
        AnswerSafety.forbidden_for_auto_use
    for name, cat, text in (
        ("work_auth_us", AnswerCategory.work_authorization, "Yes"),
        ("sponsorship_now", AnswerCategory.sponsorship, "No"),
        ("remote_pref", AnswerCategory.work_setup, "Remote or Denver hybrid"),
        ("salary_expectation", AnswerCategory.compensation, "$110k+"),
    ):
        item = AnswerBankItem(name=name, category=cat, question_pattern=name)
        session.add(item)
        session.commit()
        session.add(AnswerBankVariant(answer_id=item.id, answer_text=text, safety=safety))
    emp = Employer(canonical_name="Acme Identity")
    session.add(emp)
    session.commit()
    posting = JobPosting(
        source_id=src.id, employer_id=emp.id, external_id="1", dedupe_fingerprint="fp",
        url="https://boards.greenhouse.io/acme/jobs/1", title="IAM Engineer",
        description_text="SAML OAuth OIDC PingFederate Entra MFA Active Directory",
        location_raw="Denver, CO", salary_min=110000, salary_max=140000,
    )
    session.add(posting)
    session.commit()
    return posting


def get_app(session, posting):
    return session.exec(
        select(Application).where(Application.posting_id == posting.id)
    ).first()


def test_full_flow_to_manual_assist(session):
    posting = seed_world(session)
    score_and_stage(session, posting)
    app = get_app(session, posting)
    assert app.state == S.queued_for_review
    queue = session.exec(select(ReviewQueueItem)).first()
    assert queue.missing_fields == []

    # Modify: edit cover note -> new packet version, user_edited flagged
    packet = svc.modify_packet(session, app, {"cover_note": "Hi, I'm Scott."})
    assert packet.version_no == 2
    assert packet.snapshot["cover_note"] == "Hi, I'm Scott."
    assert app.user_modified

    # Submit: policy says manual_assist, NOT auto
    next_step = svc.approve(session, app)
    assert next_step["mode"] == "manual_assist"
    assert app.state == S.manual_assist_in_progress

    # Human confirms completion
    svc.confirm_submitted(session, app, success=True)
    assert app.state == S.submitted
    events = [e.event_type for e in session.exec(select(ApplicationEvent))]
    assert "state_change" in events and "packet_modified" in events

    # Employer memory note exists with talking points
    note = session.exec(select(EmployerMemoryNote)).first()
    assert note is not None and "Acme Identity" in note.note_md


def test_forbidden_answers_block_submit(session):
    posting = seed_world(session, safe_answers=False)
    score_and_stage(session, posting)
    app = get_app(session, posting)
    queue = session.exec(select(ReviewQueueItem)).first()
    assert any(m.startswith("answer:") for m in queue.missing_fields)
    try:
        svc.approve(session, app)
        raise AssertionError("approve should have failed")
    except svc.ReviewError as exc:
        assert "missing" in str(exc)


def test_missing_resume_blocks_submit(session):
    posting = seed_world(session, with_resume=False)
    score_and_stage(session, posting)
    app = get_app(session, posting)
    try:
        svc.approve(session, app)
        raise AssertionError("approve should have failed")
    except svc.ReviewError as exc:
        assert "resume" in str(exc)


def test_discover_only_source_never_queues(session):
    posting = seed_world(session, mode=SourceMode.discover_only, browser=False)
    score_and_stage(session, posting)
    app = get_app(session, posting)
    assert app.state == S.blocked_by_policy


def test_handoff_when_browser_assist_denied(session):
    posting = seed_world(session, mode=SourceMode.queued_for_review, browser=False)
    score_and_stage(session, posting)
    app = get_app(session, posting)
    assert app.state == S.queued_for_review
    next_step = svc.approve(session, app)
    assert next_step["mode"] == "handoff_launch"
    assert next_step["launch_url"] == posting.url
    # prevented auto-submit is logged
    from app.models.ops import PanicPanelEvent
    prevented = [e for e in session.exec(select(PanicPanelEvent))
                 if e.action == "prevented"]
    assert prevented


def test_track_override_logged_and_versioned(session):
    posting = seed_world(session)
    session.add(ResumeTrack(slug="support_enablement", name="Support"))
    session.commit()
    score_and_stage(session, posting)
    app = get_app(session, posting)
    packet = svc.set_track(session, app, "support_enablement")
    assert packet.snapshot["track"] == "support_enablement"
    events = [e for e in session.exec(select(ApplicationEvent))
              if e.event_type == "track_override"]
    assert len(events) == 1


def test_panic_stop_blocks_mid_queue_submission(session):
    posting = seed_world(session)
    score_and_stage(session, posting)
    app = get_app(session, posting)
    from app.panic.service import emergency_stop
    emergency_stop(session, "test drill")
    next_step = svc.approve(session, app)
    # panic forces the compliant handoff path, never automation
    assert next_step["mode"] == "handoff_launch"
