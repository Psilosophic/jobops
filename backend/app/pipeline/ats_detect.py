"""Detect the underlying ATS behind an arbitrary job URL.

This is the compliance workhorse: a LinkedIn/Indeed/Dice alert or a random career
page usually deep-links to Greenhouse/Lever/Ashby/SmartRecruiters — which we may
poll via OFFICIAL APIs. Detection re-routes a restricted-source discovery into a
low-risk official-API source.
"""
import re
from dataclasses import dataclass
from urllib.parse import unquote, urlparse

_PATTERNS: list[tuple[str, re.Pattern, int]] = [
    # (ats_slug, pattern over netloc+path, group index of the board/org token)
    ("greenhouse", re.compile(r"boards\.greenhouse\.io/([a-z0-9_-]+)", re.I), 1),
    ("greenhouse", re.compile(r"job-boards\.greenhouse\.io/([a-z0-9_-]+)", re.I), 1),
    ("greenhouse", re.compile(r"([a-z0-9_-]+)\.greenhouse\.io", re.I), 1),
    ("lever", re.compile(r"jobs\.lever\.co/([a-z0-9_-]+)", re.I), 1),
    ("ashby", re.compile(r"jobs\.ashbyhq\.com/([a-z0-9_.-]+)", re.I), 1),
    ("smartrecruiters", re.compile(r"jobs\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I), 1),
    ("smartrecruiters", re.compile(r"careers\.smartrecruiters\.com/([A-Za-z0-9_-]+)", re.I), 1),
    ("workday", re.compile(r"([a-z0-9-]+)\.(?:wd\d+\.)?myworkdayjobs\.com", re.I), 1),
    ("icims", re.compile(r"([a-z0-9-]+)\.icims\.com", re.I), 1),
]

_TRACKING_HOSTS = ("linkedin.com", "indeed.com", "dice.com", "click.appcast.io")


@dataclass(frozen=True)
class AtsMatch:
    ats_slug: str
    token: str          # board / org / company / tenant identifier
    url: str


def _unwrap_redirect(url: str) -> str:
    """Alert emails wrap the real URL in a tracking redirect; pull out embedded URLs."""
    parsed = urlparse(url)
    if any(h in parsed.netloc for h in _TRACKING_HOSTS):
        m = re.search(r"(https?%3A%2F%2F[^&]+|https?://[^&?\s]+)", parsed.query)
        if m:
            return unquote(m.group(1))
    return url


def detect_ats(url: str) -> AtsMatch | None:
    if not url:
        return None
    target = _unwrap_redirect(url)
    probe = urlparse(target)
    haystack = f"{probe.netloc}{probe.path}"
    for slug, pattern, group in _PATTERNS:
        m = pattern.search(haystack)
        if m:
            token = m.group(group).lower()
            if token in ("www", "jobs", "careers", "boards"):
                continue
            return AtsMatch(ats_slug=slug, token=token, url=target)
    return None
