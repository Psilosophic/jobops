"""Morning report email via SMTP. Credentials come from env ONLY; the operator
places JOBOPS_SMTP_PASSWORD in the .env on the docker host themselves. Sending is
policy-gated (panic can pause outbound email)."""
import smtplib
from datetime import date, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from sqlmodel import Session, select

from app.config import get_settings
from app.db import engine
from app.logging import get_logger
from app.models.ops import DailyReport, PanicState
from app.policy.engine import Action, gate

log = get_logger("emailer")


def _html(payload: dict) -> str:
    states = payload.get("applications_by_state", {})
    rows = "".join(
        f"<tr><td style='padding:4px 12px'>{k}</td>"
        f"<td style='padding:4px 12px;text-align:right'><b>{v}</b></td></tr>"
        for k, v in sorted(states.items())
    )
    return f"""<html><body style="font-family:Segoe UI,Arial,sans-serif;color:#222">
<h2 style="margin-bottom:4px">JobOps Morning Report — {payload.get('date')}</h2>
<p>New postings: <b>{payload.get('new_postings', 0)}</b> ·
Fetched: {payload.get('fetched', 0)} ·
Search runs: {payload.get('search_runs', 0)} ·
Source errors: <b style="color:{'#c00' if payload.get('source_errors') else '#222'}">{payload.get('source_errors', 0)}</b></p>
<table style="border-collapse:collapse;background:#f6f6f6;border-radius:6px">{rows}</table>
<p><a href="http://192.168.1.15:8180/review">Open the review queue →</a></p>
</body></html>"""


def send_morning_report() -> dict:
    s = get_settings()
    if not (s.smtp_host and s.smtp_user and s.smtp_password and s.report_email_to):
        log.info("email_skipped_not_configured")
        return {"skipped": "smtp not configured"}
    with Session(engine) as db:
        panic = db.get(PanicState, 1) or PanicState(id=1)
        decision = gate(Action.SEND_EMAIL, None, panic)
        if not decision.allowed:
            log.info("email_blocked_by_panic", reasons=list(decision.reasons))
            return {"blocked": list(decision.reasons)}
        report = db.exec(select(DailyReport).where(
            DailyReport.report_date == date.today() - timedelta(days=1))).first()
        if report is None:
            return {"skipped": "no report generated yet"}
        payload = report.payload

    msg = MIMEMultipart("alternative")
    msg["Subject"] = (f"JobOps: {payload.get('new_postings', 0)} new, "
                      f"{payload.get('applications_by_state', {}).get('queued_for_review', 0)}"
                      f" to review — {payload.get('date')}")
    msg["From"] = s.smtp_user
    msg["To"] = s.report_email_to
    msg.attach(MIMEText(_html(payload), "html"))
    with smtplib.SMTP_SSL(s.smtp_host, s.smtp_port) as server:
        server.login(s.smtp_user, s.smtp_password)
        server.send_message(msg)
    log.info("morning_report_emailed", to=s.report_email_to)
    return {"sent": s.report_email_to}
