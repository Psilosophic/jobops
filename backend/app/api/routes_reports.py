from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.db import get_session
from app.models.ops import DailyReport

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/morning")
def morning(session: Session = Depends(get_session)) -> dict:
    yesterday = date.today() - timedelta(days=1)
    report = session.exec(
        select(DailyReport).where(DailyReport.report_date == yesterday)
    ).first()
    if report:
        return report.payload
    # Not generated yet (fresh install / before 04:00 run) — build on the fly.
    from app.tasks import generate_daily_report
    return generate_daily_report.run()
