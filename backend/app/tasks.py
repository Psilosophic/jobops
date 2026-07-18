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


@celery.task(name="app.tasks.manual_assist_prefill", queue="assist")
def manual_assist_prefill(application_id: int) -> dict:
    """Headless Playwright prefill + screenshot for an application in
    manual_assist_in_progress. Policy-gated; never submits."""
    import asyncio
    from pathlib import Path

    from app.models.applications import Application, ApplicationEvent
    from app.models.base import EventActor
    from app.models.jobs import JobPosting
    from app.models.ops import PanicState
    from app.models.sources import SourcePolicy
    from app.policy.engine import Action, gate
    from app.workflow.manual_assist import build_prefill_map, fill_form_headless

    with Session(engine) as s:
        app = s.get(Application, application_id)
        if app is None:
            return {"error": "application not found"}
        posting = s.get(JobPosting, app.posting_id)
        policy = s.exec(select(SourcePolicy).where(
            SourcePolicy.source_id == posting.source_id)).first()
        panic = s.get(PanicState, 1) or PanicState(id=1)
        decision = gate(Action.BROWSER_ASSIST, policy, panic, posting.source_id)
        if not decision.allowed:
            return {"denied": list(decision.reasons)}

        pm = build_prefill_map(s, app)
        shot_dir = Path("/srv/jobops/exports/assist")
        shot_dir.mkdir(parents=True, exist_ok=True)
        shot = str(shot_dir / f"app_{application_id}.png")
        report = asyncio.run(fill_form_headless(posting.url, pm, shot))

        s.add(ApplicationEvent(
            application_id=app.id, event_type="manual_assist_prefill",
            actor=EventActor.system,
            payload={"filled": report.get("filled"), "skipped": report.get("skipped"),
                     "uploaded_resume": report.get("uploaded_resume"),
                     "error": report.get("error"), "screenshot": report.get("screenshot")},
        ))
        s.commit()
    log.info("manual_assist_done", application_id=application_id,
             filled=len(report.get("filled", [])), error=report.get("error"))
    return report


@celery.task(name="app.tasks.email_daily_report")
def email_daily_report() -> dict:
    from app.reporting.emailer import send_morning_report
    return send_morning_report()
