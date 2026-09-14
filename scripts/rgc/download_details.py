"""
Step 2: download each RGC project detail page's raw HTML.

Usage:
    python download_details.py --links links.txt

Reads one URL per line from --links, downloads each (throttled, see common.REQUEST_DELAY_SECONDS),
and saves the raw HTML under data/raw/rgc/html/. Never overwrites a file that already exists,
so it's safe to re-run after a partial run or after adding new links.
"""
import argparse
import hashlib
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from common import REPO_ROOT, fetch_html, save_text

HTML_DIR = REPO_ROOT / "data" / "raw" / "rgc" / "html"


def slug_for(url: str) -> str:
    """Use the real RGC project number (proj_id query param) as the filename so files
    are human-identifiable; falls back to a hash if a URL doesn't carry one."""
    proj_id = parse_qs(urlparse(url).query).get("proj_id", [None])[0]
    if proj_id:
        return proj_id
    return hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", required=True, help="Text file, one detail-page URL per line")
    args = parser.parse_args()

    urls = [u.strip() for u in Path(args.links).read_text(encoding="utf-8").splitlines() if u.strip()]
    print(f"{len(urls)} URLs to download")

    downloaded, skipped, failed = 0, 0, 0
    for i, url in enumerate(urls, 1):
        out_path = HTML_DIR / f"{slug_for(url)}.html"
        if out_path.exists():
            skipped += 1
            continue
        try:
            html = fetch_html(url)
            save_text(out_path, html)
            downloaded += 1
        except Exception as exc:
            print(f"[{i}/{len(urls)}] FAILED {url}: {exc}")
            failed += 1
            continue
        if i % 25 == 0:
            print(f"[{i}/{len(urls)}] downloaded so far: {downloaded}")

    print(f"Done. downloaded={downloaded} skipped(existing)={skipped} failed={failed}")
    print(f"Raw HTML saved under {HTML_DIR}")
    print("Failures are logged in data/audit/collection_log.jsonl")


if __name__ == "__main__":
    main()
