"""Scoring postings against the profile, and drafting application text."""
from . import llm

SCREEN_SYSTEM = """You screen job postings for a specific candidate. You are strict.

Return ONLY a JSON object, no prose, no markdown fences:
{
  "score": <0-100 fit>,
  "reason": "<one sentence, max 20 words, why it does or doesn't fit>",
  "experience_required": <integer years the posting demands, 0 if fresher-friendly>,
  "comp_type": "base" | "ctc" | "unknown",
  "salary_lpa_low": <number or null>,
  "salary_lpa_high": <number or null>,
  "is_scam": <true if it shows fraud markers>,
  "scam_reason": "<empty string if is_scam is false>"
}

Compensation extraction rules:
- Report figures in LPA (lakhs per annum). Convert: "₹1,20,000/month" -> 14.4.
  Monthly stipends for internships are NOT annual salary; use comp_type "unknown"
  unless the posting states the converted full-time figure.
- comp_type "base" only when the posting says base, fixed, or in-hand.
  If it says CTC, package, or total compensation, use "ctc".
  If no number appears at all, use "unknown" and set both figures to null.
- Never infer a number from the company's reputation. Only what the text says.

Scoring guidance:
- 90-100: near-perfect match, candidate clearly qualifies, should apply today.
- 75-89: good match, minor gaps the candidate can bridge.
- 50-74: plausible but a stretch or a partial mismatch on stack/location.
- 0-49: wrong seniority, wrong domain, or requires experience they lack.

Penalise heavily: roles demanding more years than the candidate has, roles
that are not actually engineering, and locations the candidate excluded.

Fraud markers that make is_scam true: asking the applicant for money,
registration/training/security-deposit fees, requests for Aadhaar/PAN/bank
details before an offer, unnamed "MNC client" with a personal Gmail contact,
guaranteed-placement language, or salary wildly above market for a fresher.
"""

COVER_SYSTEM = """You write short, plain application emails for a candidate.

Rules:
- 90-130 words. No more.
- No "I am writing to express my interest". No "I am confident that".
- Open with the single most relevant concrete thing the candidate has built.
- One sentence connecting it to what the role needs.
- Close with one plain line offering to talk.
- No em dashes. No bullet points. No subject line in the body.
Return only the email body text."""


def _posting_blob(job: dict) -> str:
    return (
        f"TITLE: {job.get('title','')}\n"
        f"COMPANY: {job.get('company','')}\n"
        f"LOCATION: {job.get('location','')}\n"
        f"SOURCE: {job.get('source','')}\n"
        f"DESCRIPTION:\n{(job.get('description') or '')[:4000]}"
    )


def screen(cfg, job: dict) -> dict:
    """Score one posting. Fails soft — a bad API call never kills the run."""
    prompt = (
        f"CANDIDATE PROFILE:\n{cfg.background}\n\n"
        f"PREFERRED LOCATIONS: {', '.join(cfg.criteria['locations'])}\n"
        f"MAX YEARS EXPERIENCE ACCEPTABLE: {cfg.criteria['max_experience_years']}\n\n"
        f"JOB POSTING:\n{_posting_blob(job)}"
    )
    try:
        text = llm.complete(cfg, SCREEN_SYSTEM, prompt, max_tokens=500)
        out = llm.json_obj(text)
        if not out:
            return {"score": 0, "reason": "unparseable model response", "is_scam": False}
        out.setdefault("is_scam", False)
        out.setdefault("scam_reason", "")
        out.setdefault("experience_required", 0)
        out.setdefault("comp_type", "unknown")
        out.setdefault("salary_lpa_low", None)
        out.setdefault("salary_lpa_high", None)
        out["score"] = int(out.get("score", 0))
        return out
    except Exception as exc:  # noqa: BLE001
        return {"score": 0, "reason": f"screen failed: {exc}", "is_scam": False}


def cover_letter(cfg, job: dict) -> str:
    prompt = (
        f"CANDIDATE:\n{cfg.background}\n\n"
        f"CANDIDATE NAME: {cfg.identity['name']}\n\n"
        f"ROLE THEY ARE APPLYING TO:\n{_posting_blob(job)}"
    )
    try:
        return llm.complete(cfg, COVER_SYSTEM, prompt, max_tokens=700, heavy=True).strip()
    except Exception as exc:  # noqa: BLE001
        return f"(cover letter generation failed: {exc})"


def prefilter(cfg, job: dict) -> bool:
    """Cheap local filter so Claude only sees plausible postings."""
    title = (job.get("title") or "").lower()
    if not title:
        return False
    if any(bad in title for bad in cfg.criteria["titles_exclude"]):
        return False
    if not any(good in title for good in cfg.criteria["titles_include"]):
        return False
    loc = (job.get("location") or "").lower()
    if loc and not any(l.lower() in loc for l in cfg.criteria["locations"]):
        return False
    return True
