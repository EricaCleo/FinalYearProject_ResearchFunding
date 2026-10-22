"""
Combine all per-year RGC CSVs (output of scripts/rgc/to_csv.py) into one
rgc_awards.csv for the RGC -> OpenAlex PI linkage pipeline.

Usage:
    python combine_rgc_data.py --input-dir path/to/csvs --out rgc_awards.csv

award_year comes from the filename (expects a 4-digit year, e.g.
"2010_results.csv"), not the page's own "Exercise Year" field, since those
two can genuinely differ. Duplicate project_ids across files keep only the
first occurrence.
"""
import argparse
import csv
import re
from pathlib import Path

OUTPUT_COLUMNS = [
    "project_id", "pi_name_raw", "institution_raw", "department_raw",
    "award_year", "project_title", "abstract", "panel", "scheme", "orcid",
    "status", "amount", "end_date", "field", "exercise_year",
    "co_investigators", "publications", "conferences", "source_url",
    # completion-report free-text fields, kept for manual review / analysis
    # later -- email isn't usable for OpenAlex matching but helps lookups
    "email", "layman_summary", "realisation_of_objectives",
    "objectives_addressed", "major_findings", "potential_development",
]

YEAR_RE = re.compile(r"(20\d{2})")


def year_from_filename(path: Path) -> str:
    m = YEAR_RE.search(path.stem)
    if not m:
        raise ValueError(f"Can't find a 4-digit year in filename: {path.name}")
    return m.group(1)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, help="Directory containing per-year CSVs")
    parser.add_argument("--out", default="rgc_awards.csv")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    files = sorted(input_dir.glob("*.csv"))
    print(f"{len(files)} input files found")

    seen_project_ids = set()
    duplicates = 0
    rows_out = []
    for path in files:
        award_year = year_from_filename(path)
        with path.open(encoding="utf-8-sig") as f:
            count_this_file = 0
            for row in csv.DictReader(f):
                project_id = row.get("grant_id", "")
                if project_id in seen_project_ids:
                    duplicates += 1
                    continue
                seen_project_ids.add(project_id)
                count_this_file += 1
                rows_out.append({
                    "project_id": project_id,
                    "pi_name_raw": row.get("pi", ""),
                    "institution_raw": row.get("institution", ""),
                    "department_raw": row.get("department", ""),
                    "award_year": award_year,
                    "project_title": row.get("title", ""),
                    "abstract": row.get("abstract", ""),
                    "panel": row.get("panel", ""),
                    "scheme": row.get("scheme", ""),
                    "orcid": "",
                    "status": row.get("status", ""),
                    "amount": row.get("amount", ""),
                    "end_date": row.get("end_date", ""),
                    "field": row.get("field", ""),
                    "exercise_year": row.get("exercise_year", ""),
                    "co_investigators": row.get("co_investigators", ""),
                    "publications": row.get("publications", ""),
                    "conferences": row.get("conferences", ""),
                    "source_url": row.get("source_url", ""),
                    "email": row.get("email", ""),
                    "layman_summary": row.get("layman_summary", ""),
                    "realisation_of_objectives": row.get("realisation_of_objectives", ""),
                    "objectives_addressed": row.get("objectives_addressed", ""),
                    "major_findings": row.get("major_findings", ""),
                    "potential_development": row.get("potential_development", ""),
                })
        print(f"  {path.name}: award_year={award_year}, {count_this_file} new rows")

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=OUTPUT_COLUMNS)
        writer.writeheader()
        writer.writerows(rows_out)

    print(f"\nWrote {len(rows_out)} unique projects -> {args.out}")
    if duplicates:
        print(f"Skipped {duplicates} duplicate project_id rows (already seen in an earlier file)")


if __name__ == "__main__":
    main()
