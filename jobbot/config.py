"""Loads profile.yaml + environment secrets into one object."""
import os
import pathlib

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _env_bool(key: str, default: bool = False) -> bool:
    val = os.environ.get(key)
    if val is None:
        return default
    return val.strip().lower() in {"1", "true", "yes", "on"}


class Config:
    def __init__(self, profile_path: str | None = None):
        path = pathlib.Path(profile_path or ROOT / "profile.yaml")
        with open(path, "r", encoding="utf-8") as fh:
            self.raw = yaml.safe_load(fh)

        self.identity = self.raw["identity"]
        self.background = self.raw["background"]
        self.criteria = self.raw["criteria"]
        self.sources = self.raw.get("sources", {})

        # --- secrets (GitHub Actions injects these) ---
        self.anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")
        self.telegram_bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.telegram_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
        self.gmail_client_id = os.environ.get("GMAIL_CLIENT_ID", "")
        self.gmail_client_secret = os.environ.get("GMAIL_CLIENT_SECRET", "")
        self.gmail_refresh_token = os.environ.get("GMAIL_REFRESH_TOKEN", "")
        self.tg_api_id = os.environ.get("TELEGRAM_API_ID", "")
        self.tg_api_hash = os.environ.get("TELEGRAM_API_HASH", "")
        self.tg_session = os.environ.get("TELEGRAM_SESSION", "")
        self.tpo_username = os.environ.get("TPO_USERNAME", "")
        self.tpo_password = os.environ.get("TPO_PASSWORD", "")
        self.adzuna_app_id = os.environ.get("ADZUNA_APP_ID", "")
        self.adzuna_app_key = os.environ.get("ADZUNA_APP_KEY", "")

        # --- behaviour switches ---
        # DRY_RUN sends you the alerts but never sends an application email.
        # Leave it on for the first week. Seriously.
        self.dry_run = _env_bool("DRY_RUN", True)
        self.max_auto_applies_per_day = int(os.environ.get("MAX_AUTO_APPLIES_PER_DAY", "8"))

        # Cheap model screens hundreds of postings; expensive model only
        # writes the handful of cover letters you actually approve.
        self.screen_model = os.environ.get("SCREEN_MODEL", "claude-haiku-4-5-20251001")
        self.write_model = os.environ.get("WRITE_MODEL", "claude-sonnet-5")

        self.resume_path = ROOT / self.identity.get("resume_path", "assets/resume.pdf")

    def missing_secrets(self) -> list[str]:
        required = {
            "ANTHROPIC_API_KEY": self.anthropic_key,
            "TELEGRAM_BOT_TOKEN": self.telegram_bot_token,
            "TELEGRAM_CHAT_ID": self.telegram_chat_id,
        }
        return [k for k, v in required.items() if not v]
