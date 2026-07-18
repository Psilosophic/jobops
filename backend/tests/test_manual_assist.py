"""Manual-assist prefill: deterministic map + bookmarklet. (Playwright headless
fill is exercised separately in the assist container; kept out of unit CI.)"""
import re

from app.models.applications import Application, ApplicationPacket
from app.models.base import AnswerSafety
from app.models.ops import UserSetting
from app.workflow.manual_assist import (
    FIELD_MATCHERS, build_bookmarklet, build_prefill_map,
)


def seed_identity(session):
    session.add(UserSetting(key="identity", value={
        "full_name": "Scott Wesley Shelton", "email": "swshelton@gmail.com",
        "phone": "+1 720-397-2240", "city": "Lakewood", "state": "Colorado",
        "linkedin": "https://www.linkedin.com/in/IAM-Scott-Shelton",
    }))
    session.commit()


def seed_app_with_packet(session, answers_status="prefilled"):
    app = Application(posting_id=1, fit_score=70.0)
    session.add(app)
    session.commit()
    session.refresh(app)
    session.add(ApplicationPacket(
        application_id=app.id, version_no=1,
        snapshot={
            "resume_file": "/srv/jobops/exports/resumes/iam_v1.docx",
            "answers": [
                {"answer_name": "work_auth_us", "text": "Yes", "status": answers_status},
                {"answer_name": "sponsorship_now", "text": "No", "status": answers_status},
                {"answer_name": "remote_pref", "text": "Remote or Denver hybrid",
                 "status": answers_status},
                {"answer_name": "salary_expectation", "text": "$110k+",
                 "status": answers_status},
            ],
        },
    ))
    session.commit()
    return app


def test_prefill_map_from_identity_and_answers(session):
    seed_identity(session)
    app = seed_app_with_packet(session)
    pm = build_prefill_map(session, app)
    by = {f.purpose: f.value for f in pm.fields}
    assert by["full_name"] == "Scott Shelton"          # display name for forms
    assert by["first_name"] == "Scott" and by["last_name"] == "Shelton"
    assert by["email"] == "swshelton@gmail.com"
    assert by["location"] == "Lakewood Colorado"
    assert by["work_auth_us"] == "Yes"
    assert by["salary_expectation"] == "$110k+"
    assert pm.resume_path.endswith("iam_v1.docx")
    assert "resume_file" not in pm.missing


def test_missing_answers_flagged_not_invented(session):
    seed_identity(session)
    app = seed_app_with_packet(session, answers_status="missing")
    pm = build_prefill_map(session, app)
    purposes = {f.purpose for f in pm.fields}
    assert "work_auth_us" not in purposes
    assert "work_auth_us" in pm.missing


def test_missing_identity_flagged(session):
    # no identity seeded
    app = seed_app_with_packet(session)
    pm = build_prefill_map(session, app)
    assert "email" in pm.missing and "full_name" in pm.missing


def test_bookmarklet_is_valid_and_contains_values(session):
    seed_identity(session)
    app = seed_app_with_packet(session)
    pm = build_prefill_map(session, app)
    bm = build_bookmarklet(pm)
    assert bm.startswith("javascript:")
    assert "swshelton@gmail.com" in bm
    assert "never" not in bm.lower()  # sanity
    # regexes compile
    for f in pm.fields:
        re.compile(f.match_regex)


def test_field_matchers_regexes_compile():
    for _purpose, rgx in FIELD_MATCHERS:
        re.compile(rgx)


def test_matchers_hit_expected_labels():
    def match(purpose, text):
        rgx = next(r for p, r in FIELD_MATCHERS if p == purpose)
        return re.search(rgx, text, re.I) is not None
    assert match("email", "Email Address")
    assert match("phone", "Mobile phone")
    assert match("work_auth_us", "Are you legally authorized to work in the United States?")
    assert match("sponsorship_now", "Will you require visa sponsorship?")
    assert match("linkedin", "LinkedIn Profile URL")


def test_last_name_is_rightmost_token(session):
    """'Scott Wesley Shelton' must split Scott / Shelton — NOT Scott / Wesley Shelton."""
    session.add(UserSetting(key="identity", value={
        "full_name": "Scott Wesley Shelton", "email": "x@y.com"}))
    session.commit()
    app = seed_app_with_packet(session)
    pm = build_prefill_map(session, app)
    by = {f.purpose: f.value for f in pm.fields}
    assert by["first_name"] == "Scott"
    assert by["last_name"] == "Shelton"
    assert by["full_name"] == "Scott Shelton"     # display name, not legal


def test_explicit_name_keys_win(session):
    session.add(UserSetting(key="identity", value={
        "full_name": "Scott Wesley Shelton", "first_name": "Scott",
        "last_name": "Shelton", "email": "x@y.com"}))
    session.commit()
    app = seed_app_with_packet(session)
    pm = build_prefill_map(session, app)
    by = {f.purpose: f.value for f in pm.fields}
    assert by["last_name"] == "Shelton"


def test_option_matcher():
    from app.workflow.manual_assist import match_option
    opts = [("", "Select..."), ("v1", "Yes"), ("v2", "No"),
            ("v3", "Yes, with restrictions")]
    assert match_option("Yes (US citizen)", opts) == "v1"   # shortest yes-lead
    assert match_option("No", opts) == "v2"
    assert match_option("banana", opts) is None             # never guesses blind

    remote_opts = [("", "Please select"), ("a", "Fully remote"),
                   ("b", "Hybrid"), ("c", "In office")]
    assert match_option("Remote", remote_opts) == "a"
    assert match_option("Hybrid (Denver metro)", remote_opts) == "b"

    us_opts = [("", "Choose an option"), ("x", "United States"), ("y", "Other")]
    assert match_option("United States of America", us_opts) == "x"


def test_cover_letter_render(session):
    from app.workflow.cover_letter import render
    text = render(session, "IAM Engineer", "Datadog", "iam", {
        "first_name": "Scott", "display_name": "Scott Shelton",
        "email": "swshelton@gmail.com", "phone": "+1 720-397-2240"})
    assert "IAM Engineer" in text and "Datadog" in text
    assert "24+ years" in text and "PingFederate" in text
    assert text.rstrip().endswith("swshelton@gmail.com | +1 720-397-2240")
    assert "Scott Shelton" in text
    assert "{" not in text                                   # all placeholders resolved


def test_cover_letter_support_track_pitch(session):
    from app.workflow.cover_letter import render
    text = render(session, "Support Engineer", "GitLab", "support_enablement", {})
    assert "enablement" in text.lower()
    assert "250 support engineers" in text
