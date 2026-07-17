from datetime import datetime, timedelta, timezone

from app.models.jobs import JobPosting
from app.models.scoring import KeywordPack, ScoringProfile
from app.scoring.engine import score_posting


def profile() -> ScoringProfile:
    return ScoringProfile(id=1, name="t", is_active=True)


def iam_pack() -> KeywordPack:
    return KeywordPack(
        name="iam", track_slug="iam",
        include={
            "titles": ["iam engineer", "identity engineer", "sso engineer"],
            "required_tech": ["saml", "oauth", "active directory"],
            "preferred_tech": ["pingfederate", "entra", "mfa", "oidc"],
        },
        exclude={"titles": ["director", "intern"], "tech": []},
    )


def support_pack() -> KeywordPack:
    return KeywordPack(
        name="sup", track_slug="support_enablement",
        include={
            "titles": ["technical support engineer", "support engineer"],
            "required_tech": ["troubleshooting", "customer"],
            "preferred_tech": ["active directory", "sso", "escalation"],
        },
        exclude={"titles": ["call center"], "tech": []},
    )


def posting(**kw) -> JobPosting:
    defaults = dict(
        source_id=1, external_id="x", dedupe_fingerprint="f", url="http://x",
        title="IAM Engineer",
        description_text="PingFederate SAML OAuth OIDC Active Directory Entra MFA federation",
        location_raw="Denver, CO", is_remote=False,
        salary_min=110000, salary_max=140000,
        posted_at=datetime.now(timezone.utc) - timedelta(days=1),
    )
    defaults.update(kw)
    return JobPosting(**defaults)


def test_strong_iam_job_scores_high_and_picks_iam_track():
    r = score_posting(posting(), profile(), [iam_pack(), support_pack()],
                      salary_floor=80000, salary_target=110000)
    assert r.chosen_track == "iam"
    assert r.total >= 70
    assert not r.rejected
    assert r.track_scores["iam"] > r.track_scores["support_enablement"]


def test_components_sum_to_total():
    r = score_posting(posting(), profile(), [iam_pack()],
                      salary_floor=80000, salary_target=110000)
    recomputed = (r.title_match + r.skill_match + r.location_match + r.comp_match
                  + r.recency + r.employer_pref + r.track_fit
                  - r.negative_penalty - r.recruiter_penalty - r.contract_penalty
                  - r.missing_salary_penalty)
    assert abs(recomputed - r.total) < 0.01


def test_support_job_routes_to_support_track():
    p = posting(
        title="Technical Support Engineer",
        description_text="customer troubleshooting escalation SSO Active Directory tickets",
    )
    r = score_posting(p, profile(), [iam_pack(), support_pack()],
                      salary_floor=60000, salary_target=90000)
    assert r.chosen_track == "support_enablement"


def test_out_of_state_onsite_rejected():
    p = posting(location_raw="Austin, TX", is_remote=False)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.rejected
    assert any("location" in x for x in r.reject_reasons)


def test_remote_us_accepted():
    p = posting(location_raw="Remote", is_remote=True, remote_scope="us")
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.location_match > 0
    assert not any("location" in x for x in r.reject_reasons)


def test_suppressed_title_rejected():
    p = posting(title="Director of IAM Engineering")
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.rejected
    assert any("suppressed" in x for x in r.reject_reasons)


def test_recruiter_language_penalized():
    clean = score_posting(posting(), profile(), [iam_pack()],
                          salary_floor=80000, salary_target=110000)
    spam = score_posting(
        posting(description_text=posting().description_text
                + " our client seeks w2 only corp to corp"),
        profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert spam.recruiter_penalty > 0
    assert spam.total < clean.total


def test_blacklisted_employer_rejected():
    r = score_posting(posting(), profile(), [iam_pack()], employer_blacklisted=True,
                      salary_floor=80000, salary_target=110000)
    assert r.rejected
    assert "employer blacklisted" in r.reject_reasons


def test_missing_salary_penalized_not_fatal():
    p = posting(salary_min=None, salary_max=None)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.missing_salary_penalty > 0


def test_salary_below_floor_zeroes_comp():
    p = posting(salary_min=40000, salary_max=55000)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.comp_match == 0.0


def test_stale_posting_gets_zero_recency():
    p = posting(posted_at=datetime.now(timezone.utc) - timedelta(days=60))
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.recency == 0.0


def test_remote_india_rejected():
    p = posting(location_raw="Remote - India", is_remote=True, remote_scope=None)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.location_match == 0.0
    assert r.rejected
    assert any("location" in x for x in r.reject_reasons)


def test_remote_emea_rejected():
    p = posting(location_raw="Remote (EMEA)", is_remote=True, remote_scope=None)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.location_match == 0.0


def test_remote_us_explicit_accepted():
    p = posting(location_raw="Remote - US", is_remote=True, remote_scope=None)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.location_match > 0


def test_plain_remote_still_accepted():
    p = posting(location_raw="Remote", is_remote=True, remote_scope=None)
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.location_match > 0


def test_remote_canada_rejected_even_with_scope():
    p = posting(location_raw="Anywhere", is_remote=True, remote_scope="Canada")
    r = score_posting(p, profile(), [iam_pack()], salary_floor=80000, salary_target=110000)
    assert r.location_match == 0.0
