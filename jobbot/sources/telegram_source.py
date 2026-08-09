"""Reads the job channels you are already a member of.

Uses your own Telegram account (Telethon + a saved session string), because
most Indian off-campus job channels do not allow bots to read history.
"""
import datetime as dt

from .. import llm

EXTRACT_SYSTEM = """You extract job postings from messages in a Telegram jobs channel.

Return ONLY a JSON array, no fences. One object per distinct posting:
[{"title": "...", "company": "...", "location": "...", "url": "...", "description": "..."}]

Rules:
- If a message is not a job posting (chatter, ads, course promotions,
  "DM me for referral" with no role), skip it entirely.
- url: use the apply link in the message. Empty string if none.
- description: keep the eligibility, batch year, stack and salary lines.
- Return [] if there is nothing to extract."""


def collect(cfg, hours: int = 6, per_channel: int = 40) -> list[dict]:
    channels = cfg.sources.get("telegram_channels", []) or []
    if not (channels and cfg.tg_session and cfg.tg_api_id and cfg.tg_api_hash):
        return []

    try:
        from telethon.sessions import StringSession
        from telethon.sync import TelegramClient
    except ImportError:
        print("[telegram] telethon not installed")
        return []

    since = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    blobs: list[str] = []
    try:
        with TelegramClient(StringSession(cfg.tg_session), int(cfg.tg_api_id), cfg.tg_api_hash) as client:
            for ch in channels:
                try:
                    for msg in client.iter_messages(ch, limit=per_channel):
                        if msg.date < since:
                            break
                        if msg.text and len(msg.text) > 60:
                            blobs.append(f"[{ch}]\n{msg.text[:1500]}")
                except Exception as exc:  # noqa: BLE001
                    print(f"[telegram] {ch}: {exc}")
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] session failed: {exc}")
        return []

    if not blobs:
        return []

    jobs: list[dict] = []
    # Batch messages so we make a handful of API calls, not one per message.
    for i in range(0, len(blobs), 12):
        chunk = "\n\n---\n\n".join(blobs[i:i + 12])
        try:
            text = llm.complete(cfg, EXTRACT_SYSTEM, chunk, max_tokens=3000)
            for j in llm.json_arr(text):
                j["source"] = "telegram"
                jobs.append(j)
        except Exception as exc:  # noqa: BLE001
            print(f"[telegram] extraction failed: {exc}")
    return jobs
