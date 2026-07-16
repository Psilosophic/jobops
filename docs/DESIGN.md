# JobOps — Self-Hosted Job Search & Application Operations Platform

**Operator:** Scott Wesley Shelton, Denver CO
**Deployment target:** docker01 (192.168.1.15), Docker Compose
**Scoring:** deterministic weighted engine (source of truth) + optional local Ollama enrichment
**Status:** Design v1.0 — Phase 1 code delivered alongside this document

---

## 1. Executive Summary

JobOps is a self-hosted, always-on platform that discovers job postings from compliant
sources, scores them against your IAM and Support/Enablement profiles with a fully
explainable weighted model, selects the correct resume track, assembles truthful
application packets, and routes every application through a policy engine that decides —
per source — whether the system may auto-submit, must queue for one-click human review,
or must stop at packet generation and hand off to you.

Nothing submits anywhere unless the source's policy record explicitly allows it AND the
global panic state allows it AND the packet passes completeness guards. Every meaningful
action writes an audit event. Every morning you get a report of everything that happened
yesterday, plus a "calls-you-might-get" cheat sheet so when a recruiter phones, you know
in ten seconds who they are, what you applied to, which resume they have, and why it
matched.

The honest core insight this design is built on: **the major job boards (LinkedIn,
Indeed, Dice) prohibit third-party scraping and bot submission in their ToS.** So JobOps
does not pretend otherwise. Volume discovery on those boards flows through their own
email alerts (which they willingly send you) parsed from a dedicated mailbox, plus your
manually saved exports. Meanwhile, the ATS platforms that host the actual applications —
Greenhouse, Lever, Ashby, SmartRecruiters — expose **official public JSON APIs** for
their job boards, and those are polled directly, legally, and fast. Built In Colorado is
handled via its RSS/alert surface. Applications themselves are human-in-the-loop by
default: the system does everything except the final click, and does that final click
only where policy says it may.

## 2. Recommended Architecture

```
                      +--------------------------------------------+
                      |                docker01 host                |
                      |                                            |
  Greenhouse API --+  |  +----------+   +-----------+  +--------+  |
  Lever API -------+--+->|  worker   |-->| PostgreSQL |<-|  api   |<-+-- Browser (you)
  Ashby API -------+  |  | (Celery)  |   |    16      |  |FastAPI |  |
  SmartRecruiters -+  |  +----+-----+   +-----------+  +---+----+  |
  BuiltIn CO RSS --+  |       |               ^             |       |
  Alert mailbox ---+  |  +----v-----+    +----+----+   +----v----+  |
  (IMAP: LinkedIn/    |  |  Redis    |    | exports |   |frontend |  |
   Indeed/Dice alerts)|  | (queue +  |    | volume  |   | React   |  |
                      |  |  cache)   |    +---------+   | (nginx) |  |
  Ollama (workstation)|  +----------+                   +---------+  |
   <---- optional ----|                                             |
                      +--------------------------------------------+
```

Six containers: `api`, `worker`, `scheduler` (beat), `frontend`, `postgres`, `redis`.
Ollama runs on your workstation (already planned per your wiki) and is reached over LAN;
if it is down, scoring still works — only prose enrichment degrades to templates.

Module layout (matches the code tree in section 13):

1. **Source Adapter Layer** (`app/adapters/`) — one adapter per source, each declaring
   `capabilities()` (retrieval method, auth, rate limits) and implementing
   `fetch() -> list[RawPosting]`. Adapters never write to the DB; the pipeline does.
2. **Source Policy Engine** (`app/policy/`) — DB-backed policy records + a pure
   `gate(action, source_policy, panic_state) -> PolicyDecision` function. Hard-stop
   logic lives here and nowhere else; workflow code must call it before any submission,
   browser automation, or scrape-class fetch.
3. **Ingestion Pipeline** (`app/pipeline/`) — fetch -> normalize -> version -> enrich ->
   classify -> dedupe -> record search run. Idempotent; re-runs update versions.
4. **Matching & Scoring Engine** (`app/scoring/`) — weighted components, per-track
   evaluation, explanation rows persisted per job.
5. **Resume & Answer Profile Store** (`app/profile/`) — resumes, tracks, versions,
   answer bank with truthfulness flags.
6. **Application Workflow Engine** (`app/workflow/`) — state machine, packet builder,
   review queue, manual-assist tasks, retries/backoff, audit events.
7. **Reporting Engine** (`app/reporting/`) — morning payload, daily summary, cheat
   sheet, CSV/JSON/HTML exports.
8. **Panic Control Layer** (`app/panic/`) — global + per-source overrides, prevention
   logging.
9. **Admin/Settings** (`app/api/settings*`) — keyword packs, thresholds, lists,
   schedules, answer-bank admin.

## 3. Why This Tech Stack

**FastAPI + SQLModel + Alembic + Postgres** gives typed models that are simultaneously
the ORM tables and the API schemas, real migrations, and JSONB where postings need
flexible metadata — SQLite would choke on the concurrent worker/API write pattern and
lacks proper JSONB indexing. **Redis + Celery** because discovery polling, scoring, and
report generation are genuinely queue-shaped (retries, backoff, per-source rate limits
via dedicated queues); APScheduler alone couples scheduling to a single process and
loses jobs on crash — we use Celery beat for schedule + Celery workers for execution,
which also gives us worker heartbeats for free (observability requirement). **httpx**
for async polling with connection pooling. **structlog** for JSON logs with secret
masking processors. **Playwright** appears only in the manual-assist container profile
and only for sources whose policy row says `browser_automation_allowed=true` — it is a
compliance-scoped tool, not a scraping engine. **React/Vite/TanStack Query/Tailwind**
because the review queue is a latency-sensitive, keyboard-driven UI and TanStack
Query's cache invalidation makes the one-click approve -> refresh loop trivially fast.
Everything runs on one modest Docker host; no SaaS anywhere in the required path.

## 4. Source Policy & Risk Matrix

Populated cautiously. Where uncertain, the more restrictive mode wins. This table ships
as seed data (`app/seeds.py`) and is editable in the UI, with `evidence_notes` and
`last_policy_reviewed_at` so drift is auditable.

| source | type | login req | official API | retrieval | scrape ok | browser auto ok | auto-submit ok | manual review req | mode | risk |
|---|---|---|---|---|---|---|---|---|---|---|
| LinkedIn | board | yes | not for individuals | **email alerts (IMAP) + user exports** | **no** (ToS prohibits scraping/bots) | **no** | **no** | yes | `discover_only` -> packet + handoff link | high |
| Indeed | board | no | publisher API discontinued for this use | **email alerts (IMAP)** | **no** (ToS prohibits crawling) | **no** | **no** | yes | `discover_only` -> packet + handoff | high |
| Dice | board | no | no public API | **email alerts (IMAP)** | no (conservative; ToS restricts automated access) | no | no | yes | `discover_only` -> packet + handoff | med-high |
| Built In Colorado | board | no | RSS/alert surfaces | RSS/alerts, conservative fetch of linked employer pages | limited (respect robots.txt; alerts preferred) | no | no | yes | `qualify_only` | medium |
| Greenhouse | ATS | no | **yes — public Job Board API** (`boards-api.greenhouse.io/v1/boards/{token}/jobs`) | official JSON API | n/a (API) | allowed for manual-assist prefill on employer-hosted forms | **no by default**; per-employer opt-in later | yes initially | `queued_for_review` + `manual_assist` | low |
| Lever | ATS | no | **yes — public Postings API** (`api.lever.co/v0/postings/{org}`) | official JSON API | n/a | manual-assist prefill allowed | no by default | yes | `queued_for_review` + `manual_assist` | low |
| Ashby | ATS | no | **yes — public Job Board API** (`api.ashbyhq.com/posting-api/job-board/{name}`) | official JSON API | n/a | manual-assist prefill allowed | no by default | yes | `queued_for_review` + `manual_assist` | low |
| SmartRecruiters | ATS | no | **yes — public Postings API** (`api.smartrecruiters.com/v1/companies/{id}/postings`) | official JSON API | n/a | manual-assist prefill allowed | no by default | yes | `queued_for_review` + `manual_assist` | low |
| iCIMS | ATS | varies | partner API only | employer career-page RSS where offered; else discover via other sources | no | no | no | yes | `packet_only` | medium |
| Workday | ATS | yes (per-tenant accounts) | no public applicant API | discover via other sources; apply on tenant site | **no** | **no** (tenant ToS + fragile) | **no** | yes | `packet_only` + handoff launch | medium |
| Direct career pages | employer | varies | sometimes (many are GH/Lever/Ashby underneath — detect and re-route to ATS adapter) | robots.txt-respecting fetch of listed pages only, per-employer allowlist | conditional | no | no | yes | `qualify_only` | medium |
| Alert mailbox (IMAP) | meta-source | yes (your own mailbox) | IMAP is the API | parse alert emails you subscribed to | n/a | n/a | n/a | n/a | `discover_only` feeder | low |

Key honesty notes: (a) LinkedIn/Indeed/Dice rows are hard-stopped in code — the adapter
classes for them are *email-parse adapters*; there is no scraping code path to
misconfigure. (b) ATS auto-submit stays off even where technically feasible until you
flip a per-employer setting AND the policy engine re-verifies; employer terms vary, so
default is one-click manual-assist. (c) The "detect underlying ATS" trick is the
workhorse: a huge share of "direct career pages" and even BuiltIn/LinkedIn postings
resolve to a Greenhouse/Lever/Ashby URL, which flips the job from a restricted source
to an official API source with a low-risk apply path.

## 5. Data Model Design

Full typed SQLModel definitions live in `backend/app/models/` (delivered). Summary of
tables, keys, and the reasoning that matters:

- **sources** (pk `id`, unique `slug`) / **source_policies** (fk source_id, one row per
  source, all boolean policy flags + `recommended_mode` enum + `evidence_notes` +
  `last_policy_reviewed_at`) / **source_health_events** (fk source_id, `event_type`
  enum: ok|error|rate_limited|policy_drift, `detail` JSONB, indexed on
  (source_id, created_at)). Policies are a separate table so policy changes are
  auditable independent of source config.
- **employers** (pk id, `canonical_name`, unique lower-index) / **employer_aliases**
  (fk employer_id, unique alias) / **employer_memory_notes** (fk employer_id, versioned
  markdown notes + `talking_points` JSONB + status history JSONB). Aliases exist
  because "Amazon Web Services" != "AWS" != "Amazon" must merge.
- **job_postings** (pk id, fk source_id, fk employer_id, `external_id`,
  `dedupe_fingerprint` sha256 of normalized(title+employer+location) — unique partial
  index, `url`, `title`, `location_raw`, `is_remote`, `remote_scope`,
  `salary_min/max/currency/interval`, `posted_at`, `first_seen_at`, `last_seen_at`,
  `status` enum, `raw` JSONB) / **job_posting_versions** (fk posting_id, `version_no`,
  `content_hash`, `snapshot` JSONB) — postings mutate (salary added, description
  edited); versions preserve what you actually saw when you applied.
- **search_runs** (fk source_id, started/finished, counts fetched/new/updated/errors,
  `status`) — the morning report reads these.
- **dedupe_groups** (pk id, `primary_posting_id`) with `job_postings.dedupe_group_id`
  fk — same role on LinkedIn + Greenhouse merges here, `duplicate_confidence` float on
  member rows.
- **keyword_packs** (name, track, `include` JSONB, `exclude` JSONB, weights) /
  **scoring_profiles** (weights + thresholds, one `is_active`) /
  **scoring_explanations** (fk posting_id, fk profile_id, per-component columns:
  title_match, skill_match, location_match, comp_match, recency, employer_pref,
  track_fit, negative_penalty, recruiter_penalty, duplicate_confidence,
  `policy_gate_result`, `total`, `chosen_track`, `rationale` text) — one row per
  scoring pass so re-scores are comparable over time.
- **resumes** / **resume_tracks** (IAM, SUPPORT_ENABLEMENT, extensible) /
  **resume_versions** (fk resume_id, `version_no`, `file_path`, `content_hash`,
  immutable) — applications reference a resume_version_id, never "latest".
- **answer_bank** (question_pattern, category enum) / **answer_bank_variants**
  (fk answer_id, fk track_id nullable, `answer_text`, `safety` enum:
  safe_for_auto_use|requires_review|forbidden_for_auto_use, `last_verified_at`) —
  safety enum enforced by the packet builder: forbidden variants are unselectable,
  requires_review variants force queue mode.
- **applications** (fk posting_id, fk resume_version_id, fk track_id, `state` enum from
  section 11, `submission_mode` enum, timestamps per state entry in
  **application_events** (fk application_id, `event_type`, `actor` enum: system|user,
  `payload` JSONB)) / **application_packets** (fk application_id, `version_no`, full
  packet snapshot JSONB incl. answers used + user-edit flags) / **review_queue**
  (fk application_id, priority, `missing_fields` JSONB, assigned state).
- **panic_panel_events** (`action`, `scope`, `operator_intent` text,
  `prevented_actions` JSONB) + a `panic_state` singleton row (current flags:
  submissions_paused, discover_only_all, browser_paused, email_paused,
  min_fit_override, review_required_all, disabled_tracks JSONB,
  disabled_answer_variants JSONB).
- **exports** (type, format, file_path, row_counts JSONB) / **daily_reports** (date pk,
  payload JSONB, generated_at) — report is materialized nightly so morning load is
  instant, and regenerable.
- **user_settings** (key/value JSONB, single-operator so no user-table gymnastics) /
  **blacklists** / **allowlists** (kind enum: employer|industry|title|keyword, value,
  reason) / **source_credentials_metadata** (fk source_id, `credential_ref` — the env
  var NAME, never the value; `last_rotated_at`) — secrets stay in env/secret store,
  DB stores only pointers.

All enums are Python `StrEnum` + Postgres native enums via Alembic. All FKs indexed.
`job_postings` gets a GIN index on `raw` and a trigram index on `title` for search UI.

## 6. Graph Memory & Wiki Intake Design

Your Brain vault is the persistence layer for *who you are*; Postgres is the
persistence layer for *what the machine did*. The intake system lives at
`Brain/wiki/JobOps/` (installed by this delivery):

- `JobOps/Intake.md` — the full template (your spec, verbatim structure) with every
  field initialized to `UNKNOWN`, plus frontmatter and the `[[...]]` graph links.
- `JobOps/Interview-Orchestrator.md` — the companion prompt (section 7).
- Node pages created as the interview fills them: `JobOps/Resume-IAM.md`,
  `JobOps/Resume-Support-Enablement.md`, `JobOps/AnswerBank-*.md`,
  `JobOps/ScoringProfile-Default.md`, `JobOps/SearchPreferences-Colorado-Remote.md`,
  `JobOps/PanicPanel-DefaultPolicy.md`, `JobOps/EmployerList-Preferred.md`,
  `JobOps/EmployerList-Blacklisted.md`, `JobOps/Compliance-Boundaries.md`.

Graph model (nodes/edges as specified, expressed as wikilinks so your existing graph
tooling picks them up):
`[[Scott Wesley Shelton]] -> HAS_RESUME_TRACK -> [[JobOps/Resume-IAM]]`,
`ScoringProfile -> PREFERS_TRACK -> Resume/IAM`,
`Workflow/HITL -> USES -> AnswerBank/WorkAuthorization`,
`Workflow/HITL -> FALLBACKS_TO -> ManualReview`,
`PanicPanel/DefaultPolicy -> OVERRIDES -> Workflow/HITL`.
Edge lines are written as `- EDGE_NAME:: [[Target]]` so they are machine-parseable.

Sync into the engine: `backend/app/intake/wiki_sync.py` (Phase 2) parses
`JobOps/*.md` frontmatter+fields into `user_settings`, `answer_bank`,
`scoring_profiles`, `blacklists`, `allowlists`, and `keyword_packs` rows, and writes a
`Missing Critical Fields` section back into `Intake.md`. One-way trust: wiki is the
human-edited source of truth for preferences; DB never overwrites wiki content, only
appends status.

## 7. Interview Orchestrator Prompt

Delivered verbatim at `Brain/wiki/JobOps/Interview-Orchestrator.md` and mirrored at
`docs/interview-orchestrator.md` in the repo. It implements: 3–7 questions per batch,
phases A–I in order, per-round output contract (Questions -> Captured answers ->
Template updates -> Missing critical fields -> Next batch), UNKNOWN discipline, no
invented facts, minimum-viable-first prioritization (Phases A/B/C unlock the engine;
D–I refine it).

## 8. Scoring Model & Resume-Track Switching

Deterministic, decomposed, persisted. Per posting, per enabled track:

```
track_score(t) = w_title*TitleMatch(t) + w_skill*SkillMatch(t)
fit_score      = max_track + w_loc*Location + w_comp*Comp + w_rec*Recency
                 + w_emp*EmployerPref - P_neg - P_recruiter - P_contract - P_nosalary
```

- **TitleMatch(t)**: normalized token/phrase match of posting title against the
  track's keyword pack `titles` (exact phrase 1.0, all-tokens 0.8, partial scaled);
  suppression titles short-circuit to rejection.
- **SkillMatch(t)**: weighted coverage of the track's `required` (2x) and `preferred`
  (1x) technologies found in the description; `excluded` techs subtract.
- **Location**: CO/remote-to-CO = 1.0; hybrid-near-Denver = configurable; else 0 and
  below-threshold rejection unless allowlisted employer.
- **Comp**: posted min >= your floor = 1.0, straddles = scaled, below floor = 0 plus
  missing-salary penalty logic when nothing is posted.
- **Recency**: exponential decay, half-life 7 days, floor at max_job_age cutoff.
- **Track selection**: highest track_score wins; margin < 0.1 flags "close call" in
  rationale; both shown in the dropdown with scores. Manual override always available
  and logged as an application_event.
- **Explainability**: every component lands in `scoring_explanations` as its own
  column, and the UI renders the exact arithmetic. The optional Ollama pass writes
  only the `rationale` prose and a suggested employer memory note — it can never
  change a number. Prompt guardrail: "you are summarizing a decision already made;
  do not re-decide."

## 9. Screener-Answer Vault

`answer_bank` + `answer_bank_variants` as in section 5. Behavior rules enforced in the
packet builder (`app/workflow/packet.py`): only `safe_for_auto_use` variants can be
prefilled without human eyes; any `requires_review` variant in a packet forces
`queued_for_review` regardless of source policy; `forbidden_for_auto_use` variants
never leave the vault automatically. Unanswered required screener questions become
`missing_fields` on the review_queue row and disable Submit with an explanation. Every
packet snapshot records exactly which variant IDs were used (audit + "what did I tell
them" recall during calls). Nothing is ever synthesized: if the vault has no truthful
answer, the field is left blank and flagged — the system asks you, it does not guess.

## 10. Panic Panel

A `panic_state` singleton + `panic_panel_events` log. UI: persistent red button in the
top bar -> drawer with big labeled switches (stop all submissions; all-sources
discover-only; per-source pause; pause browser automation; pause outbound email; raise
min fit threshold; require review for everything; disable track(s); disable answer
variant(s)). Each toggle requires an "operator intent" one-liner (logged). Enforcement
is not UI-side: the policy engine's `gate()` reads panic_state on every decision, so a
mid-flight Celery task gets blocked too, and the block increments
`prevented_actions` — the drawer shows a live "what I just stopped" feed. Panic
changes take effect on the next gate check (< seconds), no restart.

## 11. Workflow & State Machine

States: discovered -> normalized -> deduped -> scored ->
{rejected_low_fit | blocked_by_policy | packet_ready} -> queued_for_review ->
modified_by_user -> approved_for_submission -> {manual_assist_in_progress |
ready_to_submit} -> submitted -> followup_needed -> archived; errored reachable from
any active state with retry/backoff back-edges.

Guards (the ones that matter): scored->packet_ready requires fit >= threshold AND
policy mode permits packets AND no forbidden answer variants needed;
queued->approved requires human action + no missing_fields;
approved->ready_to_submit requires `gate(SUBMIT)==ALLOW` (source policy + panic +
per-employer override); approved->manual_assist requires
`gate(BROWSER_ASSIST)==ALLOW` else falls to launch-and-copy handoff; submitted is
terminal-ish (only -> followup_needed/archived). Full transition table with guard
functions: `backend/app/workflow/state_machine.py` (delivered, tested).

## 12. Dashboard UX

Landing = Morning Report (yesterday's counts, calls-you-might-get cards, top unsent
matches). Left nav: Review Queue / Search Results / Applications Log / Employers /
Sources (health + policy matrix) / Answer Bank / Exports / Settings. Review screen is
the exact three-column spec: queue list | job summary + fit breakdown + employer
memory | packet preview; top action row = Resume Track dropdown (preselected, with
one-line "why", scores for both tracks) + Modify (drawer, edit fields, original-vs-
edited diff, user-edited badges, saves packet v+1) + Submit (behavior branches by
policy mode; disabled-with-reason when missing fields or discover-only). Keyboard: j/k
queue nav, m modify, s submit, t cycle track, esc close. Dark mode via Tailwind class
strategy; everything responsive; panic button always visible top-right.

## 13. File Tree

```
jobops/
├── docker-compose.yml, .env.example, README.md, Makefile
├── docs/DESIGN.md, docs/interview-orchestrator.md
├── backend/
│   ├── pyproject.toml, Dockerfile, alembic.ini
│   ├── alembic/env.py, alembic/versions/
│   └── app/
│       ├── main.py, config.py, db.py, logging.py, celery_app.py, tasks.py, seeds.py
│       ├── models/{__init__,base,sources,employers,jobs,scoring,profile,applications,ops}.py
│       ├── policy/engine.py
│       ├── adapters/{base.py,greenhouse.py,lever.py,ashby.py,smartrecruiters.py,
│       │            builtin_co.py*,imap_alerts.py*}          (*=Phase 2)
│       ├── pipeline/ingest.py
│       ├── scoring/{engine.py,textmatch.py,ollama_enrich.py*}
│       ├── workflow/{state_machine.py,packet.py*,review.py*,manual_assist.py*}
│       ├── reporting/{morning.py*,exports.py*}
│       ├── panic/service.py
│       └── api/{routes_health.py,routes_sources.py,routes_jobs.py,routes_policy.py,
│                routes_panic.py,routes_review.py*,routes_reports.py*}
├── frontend/  (Phase 3: Vite+React+TS+Tailwind+TanStack Query)
└── backend/tests/{test_policy.py,test_scoring.py,test_state_machine.py,
                   test_adapters.py,fixtures/}
```

## 14. Phase-by-Phase Implementation Plan

- **Phase 1 (delivered now):** foundation — full data model + migrations, policy
  engine with seeded matrix, deterministic scoring with explanations, state machine,
  four official-API ATS adapters, ingestion pipeline, Celery beat schedule, panic
  core, health/sources/jobs/policy/panic API, compose stack, seeds, tests. Outcome:
  `docker compose up` on docker01 discovers and scores real
  Greenhouse/Lever/Ashby/SmartRecruiters postings for seeded CO employers.
- **Phase 2:** intake wiki sync; IMAP alert-mailbox adapter (LinkedIn/Indeed/Dice
  compliant discovery); Built In CO adapter; ATS-detection for arbitrary job URLs;
  dedupe groups; answer bank + packet builder; review queue API; employer memory notes.
- **Phase 3:** full React frontend (morning report, review queue with the exact
  Modify/Submit/track-dropdown model, policy matrix view, answer bank admin, exports
  center, panic drawer); keyboard model; dark mode.
- **Phase 4:** manual-assist Playwright profiles (policy-gated prefill on
  employer-hosted ATS forms), launch-and-copy handoff, submission audit trail,
  screenshot capture, per-employer auto-submit opt-in flow with double policy check.
- **Phase 5:** reporting polish (HTML/PDF morning report email, exports scheduler),
  Ollama enrichment, observability (heartbeats, drift alerts, high-volume safety
  alerts), backup/restore, hardening pass.

Each phase lands as runnable code + migration + tests; say "phase 2" when ready.

## 15–19. Phase Code

Phase 1 code is delivered in this repository (section 13 paths). Phases 2–5 are
specified above and generated on demand at the same fidelity — deliberately not
stubbed here so nothing pretends to be production-ready that isn't.

## 20. Docker Compose & Environment

`docker-compose.yml` + `.env.example` + `README.md` delivered. Summary: postgres:16 +
redis:7 with healthchecks; api (uvicorn), worker (celery), scheduler (celery beat)
built from one backend image; frontend (nginx) added in Phase 3; named volumes for
pgdata and exports; everything binds LAN only — put it behind your existing reverse
proxy or Tailscale, do not expose to WAN.

## 21. Test Plan

- **Unit:** policy gate truth table (every mode x every action x panic states);
  scoring decomposition (fixture postings with known-answer components); state machine
  (legal/illegal transitions, guard failures).
- **Contract:** each adapter has recorded-fixture JSON; tests assert normalization
  invariants (id stability, salary parsing, remote detection) so an upstream API shape
  change fails loudly.
- **Workflow (Phase 2+):** fixture-driven end-to-end: raw fixture -> ingest -> score
  -> packet -> queue -> approve -> (mock) submit, asserting the audit event chain.
- **E2E (Phase 3+):** Playwright against the compose stack: morning report renders,
  review approve flow, panic stop actually blocks a queued submission.
- **CI hook:** `make test` runs pytest; adapters run offline against fixtures only.

## 22. Known Limits & Compliance Boundaries

Plainly: **LinkedIn Easy Apply automation, Indeed bot apply, and Dice scraping are not
built and will not be** — their terms prohibit it, so those boards are discovery-only
via their own alert emails and your exports, with packet + handoff for the apply step.
Workday tenants get packet + launch; no credentialed automation. "Auto-submit" exists
in the state machine but ships disabled for every seeded source; enabling it requires
a per-employer policy row change AND passes through `gate()` at execution time. The
policy matrix is seed data reflecting a cautious reading as of 2026-07; terms drift,
so `last_policy_reviewed_at` staleness (> 90 days) raises a drift alert rather than
silently continuing. Salary parsing from free text is heuristic — the UI always shows
raw text next to parsed numbers. Dedupe is fingerprint + confidence, not magic; the
review screen shows duplicate_confidence so you can catch misses. And the system never
answers a screener question it doesn't have a verified truthful answer for. That's
the whole point.
