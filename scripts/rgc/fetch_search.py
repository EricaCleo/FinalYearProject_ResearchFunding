"""
Step 1: extract project detail-page links out of a saved RGC search-results page.

The RGC Project Enquiry (cerg1.ugc.edu.hk) search is a JSP form, which usually means
results come back from a POST submitted by the browser rather than a plain GET URL.
Rather than guess the form parameters, do the search manually in a browser, then feed
this script either:
  (a) the results page's URL, if it happens to be a plain GET link, or
  (b) a locally saved copy of the results HTML (File > Save Page As... in your browser)

Usage:
    python fetch_search.py --url "https://cerg1.ugc.edu.hk/cergprod/....jsp?..." --out links.txt
    python fetch_search.py --file path/to/saved_results.html --out links.txt

Once you've inspected the real HTML (browser DevTools > right-click a project link >
Inspect), update LINK_PATTERN below to match how detail-page links actually look.
"""
import argparse
import re
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from common import REPO_ROOT, fetch_html, save_text

# Confirmed from a real search-results page: each project's number links to
# scrrm00542.jsp?proj_id=<id>&... (the detail page).
LINK_PATTERN = re.compile(r"scrrm00542\.jsp\?.*proj_id=", re.IGNORECASE)


def extract_links(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if LINK_PATTERN.search(href):
            links.append(urljoin(base_url, href))
    # de-dupe, keep order
    return list(dict.fromkeys(links))


def main():
    parser = argparse.ArgumentParser()
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--url", help="URL of the search-results page")
    src.add_argument("--file", help="Path to a locally saved search-results HTML file")
    parser.add_argument("--base-url", default="https://cerg1.ugc.edu.hk/cergprod/",
                         help="Base URL to resolve relative links against")
    parser.add_argument("--out", default="links.txt", help="Output file, one detail URL per line")
    args = parser.parse_args()

    if args.url:
        html = fetch_html(args.url)
        base = args.url
        raw_out = REPO_ROOT / "data" / "raw" / "rgc" / "search_pages" / "results.html"
        save_text(raw_out, html)
        print(f"Saved raw search page to {raw_out}")
    else:
        html = Path(args.file).read_text(encoding="utf-8", errors="replace")
        base = args.base_url

    links = extract_links(html, base)
    Path(args.out).write_text("\n".join(links), encoding="utf-8")
    print(f"Found {len(links)} candidate detail links -> {args.out}")
    if not links:
        print("No links matched LINK_PATTERN. Open the saved HTML, find a real project "
              "link's href, and update LINK_PATTERN in this script.")


if __name__ == "__main__":
    main()
