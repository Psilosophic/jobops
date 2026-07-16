"""Built In Colorado via RSS/alert surfaces. Conservative: RSS only, no page
crawling. Postings usually deep-link to an underlying ATS which the pipeline
re-routes to an official-API adapter via ats_detect."""
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime

from app.adapters.base import Capabilities, RawPosting, SourceAdapter, detect_remote, register


@register
class BuiltInCOAdapter(SourceAdapter):
    slug = "builtin_co"

    @classmethod
    def capabilities(cls) -> Capabilities:
        return Capabilities(retrieval_method="rss", rate_limit_per_minute=4)

    async def fetch(self) -> list[RawPosting]:
        feeds: list[str] = self.config.get("feeds", [])
        out: list[RawPosting] = []
        async with self.client() as client:
            for feed_url in feeds:
                resp = await client.get(feed_url)
                resp.raise_for_status()
                root = ET.fromstring(resp.text)
                for item in root.iter("item"):
                    def _get(tag: str) -> str:
                        el = item.find(tag)
                        return (el.text or "").strip() if el is not None else ""
                    link, title = _get("link"), _get("title")
                    if not link or not title:
                        continue
                    posted: datetime | None = None
                    if _get("pubDate"):
                        try:
                            posted = parsedate_to_datetime(_get("pubDate"))
                        except (TypeError, ValueError):
                            posted = None
                    desc = _get("description")
                    out.append(RawPosting(
                        external_id=link.split("?")[0][-120:],
                        url=link, title=title[:200],
                        company_name=_get("author") or "Unknown (builtin)",
                        description_text=desc[:5000],
                        location_raw="Colorado",
                        is_remote=detect_remote(title, desc),
                        posted_at=posted,
                        raw={"feed": feed_url},
                    ))
        return out
