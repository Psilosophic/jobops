"""Cover letter generation: a generic, truthful template interpolated per role.

Template lives in user_settings["cover_letter_template"] (editable); a brief
professional default ships below. Placeholders: {role} {company} {track_pitch}
{first_name} {display_name} {email} {phone}. No facts are invented — the pitch
lines are static, operator-approved text per track.
"""
from pathlib import Path

from sqlmodel import Session, select

from app.models.ops import UserSetting

DEFAULT_TEMPLATE = """Dear {company} Hiring Team,

I'm writing to apply for the {role} position. {track_pitch}

Beyond the technical fit, I bring a track record of building enablement that scales: onboarding programs that cut time-to-competency by 30%, playbooks and knowledge-base standards adopted globally, and lab environments that let teams learn by doing. I care about secure design, clear documentation, and leaving every system - and team - better than I found it.

I'm based in the Denver metro area, available immediately, and open to remote, hybrid, or onsite work. I'd welcome the chance to talk about how I can contribute to {company}.

Best regards,
{display_name}
{email} | {phone}"""

TRACK_PITCHES = {
    "iam": ("With 24+ years in IT and deep specialization in Identity & Access "
            "Management - PingFederate, SAML 2.0, OAuth 2.0/OIDC, Active Directory, "
            "and Entra ID - I've spent my career making authentication and "
            "federation work reliably at enterprise scale."),
    "support_enablement": ("With 24+ years in IT, including global technical "
                           "enablement for ~250 support engineers at Ping Identity "
                           "and years of hands-on, customer-facing troubleshooting "
                           "of identity systems, I know how to turn hard technical "
                           "problems into resolved tickets and stronger teams."),
}


def get_template(session: Session) -> str:
    row = session.exec(select(UserSetting).where(
        UserSetting.key == "cover_letter_template")).first()
    return (row.value or {}).get("value") if row and (row.value or {}).get("value") \
        else DEFAULT_TEMPLATE


def render(session: Session, role: str, company: str, track_slug: str | None,
           identity: dict) -> str:
    first = identity.get("first_name") or "Scott"
    display = identity.get("display_name") or identity.get("full_name") or first
    return get_template(session).format(
        role=role or "open role",
        company=company or "your team",
        track_pitch=TRACK_PITCHES.get(track_slug or "", TRACK_PITCHES["iam"]),
        first_name=first,
        display_name=display,
        email=identity.get("email", ""),
        phone=identity.get("phone", ""),
    )


def write_docx(text: str, out_path: str) -> str:
    """Simple, ATS-clean single-column docx for upload fields."""
    from docx import Document  # python-docx
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(11)
    for para in text.split("\n\n"):
        doc.add_paragraph(para)
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    doc.save(out_path)
    return out_path
