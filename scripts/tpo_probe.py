"""Run ONCE on your laptop, on college wifi or VPN if the portal is internal.

    export TPO_USERNAME=20233581
    export TPO_PASSWORD='your-new-password'
    python scripts/tpo_probe.py

It logs in, reports which pages have content, and writes what the extractor
would see to tpo_dump/. Nothing is sent anywhere and nothing is registered.

If login fails, the printed field names tell you what to put under
`field_username` / `field_password` / `field_year` in profile.yaml.
"""
import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from jobbot.config import Config  # noqa: E402
from jobbot.sources import tpo  # noqa: E402

OUT = pathlib.Path("tpo_dump")

CANDIDATE_PATHS = [
    "/new/portal/dashboard", "/new/portal/home", "/new/portal/companies",
    "/new/portal/jobs", "/new/portal/notices", "/new/portal/drives",
    "/new/portal/applications", "/new/portal/student/dashboard",
]


def main() -> None:
    cfg = Config()
    conf = cfg.sources.get("tpo") or {}
    base = (conf.get("base_url") or "").rstrip("/")
    if not base:
        raise SystemExit("Set sources.tpo.base_url in profile.yaml first")

    import requests
    from bs4 import BeautifulSoup

    login_url = base + conf.get("login_path", "/new/portal")
    print(f"Fetching {login_url} ...")
    page = requests.get(login_url, timeout=30)
    fields = tpo._form_fields(page.text)
    print("\nDetected login form fields:")
    print(f"  username field : {fields['user']}")
    print(f"  password field : {fields['pw']}")
    print(f"  third field    : {fields['extra']}   (graduation year)")
    print(f"  hidden fields  : {list(fields['hidden']) or 'none'}")
    print(f"  form action    : {fields['action']}")

    sess = tpo.login(cfg)
    if not sess:
        raise SystemExit("\nLogin failed. Put the field names above into profile.yaml.")
    print("\n✅ Login succeeded.\n")

    OUT.mkdir(exist_ok=True)
    found = []
    for path in CANDIDATE_PATHS + (conf.get("listing_paths") or []):
        try:
            r = sess.get(base + path, timeout=30)
        except Exception as exc:  # noqa: BLE001
            print(f"  {path:<36} error: {exc}")
            continue
        text = tpo._text_of(r.text) if r.status_code == 200 else ""
        marker = "✓" if len(text) > 400 else "·"
        print(f"  {marker} {path:<36} {r.status_code}  {len(text)} chars")
        if len(text) > 400:
            found.append(path)
            (OUT / (path.strip('/').replace('/', '_') + ".txt")).write_text(text)

    print(f"\nPages with real content -> put these in listing_paths:\n  {found}")
    print(f"Text dumps written to {OUT.resolve()}")
    print("\nOpen one and check the drive details are actually in there.")


if __name__ == "__main__":
    main()
