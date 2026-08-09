# jobbot

Watches Gmail, Telegram job channels and public company job boards. Scores every
posting against your profile with Claude. Pings you on Telegram for the ones worth
your time, and applies by itself in the two narrow cases where that actually works.

Runs on GitHub Actions every 30 minutes. No server, no cost beyond a few cents a
day of Claude API usage.

---

## What it does automatically, and what it refuses to

**Applies on its own:**

1. A human emails you asking for your CV → replies on that thread with your resume attached.
2. A posting scores ≥ 85 **and** lists a real company application email → sends your resume with a short tailored cover note.

**Deliberately does not:** LinkedIn Easy Apply, Naukri quick-apply, or any ATS web
form. Those platforms fingerprint automated submissions and silently drop them, so
a bot that "applies" to 200 forms is really a bot that applies to zero while you
sit back believing otherwise. Automating LinkedIn also risks your account, which is
the one asset you cannot replace mid-search.

For those, you get a Telegram card with the score, the reason, an **Open posting**
button and a **Draft email** button that writes the cover letter for you. Roughly
fifteen seconds per application, and you keep the veto.

---

## Campus drives (TPO portal)

The most important source here, and the one with the hardest deadlines.

Campus drives are held to the **same 12L base floor** as everything else.
Below it, they get dropped. A 9 LPA CTC service-company drive resolves to
~7.6L base and never reaches you.

Unstated pay is not treated as low pay. Portals list a company without a
number constantly, so those go through the same web lookup as job-board
postings rather than getting dropped.

What survives the filter gets its own card, labelled rather than pre-judged:

- 🎓 eligible, with the CGPA cutoff, branches, deadline and the pay verdict
- 🔒 not eligible, with the reason — *needs 8.0 CGPA, you have 7.2* or *batch 2026 only*

You also get one short receipt message listing what the floor filtered out
that day. Not a second chance at those drives — just so a floor set too high
shows up as a visible line instead of a quiet inbox. Turn it off with
`tpo_filter_receipt: false`.

**It does not register you.** That is a deliberate refusal, not a missing
feature. NIT placement policy is unforgiving: at most institutes one offer
pulls you out of the pool for everything after it, and registering for a drive
you then skip is a debarment offence. A bot that signs you up for the first
eligible 12 LPA company on the calendar can cost you the entire season. That
decision needs a human who knows what else is coming.

### Setup

Credentials go in GitHub secrets as `TPO_USERNAME` and `TPO_PASSWORD`. Never in
`profile.yaml` — that file gets committed.

Then run the probe locally, on college wifi or VPN if the portal is internal:

```bash
export TPO_USERNAME=20233581
export TPO_PASSWORD='your-new-password'
python scripts/tpo_probe.py
```

It confirms login, prints the login form's real field names, tries eight likely
listing URLs and tells you which ones have content. Copy those into
`listing_paths`. If login fails, put the printed field names into
`field_username` / `field_password` / `field_year`.

The parser strips each page to text and lets Claude pull out the structure, so
it survives a portal redesign — but check `tpo_dump/` after the probe to confirm
the drive details are actually in what it captured.

---

## The salary floor

Set to **12 LPA fixed base** in `profile.yaml`. Base, not CTC — that distinction
does most of the work here, because a posting advertising 14 LPA CTC is usually
around 11.9 LPA base once variable pay comes out, and it gets dropped.

| Posting says | What happens |
|---|---|
| Base ≥ 12L | Passes. Auto-apply allowed. |
| Base < 12L | Dropped, silently. |
| CTC only | Multiplied by 0.85 to approximate base, then compared. |
| Nothing | Web search: Levels.fyi, AmbitionBox, Glassdoor, Blind. |

For unstated salaries the search result decides:

- **High confidence, clears 12L by 2L or more** → auto-apply, card says `est. 16–20L (high confidence, levels.fyi)`.
- **Clears the floor but narrowly, or medium confidence** → alerts you, no auto-apply. An estimate has an error bar and you don't want to find out in round three.
- **Clearly under** → dropped.
- **Nothing findable** → card with a **💬 Ask them the base** button. One tap emails HR asking for the range before you apply.

That last one stays a button rather than automatic on purpose. Asking about pay
before a company has shown any interest reads as presumptuous to some Indian
employers, and it's your call which roles are worth spending that on.

The lookup only runs on postings that already passed the fit screen, so it costs
cents a day rather than dollars. Tune `min_base_lpa`, `ctc_to_base_ratio` and
`estimate_buffer_lpa` in `profile.yaml`.

---

**Scam filter.** The Indian fresher market is full of fake consultancies charging
registration fees. Anything asking for money, Aadhaar/PAN/bank details before an
offer, or hiring from a personal Gmail gets flagged and never auto-replied to.

---

## Setup

### 1. Repo

Unzip first — GitHub stores files, not archives. Push the **contents** of the
`jobbot/` folder to the repo root, so that `profile.yaml` sits at the top level.

```bash
unzip jobbot.zip
cd jobbot
git init && git add -A
git commit -m "initial"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main
```

Use the command line, not drag-and-drop upload on github.com. The web uploader
silently skips dot-folders, which means `.github/workflows/run.yml` never
arrives and the schedule never fires. After pushing, open the repo and confirm
you can see `.github/workflows/run.yml`. If it isn't there, nothing will run.

Make the repo **private** — it will hold your CV and your application history.
Drop your CV at `assets/resume.pdf`.

### 2. Telegram bot (5 minutes)

- Message [@BotFather](https://t.me/botfather) → `/newbot` → copy the token.
- Message your new bot once (it can't message you first).
- Open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `chat.id`.

### 3. Anthropic API key

From [console.anthropic.com](https://console.anthropic.com). Screening runs on Haiku,
so expect roughly $2–4/month at 30-minute polling.

### 4. Gmail (optional but this is the good part)

```bash
pip install -r requirements.txt
python scripts/setup_gmail_token.py
```

Instructions are in the file header. Then **turn on LinkedIn job alert emails** —
that is how LinkedIn postings reach the bot without touching LinkedIn's site.

### 5. Telegram channels (optional)

```bash
python scripts/setup_telegram_session.py
```

### 6. Secrets

Repo → Settings → Secrets and variables → Actions:

| Secret | Required |
|---|---|
| `ANTHROPIC_API_KEY` | yes |
| `TELEGRAM_BOT_TOKEN` | yes |
| `TELEGRAM_CHAT_ID` | yes |
| `GMAIL_CLIENT_ID` / `GMAIL_CLIENT_SECRET` / `GMAIL_REFRESH_TOKEN` | for mail + auto-apply |
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` / `TELEGRAM_SESSION` | for channels |
| `TPO_USERNAME` / `TPO_PASSWORD` | for campus drives |
| `ADZUNA_APP_ID` / `ADZUNA_APP_KEY` | for aggregated listings |

Under the **Variables** tab, leave `DRY_RUN` unset. It defaults to `true`.

### 7. Edit `profile.yaml`

The starter profile is a guess. Fix the email, phone, links and background — the
match scores are only as good as what you put there.

### 8. Test

Actions tab → **jobbot** → Run workflow → tick "Run config check only". You should
get a Telegram message. Then run it normally and watch what arrives.

---

## The dry-run week

`DRY_RUN=true` means it alerts you and logs *"would have emailed careers@x.com"*
without sending anything. Run it that way for a week. Read every would-have. When
you agree with all of them, set the repo variable `DRY_RUN` to `false`.

Skipping this step is how people end up emailing forty companies with a broken
cover letter template.

---

## Tuning

| Symptom | Fix in `profile.yaml` |
|---|---|
| Too much noise | raise `min_score` to 80 |
| Missing good roles that pay well | lower `min_base_lpa`, or `estimate_buffer_lpa` to 1 |
| Only one Telegram channel | leave one line under `telegram_channels` |
| Too quiet | lower `min_score` to 65, add `titles_include` terms |
| Wrong cities | edit `locations` |
| Auto-applying too eagerly | raise `auto_apply_threshold` to 92 |
| One company spamming | tap **Mute company** on any card |

Adding companies is the highest-value change you can make. Find any company you
want, check if `boards-api.greenhouse.io/v1/boards/<name>/jobs` returns JSON, and
if it does, add `<name>` to `greenhouse_boards`. Same for `api.lever.co/v0/postings/<name>`.
These postings appear days before aggregators pick them up.

---

## Files

```
jobbot/main.py              orchestrator, one run per cron tick
jobbot/match.py             Claude scoring + cover letters
jobbot/apply.py             the two auto-apply paths, with guardrails
jobbot/notify.py            Telegram cards and button handling
jobbot/state.py             dedupe + application log, committed back to the repo
jobbot/sources/             gmail, telegram channels, ATS boards
profile.yaml                everything you tune
```
