"""Lever Postings API — official, public.
GET https://api.lever.co/v0/postings/{org}?mode=json
"""
from datetime import datetime, timezone

from app.adapters.base import (
    Capabilities, RawPosting, SourceAdapter, detect_remote, parse_salary_text, register,
)
from app.adapters.greenhouse import strip_html


@register
class LeverAdapter(SourceAdapter):
    slug = "lever"
    BASE = "https://api.lever.co/v0/postings"

    @classmethod
    def capabilities(cls) -> Capabilities:
        return Capabilities(retrieval_method="official_api", rate_limit_per_minute=30)

    async def fetch(self) -> list[RawPosting]:
        orgs: list[str] = self.config.get("orgs", [])
        out: list[RawPosting] = []
        async with self.client() as client:
            for org in orgs:
                resp = await client.get(f"{self.BASE}/{org}", params={"mode": "json"})
                resp.raise_for_status()
                for job in resp.json():
                    cats = job.get("categories") or {}
                    loc = cats.get("location", "") or ""
                    desc = strip_html(job.get("descriptionPlain") or job.get("description", ""))
                    sal = job.get("salaryRange") or {}
                    sal_lo, sal_hi = sal.get("min"), sal.get("max")
                    if sal_lo is None:
                        sal_lo, sal_hi = parse_salary_text(desc)
                    posted = None
                    if job.get("createdAt"):
                        posted = datetime.fromtimestamp(job["createdAt"] / 1000, tz=timezone.utc)
                    workplace = (job.get("workplaceType") or "").lower()
                    out.append(RawPosting(
                        external_id=str(job["id"]),
                        url=job.get("hostedUrl", ""),
                        title=job.get("text", ""),
                        company_name=self.config.get("company_names", {}).get(org, org),
                        description_text=desc,
                        location_raw=loc,
                        is_remote=workplace == "remote" or detect_remote(loc),
                        salary_min=sal_lo, salary_max=sal_hi,
                        salary_interval="year" if (sal.get("interval") or "").startswith(
                            ("per-year", "year", "")) else "hour",
                        employment_type=(cats.get("commitment") or "").lower().replace(" ", "_")
                        or None,
                        posted_at=posted,
                        raw={"org": org, "lever_id": job["id"], "team": cats.get("team")},
                    ))
        return out
