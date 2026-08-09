"""Reads Gmail for two different things:

1. Job-alert emails (LinkedIn, Naukri, Instahyre...) -> extract the postings.
   This is how LinkedIn jobs get in without scraping LinkedIn.
2. Mail addressed to you personally -> recruiter outreach, shortlists,
   interview invites, assessments. These are the "my name came up" alerts.
"""
import base64
import re

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from .. import llm

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

CLASSIFY_SYSTEM = """You read one email sent to a job-seeking candidate and classify it.

Return ONLY JSON, no fences:
{
  "kind": "personal" | "alert" | "noise",
  "urgency": "high" | "medium" | "low",
  "headline": "<max 12 words describing what this email is>",
  "wants_cv": <true only if a human is explicitly asking the candidate to send a resume/CV>,
  "is_scam": <true if fraud markers present>,
  "scam_reason": "<empty if false>",
  "jobs": [ {"title": "...", "company": "...", "location": "...", "url": "..."} ]
}

kind meanings:
- "personal": a human (recruiter, HR, hiring manager) is writing about THIS
  candidate specifically. Shortlist notices, interview invites, assessment
  links, offer discussions, direct outreach. urgency high.
- "alert": an automated digest of job postings. Fill "jobs" with every
  posting you can extract. Leave urgency low.
- "noise": newsletters, marketing, rejections with no action, anything else.

Fraud markers: any request for money, registration or training fees, security
deposits, Aadhaar/PAN/bank details before a written offer, or a "placement
consultancy" guaranteeing a job for a payment."""


def service(cfg):
    creds = Credentials(
        token=None,
        refresh_token=cfg.gmail_refresh_token,
        client_id=cfg.gmail_client_id,
        client_secret=cfg.gmail_client_secret,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _decode(part) -> str:
    data = part.get("body", {}).get("data")
    if not data:
        return ""
    return base64.urlsafe_b64decode(data.encode()).decode("utf-8", errors="replace")


def _body_text(payload) -> str:
    """Prefer text/plain; fall back to stripped HTML."""
    stack, plain, html_txt = [payload], [], []
    while stack:
        p = stack.pop()
        mime = p.get("mimeType", "")
        if mime == "text/plain":
            plain.append(_decode(p))
        elif mime == "text/html":
            html_txt.append(_decode(p))
        stack.extend(p.get("parts", []) or [])
    text = "\n".join(plain) or re.sub(r"<[^>]+>", " ", "\n".join(html_txt))
    return re.sub(r"\s+", " ", text).strip()[:8000]


def _header(msg, name: str) -> str:
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"].lower() == name.lower():
            return h["value"]
    return ""


def _classify(cfg, subject: str, sender: str, body: str) -> dict:
    try:
        text = llm.complete(
            cfg, CLASSIFY_SYSTEM,
            f"FROM: {sender}\nSUBJECT: {subject}\n\nBODY:\n{body}",
            max_tokens=1500,
        )
        return llm.json_obj(text, {"kind": "noise"})
    except Exception:  # noqa: BLE001
        return {"kind": "noise"}


def collect(cfg, state, limit: int = 40) -> tuple[list[dict], list[dict]]:
    """Returns (jobs_extracted_from_alerts, personal_messages)."""
    if not cfg.gmail_refresh_token:
        return [], []
    try:
        svc = service(cfg)
        listing = svc.users().messages().list(
            userId="me", q=cfg.sources.get("gmail_query", "newer_than:1d"), maxResults=limit
        ).execute()
    except Exception as exc:  # noqa: BLE001
        print(f"[gmail] listing failed: {exc}")
        return [], []

    jobs, personal = [], []
    for ref in listing.get("messages", []) or []:
        try:
            msg = svc.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        except Exception:  # noqa: BLE001
            continue
        if msg["id"] in state.data["replied_threads"]:
            continue

        subject = _header(msg, "Subject")
        sender = _header(msg, "From")
        body = _body_text(msg.get("payload", {}))
        if not body:
            continue

        verdict = _classify(cfg, subject, sender, body)
        kind = verdict.get("kind", "noise")

        if kind == "alert":
            for j in verdict.get("jobs", []) or []:
                j.setdefault("description", "")
                j["source"] = "gmail-alert"
                jobs.append(j)
        elif kind == "personal":
            personal.append({
                "message_id": msg["id"],
                "thread_id": msg["threadId"],
                "subject": subject,
                "from": sender,
                "headline": verdict.get("headline", subject),
                "urgency": verdict.get("urgency", "medium"),
                "wants_cv": bool(verdict.get("wants_cv")),
                "is_scam": bool(verdict.get("is_scam")),
                "scam_reason": verdict.get("scam_reason", ""),
                "body": body[:1500],
            })
    return jobs, personal
