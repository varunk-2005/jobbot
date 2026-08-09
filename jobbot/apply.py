"""The only two things this bot will ever submit without asking you.

CASE A — a human emailed you and asked for your CV. Reply on that thread with
         the resume attached.
CASE B — a posting scored above your auto-apply threshold AND lists a plain
         application email address. Send the CV plus a short cover note.

Everything else (LinkedIn Easy Apply, ATS web forms, anything behind a login)
is deliberately NOT automated. Those platforms fingerprint automated
submissions and quietly discard them, so a bot that "applies" to 200 ATS
forms is really a bot that applies to zero while you believe otherwise.
"""
import base64
import mimetypes
import re
from email.message import EmailMessage

from . import match

EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# Addresses that are never a hiring inbox.
BAD_MAILBOX = re.compile(
    r"^(no-?reply|donot-?reply|support|help|info|privacy|legal|billing|"
    r"newsletter|marketing|sales|abuse|postmaster|admin|webmaster)@", re.I
)

FREE_DOMAINS = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "rediffmail.com"}


def find_apply_email(job: dict) -> str | None:
    blob = f"{job.get('description','')} {job.get('url','')}"
    for addr in EMAIL_RE.findall(blob):
        if BAD_MAILBOX.match(addr):
            continue
        # A "company" hiring from a personal Gmail is the classic fake-consultancy
        # pattern in the Indian fresher market. Never auto-apply to those.
        if addr.split("@")[-1].lower() in FREE_DOMAINS:
            continue
        return addr
    return None


def _build_message(cfg, to_addr: str, subject: str, body: str,
                   in_reply_to: str | None = None) -> dict:
    msg = EmailMessage()
    msg["To"] = to_addr
    msg["From"] = f"{cfg.identity['name']} <{cfg.identity['email']}>"
    msg["Subject"] = subject
    if in_reply_to:
        msg["In-Reply-To"] = in_reply_to
        msg["References"] = in_reply_to

    sig = (
        f"\n\n{cfg.identity['name']}\n"
        f"{cfg.identity.get('phone','')}\n"
        f"{cfg.identity.get('linkedin','')}\n"
        f"{cfg.identity.get('github','')}"
    )
    msg.set_content(body.rstrip() + sig)

    path = cfg.resume_path
    if path.exists():
        ctype, _ = mimetypes.guess_type(str(path))
        maintype, subtype = (ctype or "application/pdf").split("/", 1)
        msg.add_attachment(
            path.read_bytes(), maintype=maintype, subtype=subtype,
            filename=f"{cfg.identity['name'].replace(' ', '_')}_Resume{path.suffix}",
        )
    return {"raw": base64.urlsafe_b64encode(msg.as_bytes()).decode()}


def _send(cfg, gmail_svc, payload: dict, thread_id: str | None = None):
    if thread_id:
        payload["threadId"] = thread_id
    return gmail_svc.users().messages().send(userId="me", body=payload).execute()


# --- CASE A -----------------------------------------------------------------
def reply_with_cv(cfg, gmail_svc, state, msg: dict) -> tuple[bool, str]:
    if msg.get("is_scam"):
        return False, "flagged as scam"
    if not msg.get("wants_cv"):
        return False, "no explicit CV request"
    if msg["thread_id"] in state.data["replied_threads"]:
        return False, "already replied"
    if re.search(r"no-?reply|donotreply", msg.get("from", ""), re.I):
        return False, "automated sender"
    if state.applies_today() >= cfg.max_auto_applies_per_day:
        return False, "daily cap reached"

    body = (
        f"Hello,\n\nThank you for reaching out. My resume is attached.\n\n"
        f"I am a {cfg.identity.get('location','India')}-based computer science "
        f"graduate and would be glad to talk through the role at your "
        f"convenience.\n\nBest regards,"
    )
    subject = msg["subject"] if msg["subject"].lower().startswith("re:") else f"Re: {msg['subject']}"
    to_addr = EMAIL_RE.search(msg["from"])
    if not to_addr:
        return False, "no reply address"

    if cfg.dry_run:
        return False, "DRY_RUN — would have replied with CV"

    _send(cfg, gmail_svc, _build_message(cfg, to_addr.group(0), subject, body,
                                         in_reply_to=msg.get("message_id")),
          thread_id=msg["thread_id"])
    state.data["replied_threads"].append(msg["thread_id"])
    return True, f"replied to {to_addr.group(0)}"


# --- CASE B -----------------------------------------------------------------
def ask_salary(cfg, gmail_svc, state, job: dict, jid: str) -> tuple[bool, str]:
    """Email the company for the base range when nothing else established it.

    Sent only on a button press, never automatically. Asking about pay before
    a company has shown interest reads as presumptuous to some Indian
    employers, so this stays a decision you make per role.
    """
    to_addr = find_apply_email(job)
    if not to_addr:
        return False, "no contact email in posting"

    body = (
        f"Hello,\n\n"
        f"I am interested in the {job.get('title','role')} position and plan to apply.\n\n"
        f"Before I do, could you share the fixed base salary range for this role? "
        f"I want to be sure the position is a fit on both sides before taking up "
        f"your team's time.\n\n"
        f"Happy to send my resume across straight away either way.\n\n"
        f"Thank you,"
    )
    subject = f"Base salary range — {job.get('title','role')}"

    if cfg.dry_run:
        return False, f"DRY_RUN — would have asked {to_addr}"

    _send(cfg, gmail_svc, _build_message(cfg, to_addr, subject, body))
    return True, f"asked {to_addr} for the base range"


def email_application(cfg, gmail_svc, state, job: dict, jid: str,
                      verdict: dict, pay=None) -> tuple[bool, str]:
    if verdict.get("is_scam"):
        return False, "flagged as scam"
    if verdict["score"] < cfg.criteria["auto_apply_threshold"]:
        return False, "below auto-apply threshold"
    if pay is not None and not pay.get("auto_ok"):
        return False, f"salary gate: {pay.get('label','not cleared')}"
    if state.has_applied(jid):
        return False, "already applied"
    if state.applies_today() >= cfg.max_auto_applies_per_day:
        return False, "daily cap reached"

    to_addr = find_apply_email(job)
    if not to_addr:
        return False, "no application email in posting"

    if not cfg.resume_path.exists():
        return False, "resume file missing"

    body = match.cover_letter(cfg, job)
    subject = f"Application: {job.get('title','Software Engineer')} — {cfg.identity['name']}"

    if cfg.dry_run:
        return False, f"DRY_RUN — would have emailed {to_addr}"

    _send(cfg, gmail_svc, _build_message(cfg, to_addr, subject, body))
    state.mark_applied(jid, "email", to_addr)
    return True, f"applied via email to {to_addr}"
