"""Job feeds from public APIs. No scraping, no ToS problems."""
import html
import re

import requests

TIMEOUT = 20
UA = {"User-Agent": "jobbot/1.0 (personal job alerts)"}


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", html.unescape(raw))
    return re.sub(r"\s+", " ", text).strip()


def greenhouse(slug: str) -> list[dict]:
    url = f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
    try:
        data = requests.get(url, timeout=TIMEOUT, headers=UA).json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for j in data.get("jobs", []):
        out.append({
            "title": j.get("title", ""),
            "company": slug.replace("-", " ").title(),
            "location": (j.get("location") or {}).get("name", ""),
            "url": j.get("absolute_url", ""),
            "description": _strip_html(j.get("content", ""))[:6000],
            "source": "greenhouse",
        })
    return out


def lever(slug: str) -> list[dict]:
    url = f"https://api.lever.co/v0/postings/{slug}?mode=json"
    try:
        data = requests.get(url, timeout=TIMEOUT, headers=UA).json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for j in data if isinstance(data, list) else []:
        cats = j.get("categories") or {}
        out.append({
            "title": j.get("text", ""),
            "company": slug.replace("-", " ").title(),
            "location": cats.get("location", ""),
            "url": j.get("hostedUrl", ""),
            "description": _strip_html(j.get("descriptionPlain") or j.get("description", ""))[:6000],
            "source": "lever",
        })
    return out


def ashby(slug: str) -> list[dict]:
    url = f"https://api.ashbyhq.com/posting-api/job-board/{slug}"
    try:
        data = requests.get(url, timeout=TIMEOUT, headers=UA).json()
    except Exception:  # noqa: BLE001
        return []
    out = []
    for j in data.get("jobs", []):
        out.append({
            "title": j.get("title", ""),
            "company": slug.replace("-", " ").title(),
            "location": j.get("location", ""),
            "url": j.get("jobUrl", ""),
            "description": _strip_html(j.get("descriptionHtml", ""))[:6000],
            "source": "ashby",
        })
    return out


def adzuna(app_id: str, app_key: str, query: str, country: str = "in", pages: int = 1) -> list[dict]:
    """Adzuna aggregates Naukri, Indeed and direct company sites."""
    if not (app_id and app_key):
        return []
    out = []
    for page in range(1, pages + 1):
        url = f"https://api.adzuna.com/v1/api/jobs/{country}/search/{page}"
        params = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": 30,
            "what": query,
            "max_days_old": 3,
            "content-type": "application/json",
        }
        try:
            data = requests.get(url, params=params, timeout=TIMEOUT, headers=UA).json()
        except Exception:  # noqa: BLE001
            break
        for j in data.get("results", []):
            out.append({
                "title": j.get("title", ""),
                "company": (j.get("company") or {}).get("display_name", ""),
                "location": (j.get("location") or {}).get("display_name", ""),
                "url": j.get("redirect_url", ""),
                "description": _strip_html(j.get("description", ""))[:6000],
                "source": "adzuna",
            })
    return out


def collect(cfg) -> list[dict]:
    jobs: list[dict] = []
    src = cfg.sources
    for slug in src.get("greenhouse_boards", []) or []:
        jobs += greenhouse(slug)
    for slug in src.get("lever_boards", []) or []:
        jobs += lever(slug)
    for slug in src.get("ashby_boards", []) or []:
        jobs += ashby(slug)
    for q in src.get("adzuna_queries", []) or []:
        jobs += adzuna(cfg.adzuna_app_id, cfg.adzuna_app_key, q)
    return jobs
