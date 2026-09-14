"""Shared helpers for the RGC crawler: HTTP fetch with throttling, JSON I/O, and audit logging."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

USER_AGENT = "Mozilla/5.0 (research-fyp-crawler; contact: your-email@example.com)"
REQUEST_DELAY_SECONDS = 1.0

REPO_ROOT = Path(__file__).resolve().parents[2]
AUDIT_LOG = REPO_ROOT / "data" / "audit" / "collection_log.jsonl"


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
        resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30, **kwargs)
        resp.raise_for_status()
        time.sleep(REQUEST_DELAY_SECONDS)
        log_event({"source_url": url, "status": "ok", "http_status": resp.status_code})
        resp.encoding = resp.apparent_encoding or resp.encoding
        return resp.text
    except requests.RequestException as exc:
        log_event({"source_url": url, "status": "error", "error": str(exc)})
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
