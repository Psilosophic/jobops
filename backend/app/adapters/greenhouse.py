"""Greenhouse Job Board API — official, public, documented.
GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true
"""
import html
import re
from datetime import datetime

from app.adapters.base import (
    Capabilities, RawPosting, SourceAdapter, detect_remote, parse_salary_text, register,
)

_TAG_RE = re.compile(r"<[^>]+>")


def strip_html(s: str) -> str:
    return _TAG_RE.sub(" ", html.unescape(s or "")).strip()


@register
class GreenhouseAdapter(SourceAdapter):
    slug = "greenhouse"
    BASE = "https://boards-api.greenhouse.io/v1/boards"

    @classmethod
    def capabilities(cls) -> Capabilities:
        return Capabilities(retrieval_method="official_api", rate_limit_per_minute=30)

    async def fetch(self) -> list[RawPosting]:
        boards: list[str] = self.config.get("boards", [])
        out: list[RawPosting] = []
        async with self.client() as client:
            for board in boards:
                resp = await client.get(f"{self.BASE}/{board}/jobs", params={"content": "true"})
                resp.raise_for_status()
                for job in resp.json().get("jobs", []):
                    desc = strip_html(job.get("content", ""))
                    loc = (job.get("location") or {}).get("name", "")
                    sal_lo, sal_hi = parse_salary_text(desc)
                    posted = None
                    if job.get("updated_at"):
                        posted = datetime.fromisoformat(job["updated_at"])
                    out.append(RawPosting(
                        external_id=str(job["id"]),
                        url=job.get("absolute_url", ""),
                        title=job.get("title", ""),
                        company_name=self.config.get("company_names", {}).get(board, board),
                        description_text=desc,
                        location_raw=loc,
                        is_remote=detect_remote(loc, job.get("title", "")),
                        salary_raw=None,
                        salary_min=sal_lo, salary_max=sal_hi,
                        posted_at=posted,
                        raw={"board": board, "greenhouse_id": job["id"],
                             "departments": job.get("departments", [])},
                    ))
        return out
