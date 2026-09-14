"""
Convert data/raw/rgc/parsed.jsonl into a CSV you can open in Excel/Numbers/Google Sheets.

Usage:
    python to_csv.py
Writes data/raw/rgc/parsed.csv (one row per project, one column per field).
The bulky raw_fields dict is left out of the CSV (it's for debugging the parser, not
for analysis) — everything meaningful is already in its own named column.
"""
import csv
import json

from common import REPO_ROOT

IN_FILE = REPO_ROOT / "data" / "raw" / "rgc" / "parsed.jsonl"
OUT_FILE = REPO_ROOT / "data" / "raw" / "rgc" / "parsed.csv"


def main():
    records = []
    with IN_FILE.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rec.pop("raw_fields", None)
            records.append(rec)

    if not records:
        print("No records found in parsed.jsonl")
        return

    # Consistent column order: fixed leading columns, then everything else seen.
    leading = ["grant_id", "project_number", "title", "title_zh", "pi", "pi_zh",
               "department", "institution", "scheme", "panel", "field",
               "exercise_year", "amount", "status", "end_date"]
    other = sorted({k for r in records for k in r} - set(leading))
    columns = leading + other

    with OUT_FILE.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote {len(records)} rows -> {OUT_FILE}")


if __name__ == "__main__":
    main()
