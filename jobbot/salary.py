"""Compensation gate.

Order of trust:
  1. Base stated in the posting            -> use it
  2. Only CTC stated                       -> derive an approximate base
  3. Nothing stated                        -> look it up on the web
  4. Web lookup inconclusive               -> ask the company directly

Indian postings routinely quote CTC, which folds in variable pay, joining
bonus and sometimes ESOP paper value. A 15 LPA CTC can be an 11 LPA base.
Since the floor here is on BASE, CTC figures get discounted before comparison.
"""
from . import llm

LOOKUP_SYSTEM = """You research what a specific role at a specific company actually pays in India.

Search the web. Prefer, in this order: Levels.fyi, AmbitionBox, Glassdoor India,
Blind, and recent Reddit/Twitter offer posts. Ignore job-board "estimated salary"
widgets — those are algorithmic guesses, not data.

Report FIXED BASE salary in LPA (lakhs per annum), not CTC. If a source gives
CTC, subtract the variable and stock components to estimate base.

Return ONLY JSON, no fences:
{
  "base_lpa_low": <number>,
  "base_lpa_high": <number>,
  "confidence": "high" | "medium" | "low",
  "basis": "<max 18 words: what you actually found, e.g. '9 Levels.fyi entries for this exact title, 2024-2025'>",
  "sources": ["<domain>", "..."]
}

confidence rules:
- "high": multiple recent data points for this company AND this seniority.
- "medium": data for the company but a different level, or a close peer company.
- "low": only broad industry averages, or nothing specific found. Say so honestly
  in basis rather than inventing a number.

Never guess to look helpful. "low" is a correct answer."""


def lookup(cfg, job: dict) -> dict:
    """Web-search what this role pays. Costs a few cents, so callers should
    only invoke it for postings that already passed the fit screen."""
    query = (
        f"Company: {job.get('company','')}\n"
        f"Role: {job.get('title','')}\n"
        f"Location: {job.get('location','India')}\n"
        f"Seniority: entry level / fresher, 0-2 years experience\n\n"
        f"What is the fixed base salary in LPA for this role?"
    )
    try:
        # search=True maps to Anthropic web_search or Gemini Google Search
        # grounding, depending on the provider.
        text = llm.complete(cfg, LOOKUP_SYSTEM, query, max_tokens=1500,
                            heavy=True, search=True)
        out = llm.json_obj(text)
        if not out:
            return {"confidence": "low", "basis": "no parseable result", "sources": []}
        out.setdefault("sources", [])
        out.setdefault("basis", "")
        return out
    except Exception as exc:  # noqa: BLE001
        return {"confidence": "low", "basis": f"lookup failed: {exc}", "sources": []}


def gate(cfg, job: dict, verdict: dict) -> dict:
    """Decide whether this posting clears the base-salary floor.

    status:
      "pass"    -> meets the floor on stated figures. Auto-apply allowed.
      "likely"  -> meets it on a web estimate. Alert only, no auto-apply.
      "fail"    -> below the floor. Dropped.
      "unknown" -> could not establish. Offers to ask the company.
    """
    floor = float(cfg.criteria.get("min_base_lpa", 0))
    if floor <= 0:
        return {"status": "pass", "label": "no salary floor set", "auto_ok": True}

    comp_type = (verdict.get("comp_type") or "unknown").lower()
    low = verdict.get("salary_lpa_low")
    high = verdict.get("salary_lpa_high")

    # --- 1 & 2: the posting told us something -----------------------------
    if comp_type in {"base", "ctc"} and isinstance(low, (int, float)) and low > 0:
        if comp_type == "ctc":
            ratio = float(cfg.criteria.get("ctc_to_base_ratio", 0.85))
            low, high = low * ratio, (high or low) * ratio
            note = f"~{low:.1f}L base derived from {verdict['salary_lpa_low']}L CTC"
        else:
            note = f"{low:.0f}–{high:.0f}L base stated" if high and high != low else f"{low:.0f}L base stated"

        if low >= floor:
            return {"status": "pass", "label": note, "auto_ok": True, "base_lpa": low}
        return {"status": "fail", "label": f"{note}, below {floor:.0f}L floor", "auto_ok": False}

    # --- 3: nothing stated, go look --------------------------------------
    est = lookup(cfg, job)
    conf = (est.get("confidence") or "low").lower()
    e_low = est.get("base_lpa_low")
    e_high = est.get("base_lpa_high") or e_low
    srcs = ", ".join(est.get("sources", [])[:3])

    if conf in {"high", "medium"} and isinstance(e_low, (int, float)):
        label = f"est. {e_low:.0f}–{e_high:.0f}L base ({conf} confidence"
        label += f", {srcs})" if srcs else ")"

        if e_high < floor:
            return {"status": "fail", "label": f"{label} — under floor", "auto_ok": False}

        # Only auto-apply on an estimate when it clears the floor with room to
        # absorb the error bar. Otherwise you interview for a 9L job.
        buffer = float(cfg.criteria.get("estimate_buffer_lpa", 2))
        auto_ok = conf == "high" and e_low >= floor + buffer
        return {
            "status": "likely", "label": label, "auto_ok": auto_ok,
            "base_lpa": e_low, "basis": est.get("basis", ""),
        }

    # --- 4: genuinely unknown --------------------------------------------
    return {
        "status": "unknown",
        "label": f"salary not stated, web search inconclusive ({est.get('basis','')})",
        "auto_ok": False,
    }
