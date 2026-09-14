"""
Convert data/raw/rgc/parsed.jsonl into a CSV you can open in Excel/Numbers/Google Sheets.

parsed.jsonl is cumulative (every project ever downloaded, any year). Usually you want
just one year's worth in its own file, so --year filters by the "exercise_year" field
(e.g. "2007 / 08") and writes a year-specific file instead of overwriting a shared one.

Usage:
    python to_csv.py --year 2007      -> data/raw/rgc/parsed_2007.csv (2007 only)
    python to_csv.py                  -> data/raw/rgc/parsed.csv (every year combined)
"""
import argparse
import csv
import json

from common import REPO_ROOT

IN_FILE = REPO_ROOT / "data" / "raw" / "rgc" / "parsed.jsonl"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", help="Only include this award year, e.g. 2007 (matches the exercise_year field)")
    args = parser.parse_args()

    out_file = (REPO_ROOT / "data" / "raw" / "rgc" / f"parsed_{args.year}.csv" if args.year
                else REPO_ROOT / "data" / "raw" / "rgc" / "parsed.csv")

    records = []
    with IN_FILE.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rec.pop("raw_fields", None)
            if args.year and not rec.get("exercise_year", "").startswith(args.year):
                continue
            records.append(rec)

    if not records:
        print(f"No records found{' for year ' + args.year if args.year else ''} in parsed.jsonl")
        return

    # Consistent column order: fixed leading columns, then everything else seen.
    leading = ["grant_id", "project_number", "title", "title_zh", "pi", "pi_zh",
               "department", "institution", "scheme", "panel", "field",
               "exercise_year", "amount", "status", "end_date"]
    other = sorted({k for r in records for k in r} - set(leading))
    columns = leading + other

    with out_file.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    print(f"Wrote {len(records)} rows -> {out_file}")


if __name__ == "__main__":
    main()
