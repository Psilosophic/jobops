"""Ashby Job Board API — official, public.
GET https://api.ashbyhq.com/posting-api/job-board/{board}?includeCompensation=true
"""
from app.adapters.base import (
    Capabilities, RawPosting, SourceAdapter, detect_remote, register,
)
from app.adapters.greenhouse import strip_html


@register
class AshbyAdapter(SourceAdapter):
    slug = "ashby"
    BASE = "https://api.ashbyhq.com/posting-api/job-board"

    @classmethod
    def capabilities(cls) -> Capabilities:
        return Capabilities(retrieval_method="official_api", rate_limit_per_minute=30)

    async def fetch(self) -> list[RawPosting]:
        boards: list[str] = self.config.get("boards", [])
        out: list[RawPosting] = []
        async with self.client() as client:
            for board in boards:
                resp = await client.get(
                    f"{self.BASE}/{board}", params={"includeCompensation": "true"}
                )
                resp.raise_for_status()
                for job in resp.json().get("jobs", []):
                    comp = job.get("compensation") or {}
                    tiers = comp.get("compensationTierSummaries") or []
                    sal_lo = sal_hi = None
                    if tiers:
                        comps = tiers[0].get("components") or []
                        for c in comps:
                            if c.get("compensationType") == "Salary":
                                sal_lo = int(c.get("minValue") or 0) or None
                                sal_hi = int(c.get("maxValue") or 0) or None
                    loc = job.get("location", "") or ""
                    out.append(RawPosting(
                        external_id=str(job["id"]),
                        url=job.get("jobUrl", "") or job.get("applyUrl", ""),
                        title=job.get("title", ""),
                        company_name=self.config.get("company_names", {}).get(board, board),
                        description_text=strip_html(job.get("descriptionHtml", "")),
                        location_raw=loc,
                        is_remote=bool(job.get("isRemote")) or detect_remote(loc),
                        salary_min=sal_lo, salary_max=sal_hi,
                        salary_raw=comp.get("scrapeableCompensationSalarySummary"),
                        employment_type=(job.get("employmentType") or "").lower() or None,
                        raw={"board": board, "ashby_id": job["id"],
                             "department": job.get("department")},
                    ))
        return out
