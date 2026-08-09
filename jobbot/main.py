"""Entry point. One cron tick = one run of this file."""
import argparse
import sys
import time

from . import apply as apply_mod
from . import match, notify, salary
from .config import Config
from .sources import boards, gmail_source, telegram_source, tpo
from .state import State, job_id


def handle_buttons(cfg, state, gmail_svc):
    for ev in notify.fetch_callbacks(cfg, state):
        jid, action = ev["job_id"], ev["action"]
        job = state.data["pending"].get(jid)
        if action == "mute" and job:
            state.ignore_company(job.get("company", ""))
            notify.send(cfg, f"🔕 Muted <b>{job.get('company')}</b>.")
        elif action == "done":
            state.mark_applied(jid, "manual", (job or {}).get("url", ""))
            notify.send(cfg, "✅ Logged as applied.")
        elif action == "askpay" and job:
            if not gmail_svc:
                notify.send(cfg, "Gmail is not connected, so I cannot send that.")
            else:
                ok, why = apply_mod.ask_salary(cfg, gmail_svc, state, job, jid)
                notify.send(cfg, f"{'💬 Asked them.' if ok else '⚠️'} {why}")
        elif action == "draft" and job:
            letter = match.cover_letter(cfg, job)
            addr = apply_mod.find_apply_email(job) or "(use the apply link)"
            notify.send(
                cfg,
                f"✍️ <b>Draft for {job.get('title')} at {job.get('company')}</b>\n"
                f"Send to: <code>{addr}</code>\n\n<pre>{letter}</pre>",
            )


def check_tpo(cfg, state) -> None:
    """Campus drives. Same salary floor as everything else.

    Below the floor gets dropped. Unstated pay does NOT get dropped — it goes
    through the same web lookup as job-board postings, because portals list a
    company without a number all the time and that is not evidence of low pay.
    """
    if not (cfg.sources.get("tpo") and cfg.tpo_username):
        return
    sess = tpo.login(cfg)
    if not sess:
        notify.send(cfg, "⚠️ Could not log in to the TPO portal. Password changed?")
        return

    drives = tpo.fetch_drives(cfg, sess)
    print(f"[tpo] {len(drives)} drives on portal")
    filtered = []

    for d in drives:
        jid = "tpo-" + job_id(d)
        if not state.is_new(jid):
            continue
        state.mark_seen(jid)

        # Reuse the exact salary logic the job boards use, so base-vs-CTC and
        # the web lookup behave identically everywhere.
        if isinstance(d.get("base_lpa"), (int, float)) and d["base_lpa"]:
            verdict = {"comp_type": "base", "salary_lpa_low": d["base_lpa"],
                       "salary_lpa_high": d["base_lpa"]}
        elif isinstance(d.get("ctc_lpa"), (int, float)) and d["ctc_lpa"]:
            verdict = {"comp_type": "ctc", "salary_lpa_low": d["ctc_lpa"],
                       "salary_lpa_high": d["ctc_lpa"]}
        else:
            verdict = {"comp_type": "unknown", "salary_lpa_low": None}

        pay = salary.gate(cfg, d, verdict)
        print(f"[tpo] {d.get('company','')[:30]}: {pay['status']} — {pay['label']}")

        if pay["status"] == "fail":
            filtered.append(f"{d.get('company','?')} ({pay['label']})")
            continue

        ok, why = tpo.eligibility(cfg, d)
        notify.tpo_alert(cfg, d, ok, why, pay=pay)
        time.sleep(0.6)

    # A one-line receipt so a filter that is set too high is visible to you
    # rather than silently eating the season. Set tpo_filter_receipt: false
    # in profile.yaml to turn it off.
    if filtered and cfg.criteria.get("tpo_filter_receipt", True):
        notify.send(
            cfg,
            f"🔇 Filtered {len(filtered)} campus drive(s) under your "
            f"{cfg.criteria['min_base_lpa']}L base floor:\n· " + "\n· ".join(filtered[:8]),
        )


def run(cfg, state, once_limit: int | None = None) -> None:
    gmail_svc = None
    if cfg.gmail_refresh_token:
        try:
            gmail_svc = gmail_source.service(cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[gmail] auth failed: {exc}")

    handle_buttons(cfg, state, gmail_svc)

    # Campus first — these have deadlines that do not move.
    try:
        check_tpo(cfg, state)
    except Exception as exc:  # noqa: BLE001
        print(f"[tpo] cycle failed: {exc}")

    # ---- gather -----------------------------------------------------------
    jobs = boards.collect(cfg)
    print(f"[collect] boards: {len(jobs)}")

    tg = telegram_source.collect(cfg)
    print(f"[collect] telegram: {len(tg)}")
    jobs += tg

    mail_jobs, personal = gmail_source.collect(cfg, state)
    print(f"[collect] gmail postings: {len(mail_jobs)}, personal: {len(personal)}")
    jobs += mail_jobs

    # ---- "your name came up" ---------------------------------------------
    for msg in personal:
        notify.personal_alert(cfg, msg)
        if gmail_svc and not msg.get("is_scam"):
            ok, why = apply_mod.reply_with_cv(cfg, gmail_svc, state, msg)
            print(f"[reply] {msg['subject'][:50]}: {why}")
            if ok:
                notify.send(cfg, "📎 Sent your CV on that thread.")

    # ---- score and alert --------------------------------------------------
    fresh = []
    for job in jobs:
        jid = job_id(job)
        if not state.is_new(jid):
            continue
        if state.is_ignored(job.get("company", "")):
            state.mark_seen(jid)
            continue
        if not match.prefilter(cfg, job):
            state.mark_seen(jid)
            continue
        fresh.append((jid, job))

    if once_limit:
        fresh = fresh[:once_limit]
    print(f"[screen] {len(fresh)} new postings to score")

    alerted = 0
    for jid, job in fresh:
        verdict = match.screen(cfg, job)
        state.mark_seen(jid)

        if verdict.get("is_scam"):
            notify.send(
                cfg,
                f"⚠️ <b>Scam-flagged posting skipped</b>\n{job.get('title')} — "
                f"{job.get('company')}\n{verdict.get('scam_reason')}",
            )
            continue

        if verdict["score"] < cfg.criteria["min_score"]:
            continue
        if verdict.get("experience_required", 0) > cfg.criteria["max_experience_years"]:
            continue

        # Salary gate runs only after the fit screen passes, so the web
        # lookups cost cents a day rather than dollars.
        pay = salary.gate(cfg, job, verdict)
        print(f"[pay] {job.get('title','')[:40]}: {pay['status']} — {pay['label']}")
        if pay["status"] == "fail":
            continue
        if pay["status"] == "unknown" and \
                cfg.criteria.get("unknown_salary_action") == "skip":
            continue

        applied = False
        if gmail_svc:
            applied, why = apply_mod.email_application(
                cfg, gmail_svc, state, job, jid, verdict, pay=pay
            )
            print(f"[apply] {job.get('title','')[:40]}: {why}")

        state.data["pending"][jid] = job
        notify.job_alert(cfg, job, jid, verdict, auto_applied=applied, pay=pay)
        alerted += 1
        time.sleep(0.6)  # stay under Telegram's rate limit

    print(f"[done] alerted on {alerted} roles, {state.applies_today()} auto-applies today")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None, help="cap postings scored this run")
    ap.add_argument("--check", action="store_true", help="verify config and exit")
    args = ap.parse_args()

    cfg = Config()
    missing = cfg.missing_secrets()
    if missing:
        print(f"Missing required secrets: {', '.join(missing)}")
        return 1

    if args.check:
        notify.send(cfg, "✅ jobbot is configured correctly and can reach you.")
        print(f"resume present: {cfg.resume_path.exists()}")
        print(f"dry_run: {cfg.dry_run}")
        return 0

    state = State()
    try:
        run(cfg, state, once_limit=args.limit)
    finally:
        state.save()
    return 0


if __name__ == "__main__":
    sys.exit(main())
