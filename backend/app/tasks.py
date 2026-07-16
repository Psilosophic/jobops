"""Celery tasks. Thin wrappers; logic lives in pipeline/reporting modules."""
import asyncio
from datetime import date, timedelta

from sqlmodel import Session, select

from app.celery_app import celery
from app.db import engine
from app.logging import configure_logging, get_logger
from app.models.jobs import SearchRun
from app.models.ops import DailyReport
from app.models.sources import Source
from app.pipeline.ingest import run_source

configure_logging()
log = get_logger("tasks")


@celery.task(name="app.tasks.discover_all")
def discover_all() -> dict:
    with Session(engine) as session:
        sources = list(session.exec(select(Source).where(Source.enabled == True)))  # noqa: E712
    for src in sources:
        discover_source.delay(src.id)
    return {"dispatched": len(sources)}


@celery.task(
    name="app.tasks.discover_source",
    autoretry_for=(Exception,),
    retry_backoff=60,          # 60s, 120s, 240s...
    retry_backoff_max=3600,
    max_retries=5,
    retry_jitter=True,
)
def discover_source(source_id: int) -> dict:
    with Session(engine) as session:
        source = session.get(Source, source_id)
        if source is None or not source.enabled:
            return {"skipped": source_id}
        run = asyncio.run(run_source(session, source))
        return {"source": source.slug, "status": run.status,
                "fetched": run.fetched, "new": run.new}


@celery.task(name="app.tasks.generate_daily_report")
def generate_daily_report() -> dict:
    """Phase 1: counts skeleton. Phase 5 adds cheat sheet + email delivery."""
    from sqlalchemy import func
    from app.models.applications import Application

    report_date = date.today() - timedelta(days=1)
    with Session(engine) as session:
        runs = list(session.exec(select(SearchRun).where(
            func.date(SearchRun.started_at) == report_date)))
        apps_by_state: dict[str, int] = {}
        for (state, count) in session.exec(
            select(Application.state, func.count()).group_by(Application.state)
        ):
            apps_by_state[str(state)] = count
        payload = {
            "date": str(report_date),
            "search_runs": len(runs),
            "fetched": sum(r.fetched for r in runs),
            "new_postings": sum(r.new for r in runs),
            "source_errors": sum(1 for r in runs if r.status == "error"),
            "applications_by_state": apps_by_state,
        }
        existing = session.exec(select(DailyReport).where(
            DailyReport.report_date == report_date)).first()
        if existing:
            existing.payload = payload
            session.add(existing)
        else:
            session.add(DailyReport(report_date=report_date, payload=payload))
        session.commit()
    log.info("daily_report_generated", date=str(report_date))
    return payload
