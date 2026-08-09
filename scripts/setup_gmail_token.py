"""Run ONCE on your own laptop. Prints the refresh token for GitHub secrets.

Before running:
1. console.cloud.google.com -> new project
2. APIs & Services -> Library -> enable "Gmail API"
3. OAuth consent screen -> External -> add your own address under Test users
4. Credentials -> Create credentials -> OAuth client ID -> Desktop app
5. Download the JSON, save it next to this script as credentials.json

Then:  python scripts/setup_gmail_token.py
"""
import json
import pathlib

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.send",
]

HERE = pathlib.Path(__file__).parent
CREDS = HERE / "credentials.json"


def main() -> None:
    if not CREDS.exists():
        raise SystemExit(f"Put your OAuth client JSON at {CREDS}")

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS), SCOPES)
    creds = flow.run_local_server(port=0, prompt="consent", access_type="offline")

    installed = json.loads(CREDS.read_text())
    node = installed.get("installed") or installed.get("web")

    print("\n" + "=" * 62)
    print("Add these three as GitHub repository secrets:\n")
    print(f"GMAIL_CLIENT_ID      = {node['client_id']}")
    print(f"GMAIL_CLIENT_SECRET  = {node['client_secret']}")
    print(f"GMAIL_REFRESH_TOKEN  = {creds.refresh_token}")
    print("=" * 62)
    print("\nThen delete credentials.json. Never commit it.")


if __name__ == "__main__":
    main()
