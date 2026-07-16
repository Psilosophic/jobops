"""Matching & Scoring Engine.

fit = max over enabled tracks of (w_title*title + w_skill*skill) [scaled to 100 with
track-fit weight] + location + comp + recency + employer preference - penalties.
Every component is persisted in ScoringExplanation. Deterministic by construction.
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.models.jobs import JobPosting
from app.models.scoring import KeywordPack, ScoringProfile
from app.scoring import textmatch as tm

RECRUITER_MARKERS = [
    "staffing", "recruiting", "talent solutions", "our client", "w2 only",
    "corp to corp", "c2c", "third party", "recruitment agency",
]
CONTRACT_MARKERS = ["contract", "contractor", "6 month", "12 month", "temp to hire", "c2h"]


@dataclass
class TrackScore:
    track_slug: str
    title_match: float
    skill_match: float
    score: float  # 0..1 combined
    suppressed_by: str | None = None


@dataclass
class ScoreResult:
    total: float
    chosen_track: str | None
    track_scores: dict[str, float]
    title_match: float
    skill_match: float
    location_match: float
    comp_match: float
    recency: float
    employer_pref: float
    track_fit: float
    negative_penalty: float
    recruiter_penalty: float
    contract_penalty: float
    missing_salary_penalty: float
    rejected: bool
    reject_reasons: list[str] = field(default_factory=list)
    rationale: str = ""


def _location_component(p: JobPosting, allow_hybrid: bool = True) -> float:
    loc = (p.location_raw or "").lower()
    if p.is_remote:
        scope = (p.remote_scope or "").lower()
        if scope in ("", "us", "usa", "global", "co", "colorado", "north america"):
            return 1.0
        return 0.0
    if "colorado" in loc or ", co" in loc or loc.strip().endswith(" co") \
            or "denver" in loc or "boulder" in loc or "colorado springs" in loc:
        return 1.0 if not allow_hybrid else 0.9
    return 0.0


def _comp_component(p: JobPosting, floor: int, target: int) -> tuple[float, bool]:
    """Returns (component, salary_missing)."""
    if p.salary_min is None and p.salary_max is None:
        return 0.5, True  # neutral-ish; the missing-salary penalty handles the rest
    high = p.salary_max or p.salary_min or 0
    low = p.salary_min or p.salary_max or 0
    if p.salary_interval == "hour":
        low, high = low * 2080, high * 2080
    if high < floor:
        return 0.0, False
    if low >= target:
        return 1.0, False
    span = max(target - floor, 1)
    return round(max(0.0, min(1.0, (high - floor) / span)), 4), False


def _recency_component(p: JobPosting, max_age_days: int) -> float:
    ref = p.posted_at or p.first_seen_at
    if ref is None:
        return 0.5
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    age_days = (datetime.now(timezone.utc) - ref).total_seconds() / 86400
    if age_days > max_age_days:
        return 0.0
    return round(0.5 ** (age_days / 7.0), 4)  # half-life 7 days


def score_posting(
    posting: JobPosting,
    profile: ScoringProfile,
    packs: list[KeywordPack],
    employer_preferred: bool = False,
    employer_blacklisted: bool = False,
    global_suppress_keywords: list[str] | None = None,
    salary_floor: int = 60000,
    salary_target: int = 100000,
) -> ScoreResult:
    text = f"{posting.title}\n{posting.description_text}"
    reject: list[str] = []

    if employer_blacklisted:
        reject.append("employer blacklisted")

    hit = tm.any_phrase(text, global_suppress_keywords or [])
    if hit:
        reject.append(f"suppressed keyword: {hit}")

    # --- per-track evaluation ---
    track_results: list[TrackScore] = []
    for pack in packs:
        if not pack.enabled:
            continue
        inc, exc = pack.include or {}, pack.exclude or {}
        sup = tm.any_phrase(posting.title, exc.get("titles", []))
        t = tm.title_match(posting.title, inc.get("titles", []))
        s = tm.skill_coverage(
            text, inc.get("required_tech", []), inc.get("preferred_tech", []),
            exc.get("tech", []),
        )
        combined = (profile.w_title * t + profile.w_skill * s) / max(
            profile.w_title + profile.w_skill, 1e-9
        )
        track_results.append(TrackScore(pack.track_slug, t, s, round(combined, 4), sup))

    viable = [t for t in track_results if t.suppressed_by is None]
    if not viable:
        sup_by = next((t.suppressed_by for t in track_results if t.suppressed_by), None)
        if sup_by:
            reject.append(f"title suppressed: {sup_by}")
        best = TrackScore("none", 0.0, 0.0, 0.0)
    else:
        best = max(viable, key=lambda t: t.score)

    loc = _location_component(posting)
    comp, salary_missing = _comp_component(posting, salary_floor, salary_target)
    rec = _recency_component(posting, profile.max_job_age_days)
    emp = 1.0 if employer_preferred else 0.0

    recruiter_pen = profile.p_recruiter if tm.any_phrase(text, RECRUITER_MARKERS) else 0.0
    is_contract = (posting.employment_type or "").lower().startswith("contract") or bool(
        tm.any_phrase(posting.title, CONTRACT_MARKERS)
    )
    contract_pen = profile.p_contract if is_contract else 0.0
    missing_salary_pen = profile.p_missing_salary if salary_missing else 0.0
    poor_title_pen = profile.p_poor_title if best.title_match < 0.2 and best.score > 0 else 0.0
    negative_pen = poor_title_pen

    # components in points (0..100 scale)
    pts_title = 100 * profile.w_title * best.title_match
    pts_skill = 100 * profile.w_skill * best.skill_match
    pts_loc = 100 * profile.w_location * loc
    pts_comp = 100 * profile.w_comp * comp
    pts_rec = 100 * profile.w_recency * rec
    pts_emp = 100 * profile.w_employer_pref * emp
    pts_trackfit = 100 * profile.w_track_fit * best.score

    total = (pts_title + pts_skill + pts_loc + pts_comp + pts_rec + pts_emp + pts_trackfit
             - recruiter_pen - contract_pen - missing_salary_pen - negative_pen)
    total = round(max(0.0, total), 2)

    if loc == 0.0 and not employer_preferred:
        reject.append("location outside Colorado/remote scope")

    rejected = bool(reject) or total < profile.min_fit_threshold
    if total < profile.min_fit_threshold and not reject:
        reject.append(f"fit {total} below threshold {profile.min_fit_threshold}")

    close_call = ""
    if len(viable) >= 2:
        top2 = sorted(viable, key=lambda t: t.score, reverse=True)[:2]
        if top2[0].score - top2[1].score < 0.1:
            close_call = (f" Close call: {top2[1].track_slug} scored "
                          f"{top2[1].score:.2f} vs {top2[0].score:.2f}.")

    rationale = (
        f"Track '{best.track_slug}' chosen (title {best.title_match:.2f}, "
        f"skills {best.skill_match:.2f}).{close_call} "
        f"Location {loc:.1f}, comp {comp:.1f}, recency {rec:.2f}."
        + (f" Penalties: recruiter -{recruiter_pen}, contract -{contract_pen},"
           f" missing salary -{missing_salary_pen}, weak title -{negative_pen}."
           if (recruiter_pen or contract_pen or missing_salary_pen or negative_pen) else "")
    )

    return ScoreResult(
        total=total,
        chosen_track=best.track_slug if best.score > 0 else None,
        track_scores={t.track_slug: t.score for t in track_results},
        title_match=round(pts_title, 2), skill_match=round(pts_skill, 2),
        location_match=round(pts_loc, 2), comp_match=round(pts_comp, 2),
        recency=round(pts_rec, 2), employer_pref=round(pts_emp, 2),
        track_fit=round(pts_trackfit, 2),
        negative_penalty=negative_pen, recruiter_penalty=recruiter_pen,
        contract_penalty=contract_pen, missing_salary_penalty=missing_salary_pen,
        rejected=rejected, reject_reasons=reject, rationale=rationale,
    )
