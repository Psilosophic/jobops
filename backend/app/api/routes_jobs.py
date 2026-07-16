from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import Session, select

from app.db import get_session
from app.models.applications import Application
from app.models.employers import Employer
from app.models.jobs import JobPosting
from app.models.scoring import ScoringExplanation

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("")
def list_jobs(
    session: Session = Depends(get_session),
    min_fit: float = Query(0.0),
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[dict]:
    rows = session.exec(
        select(JobPosting, Application)
        .join(Application, Application.posting_id == JobPosting.id, isouter=True)
        .order_by(Application.fit_score.desc().nullslast())
        .limit(limit).offset(offset)
    )
    out = []
    for posting, app in rows:
        if app and app.fit_score is not None and app.fit_score < min_fit:
            continue
        emp = session.get(Employer, posting.employer_id) if posting.employer_id else None
        out.append({
            "posting": posting.model_dump(exclude={"raw", "description_text"}),
            "employer": emp.canonical_name if emp else None,
            "application": app.model_dump() if app else None,
        })
    return out


@router.get("/{posting_id}")
def job_detail(posting_id: int, session: Session = Depends(get_session)) -> dict:
    posting = session.get(JobPosting, posting_id)
    if posting is None:
        raise HTTPException(404)
    explanation = session.exec(
        select(ScoringExplanation).where(ScoringExplanation.posting_id == posting_id)
        .order_by(ScoringExplanation.created_at.desc())
    ).first()
    app = session.exec(
        select(Application).where(Application.posting_id == posting_id)
    ).first()
    emp = session.get(Employer, posting.employer_id) if posting.employer_id else None
    return {
        "posting": posting.model_dump(),
        "employer": emp.model_dump() if emp else None,
        "scoring": explanation.model_dump() if explanation else None,
        "application": app.model_dump() if app else None,
    }
