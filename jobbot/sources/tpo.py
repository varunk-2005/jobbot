"""MNNIT Training & Placement Office portal.

This is the highest-value source in the whole bot. Campus drives have hard
deadlines, fixed eligibility gates, and no second chance if you miss the
registration window.

It logs in with your own credentials and reads the listings. It does NOT
auto-register you for drives — see notes in register() for why.

The portal's HTML is unknown to this code, so instead of hardcoding CSS
selectors that would break on the first redesign, it strips the page to text
and lets Claude pull the structure out. Run scripts/tpo_probe.py once to
confirm login works and see what the parser is actually receiving.
"""
import re

import requests
from bs4 import BeautifulSoup

from .. import llm

TIMEOUT = 30

EXTRACT_SYSTEM = """You read a college placement portal page and extract company drives.

Return ONLY a JSON array, no fences:
[{
  "company": "...",
  "title": "<role, or 'Not stated'>",
  "ctc_text": "<the compensation exactly as written, e.g. '18 LPA (14 base + 4 variable)'>",
  "base_lpa": <number or null: the FIXED BASE only, converted to LPA>,
  "ctc_lpa": <number or null>,
  "min_cgpa": <number or null>,
  "eligible_branches": "<as written, or 'All'>",
  "eligible_batch": "<year, or empty>",
  "deadline": "<registration deadline exactly as written, or empty>",
  "status": "open" | "closed" | "unknown",
  "notes": "<max 20 words: backlogs policy, test date, bond, anything gating>"
}]

Rules:
- One object per company drive. Skip navigation, headers, footers, menus.
- Do not invent figures. If the page does not state CTC or CGPA, use null.
- If a page shows only a notice with no drives, return [].
- Distinguish base from CTC carefully. "18 LPA CTC" means ctc_lpa 18, base_lpa null."""


def _text_of(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "svg"]):
        tag.decompose()
    return re.sub(r"\n{3,}", "\n\n", soup.get_text("\n", strip=True))[:14000]


def _form_fields(html: str) -> dict:
    """Auto-detect the login form's field names so this survives a redesign."""
    soup = BeautifulSoup(html, "html.parser")
    form = soup.find("form") or soup
    out = {"hidden": {}, "user": None, "pw": None, "extra": None, "action": None}
    if getattr(form, "get", None):
        out["action"] = form.get("action")

    for inp in form.find_all("input"):
        itype = (inp.get("type") or "text").lower()
        name = inp.get("name")
        if not name:
            continue
        if itype == "hidden":                      # CSRF tokens live here
            out["hidden"][name] = inp.get("value", "")
        elif itype == "password" and not out["pw"]:
            out["pw"] = name
        elif itype in {"text", "email", "number"}:
            if not out["user"]:
                out["user"] = name
            elif not out["extra"]:
                out["extra"] = name

    for sel in form.find_all("select"):
        if sel.get("name") and not out["extra"]:
            out["extra"] = sel.get("name")
    return out


def login(cfg) -> requests.Session | None:
    tpo = cfg.sources.get("tpo") or {}
    base = (tpo.get("base_url") or "").rstrip("/")
    if not (base and cfg.tpo_username and cfg.tpo_password):
        return None

    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"
    login_url = base + tpo.get("login_path", "/new/portal")

    try:
        page = sess.get(login_url, timeout=TIMEOUT)
        fields = _form_fields(page.text)

        payload = dict(fields["hidden"])
        payload[tpo.get("field_username") or fields["user"] or "username"] = cfg.tpo_username
        payload[tpo.get("field_password") or fields["pw"] or "password"] = cfg.tpo_password
        year_field = tpo.get("field_year") or fields["extra"]
        if year_field:
            payload[year_field] = str(tpo.get("graduation_year", ""))

        action = tpo.get("login_post_path") or fields["action"] or tpo.get("login_path", "/new/portal")
        post_url = action if action.startswith("http") else base + ("" if action.startswith("/") else "/") + action

        resp = sess.post(post_url, data=payload, timeout=TIMEOUT, allow_redirects=True)

        # Still looking at a password box means the credentials bounced.
        if "type=\"password\"" in resp.text.lower() or "student login" in resp.text.lower():
            print("[tpo] login rejected — check credentials, or the password was reset")
            return None
        return sess
    except Exception as exc:  # noqa: BLE001
        print(f"[tpo] login failed: {exc}")
        return None


def fetch_drives(cfg, sess: requests.Session) -> list[dict]:
    tpo = cfg.sources.get("tpo") or {}
    base = (tpo.get("base_url") or "").rstrip("/")
    pages = tpo.get("listing_paths") or ["/new/portal/dashboard"]

    blobs = []
    for path in pages:
        try:
            r = sess.get(base + path, timeout=TIMEOUT)
            if r.status_code == 200:
                text = _text_of(r.text)
                if len(text) > 200:
                    blobs.append(f"### PAGE {path}\n{text}")
        except Exception as exc:  # noqa: BLE001
            print(f"[tpo] {path}: {exc}")

    if not blobs:
        return []

    drives = []
    for blob in blobs:
        try:
            text = llm.complete(cfg, EXTRACT_SYSTEM, blob, max_tokens=4000)
            for d in llm.json_arr(text):
                d["source"] = "tpo"
                d["url"] = base + tpo.get("login_path", "/new/portal")
                drives.append(d)
        except Exception as exc:  # noqa: BLE001
            print(f"[tpo] extraction failed: {exc}")
    return drives


def eligibility(cfg, drive: dict) -> tuple[bool, str]:
    """Check the gates the portal enforces before you can even register."""
    me_cgpa = float(cfg.identity.get("cgpa") or 0)
    me_batch = str(cfg.identity.get("graduation_year") or "")

    need = drive.get("min_cgpa")
    if isinstance(need, (int, float)) and me_cgpa and me_cgpa < need:
        return False, f"needs {need} CGPA, you have {me_cgpa}"

    batch = str(drive.get("eligible_batch") or "")
    if batch and me_batch and me_batch not in batch:
        return False, f"batch {batch} only"

    if (drive.get("status") or "").lower() == "closed":
        return False, "registration closed"

    return True, "eligible"


def register(cfg, sess, drive: dict):
    """Deliberately not implemented as an automatic action.

    NIT placement policy makes bulk auto-registration genuinely dangerous:
    at most institutes a single offer removes you from the pool for everything
    that follows, and registering for a drive you then skip is a debarment
    offence. A bot that signs you up for the first eligible 12 LPA company can
    cost you the whole season.

    To wire up one-tap registration: run scripts/tpo_probe.py, open a drive's
    registration page, and copy the form's field names and POST target into
    the tpo block of profile.yaml. Then fill this in. Keep it button-driven.
    """
    raise NotImplementedError("TPO registration is intentionally manual")
