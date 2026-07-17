"""Re-score every active posting after a scoring-logic change.

Wipes derived rows (applications, explanations, packets, review-queue) and re-runs
the ingest scoring/staging path so thresholds and location rules apply uniformly.
Safe while nothing is submitted yet; refuses to touch submitted/archived apps.

Run: docker exec jobops-api-1 python -m app.rescore
"""
from sqlalchemy import delete
from sqlmodel import Session, select

from app.db import engine
from app.logging import configure_logging, get_logger
from app.models.applications import (
    Application, ApplicationEvent, ApplicationPacket, ReviewQueueItem,
)
from app.models.base import ApplicationState
from app.models.jobs import JobPosting
from app.models.scoring import ScoringExplanation
from app.pipeline.ingest import score_and_stage

configure_logging()
log = get_logger("rescore")

# Never blow away real outcomes.
PROTECTED = {ApplicationState.submitted, ApplicationState.followup_needed,
             ApplicationState.manual_assist_in_progress, ApplicationState.ready_to_submit,
             ApplicationState.approved_for_submission}


def rescore() -> dict:
    wiped = kept = restaged = 0
    with Session(engine) as s:
        apps = list(s.exec(select(Application)))
        protected_posting_ids = set()
        for app in apps:
            if app.state in PROTECTED or app.user_modified:
                kept += 1
                protected_posting_ids.add(app.posting_id)
                continue
            # wipe derived rows for this application
            s.exec(delete(ReviewQueueItem).where(ReviewQueueItem.application_id == app.id))
            s.exec(delete(ApplicationPacket).where(ApplicationPacket.application_id == app.id))
            s.exec(delete(ApplicationEvent).where(ApplicationEvent.application_id == app.id))
            s.delete(app)
            wiped += 1
        s.commit()
        # orphan explanations for non-protected postings
        for posting in s.exec(select(JobPosting)):
            if posting.id in protected_posting_ids:
                continue
            s.exec(delete(ScoringExplanation).where(
                ScoringExplanation.posting_id == posting.id))
        s.commit()
        # re-stage every non-protected posting
        for posting in s.exec(select(JobPosting)):
            if posting.id in protected_posting_ids:
                continue
            score_and_stage(s, posting)
            restaged += 1
    log.info("rescore_complete", wiped=wiped, kept=kept, restaged=restaged)
    return {"wiped": wiped, "kept_protected": kept, "restaged": restaged}


if __name__ == "__main__":
    print(rescore())
