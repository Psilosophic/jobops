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
    assert by["full_name"] == "Scott Wesley Shelton"
    assert by["first_name"] == "Scott" and by["last_name"] == "Wesley Shelton"
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
