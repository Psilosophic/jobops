from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import Session, select

from app.db import get_session
from app.models.base import SourceMode
from app.models.sources import SourcePolicy

router = APIRouter(prefix="/policies", tags=["policy"])


class PolicyUpdate(BaseModel):
    scraping_allowed: bool | None = None
    browser_automation_allowed: bool | None = None
    auto_submit_allowed: bool | None = None
    manual_review_required: bool | None = None
    recommended_mode: SourceMode | None = None
    evidence_notes: str | None = None


@router.get("")
def policy_matrix(session: Session = Depends(get_session)) -> list[dict]:
    return [p.model_dump() for p in session.exec(select(SourcePolicy))]


@router.patch("/{policy_id}")
def update_policy(policy_id: int, body: PolicyUpdate,
                  session: Session = Depends(get_session)) -> dict:
    policy = session.get(SourcePolicy, policy_id)
    if policy is None:
        raise HTTPException(404)
    data = body.model_dump(exclude_none=True)
    # Loosening ANY restriction requires fresh review evidence. Non-negotiable.
    loosening = (
        data.get("scraping_allowed") or data.get("browser_automation_allowed")
        or data.get("auto_submit_allowed") or data.get("manual_review_required") is False
    )
    if loosening and not data.get("evidence_notes"):
        raise HTTPException(422, "Loosening a policy requires evidence_notes explaining why.")
    for k, v in data.items():
        setattr(policy, k, v)
    policy.last_policy_reviewed_at = datetime.now(timezone.utc)
    policy.updated_at = datetime.now(timezone.utc)
    session.add(policy)
    session.commit()
    return policy.model_dump()
