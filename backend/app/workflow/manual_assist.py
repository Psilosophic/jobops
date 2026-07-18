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
    ("cover_letter", r"cover\s*letter"),
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
    cover_letter_path: str | None = None
    missing: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "fields": [
                {"purpose": f.purpose, "value": f.value, "match": f.match_regex,
                 "source": f.source}
                for f in self.fields
            ],
            "resume_path": self.resume_path,
            "cover_letter_path": self.cover_letter_path,
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

    legal = ident.get("full_name") or ident.get("name")
    first = ident.get("first_name")
    last = ident.get("last_name")
    if legal and not (first and last):
        # Split from the RIGHT: middle names are far more common than
        # unhyphenated compound surnames. "Scott Wesley Shelton" -> Scott / Shelton.
        tokens = legal.split()
        if len(tokens) >= 2:
            first = first or tokens[0]
            last = last or tokens[-1]
    display = ident.get("display_name") or (f"{first} {last}" if first and last else legal)
    add("full_name", display, "identity")
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

    if packet and packet.snapshot.get("cover_note"):
        add("cover_letter", packet.snapshot["cover_note"], "packet")

    if packet and packet.snapshot.get("resume_file"):
        pm.resume_path = packet.snapshot["resume_file"]
    else:
        pm.missing.append("resume_file")
    if packet and packet.snapshot.get("cover_letter_file"):
        pm.cover_letter_path = packet.snapshot["cover_letter_file"]
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
        "if(re.test(lbl(e))){e.focus();"
        "if(e.tagName==='SELECT'){var best=null,bl=1e9,v=r.val.toLowerCase();"
        "for(var j=0;j<e.options.length;j++){var ot=e.options[j].textContent.toLowerCase().trim();"
        "if(!ot||ot.indexOf('select')===0||ot.indexOf('choose')===0)continue;"
        "if(ot===v){best=j;break;}"
        "if((v.indexOf('yes')===0&&ot.indexOf('yes')===0)||(v.indexOf('no')===0&&ot.indexOf('no')===0)"
        "||ot.indexOf(v)>-1||v.indexOf(ot)>-1){if(ot.length<bl){best=j;bl=ot.length;}}}"
        "if(best===null)continue;e.selectedIndex=best;}"
        "else{e.value=r.val;}"
        "e.dispatchEvent(new Event('input',{bubbles:true}));"
        "e.dispatchEvent(new Event('change',{bubbles:true}));"
        "e.dataset.jobopsFilled='1';e.style.outline='2px solid #10b981';n++;break;}}});"
        "alert('JobOps prefilled '+n+' fields. Review, attach resume, and submit yourself.');"
        "})();"
    )
    return "javascript:" + js


_NORM_RE = re.compile(r"[^a-z0-9 ]+")


def _norm(t: str) -> str:
    return _NORM_RE.sub(" ", (t or "").lower()).strip()


def match_option(value: str, options: list[tuple[str, str]]) -> str | None:
    """Pick the best <option> for a desired value. options = [(value_attr, text)].
    Rules, in order: exact normalized text match; yes/no prefix mapping (a value
    starting 'yes'/'no' selects the option starting 'yes'/'no'); desired value
    contained in option text (or vice versa); best token overlap >= 0.5.
    Returns the option's value attribute, or None (never guesses blind)."""
    v = _norm(value)
    if not v:
        return None
    cands = [(val, _norm(txt)) for val, txt in options
             if _norm(txt) not in ("", "select", "select an option", "please select",
                                   "choose", "choose an option", "select one")]
    for val, txt in cands:
        if txt == v:
            return val
    for lead in ("yes", "no"):
        if v.startswith(lead):
            leads = [c for c in cands if c[1].startswith(lead)]
            if len(leads) == 1:
                return leads[0][0]
            # prefer the shortest option that starts with the same lead ("Yes" over
            # "Yes, with conditions") when several exist
            if leads:
                return min(leads, key=lambda c: len(c[1]))[0]
    for val, txt in cands:
        if v in txt or txt in v:
            return val
    vt = set(v.split())
    best, best_score = None, 0.0
    for val, txt in cands:
        tt = set(txt.split())
        if not tt:
            continue
        score = len(vt & tt) / len(vt | tt)
        if score > best_score:
            best, best_score = val, score
    return best if best_score >= 0.5 else None


# --------- Playwright headless filler (optional; runs in the assist container) ----------

async def fill_form_headless(url: str, pm: PrefillMap, screenshot_path: str) -> dict:
    """Open the apply page headless, fill confidently-matched fields, upload files,
    screenshot. If the landing page is a job DESCRIPTION with no form (common on
    branded career sites like Datadog/Twilio), follow the Apply link once and
    retry. NEVER submits.

    Imported lazily so the API/worker images don't need Playwright installed.
    """
    from playwright.async_api import async_playwright  # noqa: PLC0415

    report: dict = {"filled": [], "skipped": [], "uploaded_resume": False,
                    "uploaded_cover_letter": False, "clicked_apply": False,
                    "screenshot": screenshot_path, "error": None}

    async def scan_and_fill(page) -> int:
        filled = 0
        controls = await page.query_selector_all("input, textarea, select")
        for f in pm.fields:
            if f.purpose in report["filled"]:
                continue
            rgx = re.compile(f.match_regex, re.I)
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
                        opts = await el.evaluate(
                            "e => Array.from(e.options).map(o => ({v: o.value, t: o.textContent}))"
                        )
                        pick = match_option(f.value, [(o["v"], o["t"]) for o in opts])
                        if pick is None:
                            continue
                        await el.select_option(value=pick)
                    else:
                        await el.fill(f.value)
                    report["filled"].append(f.purpose)
                    filled += 1
                    break
                except Exception:  # noqa: BLE001,PERF203
                    continue
        return filled

    async def upload_files(page) -> None:
        file_inputs = await page.query_selector_all('input[type="file"]')
        cover_rgx = re.compile(r"cover", re.I)
        for fi in file_inputs:
            haystack = " ".join(filter(None, [
                await fi.get_attribute("name"), await fi.get_attribute("id"),
                await fi.get_attribute("aria-label"),
            ]))
            is_cover = bool(cover_rgx.search(haystack))
            try:
                if is_cover and pm.cover_letter_path:
                    await fi.set_input_files(pm.cover_letter_path)
                    report["uploaded_cover_letter"] = True
                elif not is_cover and pm.resume_path and not report["uploaded_resume"]:
                    await fi.set_input_files(pm.resume_path)
                    report["uploaded_resume"] = True
            except Exception as exc:  # noqa: BLE001
                report["skipped"].append(f"file_upload:{exc}")

    async def click_apply(page) -> bool:
        """Follow an Apply link/button on a description-only page. One hop max;
        never clicks anything that could submit (forms have no fields filled yet)."""
        candidates = await page.query_selector_all(
            "a[href*='apply' i], a[href*='#app' i], button, a[role='button']")
        for el in candidates:
            try:
                text = ((await el.text_content()) or "").strip().lower()
                if not re.fullmatch(r"apply( now| for this job| here)?!?", text):
                    continue
                async with page.expect_navigation(wait_until="domcontentloaded",
                                                  timeout=15000) as _nav:
                    await el.click()
                return True
            except Exception:  # noqa: BLE001,PERF203
                try:
                    # SPA apply buttons may not navigate; give the form a beat
                    await page.wait_for_timeout(2500)
                    return True
                except Exception:  # noqa: BLE001
                    continue
        return False

    try:
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=True)
            page = await browser.new_page(viewport={"width": 1280, "height": 1600})
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await page.wait_for_timeout(1500)
            n = await scan_and_fill(page)
            if n < 2 and await click_apply(page):
                report["clicked_apply"] = True
                await page.wait_for_timeout(2000)
                await scan_and_fill(page)
            for f in pm.fields:
                if f.purpose not in report["filled"]:
                    report["skipped"].append(f.purpose)
            await upload_files(page)
            await page.screenshot(path=screenshot_path, full_page=True)
            await browser.close()
    except Exception as exc:  # noqa: BLE001
        report["error"] = str(exc)[:500]
    return report
