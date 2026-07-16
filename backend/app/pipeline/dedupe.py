"""Cross-source dedupe: exact fingerprint match + fuzzy title/employer confidence."""
from sqlmodel import Session, select

from app.models.jobs import DedupeGroup, JobPosting
from app.scoring.textmatch import tokens


def title_similarity(a: str, b: str) -> float:
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)  # Jaccard


def assign_dedupe_group(session: Session, posting: JobPosting) -> None:
    """Exact fingerprint twins join the same group with 0.95 confidence; fuzzy
    (same employer, title Jaccard >= 0.7) join with scaled confidence."""
    twin = session.exec(
        select(JobPosting).where(
            JobPosting.dedupe_fingerprint == posting.dedupe_fingerprint,
            JobPosting.id != posting.id,
        )
    ).first()
    candidate, confidence = twin, 0.95

    if candidate is None and posting.employer_id:
        for other in session.exec(
            select(JobPosting).where(
                JobPosting.employer_id == posting.employer_id,
                JobPosting.id != posting.id,
            )
        ):
            sim = title_similarity(posting.title, other.title)
            if sim >= 0.7:
                candidate, confidence = other, round(0.5 + 0.4 * sim, 2)
                break

    if candidate is None:
        return

    if candidate.dedupe_group_id is None:
        group = DedupeGroup(primary_posting_id=candidate.id)
        session.add(group)
        session.commit()
        session.refresh(group)
        candidate.dedupe_group_id = group.id
        session.add(candidate)
    posting.dedupe_group_id = candidate.dedupe_group_id
    posting.duplicate_confidence = confidence
    session.add(posting)
    session.commit()
