# JobOps

Self-hosted job search & application operations platform. Design: `docs/DESIGN.md`.

## What Phase 1 gives you

- Postgres schema for the whole system (sources, policies, postings, versions,
  scoring explanations, applications, packets, review queue, panic state, ...)
- Source policy engine: every outward action is gated; LinkedIn/Indeed/Dice are
  hard-coded discover-only (no scraping code path exists)
- Deterministic explainable scoring with IAM + Support/Enablement track selection
- Official-API adapters: Greenhouse, Lever, Ashby, SmartRecruiters
- Celery worker + beat schedule polling enabled sources every 30 min
- Panic layer (emergency stop actually blocks in-flight work at the policy gate)
- REST API: /health /sources /policies /jobs /panic /reports/morning

## Deploy on docker01

    git clone <your-repo> jobops && cd jobops
    cp .env.example .env
    # edit .env: set POSTGRES_PASSWORD
    docker compose up -d --build

First boot runs `alembic upgrade head` + seeds automatically (entrypoint).

Generate the initial migration on first checkout (one-time, from your machine):

    docker compose run --rm api alembic revision --autogenerate -m "initial schema"
    docker compose run --rm api alembic upgrade head

## Point it at real employers

Add ATS boards for Colorado/remote employers you care about, e.g.:

    curl -X PATCH localhost:8100/sources/1/config \
      -H 'content-type: application/json' \
      -d '{"boards": ["exampleco"], "company_names": {"exampleco": "Example Co"}}'

Then trigger a run: `curl -X POST localhost:8100/sources/1/run`

## Tests

    cd backend
    pip install -e '.[dev]'
    pytest -q

## Compliance stance (read this once)

LinkedIn, Indeed, and Dice prohibit scraping/automation, so JobOps ingests them via
the alert emails THEY send to YOUR mailbox (Phase 2) and never automates on their
sites. ATS sources use official public APIs. Auto-submit ships disabled everywhere;
enabling it requires a policy edit WITH evidence notes, and even then every
submission passes the policy gate + panic state at execution time.

## Phase 3: UI

`docker compose up -d --build` now also builds the frontend (nginx on **:8180**).
Pages: Morning Report (landing) / Review Queue (three-column; Resume Track
dropdown, Modify drawer, policy-routed Submit; keys: j/k move, t cycle track,
m modify, s submit) / Jobs / Sources & Policy. Panic button top-right, always.

## Load your resumes (one-time per new version)

    docker compose cp "Scott Shelton Resume - IAM (ATS).docx" api:/tmp/iam.docx
    docker compose exec api python -m app.profile.load_resume iam /tmp/iam.docx
    docker compose cp "Scott Shelton Resume - Support Enablement (ATS).docx" api:/tmp/sup.docx
    docker compose exec api python -m app.profile.load_resume support_enablement /tmp/sup.docx

## Sync intake from the Brain wiki

    docker compose cp /path/to/Brain/wiki/JobOps/Intake.md api:/tmp/Intake.md
    docker compose exec api python -m app.intake.wiki_sync /tmp/Intake.md
