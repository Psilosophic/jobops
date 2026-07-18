"""One-way sync: Brain wiki JobOps/Intake.md -> engine settings.

The wiki is the human-edited source of truth for preferences. This parser reads
'- Field: value' lines under known sections and writes user_settings, answer bank
variants, and list entries. It never writes wiki content (the interviewer does).

Run: python -m app.intake.wiki_sync /path/to/Brain/wiki/JobOps/Intake.md
"""
import re
import sys
from datetime import datetime, timezone

from sqlmodel import Session, select

from app.db import engine
from app.logging import configure_logging, get_logger
from app.models.base import AnswerSafety, ListKind
from app.models.ops import ListEntry, UserSetting
from app.models.profile import AnswerBankItem, AnswerBankVariant

configure_logging()
log = get_logger("wiki_sync")

_FIELD_RE = re.compile(r"^-\s+(.+?):\s*(.*)$")
_SECTION_RE = re.compile(r"^(#{2,4})\s+(.*)$")

UNKNOWN_VALUES = {"", "unknown", "unknown — set during intake", "n/a", "tbd"}


def parse_intake(md: str) -> dict[str, dict[str, str]]:
    """Returns {section_path: {field: value}} skipping UNKNOWNs."""
    out: dict[str, dict[str, str]] = {}
    stack: list[str] = []
    for line in md.splitlines():
        sec = _SECTION_RE.match(line)
        if sec:
            depth = len(sec.group(1)) - 2  # ## -> 0, ### -> 1, #### -> 2
            stack = stack[:depth] + [sec.group(2).strip()]
            continue
        m = _FIELD_RE.match(line.strip())
        if m and stack:
            field, value = m.group(1).strip(), m.group(2).strip()
            if value.lower().rstrip("?") in UNKNOWN_VALUES or value.startswith("UNKNOWN"):
                continue
            out.setdefault(" / ".join(stack), {})[field] = value
    return out


_MONEY_RE = re.compile(r"\$?\s*(\d{2,3})[,.]?(\d{3})?\s*(k)?", re.I)


def parse_money(value: str) -> int | None:
    m = _MONEY_RE.search(value)
    if not m:
        return None
    n = int(m.group(1) + (m.group(2) or ""))
    if m.group(3) or n < 1000:
        n *= 1000
    return n


ANSWER_MAP = {
    # (section suffix, field) -> (bank item name, treat_as)
    ("Work Authorization", "Are you legally authorized to work in the US?"):
        ("work_auth_us", "text"),
    ("Work Authorization", "Need sponsorship now?"): ("sponsorship_now", "text"),
    ("Work Setup", "Remote preference"): ("remote_pref", "text"),
    ("Compensation", "Preferred base salary"): ("salary_expectation", "text"),
}


def sync(md_path: str) -> dict:
    md = open(md_path, encoding="utf-8").read()
    data = parse_intake(md)
    applied = {"settings": 0, "answers": 0, "lists": 0}

    with Session(engine) as s:
        def put_setting(key: str, value) -> None:
            row = s.exec(select(UserSetting).where(UserSetting.key == key)).first() \
                or UserSetting(key=key, value={})
            row.value = {"value": value}
            row.updated_at = datetime.now(timezone.utc)
            s.add(row)
            applied["settings"] += 1

        # Profile Identity -> user_settings["identity"] (feeds manual-assist prefill)
        identity_map = {
            "Full name": "full_name", "Preferred name": "preferred_name",
            "Email address": "email", "Phone number": "phone",
            "City": "city", "State": "state", "Zip code": "zip",
            "LinkedIn URL": "linkedin", "GitHub URL": "github",
            "Portfolio URL": "portfolio", "Personal website URL": "portfolio",
        }
        identity: dict = {}
        for section, fields in data.items():
            if section.endswith("Profile Identity"):
                for label, key in identity_map.items():
                    if label in fields:
                        identity[key] = fields[label]
        if identity:
            full = identity.get("full_name", "")
            tokens = full.split()
            if len(tokens) >= 2:
                identity.setdefault("first_name", tokens[0])
                identity.setdefault("last_name", tokens[-1])   # right token = surname
            if identity.get("first_name") and identity.get("last_name"):
                identity.setdefault(
                    "display_name",
                    f"{identity['first_name']} {identity['last_name']}")
            loc_bits = [identity.get("city"), identity.get("state"), identity.get("zip")]
            if identity.get("city"):
                identity.setdefault("location", ", ".join(
                    b for b in loc_bits[:2] if b) + (f" {loc_bits[2]}" if loc_bits[2] else ""))
            row = s.exec(select(UserSetting).where(UserSetting.key == "identity")).first() \
                or UserSetting(key="identity", value={})
            row.value = {**(row.value or {}), **identity}
            row.updated_at = datetime.now(timezone.utc)
            s.add(row)
            applied["settings"] += 1

        for section, fields in data.items():
            if section.endswith("Compensation"):
                if "Minimum base salary" in fields:
                    floor = parse_money(fields["Minimum base salary"])
                    if floor:
                        put_setting("salary_floor", floor)
                if "Preferred base salary" in fields:
                    target = parse_money(fields["Preferred base salary"])
                    if target:
                        put_setting("salary_target", target)
            if section.endswith("Search Preferences"):
                for field, kind, allow in (
                    ("Blacklisted employers", ListKind.employer, False),
                    ("Preferred employers", ListKind.employer, True),
                    ("Keywords to suppress", ListKind.keyword, False),
                    ("Titles to suppress", ListKind.title, False),
                ):
                    if field in fields:
                        for value in re.split(r"[;,]", fields[field]):
                            value = value.strip()
                            if not value:
                                continue
                            exists = s.exec(select(ListEntry).where(
                                ListEntry.kind == kind, ListEntry.value == value,
                                ListEntry.is_allow == allow)).first()
                            if not exists:
                                s.add(ListEntry(kind=kind, is_allow=allow, value=value,
                                                reason="wiki intake"))
                                applied["lists"] += 1

            for (suffix, field), (bank_name, _mode) in ANSWER_MAP.items():
                if section.endswith(suffix) and field in fields:
                    item = s.exec(select(AnswerBankItem).where(
                        AnswerBankItem.name == bank_name)).first()
                    if item is None:
                        continue
                    variant = s.exec(select(AnswerBankVariant).where(
                        AnswerBankVariant.answer_id == item.id,
                        AnswerBankVariant.track_id == None)).first()  # noqa: E711
                    if variant is None:
                        variant = AnswerBankVariant(answer_id=item.id)
                    variant.answer_text = fields[field]
                    # intake-confirmed truths are reviewable-by-default; the user
                    # flips to safe_for_auto_use per-variant in the UI/interview
                    if variant.safety == AnswerSafety.forbidden_for_auto_use:
                        variant.safety = AnswerSafety.requires_review
                    variant.last_verified_at = datetime.now(timezone.utc)
                    s.add(variant)
                    applied["answers"] += 1
        s.commit()
    log.info("wiki_sync_complete", **applied)
    return applied


if __name__ == "__main__":
    print(sync(sys.argv[1]))
