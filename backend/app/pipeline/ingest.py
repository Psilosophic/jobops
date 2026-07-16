"""Ingestion pipeline: fetch -> normalize -> version -> employer-resolve -> score.

Idempotent per (source_id, external_id). Policy-gated: fetch only proceeds if the
policy engine allows FETCH_OFFICIAL for the source; there is no scrape path here.
"""
from sqlmodel import Session, select

from app.adapters.base import ADAPTER_REGISTRY, RawPosting
from app.logging import get_logger
from app.models.applications import Application
from app.models.base import ApplicationState, HealthEventType, utcnow
from app.models.employers import Employer, EmployerAlias
from app.models.jobs import JobPosting, JobPostingVersion, SearchRun
from app.models.ops import ListEntry, PanicState
from app.models.scoring import KeywordPack, ScoringExplanation, ScoringProfile
from app.models.sources import Source, SourceHealthEvent, SourcePolicy
from app.models.ops import UserSetting
from app.pipeline.ats_detect import detect_ats
from app.pipeline.dedupe import assign_dedupe_group
from app.policy.engine import Action, gate
from app.workflow.packet import build_packet
from app.scoring.engine import score_posting
from app.workflow.state_machine import Ctx, transition

log = get_logger("pipeline")


def _get_panic(session: Session) -> PanicState:
    panic = session.get(PanicState, 1)
    if panic is None:
        panic = PanicState(id=1)
        session.add(panic)
        session.commit()
        session.refresh(panic)
    return panic


def resolve_employer(session: Session, name: str) -> Employer:
    norm = name.strip()
    alias = session.exec(select(EmployerAlias).where(EmployerAlias.alias == norm)).first()
    if alias:
        return session.get(Employer, alias.employer_id)
    emp = session.exec(
        select(Employer).where(Employer.canonical_name == norm)
    ).first()
    if emp:
        return emp
    emp = Employer(canonical_name=norm)
    session.add(emp)
    session.commit()
    session.refresh(emp)
    session.add(EmployerAlias(employer_id=emp.id, alias=norm))
    session.commit()
    return emp


def upsert_posting(session: Session, source: Source, rp: RawPosting) -> tuple[JobPosting, bool]:
    """Returns (posting, is_new). Creates a new version row when content changed."""
    existing = session.exec(
        select(JobPosting).where(
            JobPosting.source_id == source.id, JobPosting.external_id == rp.external_id
        )
    ).first()
    emp = resolve_employer(session, rp.company_name)
    chash = rp.content_hash()

    if existing:
        existing.last_seen_at = utcnow()
        changed = False
        last_ver = session.exec(
            select(JobPostingVersion)
            .where(JobPostingVersion.posting_id == existing.id)
            .order_by(JobPostingVersion.version_no.desc())
        ).first()
        if last_ver is None or last_ver.content_hash != chash:
            changed = True
            for f in ("title", "description_text", "location_raw", "is_remote",
                      "salary_min", "salary_max", "salary_raw", "url"):
                setattr(existing, f, getattr(rp, f))
            session.add(JobPostingVersion(
                posting_id=existing.id,
                version_no=(last_ver.version_no + 1) if last_ver else 1,
                content_hash=chash,
                snapshot=rp.raw | {"title": rp.title, "salary_min": rp.salary_min,
                                   "salary_max": rp.salary_max},
            ))
        session.add(existing)
        session.commit()
        return existing, False

    posting = JobPosting(
        source_id=source.id, employer_id=emp.id,
        external_id=rp.external_id, dedupe_fingerprint=rp.fingerprint(),
        url=rp.url, title=rp.title, description_text=rp.description_text,
        location_raw=rp.location_raw, is_remote=rp.is_remote, remote_scope=rp.remote_scope,
        salary_raw=rp.salary_raw, salary_min=rp.salary_min, salary_max=rp.salary_max,
        salary_interval=rp.salary_interval, employment_type=rp.employment_type,
        posted_at=rp.posted_at, raw=rp.raw,
    )
    session.add(posting)
    session.commit()
    session.refresh(posting)
    session.add(JobPostingVersion(
        posting_id=posting.id, version_no=1, content_hash=chash,
        snapshot=rp.raw | {"title": rp.title},
    ))
    assign_dedupe_group(session, posting)
    session.commit()
    return posting, True


def score_and_stage(session: Session, posting: JobPosting) -> None:
    """Runs discovered->normalized->deduped->scored and either rejects, blocks, or
    stages a packet-ready application."""
    profile = session.exec(
        select(ScoringProfile).where(ScoringProfile.is_active == True)  # noqa: E712
    ).first()
    if profile is None:
        log.warning("no_active_scoring_profile")
        return
    packs = list(session.exec(select(KeywordPack).where(KeywordPack.enabled == True)))  # noqa: E712
    panic = _get_panic(session)

    emp = session.get(Employer, posting.employer_id) if posting.employer_id else None
    suppress = [
        e.value for e in session.exec(
            select(ListEntry).where(ListEntry.kind == "keyword", ListEntry.is_allow == False)  # noqa: E712
        )
    ]
    def _setting(key: str, default: int) -> int:
        row = session.exec(select(UserSetting).where(UserSetting.key == key)).first()
        try:
            return int((row.value or {}).get("value", default)) if row else default
        except (TypeError, ValueError):
            return default

    salary_floor = _setting("salary_floor", 60000)
    salary_target = _setting("salary_target", 100000)

    # disabled tracks via panic
    packs = [p for p in packs if p.track_slug not in (panic.disabled_tracks or [])]

    result = score_posting(
        posting, profile, packs,
        employer_preferred=bool(emp and emp.preferred),
        employer_blacklisted=bool(emp and emp.blacklisted),
        global_suppress_keywords=suppress,
        salary_floor=salary_floor, salary_target=salary_target,
    )

    policy = session.exec(
        select(SourcePolicy).where(SourcePolicy.source_id == posting.source_id)
    ).first()
    packet_decision = gate(Action.GENERATE_PACKET, policy, panic, posting.source_id)

    session.add(ScoringExplanation(
        posting_id=posting.id, profile_id=profile.id,
        title_match=result.title_match, skill_match=result.skill_match,
        location_match=result.location_match, comp_match=result.comp_match,
        recency=result.recency, employer_pref=result.employer_pref,
        track_fit=result.track_fit, negative_penalty=result.negative_penalty,
        recruiter_penalty=result.recruiter_penalty,
        contract_penalty=result.contract_penalty,
        missing_salary_penalty=result.missing_salary_penalty,
        duplicate_confidence=posting.duplicate_confidence,
        policy_gate_result=packet_decision.serialize(),
        total=result.total, chosen_track=result.chosen_track,
        track_scores=result.track_scores, rationale=result.rationale,
    ))

    app = Application(posting_id=posting.id, fit_score=result.total)
    session.add(app)
    session.commit()
    session.refresh(app)

    ctx = Ctx(
        fit_score=result.total,
        min_fit_threshold=(panic.min_fit_override or profile.min_fit_threshold),
        policy_allows_packet=packet_decision.allowed,
    )
    transition(session, app, ApplicationState.normalized, ctx)
    transition(session, app, ApplicationState.deduped, ctx)
    transition(session, app, ApplicationState.scored, ctx,
               detail={"fit": result.total, "track": result.chosen_track})

    if result.rejected:
        transition(session, app, ApplicationState.rejected_low_fit, ctx,
                   detail={"reasons": result.reject_reasons})
    elif not packet_decision.allowed:
        transition(session, app, ApplicationState.blocked_by_policy, ctx,
                   detail={"policy": packet_decision.serialize()})
    else:
        transition(session, app, ApplicationState.packet_ready, ctx)
        session.commit()
        # Phase 2: assemble the packet and queue for human review immediately.
        queue_decision = gate(Action.QUEUE_FOR_REVIEW, policy, panic, posting.source_id)
        _, missing = build_packet(session, app)
        if queue_decision.allowed:
            transition(session, app, ApplicationState.queued_for_review, ctx,
                       detail={"missing_fields": missing})
        # discover/qualify/packet-only sources stop at packet_ready by policy.
    session.commit()


async def run_source(session: Session, source: Source) -> SearchRun:
    """One discovery pass for one source, policy-gated, health-recorded."""
    run = SearchRun(source_id=source.id)
    session.add(run)
    session.commit()
    session.refresh(run)

    panic = _get_panic(session)
    policy = session.exec(
        select(SourcePolicy).where(SourcePolicy.source_id == source.id)
    ).first()
    decision = gate(Action.FETCH_OFFICIAL, policy, panic, source.id)
    if not decision.allowed:
        run.status, run.error_detail = "error", f"policy denied fetch: {decision.reasons}"
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
        return run

    adapter_cls = ADAPTER_REGISTRY.get(source.slug.split(":")[0])
    if adapter_cls is None:
        run.status, run.error_detail = "error", f"no adapter for {source.slug}"
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
        return run

    try:
        postings = await adapter_cls(source.config).fetch()
        run.fetched = len(postings)
        for rp in postings:
            posting, is_new = upsert_posting(session, source, rp)
            if is_new:
                run.new += 1
                _reroute_to_ats(session, source, posting)
                score_and_stage(session, posting)
            else:
                run.updated += 1
        run.status = "ok"
        session.add(SourceHealthEvent(source_id=source.id, event_type=HealthEventType.ok,
                                      detail={"fetched": run.fetched, "new": run.new}))
    except Exception as exc:  # noqa: BLE001 — health event + rethrow-safe record
        run.status, run.errors, run.error_detail = "error", 1, str(exc)[:500]
        session.add(SourceHealthEvent(source_id=source.id, event_type=HealthEventType.error,
                                      detail={"error": str(exc)[:500]}))
        log.error("source_run_failed", source=source.slug, error=str(exc))
    finally:
        run.finished_at = utcnow()
        session.add(run)
        session.commit()
    return run


_ATS_CONFIG_KEYS = {"greenhouse": "boards", "lever": "orgs", "ashby": "boards",
                    "smartrecruiters": "companies"}


def _reroute_to_ats(session: Session, source: Source, posting: JobPosting) -> None:
    """The compliance workhorse: if a discovery from a restricted source deep-links
    to an official-API ATS, register that board with the ATS source so future
    discovery (and the apply path) flows through the official API."""
    if source.source_type not in ("mailbox", "board", "employer_page"):
        return
    match = detect_ats(posting.url)
    if match is None:
        return
    posting.raw = dict(posting.raw or {}) | {
        "ats_detected": match.ats_slug, "ats_token": match.token, "ats_url": match.url,
    }
    session.add(posting)
    key = _ATS_CONFIG_KEYS.get(match.ats_slug)
    if key is None:
        return  # workday/icims: detected + recorded, but stays packet-only
    ats_source = session.exec(select(Source).where(Source.slug == match.ats_slug)).first()
    if ats_source is None:
        return
    config = dict(ats_source.config or {})
    tokens = list(config.get(key, []))
    if match.token not in tokens:
        tokens.append(match.token)
        config[key] = tokens
        ats_source.config = config
        session.add(ats_source)
        log.info("ats_reroute_registered", ats=match.ats_slug, token=match.token,
                 from_source=source.slug)
    session.commit()
