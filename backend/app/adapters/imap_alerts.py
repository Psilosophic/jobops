"""Alert-mailbox adapters (LinkedIn / Indeed / Dice) — COMPLIANT discovery.

These boards prohibit scraping and automation on their platforms. They do, however,
send job-alert emails to a mailbox YOU own because YOU subscribed. Reading your own
mailbox over IMAP is your data. These adapters parse those alert emails into
discover-only RawPostings. There is deliberately no code path that touches the
boards' websites.

Setup: create a dedicated mailbox, subscribe to saved-search alerts on each board,
set JOBOPS_IMAP_* env vars. Parsers are heuristic (alert HTML changes); parse
failures raise health events rather than fake data.
"""
import email
import email.policy
import imaplib
import os
import re
from html import unescape

from app.adapters.base import Capabilities, RawPosting, SourceAdapter, register

_LINK_RE = re.compile(r'href="(https?://[^"]+)"', re.I)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(html_chunk: str) -> str:
    return re.sub(r"\s+", " ", _TAG_RE.sub(" ", unescape(html_chunk))).strip()


def extract_alert_jobs(html: str, link_filter: str) -> list[dict]:
    """Generic alert parser: find posting links, take nearby text as title/company.

    Works on the common alert layout of '<a href=JOB_URL>Title</a> ... Company ·
    Location'. Pure + fixture-tested; per-provider quirks live in the config
    link_filter regex.
    """
    jobs: list[dict] = []
    seen: set[str] = set()
    for m in _LINK_RE.finditer(html):
        url = m.group(1)
        if not re.search(link_filter, url, re.I):
            continue
        # de-dupe on the URL sans query tracking params
        key = url.split("?")[0]
        if key in seen:
            continue
        seen.add(key)
        # title = the anchor's inner text; company/location = text between this
        # anchor and the NEXT anchor (so rows don't bleed into each other)
        tag_close = html.find(">", m.end())
        anchor_end = html.find("</a>", tag_close)
        title = _text(html[tag_close + 1:anchor_end]) if 0 < tag_close < anchor_end else ""
        next_anchor = html.find("<a ", anchor_end)
        window_end = next_anchor if next_anchor > 0 else anchor_end + 400
        window = _text(html[anchor_end + 4:window_end]) if anchor_end > 0 else ""
        company, location = "", ""
        parts = re.split(r"\s+[·|•|-]\s+", window)
        if parts:
            company = parts[0][:120]
        if len(parts) > 1:
            location = parts[1][:120]
        if title:
            jobs.append({"url": url, "title": title[:200],
                         "company": company, "location": location})
    return jobs


class ImapAlertsAdapter(SourceAdapter):
    """Base for all mailbox adapters. Subclasses pin sender + link filters."""
    slug = "imap_alerts"
    sender_filter: str = ""
    link_filter: str = ""

    @classmethod
    def capabilities(cls) -> Capabilities:
        return Capabilities(retrieval_method="imap", requires_auth=True,
                            rate_limit_per_minute=6)

    def _connect(self) -> imaplib.IMAP4_SSL:
        host = os.environ["JOBOPS_IMAP_HOST"]
        user = os.environ["JOBOPS_IMAP_USER"]
        password = os.environ["JOBOPS_IMAP_PASSWORD"]
        conn = imaplib.IMAP4_SSL(host)
        conn.login(user, password)
        return conn

    async def fetch(self) -> list[RawPosting]:
        folder = self.config.get("folder", "INBOX")
        limit = int(self.config.get("max_messages", 30))
        conn = self._connect()
        out: list[RawPosting] = []
        try:
            conn.select(folder, readonly=True)
            typ, data = conn.search(None, "UNSEEN", "FROM", f'"{self.sender_filter}"')
            if typ != "OK":
                return out
            ids = data[0].split()[-limit:]
            for msg_id in ids:
                typ, msg_data = conn.fetch(msg_id, "(BODY.PEEK[])")
                if typ != "OK" or not msg_data or msg_data[0] is None:
                    continue
                msg = email.message_from_bytes(msg_data[0][1], policy=email.policy.default)
                html = ""
                for part in msg.walk():
                    if part.get_content_type() == "text/html":
                        html = part.get_content()
                        break
                for job in extract_alert_jobs(html, self.link_filter):
                    out.append(RawPosting(
                        external_id=job["url"].split("?")[0][-120:],
                        url=job["url"],
                        title=job["title"],
                        company_name=job["company"] or "Unknown (alert)",
                        location_raw=job["location"],
                        is_remote="remote" in (job["title"] + job["location"]).lower(),
                        raw={"via": self.slug, "message_id": msg.get("Message-ID", "")},
                    ))
        finally:
            try:
                conn.logout()
            except Exception:  # noqa: BLE001
                pass
        return out


@register
class LinkedInAlertsAdapter(ImapAlertsAdapter):
    slug = "linkedin_alerts"
    sender_filter = "jobs-noreply@linkedin.com"
    link_filter = r"linkedin\.com/(comm/)?jobs/view"


@register
class IndeedAlertsAdapter(ImapAlertsAdapter):
    slug = "indeed_alerts"
    sender_filter = "alert@indeed.com"
    link_filter = r"indeed\.com/(rc/clk|viewjob|pagead)"


@register
class DiceAlertsAdapter(ImapAlertsAdapter):
    slug = "dice_alerts"
    sender_filter = "dice.com"
    link_filter = r"dice\.com/(job-detail|jobs/detail)"
