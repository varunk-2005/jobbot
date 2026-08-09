"""Run ONCE on your own laptop. Prints a session string for GitHub secrets.

Get api_id and api_hash from https://my.telegram.org -> API development tools.

    python scripts/setup_telegram_session.py

Treat the printed string like a password: it is a logged-in session for your
Telegram account. Store it only as an encrypted GitHub secret.
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient


def main() -> None:
    api_id = int(input("api_id: ").strip())
    api_hash = input("api_hash: ").strip()

    with TelegramClient(StringSession(), api_id, api_hash) as client:
        print("\n" + "=" * 62)
        print("TELEGRAM_API_ID   =", api_id)
        print("TELEGRAM_API_HASH =", api_hash)
        print("TELEGRAM_SESSION  =", client.session.save())
        print("=" * 62)


if __name__ == "__main__":
    main()
