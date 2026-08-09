"""Outbound alerts + inline buttons.

There is no long-running process, so button presses are collected on the next
cron tick via getUpdates. Telegram queues them for 24h, which is plenty.
"""
import html

import requests

API = "https://api.telegram.org/bot{token}/{method}"
TIMEOUT = 20


def _call(cfg, method: str, **payload):
    try:
        r = requests.post(
            API.format(token=cfg.telegram_bot_token, method=method),
            json=payload, timeout=TIMEOUT,
        )
        return r.json()
    except Exception as exc:  # noqa: BLE001
        print(f"[telegram] {method} failed: {exc}")
        return {"ok": False}


def _esc(s) -> str:
    return html.escape(str(s or ""))


def send(cfg, text: str, buttons: list[list[dict]] | None = None):
    payload = {
        "chat_id": cfg.telegram_chat_id,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    if buttons:
        payload["reply_markup"] = {"inline_keyboard": buttons}
    return _call(cfg, "sendMessage", **payload)


_PAY_ICON = {"pass": "💰", "likely": "≈", "unknown": "❓"}


def job_alert(cfg, job: dict, jid: str, verdict: dict, auto_applied: bool = False,
              pay: dict | None = None):
    bar = "🟢" if verdict["score"] >= 85 else "🟡"
    lines = [
        f"{bar} <b>{_esc(job.get('title'))}</b>",
        f"{_esc(job.get('company'))} · {_esc(job.get('location') or 'location n/a')}",
        f"<b>{verdict['score']}/100</b> — {_esc(verdict.get('reason'))}",
    ]
    if pay:
        icon = _PAY_ICON.get(pay.get("status"), "")
        lines.append(f"{icon} {_esc(pay.get('label'))}")
    lines.append(f"<i>via {_esc(job.get('source'))}</i>")

    if auto_applied:
        lines.append("\n✅ <b>Applied automatically.</b>")
    text = "\n".join(lines)

    buttons = []
    row = []
    if job.get("url"):
        row.append({"text": "Open posting", "url": job["url"]})
    if not auto_applied:
        row.append({"text": "Draft email", "callback_data": f"draft:{jid}"})
    if row:
        buttons.append(row)

    if pay and pay.get("status") == "unknown" and \
            cfg.criteria.get("unknown_salary_action") == "ask":
        buttons.append([{"text": "💬 Ask them the base", "callback_data": f"askpay:{jid}"}])

    buttons.append([
        {"text": "Mark applied", "callback_data": f"done:{jid}"},
        {"text": "Mute company", "callback_data": f"mute:{jid}"},
    ])
    return send(cfg, text, buttons)


def tpo_alert(cfg, drive: dict, eligible: bool, why: str, pay: dict | None = None):
    """Campus drive card. Only reached if the drive cleared the salary floor."""
    head = "🎓" if eligible else "🔒"
    lines = [
        f"{head} <b>CAMPUS DRIVE — {_esc(drive.get('company'))}</b>",
        f"{_esc(drive.get('title') or 'Role not stated')}",
    ]
    if drive.get("ctc_text"):
        lines.append(f"💰 {_esc(drive['ctc_text'])}")
    if pay:
        icon = _PAY_ICON.get(pay.get("status"), "")
        lines.append(f"{icon} {_esc(pay.get('label'))}")
    if drive.get("min_cgpa"):
        lines.append(f"CGPA cutoff: {_esc(drive['min_cgpa'])}")
    if drive.get("eligible_branches"):
        lines.append(f"Branches: {_esc(drive['eligible_branches'])}")
    if drive.get("deadline"):
        lines.append(f"⏰ <b>Deadline: {_esc(drive['deadline'])}</b>")
    if drive.get("notes"):
        lines.append(f"<i>{_esc(drive['notes'])}</i>")
    if not eligible:
        lines.append(f"\n🔒 <b>Not eligible</b> — {_esc(why)}")
    else:
        lines.append("\n👉 <b>Register on the portal yourself.</b>")

    buttons = [[{"text": "Open TPO portal", "url": drive.get("url", cfg.sources['tpo']['base_url'])}]]
    return send(cfg, "\n".join(lines), buttons)
    if msg.get("is_scam"):
        text = (
            "⚠️ <b>Likely scam — do not reply</b>\n"
            f"From: {_esc(msg['from'])}\n"
            f"Subject: {_esc(msg['subject'])}\n\n"
            f"{_esc(msg.get('scam_reason'))}"
        )
        return send(cfg, text)

    icon = "🔔" if msg["urgency"] == "high" else "📩"
    text = (
        f"{icon} <b>{_esc(msg['headline'])}</b>\n"
        f"From: {_esc(msg['from'])}\n"
        f"Subject: {_esc(msg['subject'])}\n\n"
        f"{_esc(msg['body'][:400])}…"
    )
    buttons = [[{
        "text": "Open in Gmail",
        "url": f"https://mail.google.com/mail/u/0/#inbox/{msg['thread_id']}",
    }]]
    return send(cfg, text, buttons)


def fetch_callbacks(cfg, state) -> list[dict]:
    """Drain queued button presses since the last run."""
    offset = state.data.get("last_telegram_update_id", 0) + 1
    data = _call(cfg, "getUpdates", offset=offset, timeout=0, allowed_updates=["callback_query"])
    events = []
    for upd in data.get("result", []) or []:
        state.data["last_telegram_update_id"] = max(
            state.data["last_telegram_update_id"], upd["update_id"]
        )
        cq = upd.get("callback_query")
        if not cq:
            continue
        _call(cfg, "answerCallbackQuery", callback_query_id=cq["id"])
        action, _, jid = (cq.get("data") or "").partition(":")
        if action and jid:
            events.append({"action": action, "job_id": jid})
    return events
