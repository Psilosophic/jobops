"""Application packet builder.

Assembles a truthful, auditable packet: resume version for the chosen track +
answer-bank answers with safety enforcement. NEVER synthesizes an answer — a
question the vault can't answer becomes a missing_field that disables Submit.
"""
import re

from sqlmodel import Session, select

from app.models.applications import Application, ApplicationPacket, ReviewQueueItem
from app.models.base import AnswerSafety, EventActor
from app.models.employers import Employer, EmployerMemoryNote
from app.models.jobs import JobPosting
from app.models.ops import PanicState
from app.models.profile import (
    AnswerBankItem, AnswerBankVariant, Resume, ResumeTrack, ResumeVersion,
)
from app.models.scoring import ScoringExplanation

# The standard screener set every packet pre-answers (job-specific questions are
# merged in by the manual-assist layer in Phase 4).
STANDARD_QUESTIONS = [
    ("work_auth_us", "Are you legally authorized to work in the United States?"),
    ("sponsorship_now", "Will you now or in the future require sponsorship?"),
    ("remote_pref", "What is your remote/hybrid/onsite preference?"),
    ("salary_expectation", "What are your salary expectations?"),
]


def pick_variant(
    session: Session,
    item: AnswerBankItem,
    track_id: int | None,
    panic: PanicState,
) -> AnswerBankVariant | None:
    """Track-specific variant wins over generic; disabled/panic-disabled excluded."""
    variants = list(session.exec(
        select(AnswerBankVariant).where(
            AnswerBankVariant.answer_id == item.id,
            AnswerBankVariant.enabled == True,  # noqa: E712
        )
    ))
    variants = [v for v in variants if v.id not in (panic.disabled_answer_variants or [])]
    for v in variants:
        if track_id is not None and v.track_id == track_id:
            return v
    for v in variants:
        if v.track_id is None:
            return v
    return None


def match_bank_item(session: Session, question: str) -> AnswerBankItem | None:
    for item in session.exec(select(AnswerBankItem)):
        try:
            if re.search(item.question_pattern, question, re.I):
                return item
        except re.error:
            continue
    return None


def build_packet(session: Session, app: Application) -> tuple[ApplicationPacket, list[str]]:
    """Returns (packet, missing_fields). Also creates/refreshes the review queue row
    and the employer memory note."""
    posting = session.get(JobPosting, app.posting_id)
    panic = session.get(PanicState, 1) or PanicState(id=1)
    explanation = session.exec(
        select(ScoringExplanation).where(ScoringExplanation.posting_id == posting.id)
        .order_by(ScoringExplanation.created_at.desc())
    ).first()

    # --- resume track + version ---
    track = None
    if explanation and explanation.chosen_track:
        track = session.exec(
            select(ResumeTrack).where(ResumeTrack.slug == explanation.chosen_track)
        ).first()
    missing: list[str] = []
    resume_version = None
    if track is None:
        missing.append("resume_track")
    else:
        app.track_id = track.id
        resume = session.exec(select(Resume).where(Resume.track_id == track.id)).first()
        if resume:
            resume_version = session.exec(
                select(ResumeVersion).where(ResumeVersion.resume_id == resume.id)
                .order_by(ResumeVersion.version_no.desc())
            ).first()
        if resume_version is None:
            missing.append(f"resume_file:{track.slug}")
        else:
            app.resume_version_id = resume_version.id

    # --- answers, safety-enforced ---
    answers: list[dict] = []
    requires_review = False
    for name, question in STANDARD_QUESTIONS:
        item = session.exec(select(AnswerBankItem).where(AnswerBankItem.name == name)).first() \
            or match_bank_item(session, question)
        variant = pick_variant(session, item, app.track_id, panic) if item else None
        if variant is None or variant.safety == AnswerSafety.forbidden_for_auto_use:
            missing.append(f"answer:{name}")
            answers.append({"question": question, "answer_name": name, "variant_id": None,
                            "text": None, "status": "missing"})
            continue
        if variant.safety == AnswerSafety.requires_review:
            requires_review = True
        answers.append({
            "question": question, "answer_name": name, "variant_id": variant.id,
            "text": variant.answer_text, "safety": str(variant.safety),
            "user_edited": False, "status": "prefilled",
        })

    last = session.exec(
        select(ApplicationPacket).where(ApplicationPacket.application_id == app.id)
        .order_by(ApplicationPacket.version_no.desc())
    ).first()
    packet = ApplicationPacket(
        application_id=app.id,
        version_no=(last.version_no + 1) if last else 1,
        snapshot={
            "track": track.slug if track else None,
            "track_rationale": explanation.rationale if explanation else "",
            "track_scores": explanation.track_scores if explanation else {},
            "resume_version_id": resume_version.id if resume_version else None,
            "resume_file": resume_version.file_path if resume_version else None,
            "summary": "", "cover_note": "",
            "answers": answers,
            "requires_review": True,  # everything starts human-reviewed
            "has_requires_review_answers": requires_review,
            "fit_score": app.fit_score,
        },
        created_by=EventActor.system,
    )
    session.add(packet)
    session.add(app)

    queue_item = session.exec(
        select(ReviewQueueItem).where(ReviewQueueItem.application_id == app.id)
    ).first()
    if queue_item is None:
        queue_item = ReviewQueueItem(application_id=app.id)
    queue_item.priority = app.fit_score or 0.0
    queue_item.missing_fields = missing
    session.add(queue_item)

    _upsert_memory_note(session, posting, explanation)
    session.commit()
    session.refresh(packet)
    return packet, missing


def _upsert_memory_note(session: Session, posting: JobPosting, explanation) -> None:
    if posting.employer_id is None:
        return
    emp = session.get(Employer, posting.employer_id)
    note = session.exec(
        select(EmployerMemoryNote).where(EmployerMemoryNote.employer_id == emp.id)
    ).first() or EmployerMemoryNote(employer_id=emp.id)
    note.role_family = (explanation.chosen_track if explanation else None) or note.role_family
    salary = (f"${posting.salary_min:,}-${posting.salary_max:,}"
              if posting.salary_min and posting.salary_max else "salary not posted")
    note.note_md = (
        f"**{emp.canonical_name}** — {posting.title}\n\n"
        f"- Location: {posting.location_raw or ('Remote' if posting.is_remote else 'n/a')}\n"
        f"- Comp: {salary}\n"
        f"- Why it matched: {explanation.rationale if explanation else 'n/a'}\n"
        f"- Posting: {posting.url}\n"
    )
    note.talking_points = [
        f"Applied via {posting.url.split('/')[2]}",
        f"Track: {note.role_family or 'n/a'}",
        f"Fit rationale: {(explanation.rationale[:160] if explanation else 'n/a')}",
    ]
    note.keywords = list((posting.raw or {}).keys())[:10]
    session.add(note)
