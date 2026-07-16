"""Seed data: source policy matrix (cautious), resume tracks, keyword packs,
default scoring profile, starter answer bank, panic defaults.
Run: python -m app.seeds  (idempotent)."""
from sqlmodel import Session, select

from app.db import engine
from app.logging import configure_logging, get_logger
from app.models.base import (
    AnswerCategory, AnswerSafety, RiskLevel, SourceMode, SourceType,
)
from app.models.ops import PanicState
from app.models.profile import AnswerBankItem, AnswerBankVariant, ResumeTrack
from app.models.scoring import KeywordPack, ScoringProfile
from app.models.sources import Source, SourcePolicy

configure_logging()
log = get_logger("seeds")

SOURCES = [
    # slug, name, type, login, api, retrieval, config
    ("greenhouse", "Greenhouse Job Board API", SourceType.ats, False, True, "official_api",
     {"boards": [], "company_names": {}}),
    ("lever", "Lever Postings API", SourceType.ats, False, True, "official_api",
     {"orgs": [], "company_names": {}}),
    ("ashby", "Ashby Job Board API", SourceType.ats, False, True, "official_api",
     {"boards": [], "company_names": {}}),
    ("smartrecruiters", "SmartRecruiters Postings API", SourceType.ats, False, True,
     "official_api", {"companies": [], "company_names": {}}),
    ("builtin_co", "Built In Colorado", SourceType.board, False, False, "rss", {}),
    ("linkedin_alerts", "LinkedIn (email alerts)", SourceType.mailbox, True, False, "imap", {}),
    ("indeed_alerts", "Indeed (email alerts)", SourceType.mailbox, False, False, "imap", {}),
    ("dice_alerts", "Dice (email alerts)", SourceType.mailbox, False, False, "imap", {}),
    ("icims", "iCIMS employer boards", SourceType.ats, False, False, "rss", {}),
    ("workday", "Workday tenants", SourceType.ats, True, False, "none", {}),
    ("career_pages", "Direct employer career pages", SourceType.employer_page, False, False,
     "allowlisted_fetch", {}),
]

# slug -> (scrape, browser, auto_submit, manual_review, mode, risk, evidence)
POLICIES = {
    "greenhouse": (False, True, False, True, SourceMode.manual_assist, RiskLevel.low,
                   "Official public Job Board API. Apply forms are employer-hosted; "
                   "manual-assist prefill only, human confirms. Auto-submit off by default."),
    "lever": (False, True, False, True, SourceMode.manual_assist, RiskLevel.low,
              "Official public Postings API. Same manual-assist stance as Greenhouse."),
    "ashby": (False, True, False, True, SourceMode.manual_assist, RiskLevel.low,
              "Official public Job Board API incl. compensation data."),
    "smartrecruiters": (False, True, False, True, SourceMode.manual_assist, RiskLevel.low,
                        "Official public Postings API."),
    "builtin_co": (False, False, False, True, SourceMode.qualify_only, RiskLevel.medium,
                   "Use RSS/alert surfaces; respect robots.txt; postings usually deep-link "
                   "to an ATS which we re-route to the ATS adapter."),
    "linkedin_alerts": (False, False, False, True, SourceMode.discover_only, RiskLevel.high,
                        "LinkedIn ToS prohibits scraping/automation. Discovery ONLY via "
                        "alert emails LinkedIn sends to our own mailbox + user exports. "
                        "Apply = packet + official-page handoff."),
    "indeed_alerts": (False, False, False, True, SourceMode.discover_only, RiskLevel.high,
                      "Indeed ToS prohibits crawling; alert-email discovery only."),
    "dice_alerts": (False, False, False, True, SourceMode.discover_only, RiskLevel.med_high,
                    "No public API; conservative stance: alert-email discovery only."),
    "icims": (False, False, False, True, SourceMode.packet_only, RiskLevel.medium,
              "Partner-only API. Packet + handoff."),
    "workday": (False, False, False, True, SourceMode.packet_only, RiskLevel.medium,
                "Per-tenant accounts; no applicant API. Packet + launch official page."),
    "career_pages": (False, False, False, True, SourceMode.qualify_only, RiskLevel.medium,
                     "Per-employer allowlist; robots.txt respected; ATS detection re-routes."),
}

TRACKS = [
    ("iam", "IAM / Identity Engineering", 1,
     "PingFederate, SAML, OAuth2/OIDC, AD, Entra ID, MFA, RBAC, federation."),
    ("support_enablement", "Support / Enablement", 2,
     "Technical support engineering, customer-facing troubleshooting, enablement."),
]

KEYWORD_PACKS = [
    ("iam-default", "iam", {
        "titles": [
            "iam engineer", "identity engineer", "identity and access management",
            "iam administrator", "identity access management engineer",
            "sso engineer", "federation engineer", "iam analyst",
            "identity engineer", "access management engineer",
            "pingfederate engineer", "identity architect",
        ],
        "required_tech": ["saml", "oauth", "oidc", "active directory"],
        "preferred_tech": [
            "pingfederate", "entra", "azure ad", "mfa", "rbac", "okta", "ping identity",
            "openid connect", "federation", "scim", "ldap", "kerberos", "radius",
        ],
    }, {
        "titles": ["director", "vp ", "vice president", "intern", "principal architect"],
        "tech": ["sailpoint developer", "cyberark developer"],
    }),
    ("support-enablement-default", "support_enablement", {
        "titles": [
            "technical support engineer", "support engineer", "customer support engineer",
            "support enablement", "technical enablement", "escalation engineer",
            "customer engineer", "solutions support engineer", "systems administrator",
            "infrastructure support", "technical account manager",
        ],
        "required_tech": ["troubleshooting", "customer"],
        "preferred_tech": [
            "active directory", "azure", "networking", "windows server", "sso", "saml",
            "identity", "enablement", "documentation", "knowledge base", "escalation",
            "linux", "powershell",
        ],
    }, {
        "titles": ["call center", "tier 1", "help desk intern", "sales engineer"],
        "tech": [],
    }),
]

ANSWER_BANK = [
    # (name, category, question_pattern, [(track, text, safety)])
    ("work_auth_us", AnswerCategory.work_authorization,
     r"(authorized|eligible).*(work).*(us|united states)",
     [(None, "UNKNOWN — set during intake", AnswerSafety.forbidden_for_auto_use)]),
    ("sponsorship_now", AnswerCategory.sponsorship,
     r"(require|need).*(sponsorship|visa)",
     [(None, "UNKNOWN — set during intake", AnswerSafety.forbidden_for_auto_use)]),
    ("remote_pref", AnswerCategory.work_setup,
     r"(remote|hybrid|onsite|on-site).*(preference|willing|able)",
     [(None, "UNKNOWN — set during intake", AnswerSafety.forbidden_for_auto_use)]),
    ("salary_expectation", AnswerCategory.compensation,
     r"(salary|compensation|pay).*(expectation|requirement|range)",
     [(None, "UNKNOWN — set during intake", AnswerSafety.forbidden_for_auto_use)]),
]


def seed() -> None:
    with Session(engine) as s:
        for slug, name, stype, login, api, method, config in SOURCES:
            if s.exec(select(Source).where(Source.slug == slug)).first():
                continue
            src = Source(slug=slug, name=name, source_type=stype, login_required=login,
                         official_api_available=api, retrieval_method=method, config=config,
                         enabled=slug in ("greenhouse", "lever", "ashby", "smartrecruiters"))
            s.add(src)
            s.commit()
            s.refresh(src)
            scrape, browser, auto, review, mode, risk, evidence = POLICIES[slug]
            s.add(SourcePolicy(
                source_id=src.id, scraping_allowed=scrape,
                browser_automation_allowed=browser, auto_submit_allowed=auto,
                manual_review_required=review, recommended_mode=mode,
                risk_level=risk, evidence_notes=evidence,
            ))
            s.commit()
            log.info("seeded_source", slug=slug, mode=str(mode))

        for slug, name, prio, summary in TRACKS:
            if not s.exec(select(ResumeTrack).where(ResumeTrack.slug == slug)).first():
                s.add(ResumeTrack(slug=slug, name=name, priority=prio, summary=summary))
        s.commit()

        for name, track, include, exclude in KEYWORD_PACKS:
            if not s.exec(select(KeywordPack).where(KeywordPack.name == name)).first():
                s.add(KeywordPack(name=name, track_slug=track, include=include,
                                  exclude=exclude))
        s.commit()

        if not s.exec(select(ScoringProfile).where(ScoringProfile.name == "default")).first():
            s.add(ScoringProfile(name="default", is_active=True))
            s.commit()

        for name, cat, pattern, variants in ANSWER_BANK:
            if s.exec(select(AnswerBankItem).where(AnswerBankItem.name == name)).first():
                continue
            item = AnswerBankItem(name=name, category=cat, question_pattern=pattern)
            s.add(item)
            s.commit()
            s.refresh(item)
            for _track, text, safety in variants:
                s.add(AnswerBankVariant(answer_id=item.id, answer_text=text, safety=safety))
            s.commit()

        if s.get(PanicState, 1) is None:
            # Ships in maximum-caution posture: review required for everything.
            s.add(PanicState(id=1, review_required_all=True))
            s.commit()
    log.info("seed_complete")


if __name__ == "__main__":
    seed()
