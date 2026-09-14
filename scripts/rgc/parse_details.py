"""
Step 3: parse downloaded RGC project HTML into structured JSON records (Slide 4 schema).

This is a best-effort generic parser: RGC detail pages are typically laid out as
label/value pairs in an HTML table. It pulls every such pair into `raw_fields`, and
maps the common ones (title, PI, institution, amount, dates, status, panel) into named
fields via keyword matching.

IMPORTANT: this WILL need tuning once you look at real saved pages, because we don't
yet know the exact label wording RGC uses. Send Claude one or two saved HTML files from
data/raw/rgc/html/ and the FIELD_KEYWORDS map below can be corrected precisely instead
of guessed.

Usage:
    python parse_details.py
Reads every file in data/raw/rgc/html/, writes one combined JSONL:
    data/raw/rgc/parsed.jsonl
"""
from pathlib import Path

from bs4 import BeautifulSoup

from common import REPO_ROOT, now_iso, append_jsonl

HTML_DIR = REPO_ROOT / "data" / "raw" / "rgc" / "html"
OUT_FILE = REPO_ROOT / "data" / "raw" / "rgc" / "parsed.jsonl"

# label keyword (lowercased, substring match) -> normalized field name
FIELD_KEYWORDS = {
    "project title": "title",
    "principal investigator": "pi",
    "institution": "institution",
    "amount": "amount",
    "approved amount": "amount",
    "start date": "start_date",
    "completion date": "end_date",
    "end date": "end_date",
    "status": "status",
    "panel": "panel",
    "subject area": "field",
    "funding scheme": "scheme",
}


def extract_label_value_pairs(soup: BeautifulSoup) -> dict[str, str]:
    """Best-effort: RGC pages are commonly <table> layouts with a label cell followed
    by a value cell. Falls back gracefully if that's not how a given page is built."""
    pairs = {}
    for row in soup.find_all("tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) >= 2:
            label = cells[0].get_text(strip=True).rstrip(":")
            value = cells[1].get_text(" ", strip=True)
            if label and value:
                pairs[label] = value
    return pairs


def map_known_fields(raw_fields: dict[str, str]) -> dict[str, str]:
    mapped = {}
    for label, value in raw_fields.items():
        label_lower = label.lower()
        for keyword, field_name in FIELD_KEYWORDS.items():
            if keyword in label_lower and field_name not in mapped:
                mapped[field_name] = value
    return mapped


def parse_file(path: Path) -> dict:
    html = path.read_text(encoding="utf-8", errors="replace")
    soup = BeautifulSoup(html, "lxml")
    raw_fields = extract_label_value_pairs(soup)
    record = {
        "grant_id": path.stem,
        "source_url": None,  # TODO: fill from data/audit/collection_log.jsonl by matching this file's slug
        "collected_at": now_iso(),
        **map_known_fields(raw_fields),
        "raw_fields": raw_fields,
    }
    return record


def main():
    files = sorted(HTML_DIR.glob("*.html"))
    print(f"{len(files)} HTML files to parse")
    if OUT_FILE.exists():
        OUT_FILE.unlink()  # rebuild fresh each run; raw HTML is untouched
    for path in files:
        record = parse_file(path)
        append_jsonl(OUT_FILE, record)
    print(f"Wrote {len(files)} records -> {OUT_FILE}")
    print("Check a few records: are title/pi/institution/amount actually populated?")
    print("If raw_fields has the data under different labels, fix FIELD_KEYWORDS above.")


if __name__ == "__main__":
    main()
