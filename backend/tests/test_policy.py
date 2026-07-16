"""Policy gate truth table. If any of these fail, do not ship."""
from app.models.base import RiskLevel, SourceMode
from app.models.ops import PanicState
from app.models.sources import SourcePolicy
from app.policy.engine import Action, Verdict, gate


def policy(mode: SourceMode, scrape=False, browser=False, auto=False, review=True):
    return SourcePolicy(
        source_id=1, scraping_allowed=scrape, browser_automation_allowed=browser,
        auto_submit_allowed=auto, manual_review_required=review,
        recommended_mode=mode, risk_level=RiskLevel.medium,
    )


def calm():
    return PanicState(id=1, review_required_all=False)


def test_discover_only_blocks_everything_but_fetch():
    p = policy(SourceMode.discover_only)
    assert gate(Action.FETCH_OFFICIAL, p, calm()).allowed
    for action in (Action.GENERATE_PACKET, Action.QUEUE_FOR_REVIEW,
                   Action.BROWSER_ASSIST, Action.AUTO_SUBMIT):
        assert not gate(action, p, calm()).allowed, action


def test_scrape_requires_explicit_flag():
    assert not gate(Action.FETCH_SCRAPE, policy(SourceMode.auto_submit_allowed), calm()).allowed
    assert gate(Action.FETCH_SCRAPE, policy(SourceMode.qualify_only, scrape=True), calm()).allowed


def test_auto_submit_needs_flag_and_mode_and_no_review():
    # right mode, missing flag
    assert not gate(Action.AUTO_SUBMIT, policy(SourceMode.auto_submit_allowed), calm()).allowed
    # flag set but review still required
    assert not gate(
        Action.AUTO_SUBMIT, policy(SourceMode.auto_submit_allowed, auto=True), calm()
    ).allowed
    # everything aligned
    ok = policy(SourceMode.auto_submit_allowed, auto=True, review=False)
    assert gate(Action.AUTO_SUBMIT, ok, calm()).allowed


def test_no_policy_row_is_default_deny():
    d = gate(Action.GENERATE_PACKET, None, calm())
    assert d.verdict == Verdict.DENY
    assert "default deny" in d.reasons[0]


def test_panic_submissions_pause_beats_permissive_policy():
    ok = policy(SourceMode.auto_submit_allowed, auto=True, review=False)
    panic = calm()
    panic.submissions_paused = True
    assert not gate(Action.AUTO_SUBMIT, ok, panic).allowed


def test_panic_discover_only_all():
    ok = policy(SourceMode.manual_assist, browser=True)
    panic = calm()
    panic.discover_only_all = True
    assert gate(Action.FETCH_OFFICIAL, ok, panic).allowed
    assert not gate(Action.GENERATE_PACKET, ok, panic).allowed
    assert not gate(Action.BROWSER_ASSIST, ok, panic).allowed


def test_panic_paused_source_blocks_fetch():
    p = policy(SourceMode.manual_assist)
    panic = calm()
    panic.paused_sources = [7]
    assert not gate(Action.FETCH_OFFICIAL, p, panic, source_id=7).allowed
    assert gate(Action.FETCH_OFFICIAL, p, panic, source_id=8).allowed


def test_review_required_all_default_blocks_auto_submit():
    ok = policy(SourceMode.auto_submit_allowed, auto=True, review=False)
    panic = PanicState(id=1)  # ships with review_required_all=True
    assert not gate(Action.AUTO_SUBMIT, ok, panic).allowed


def test_browser_assist_needs_flag_and_mode():
    assert not gate(Action.BROWSER_ASSIST, policy(SourceMode.manual_assist), calm()).allowed
    assert not gate(
        Action.BROWSER_ASSIST, policy(SourceMode.packet_only, browser=True), calm()
    ).allowed
    assert gate(
        Action.BROWSER_ASSIST, policy(SourceMode.manual_assist, browser=True), calm()
    ).allowed


def test_deny_reasons_are_explanatory():
    d = gate(Action.AUTO_SUBMIT, policy(SourceMode.discover_only), calm())
    assert len(d.reasons) >= 2  # flag missing AND mode wrong AND review required
