# Phase 5 Design — Multi-Profile JobOps

Goal: let trusted people on the LAN create their own profile (dropdown-driven
wizard), upload their resumes, set their preferences, and get their own scored
queue — one shared stack, shared discovery, per-person everything else.

## Schema changes
New table **profiles** (id, slug, display_name, email, created_at, active).
Add `profile_id` FK (indexed, NOT NULL after backfill) to: resumes,
resume_versions (via resume), answer_bank_variants, applications,
application_packets, review_queue, scoring_profiles, keyword_packs,
user_settings (becomes (profile_id, key) unique), list_entries, daily_reports,
exports, employer_memory_notes. **Shared (no profile_id):** sources,
source_policies, job_postings + versions, search_runs, dedupe_groups, employers
— discovery is communal; scoring/workflow is personal.
Migration: create table, add nullable FKs, backfill profile 1 = Scott from
existing rows, then set NOT NULL. PanicState gains scope: global row + optional
per-profile row (global always wins).

## Scoring & workflow
`score_and_stage` loops enabled profiles per posting: per-profile keyword
packs, weights, thresholds, floors -> per-profile Application rows. Review
queue, packets, prefill maps, cover letters, morning reports all filter by
profile. Celery unchanged (tasks take profile_id where relevant).

## Profile creation wizard (LAN UI)
`/welcome` on the frontend: 4 dropdown-driven steps mirroring the choice-first
interview: (A) identity + contact, (B) work auth/setup/comp (all chips/selects),
(C) track picker from templates (IAM / Support / SysAdmin / Custom keywords) +
resume upload (drag-drop, stored as resume v1), (D) thresholds (defaults
pre-selected) + report email. Creates profile + settings + answer bank in one
POST. Profile switcher dropdown in the top bar; X-Profile-Id header scopes every
API call (single-operator LAN trust model — no auth beyond profile selection,
documented as such).

## Safety
Panic remains global-first. Per-profile answer banks keep the same safety enum.
Auto-submit stays globally disabled. High-volume alert thresholds apply
per-profile.

## Estimate
Migration + backfill ~1 session; wizard UI ~1 session; report/email scoping a
few hours. Ship order: migration -> API scoping -> wizard -> reports.
