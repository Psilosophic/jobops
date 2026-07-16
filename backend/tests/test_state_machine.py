import pytest

from app.models.base import ApplicationState as S
from app.workflow.state_machine import Ctx, can_transition


def test_happy_path_to_queue():
    ctx = Ctx(fit_score=80, min_fit_threshold=55, policy_allows_packet=True)
    assert can_transition(S.discovered, S.normalized, ctx)[0]
    assert can_transition(S.normalized, S.deduped, ctx)[0]
    assert can_transition(S.deduped, S.scored, ctx)[0]
    assert can_transition(S.scored, S.packet_ready, ctx)[0]
    assert can_transition(S.packet_ready, S.queued_for_review, ctx)[0]


def test_low_fit_cannot_reach_packet():
    ctx = Ctx(fit_score=30, min_fit_threshold=55, policy_allows_packet=True)
    ok, why = can_transition(S.scored, S.packet_ready, ctx)
    assert not ok and "below threshold" in why


def test_policy_block_cannot_reach_packet():
    ctx = Ctx(fit_score=90, min_fit_threshold=55, policy_allows_packet=False)
    ok, why = can_transition(S.scored, S.packet_ready, ctx)
    assert not ok and "policy" in why


def test_forbidden_answers_block_packet():
    ctx = Ctx(fit_score=90, min_fit_threshold=55, policy_allows_packet=True,
              forbidden_answers_needed=True)
    ok, why = can_transition(S.scored, S.packet_ready, ctx)
    assert not ok and "forbidden" in why


def test_approval_requires_human_and_completeness():
    assert not can_transition(S.queued_for_review, S.approved_for_submission, Ctx())[0]
    missing = Ctx(human_action=True, missing_fields=["work_auth"])
    ok, why = can_transition(S.queued_for_review, S.approved_for_submission, missing)
    assert not ok and "work_auth" in why
    assert can_transition(
        S.queued_for_review, S.approved_for_submission, Ctx(human_action=True)
    )[0]


def test_submit_paths_respect_policy():
    approved = S.approved_for_submission
    assert not can_transition(approved, S.ready_to_submit, Ctx(human_action=True))[0]
    assert can_transition(approved, S.ready_to_submit,
                          Ctx(policy_allows_submit=True))[0]
    assert not can_transition(approved, S.manual_assist_in_progress, Ctx())[0]
    assert can_transition(approved, S.manual_assist_in_progress,
                          Ctx(policy_allows_browser_assist=True))[0]
    # handoff completion is human-confirmed
    assert can_transition(approved, S.submitted, Ctx(human_action=True))[0]
    assert not can_transition(approved, S.submitted, Ctx())[0]


def test_illegal_jumps_rejected():
    assert not can_transition(S.discovered, S.submitted, Ctx(human_action=True))[0]
    assert not can_transition(S.scored, S.approved_for_submission, Ctx(human_action=True))[0]


def test_archived_is_terminal():
    assert not can_transition(S.archived, S.queued_for_review, Ctx(human_action=True))[0]


def test_errored_reachable_from_active_only():
    assert can_transition(S.ready_to_submit, S.errored, Ctx())[0]
    assert not can_transition(S.archived, S.errored, Ctx())[0]


def test_failed_submission_recovers_to_queue():
    assert can_transition(S.failed_submission, S.queued_for_review, Ctx())[0]
