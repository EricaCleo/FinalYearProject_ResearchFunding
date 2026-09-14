"""
Step 3: parse downloaded RGC project HTML into structured JSON records (Slide 4 schema).

RGC detail pages (scrrm00542.jsp) are a single <table> of label/value row pairs, e.g.:
    Funding Scheme :          | General Research Fund
    Project Number :          | 100110
    Project Title(English) :  | Stability of Error Bounds in Statistical Learning Theory
    Principal Investigator(English) : | Dr Caponnetto, Andrea
    Fund Approved :           | 540,000
    Project Status :          | Completed
    Completion Date :         | 31-7-2013
    Project Objectives :      | ...

Every label/value pair found is kept in `raw_fields` regardless of whether it's in
FIELD_KEYWORDS below, so nothing is silently dropped even if a page has an unexpected
field.

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
DETAIL_URL_TEMPLATE = "https://cerg1.ugc.edu.hk/cergprod/scrrm00542.jsp?proj_id={proj_id}"

# label keyword (lowercased, substring match) -> normalized field name.
# Order matters: for a label matching multiple keywords, the first (English) wins.
FIELD_KEYWORDS = {
    "funding scheme": "scheme",
    "project number": "project_number",
    "project title(english)": "title",
    "project title(chinese)": "title_zh",
    "principal investigator(english)": "pi",
    "principal investigator(chinese)": "pi_zh",
    "department": "department",
    "institution": "institution",
    "e-mail address": "email",
    "tel": "phone",
    "co - investigator": "co_investigators",
    "panel": "panel",
    "subject area": "field",
    "exercise year": "exercise_year",
    "fund approved": "amount",
    "project status": "status",
    "completion date": "end_date",
    "project objectives": "objectives",
    "abstract as per original application": "abstract",
    "layman's summary": "layman_summary",
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
    proj_id = path.stem  # download_details.py names files by proj_id when present
    record = {
        "grant_id": proj_id,
        "source_url": DETAIL_URL_TEMPLATE.format(proj_id=proj_id),
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
