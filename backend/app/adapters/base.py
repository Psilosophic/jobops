"""Source Adapter Layer.

Contract: an adapter turns a source's OFFICIAL surface into RawPosting objects.
Adapters do not write to the DB, do not score, do not dedupe — the pipeline does.
Adapters must declare capabilities so the policy engine can cross-check that the
retrieval method actually used matches what the policy row permits.
"""
import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime

import httpx

DEFAULT_TIMEOUT = httpx.Timeout(30.0, connect=10.0)
USER_AGENT = "JobOps/0.1 (personal job-search tool; single operator; contact: operator)"


@dataclass
class Capabilities:
    retrieval_method: str            # must match Source.retrieval_method
    requires_auth: bool = False
    rate_limit_per_minute: int = 30


@dataclass
class RawPosting:
    external_id: str
    url: str
    title: str
    company_name: str
    description_text: str = ""
    location_raw: str = ""
    is_remote: bool = False
    remote_scope: str | None = None
    salary_raw: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    salary_interval: str = "year"
    employment_type: str | None = None
    posted_at: datetime | None = None
    raw: dict = field(default_factory=dict)

    def fingerprint(self) -> str:
        basis = "|".join(
            re.sub(r"\s+", " ", s.lower().strip())
            for s in (self.title, self.company_name, self.location_raw or "remote")
        )
        return hashlib.sha256(basis.encode()).hexdigest()

    def content_hash(self) -> str:
        basis = f"{self.title}|{self.description_text}|{self.salary_raw}|{self.location_raw}"
        return hashlib.sha256(basis.encode()).hexdigest()


class SourceAdapter:
    slug: str = "base"

    def __init__(self, config: dict):
        self.config = config or {}

    @classmethod
    def capabilities(cls) -> Capabilities:
        raise NotImplementedError

    async def fetch(self) -> list[RawPosting]:
        raise NotImplementedError

    @staticmethod
    def client() -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=DEFAULT_TIMEOUT, headers={"User-Agent": USER_AGENT},
            follow_redirects=True,
        )


_SALARY_RE = re.compile(
    r"\$\s?(\d{2,3}(?:,\d{3})?(?:\.\d+)?)\s?(k)?\s*(?:-|–|to)\s*"
    r"\$?\s?(\d{2,3}(?:,\d{3})?(?:\.\d+)?)\s?(k)?", re.I,
)


def parse_salary_text(text: str) -> tuple[int | None, int | None]:
    """Heuristic. Callers must keep salary_raw so the human always sees the source."""
    if not text:
        return None, None
    m = _SALARY_RE.search(text)
    if not m:
        return None, None

    def _num(val: str, k: str | None) -> int:
        n = float(val.replace(",", ""))
        if k:
            n *= 1000
        elif n < 1000:  # "$95 - $120" with no k almost always means thousands
            n *= 1000
        return int(n)

    lo, hi = _num(m.group(1), m.group(2)), _num(m.group(3), m.group(4))
    if lo > hi:
        lo, hi = hi, lo
    # Hourly figures sneak through; anything under 250 pre-multiplier was handled above.
    return lo, hi


REMOTE_RE = re.compile(r"\bremote\b", re.I)


def detect_remote(*chunks: str) -> bool:
    return any(REMOTE_RE.search(c or "") for c in chunks)


ADAPTER_REGISTRY: dict[str, type[SourceAdapter]] = {}


def register(cls: type[SourceAdapter]) -> type[SourceAdapter]:
    ADAPTER_REGISTRY[cls.slug] = cls
    return cls
