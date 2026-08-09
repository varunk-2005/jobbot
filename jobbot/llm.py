"""One LLM interface, two backends.

Set LLM_PROVIDER=gemini to run the whole bot on a free Google AI Studio key.
Everything else in the codebase calls complete() and does not care which.

Free-tier Gemini has hard daily request caps, so this module throttles calls
to stay under the per-minute limit and backs off on 429 rather than dying.
"""
import json
import os
import re
import time

_JSON_OBJ = re.compile(r"\{.*\}", re.S)
_JSON_ARR = re.compile(r"\[.*\]", re.S)

_last_call = [0.0]      # module-level clock for throttling
_calls_made = [0]


class LLMError(Exception):
    pass


def _throttle(cfg) -> None:
    gap = cfg.llm_min_interval
    if gap <= 0:
        return
    wait = gap - (time.time() - _last_call[0])
    if wait > 0:
        time.sleep(wait)
    _last_call[0] = time.time()


def calls_made() -> int:
    return _calls_made[0]


# --- Anthropic --------------------------------------------------------------
def _anthropic(cfg, model, system, user, max_tokens, search):
    import anthropic

    kwargs = dict(
        model=model, max_tokens=max_tokens, system=system,
        messages=[{"role": "user", "content": user}],
    )
    if search:
        kwargs["tools"] = [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]

    resp = anthropic.Anthropic(api_key=cfg.anthropic_key).messages.create(**kwargs)
    return "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")


# --- Gemini -----------------------------------------------------------------
def _gemini(cfg, model, system, user, max_tokens, search):
    from google import genai
    from google.genai import types

    client = genai.Client(api_key=cfg.gemini_key)
    gc = types.GenerateContentConfig(
        system_instruction=system,
        max_output_tokens=max_tokens,
        temperature=0.2,
    )
    if search:
        # Google Search grounding — the equivalent of Anthropic's web_search.
        gc.tools = [types.Tool(google_search=types.GoogleSearch())]

    resp = client.models.generate_content(model=model, contents=user, config=gc)
    return resp.text or ""


_BACKENDS = {"anthropic": _anthropic, "gemini": _gemini}


def complete(cfg, system: str, user: str, max_tokens: int = 1000,
             heavy: bool = False, search: bool = False) -> str:
    """heavy=True picks the stronger model (cover letters, salary research)."""
    backend = _BACKENDS.get(cfg.llm_provider)
    if not backend:
        raise LLMError(f"unknown LLM_PROVIDER: {cfg.llm_provider}")

    model = cfg.write_model if heavy else cfg.screen_model
    delay = 4.0

    for attempt in range(4):
        _throttle(cfg)
        try:
            _calls_made[0] += 1
            return backend(cfg, model, system, user, max_tokens, search)
        except Exception as exc:  # noqa: BLE001
            msg = str(exc).lower()
            transient = any(k in msg for k in
                            ("429", "rate", "quota", "exhaust", "overload", "503", "500", "timeout"))
            if not transient or attempt == 3:
                raise LLMError(str(exc)) from exc
            # A daily quota is not going to clear in 30 seconds. Give up early.
            if "daily" in msg or "per day" in msg or "rpd" in msg:
                raise LLMError(f"daily quota exhausted: {exc}") from exc
            print(f"[llm] {type(exc).__name__}, retrying in {delay:.0f}s")
            time.sleep(delay)
            delay *= 2
    raise LLMError("unreachable")


# --- parsing helpers shared by every caller ---------------------------------
def json_obj(text: str, default=None):
    m = _JSON_OBJ.search(text or "")
    if not m:
        return default
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return default


def json_arr(text: str, default=None):
    m = _JSON_ARR.search(text or "")
    if not m:
        return default if default is not None else []
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return default if default is not None else []
