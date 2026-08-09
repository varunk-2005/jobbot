"""GitHub Actions is stateless, so we keep state in a JSON file that the
workflow commits back to the repo after every run."""
import datetime as dt
import hashlib
import json
import pathlib

STATE_PATH = pathlib.Path(__file__).resolve().parent.parent / "state.json"

_DEFAULT = {
    "seen": {},              # job_id -> ISO date first seen
    "applied": {},           # job_id -> {date, method, target}
    "replied_threads": [],   # Gmail thread ids already auto-replied to
    "ignored_companies": [],
    "last_telegram_update_id": 0,
    "pending": {},           # job_id -> full job dict, awaiting a button press
}


def job_id(job: dict) -> str:
    """Stable id so the same posting seen on three sites alerts you once."""
    basis = f"{job.get('company','').lower().strip()}|{job.get('title','').lower().strip()}"
    return hashlib.sha1(basis.encode()).hexdigest()[:16]


class State:
    def __init__(self, path: pathlib.Path = STATE_PATH):
        self.path = path
        if path.exists():
            self.data = {**_DEFAULT, **json.loads(path.read_text() or "{}")}
        else:
            self.data = json.loads(json.dumps(_DEFAULT))

    def save(self) -> None:
        self._prune()
        self.path.write_text(json.dumps(self.data, indent=2, sort_keys=True))

    # --- seen tracking -----------------------------------------------------
    def is_new(self, jid: str) -> bool:
        return jid not in self.data["seen"]

    def mark_seen(self, jid: str) -> None:
        self.data["seen"][jid] = dt.date.today().isoformat()

    # --- application tracking ---------------------------------------------
    def has_applied(self, jid: str) -> bool:
        return jid in self.data["applied"]

    def mark_applied(self, jid: str, method: str, target: str) -> None:
        self.data["applied"][jid] = {
            "date": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
            "method": method,
            "target": target,
        }

    def applies_today(self) -> int:
        today = dt.date.today().isoformat()
        return sum(1 for v in self.data["applied"].values() if v["date"].startswith(today))

    # --- misc --------------------------------------------------------------
    def is_ignored(self, company: str) -> bool:
        c = (company or "").lower().strip()
        return any(c == x.lower().strip() for x in self.data["ignored_companies"])

    def ignore_company(self, company: str) -> None:
        if company and company not in self.data["ignored_companies"]:
            self.data["ignored_companies"].append(company)

    def _prune(self) -> None:
        """Keep the file small — forget postings seen more than 60 days ago."""
        cutoff = (dt.date.today() - dt.timedelta(days=60)).isoformat()
        self.data["seen"] = {k: v for k, v in self.data["seen"].items() if v >= cutoff}
        self.data["replied_threads"] = self.data["replied_threads"][-500:]
        if len(self.data["pending"]) > 200:
            keys = list(self.data["pending"])[-200:]
            self.data["pending"] = {k: self.data["pending"][k] for k in keys}
