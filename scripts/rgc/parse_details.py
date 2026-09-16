"""
Step 3: parse downloaded RGC project HTML into structured JSON records (Slide 4 schema).

RGC detail pages (scrrm00542.jsp) are a single <table> of label/value row pairs, e.g.:
    Funding Scheme :          | General Research Fund
    Project Number :          | 100110
    Project Title(English) :  | Stability of Error Bounds in Statistical Learning Theory
    Fund Approved :           | 540,000
    Project Objectives :      | ...

Completed projects with a submitted completion report carry extra rows whose VALUE is
itself a nested table rather than plain text — most importantly the Research Output
section (peer-reviewed publications, conference presentations). Those are extracted as
a list of {column: value} dicts instead of being flattened into one text blob, so
publication data isn't lost. A nested table that's just a plain bulleted list with no
header row (e.g. Project Objectives) still falls back to plain concatenated text.

Every label/value pair found is kept in `raw_fields` regardless of whether it's in
FIELD_KEYWORDS below, so nothing is silently dropped even if a page has an unexpected
field. Projects without a given section (e.g. no completion report yet, or an older
project with fewer fields) simply get "" for that field — never an error.

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
    "realisation of objectives": "realisation_of_objectives",
    "summary of objectives addressed": "objectives_addressed",
    "major findings and research outcome": "major_findings",
    "potential for further development": "potential_development",
    "layman's summary": "layman_summary",
    "peer-reviewed journal publication": "publications",
    "recognized international conference": "conferences",
    "other impact": "other_impact",
}


def get_outer_table(soup: BeautifulSoup):
    """The main Project Details table is the first <table border="1"> in the document.
    Several NESTED tables (Objectives, Publications, Conferences, ...) also carry
    border="1", but only ever appear later, inside this table's own cells."""
    return soup.find("table", attrs={"border": "1"})


def extract_nested_table_rows(td) -> list[dict] | None:
    """If `td` contains a nested table shaped like a real data table (a header row
    followed by data rows with the same number of columns), extract it as a list of
    {column_header: value} dicts — this is how Research Output publications and
    conference presentations are laid out. Returns None if there's no nested table, or
    it isn't a clean uniform table (e.g. Project Objectives is just repeated
    single-cell rows with no header row at all) — callers should fall back to plain
    text in that case."""
    inner_table = td.find("table")
    if inner_table is None:
        return None
    rows = inner_table.select(":scope > tbody > tr") or inner_table.select(":scope > tr")
    if len(rows) < 2:
        return None
    header_cells = rows[0].find_all(["td", "th"], recursive=False)
    if len(header_cells) < 2:
        return None
    headers = [c.get_text(strip=True) or f"col{i + 1}" for i, c in enumerate(header_cells)]
    records = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) != len(headers):
            return None  # not a clean uniform table — bail out, caller falls back to plain text
        records.append({h: c.get_text(" ", strip=True) for h, c in zip(headers, cells)})
    return records or None


def extract_label_value_pairs(soup: BeautifulSoup) -> dict:
    """Walk only the direct rows of the main Project Details table (not recursively —
    that would also pick up every row of every nested sub-table as its own spurious
    top-level label/value pair)."""
    outer = get_outer_table(soup)
    if outer is None:
        return {}
    rows = outer.select(":scope > tbody > tr") or outer.select(":scope > tr")
    pairs = {}
    for row in rows:
        cells = row.find_all(["td", "th"], recursive=False)
        if len(cells) < 2:
            continue
        label = cells[0].get_text(strip=True).rstrip(":")
        if not label:
            continue
        table_rows = extract_nested_table_rows(cells[1])
        value = table_rows if table_rows else cells[1].get_text(" ", strip=True)
        if value:
            pairs[label] = value
    return pairs


def map_known_fields(raw_fields: dict) -> dict:
    # Every record gets every known field name, "" when this page didn't have it — so
    # every row in parsed.jsonl has the same set of columns (important for loading this
    # into pandas/Excel as a clean table, e.g. an older project with no Abstract field
    # still gets "abstract": "" instead of the key being missing entirely). Some values
    # here are now lists of dicts (publications, conferences, objectives_addressed)
    # rather than plain strings — to_csv.py JSON-encodes those for the spreadsheet.
    mapped = {field_name: "" for field_name in dict.fromkeys(FIELD_KEYWORDS.values())}
    for label, value in raw_fields.items():
        label_lower = label.lower()
        for keyword, field_name in FIELD_KEYWORDS.items():
            if keyword in label_lower and not mapped[field_name]:
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
