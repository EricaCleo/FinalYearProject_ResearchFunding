"""Shared helpers for the RGC crawler: HTTP fetch with throttling, JSON I/O, and audit logging."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# A real browser UA + Referer/Origin: RGC's site returned a correct record count but
# zero result rows to a plain requests.post() with a generic UA and no session/Referer,
# even with form fields that exactly matched a captured real browser payload — so it
# likely does some basic anti-bot/CSRF checking. A persistent Session (cookies carried
# across requests, like a browser tab) plus these headers should look like a real visit.
USER_AGENT = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36")
SEARCH_BASE_URL = "https://cerg1.ugc.edu.hk/cergprod/scrrm00541.jsp"
REQUEST_DELAY_SECONDS = 1.0

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_LOG = REPO_ROOT / "data" / "audit" / "collection_log.jsonl"

# Shared session so cookies (e.g. JSESSIONID) persist across requests, same as a browser tab.
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
})


def prime_session() -> None:
    """GET the search page once to pick up a session cookie before any POST, like a
    browser would from actually visiting the page. Safe to call multiple times."""
    SESSION.get(SEARCH_BASE_URL, timeout=30)
    time.sleep(REQUEST_DELAY_SECONDS)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def log_event(event: dict) -> None:
    AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
    event = {"collected_at": now_iso(), **event}
    with AUDIT_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


def fetch_html(url: str, **kwargs) -> str:
    """GET a page, throttled, with failures logged to the audit trail."""
    try:
        resp = SESSION.get(url, timeout=30, **kwargs)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)
        log_event({"source_url": url, "status": "ok", "http_status": resp.status_code})
        # The site's own <meta> tag declares UTF-8. Don't guess via apparent_encoding —
        # a page that's mostly English text (e.g. a long abstract) with only a little
        # embedded Chinese can fool that heuristic into picking the wrong single-byte
        # encoding, corrupting the Chinese text into mojibake. Force it instead.
        resp.encoding = "utf-8"
        return resp.text
    except requests.RequestException as exc:
        log_event({"source_url": url, "status": "error", "error": str(exc)})
        raise


def post_html(url: str, data: dict) -> str:
    """POST a form submission, throttled, with failures logged to the audit trail.
    Used to replicate RGC's JavaScript-driven search/pagination forms directly.
    Sends a Referer so the request looks like it came from the search page itself."""
    try:
        resp = SESSION.post(url, data=data, headers={"Referer": SEARCH_BASE_URL}, timeout=30)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)
        log_event({"source_url": url, "status": "ok", "http_status": resp.status_code, "post_data": data})
        # The site's own <meta> tag declares UTF-8. Don't guess via apparent_encoding —
        # a page that's mostly English text (e.g. a long abstract) with only a little
        # embedded Chinese can fool that heuristic into picking the wrong single-byte
        # encoding, corrupting the Chinese text into mojibake. Force it instead.
        resp.encoding = "utf-8"
        return resp.text
    except requests.RequestException as exc:
        log_event({"source_url": url, "status": "error", "error": str(exc), "post_data": data})
        raise


def save_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def append_jsonl(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")
