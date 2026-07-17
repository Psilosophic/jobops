"""Phase 4 — manual-assist prefill.

Three layers, all policy-gated on Action.BROWSER_ASSIST, none of which submit:

1. build_prefill_map()  — deterministic {field_purpose: value} from the operator
   profile (identity) + the truthful answer bank. Pure, fully tested.
2. FormFiller (Playwright) — headless: opens the official apply page, fills the
   fields it can confidently match, uploads the resume, screenshots the result,
   and returns a coverage report. It NEVER clicks submit.
3. build_bookmarklet() — the practical handoff: a javascript: bookmarklet the
   operator runs in THEIR OWN authenticated browser (where they'll actually
   submit), which fills matching fields from the same prefill map.

Compliance: prefill only assists a human who does the final review + submit.
Auto-submit stays off everywhere; the policy gate is re-checked before any
browser action.
"""
import json
import re
from dataclasses import dataclass, field

from sqlmodel import Session, select

from app.models.applications import Application, ApplicationPacket
from app.models.ops import UserSetting

# Canonical field purposes we know how to fill, with the label/name/placeholder
# regexes that identify them on a form.
FIELD_MATCHERS: list[tuple[str, str]] = [
    ("first_name", r"first[\s_-]*name|given[\s_-]*name|fname"),
    ("last_name", r"last[\s_-]*name|family[\s_-]*name|surname|lname"),
    ("full_name", r"\b(full[\s_-]*)?name\b"),
    ("email", r"e-?mail"),
    ("phone", r"phone|mobile|tel\b|telephone"),
    ("location", r"location|city|address|where.*based"),
    ("linkedin", r"linkedin"),
    ("github", r"github"),
    ("portfolio", r"portfolio|website|personal\s*site"),
    ("work_auth_us", r"authoriz|eligib.*work|legally.*work|right to work"),
    ("sponsorship_now", r"sponsor|visa"),
    ("remote_pref", r"remote|hybrid|onsite|work\s*setup|work\s*location\s*pref"),
    ("salary_expectation", r"salary|compensation|desired\s*pay|expected\s*pay"),
]

# answer-bank names that satisfy the screener purposes above
ANSWER_PURPOSES = {"work_auth_us", "sponsorship_now", "remote_pref", "salary_expectation"}


@dataclass
class PrefillField:
    purpose: str
    value: str
    match_regex: str
    source: str  # "identity" | "answer_bank"


@dataclass
class PrefillMap:
    fields: list[PrefillField] = field(default_factory=list)
    resume_path: str | None = None
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fields": [
                {"purpose": f.purpose, "value": f.value, "match": f.match_regex,
                 "source": f.source}
                for f in self.fields
            ],
            "resume_path": self.resume_path,
            "missing": self.missing,
        }


def _identity(session: Session) -> dict:
    row = session.exec(select(UserSetting).where(UserSetting.key == "identity")).first()
    return (row.value or {}) if row else {}


def build_prefill_map(session: Session, app: Application) -> PrefillMap:
    """Assemble field values from identity settings + the packet's chosen answers.
    Only truthful, present values are included; anything absent is flagged missing."""
    ident = _identity(session)
    pm = PrefillMap()

    def add(purpose: str, value: str | None, source: str) -> None:
        rgx = next((r for p, r in FIELD_MATCHERS if p == purpose), purpose)
        if value:
            pm.fields.append(PrefillField(purpose, str(value), rgx, source))
        else:
            pm.missing.append(purpose)

    full = ident.get("full_name") or ident.get("name")
    first = ident.get("first_name")
    last = ident.get("last_name")
    if full and not (first and last) and " " in full:
        first, last = full.split(" ", 1)
    add("full_name", full, "identity")
    add("first_name", first, "identity")
    add("last_name", last, "identity")
    add("email", ident.get("email"), "identity")
    add("phone", ident.get("phone"), "identity")
    loc = ident.get("location") or " ".join(
        x for x in [ident.get("city"), ident.get("state")] if x)
    add("location", loc or None, "identity")
    add("linkedin", ident.get("linkedin"), "identity")
    add("github", ident.get("github"), "identity")
    add("portfolio", ident.get("portfolio"), "identity")

    # screener answers from the latest packet (already safety-filtered)
    packet = session.exec(
        select(ApplicationPacket).where(ApplicationPacket.application_id == app.id)
        .order_by(ApplicationPacket.version_no.desc())
    ).first()
    answers = {a.get("answer_name"): a for a in (packet.snapshot.get("answers", [])
                                                 if packet else [])}
    for name in ANSWER_PURPOSES:
        row = answers.get(name)
        add(name, row.get("text") if row and row.get("status") != "missing" else None,
            "answer_bank")

    if packet and packet.snapshot.get("resume_file"):
        pm.resume_path = packet.snapshot["resume_file"]
    else:
        pm.missing.append("resume_file")
    return pm


def build_bookmarklet(pm: PrefillMap) -> str:
    """A javascript: bookmarklet that fills matching fields in the operator's own
    browser. Matches inputs by label text, name, id, placeholder, or aria-label.
    Never submits."""
    rules = [{"re": f.match_regex, "val": f.value} for f in pm.fields]
    payload = json.dumps(rules)
    js = (
        "(function(){var R=" + payload + ";"
        "function lbl(el){var t=(el.name||'')+' '+(el.id||'')+' '+(el.placeholder||'')"
        "+' '+(el.getAttribute('aria-label')||'');"
        "if(el.labels&&el.labels.length){for(var i=0;i<el.labels.length;i++)"
        "t+=' '+el.labels[i].textContent;}return t.toLowerCase();}"
        "var n=0,els=document.querySelectorAll('input,textarea,select');"
        "R.forEach(function(r){var re=new RegExp(r.re,'i');"
        "for(var i=0;i<els.length;i++){var e=els[i];if(e.dataset.jobopsFilled)continue;"
        "if(e.type==='hidden'||e.type==='password'||e.type==='file')continue;"
        "if(re.test(lbl(e))){e.focus();e.value=r.val;"
        "e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "e.dataset.jobopsFilled='1';e.style.outline='2px solid #10b981';n++;break;}}});"
        "alert('JobOps prefilled '+n+' fields. Review, attach resume, and submit yourself.');"
        "})();"
    )
    return "javascript:" + js


# --------- Playwright headless filler (optional; runs in the assist container) ----------

async def fill_form_headless(url: str, pm: PrefillMap, screenshot_path: str) -> dict:
    """Open the apply page headless, fill confidently-matched fields, upload the
    resume, screenshot. Returns a coverage report. NEVER submits.

    Imported lazily so the API/worker images don't need Playwright installed.
    """
    from playwright.async_api import async_playwright  # noqa: PLC0415

    report: dict = {"filled": [], "skipped": [], "uploaded_resume": False,
                    "screenshot": screenshot_path, "error": None}
    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 1600})
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            controls = await page.query_selector_all("input, textarea, select")
            for f in pm.fields:
                rgx = re.compile(f.match_regex, re.I)
                done = False
                for el in controls:
                    try:
                        tag = (await el.evaluate("e => e.tagName")).lower()
                        typ = (await el.get_attribute("type") or "").lower()
                        if typ in ("hidden", "file", "password", "submit", "button"):
                            continue
                        haystack = " ".join(filter(None, [
                            await el.get_attribute("name"),
                            await el.get_attribute("id"),
                            await el.get_attribute("placeholder"),
                            await el.get_attribute("aria-label"),
                        ])).lower()
                        if not rgx.search(haystack):
                            continue
                        if tag == "select":
                            await el.select_option(label=re.compile(f.value, re.I))
                        else:
                            await el.fill(f.value)
                        report["filled"].append(f.purpose)
                        done = True
                        break
                    except Exception:  # noqa: BLE001,PERF203
                        continue
                if not done:
                    report["skipped"].append(f.purpose)
            if pm.resume_path:
                file_input = await page.query_selector('input[type="file"]')
                if file_input:
                    try:
                        await file_input.set_input_files(pm.resume_path)
                        report["uploaded_resume"] = True
                    except Exception as exc:  # noqa: BLE001
                        report["skipped"].append(f"resume_upload:{exc}")
            await page.screenshot(path=screenshot_path, full_page=True)
            await browser.close()
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)[:500]
    return report
