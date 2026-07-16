"""SmartRecruiters Postings API — official, public.
GET https://api.smartrecruiters.com/v1/companies/{companyId}/postings
Detail: /postings/{postingId} for full jobAd content.
"""
from datetime import datetime

from app.adapters.base import (
    Capabilities, RawPosting, SourceAdapter, detect_remote, parse_salary_text, register,
)
from app.adapters.greenhouse import strip_html


@register
class SmartRecruitersAdapter(SourceAdapter):
    slug = "smartrecruiters"
    BASE = "https://api.smartrecruiters.com/v1/companies"

    @classmethod
    def capabilities(cls) -> Capabilities:
        return Capabilities(retrieval_method="official_api", rate_limit_per_minute=20)

    async def fetch(self) -> list[RawPosting]:
        companies: list[str] = self.config.get("companies", [])
        fetch_details: bool = self.config.get("fetch_details", True)
        out: list[RawPosting] = []
        async with self.client() as client:
            for company in companies:
                resp = await client.get(f"{self.BASE}/{company}/postings", params={"limit": 100})
                resp.raise_for_status()
                for item in resp.json().get("content", []):
                    desc = ""
                    if fetch_details:
                        d = await client.get(f"{self.BASE}/{company}/postings/{item['id']}")
                        if d.status_code == 200:
                            sections = ((d.json().get("jobAd") or {}).get("sections") or {})
                            desc = " ".join(
                                strip_html(sec.get("text", "")) for sec in sections.values()
                                if isinstance(sec, dict)
                            )
                    loc_obj = item.get("location") or {}
                    loc = ", ".join(filter(None, [loc_obj.get("city"), loc_obj.get("region"),
                                                  loc_obj.get("country")]))
                    sal_lo, sal_hi = parse_salary_text(desc)
                    posted = None
                    if item.get("releasedDate"):
                        posted = datetime.fromisoformat(
                            item["releasedDate"].replace("Z", "+00:00"))
                    out.append(RawPosting(
                        external_id=str(item["id"]),
                        url=f"https://jobs.smartrecruiters.com/{company}/{item['id']}",
                        title=item.get("name", ""),
                        company_name=self.config.get("company_names", {}).get(company, company),
                        description_text=desc,
                        location_raw=loc,
                        is_remote=bool(loc_obj.get("remote")) or detect_remote(loc),
                        salary_min=sal_lo, salary_max=sal_hi,
                        posted_at=posted,
                        raw={"company": company, "sr_id": item["id"]},
                    ))
        return out
