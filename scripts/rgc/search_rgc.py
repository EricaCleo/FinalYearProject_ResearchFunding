"""
Fully automated RGC search + pagination. Replaces manually saving each search-results
page in a browser.

How this was figured out: a saved copy of a real results page showed that project rows
aren't plain <a href> links, and the "next page" numbers aren't links either — they're
JavaScript buttons (goToPage(...)) that fill in a hidden form (frm_goToPage) and POST it
to scrrm00541.jsp. This script sends the exact same POST requests directly, so it can
walk every page of every year's results without a browser.

Usage:
    python search_rgc.py --years 2006-2026 --status C --out links.txt

--status: C=Completed, O=On-going, T=Terminated, W=Withdrawn, or "" for all statuses.
Every fetched search-results page is also saved to data/raw/rgc/search_pages/ (one file
per year per page) so you can audit exactly what was searched.

This can take a while for a wide year range (RGC lists 10 projects per page, and some
years have 800+ projects = 80+ pages each). It's fine to let it run in the background;
re-running with the same --out just recomputes the full link list from scratch (cheap —
it's the download step, not this one, that's slow).
"""
import argparse
import math
import re
from pathlib import Path

from common import REPO_ROOT, post_html, prime_session, save_text

SEARCH_URL = "https://cerg1.ugc.edu.hk/cergprod/scrrm00541.jsp"
DETAIL_URL_TEMPLATE = "https://cerg1.ugc.edu.hk/cergprod/scrrm00542.jsp?proj_id={proj_id}"
PAGE_SIZE = 10  # confirmed from a real results page: 10 projects listed per page

SEARCH_PAGES_DIR = REPO_ROOT / "data" / "raw" / "rgc" / "search_pages"

PROJ_ID_RE = re.compile(r'name="proj_id"\s+value="(\d+)"')
RECORDS_RE = re.compile(r"Number of records found\s*:\s*([\d,]+)")


def fetch_search_page(year: str, page: int, status: str, scheme: str) -> str:
    if page == 1:
        # Mirrors the visible search form (scrrm00541) fields — confirmed via a real
        # browser's DevTools Network payload for Award Year 2006.
        data = {
            "mode": "search", "page": "1", "Year": year,
            "sScheme": scheme, "panel": "", "subject": "", "institution": "",
            "proj_id": "", "proj_title": "", "isname": "", "ioname": "",
            "fromAwardYear": "", "toAwardYear": "", "sStatus": status,
        }
    else:
        # Mirrors the hidden frm_goToPage fields the goToPage() JS function fills in —
        # confirmed via DevTools payload for a page-2 request.
        data = {
            "mode": "search", "subject": "", "panel": "", "scheme": scheme,
            "sScheme": scheme, "sStatus": status, "proj_id": "", "Old_proj_id": "",
            "proj_title": "", "isname": "", "ioname": "", "institution": "",
            "Year": year, "pages": str(page),
        }
    return post_html(SEARCH_URL, data=data)


def parse_records_count(html: str) -> int:
    m = RECORDS_RE.search(html)
    return int(m.group(1).replace(",", "")) if m else 0


def extract_proj_ids(html: str) -> list[str]:
    # de-dupe within a page, keep order
    return list(dict.fromkeys(PROJ_ID_RE.findall(html)))


def crawl_year(year: str, status: str, scheme: str) -> list[str]:
    html = fetch_search_page(year, 1, status, scheme)
    save_text(SEARCH_PAGES_DIR / f"{year}_page001.html", html)
    total = parse_records_count(html)
    proj_ids = extract_proj_ids(html)
    pages = math.ceil(total / PAGE_SIZE) if total else (1 if proj_ids else 0)
    print(f"  {year}: {total} records, {pages} pages")
    if total and not proj_ids:
        print(f"    WARNING: page 1 reports {total} records but extracted 0 proj_ids — "
              f"the --scheme code ({scheme!r}) is probably wrong for this year. "
              f"Check this year's Funding Scheme dropdown value in DevTools.")

    for page in range(2, pages + 1):
        html = fetch_search_page(year, page, status, scheme)
        save_text(SEARCH_PAGES_DIR / f"{year}_page{page:03d}.html", html)
        found = extract_proj_ids(html)
        if not found:
            print(f"    WARNING: page {page} returned 0 projects (expected more) — stopping this year early")
            break
        proj_ids.extend(found)

    return list(dict.fromkeys(proj_ids))


def parse_year_range(spec: str) -> list[str]:
    if "-" in spec:
        start, end = spec.split("-")
        return [str(y) for y in range(int(start), int(end) + 1)]
    return [spec]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", required=True, help="e.g. 2006-2026 or a single year like 2006")
    parser.add_argument("--status", default="C", help="C=Completed (default), O=On-going, T=Terminated, W=Withdrawn, blank for all")
    parser.add_argument("--scheme", default="1",
                         help="Funding Scheme code (default 1 = General Research Fund, confirmed for 2006). "
                              "Some later years may offer more schemes in the dropdown — if a year's page 1 "
                              "warns about 0 extracted proj_ids despite records>0, check that year's Funding "
                              "Scheme dropdown value in DevTools and pass the right code here.")
    parser.add_argument("--out", default="links.txt")
    args = parser.parse_args()

    prime_session()
    years = parse_year_range(args.years)
    all_proj_ids = []
    for year in years:
        print(f"Searching year {year}...")
        all_proj_ids.extend(crawl_year(year, args.status, args.scheme))

    all_proj_ids = list(dict.fromkeys(all_proj_ids))
    links = [DETAIL_URL_TEMPLATE.format(proj_id=pid) for pid in all_proj_ids]
    Path(args.out).write_text("\n".join(links), encoding="utf-8")
    print(f"\nTotal unique projects found across {len(years)} year(s): {len(links)} -> {args.out}")


if __name__ == "__main__":
    main()
