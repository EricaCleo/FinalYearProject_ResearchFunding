"""
Convert data/raw/rgc/parsed.jsonl into a CSV you can open in Excel/Numbers/Google Sheets.

parsed.jsonl is cumulative (every project ever downloaded, any year). --links filters it
down to just the projects in one year's links_<year>.txt file — that file is the
authoritative record of "everything found by searching Award Year <year>", produced by
search_rgc.py. (Earlier this filtered by the page's own "Exercise Year" field instead,
but that can differ from the Award Year actually searched, silently dropping projects.)

Usage:
    python to_csv.py --links links_2008.txt   -> data/raw/rgc/parsed_2008.csv
    python to_csv.py                          -> data/raw/rgc/parsed.csv (every year combined)
"""
import argparse
import csv
import json
import re
from pathlib import Path
from urllib.parse import urlparse, parse_qs

from common import REPO_ROOT

IN_FILE = REPO_ROOT / "data" / "raw" / "rgc" / "parsed.jsonl"


def proj_ids_from_links_file(links_path: Path) -> set[str]:
    ids = set()
    for url in links_path.read_text(encoding="utf-8").splitlines():
        url = url.strip()
        if not url:
            continue
        proj_id = parse_qs(urlparse(url).query).get("proj_id", [None])[0]
        if proj_id:
            ids.add(proj_id)
    return ids


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--links", help="Path to a links_<year>.txt file to restrict output to that year's projects")
    args = parser.parse_args()

    if args.links:
        links_path = Path(args.links)
        wanted_ids = proj_ids_from_links_file(links_path)
        # links_2008.txt -> parsed_2008.csv
        year_label = re.sub(r"^links_?", "", links_path.stem) or links_path.stem
        out_file = REPO_ROOT / "data" / "raw" / "rgc" / f"parsed_{year_label}.csv"
    else:
        wanted_ids = None
        out_file = REPO_ROOT / "data" / "raw" / "rgc" / "parsed.csv"

    records = []
    with IN_FILE.open(encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            rec.pop("raw_fields", None)
            if wanted_ids is not None and rec.get("grant_id") not in wanted_ids:
                continue
            records.append(rec)

    if not records:
        print(f"No records found{' for ' + args.links if args.links else ''} in parsed.jsonl")
        return

    if wanted_ids is not None and len(records) != len(wanted_ids):
        missing = wanted_ids - {r["grant_id"] for r in records}
        print(f"WARNING: {links_path} lists {len(wanted_ids)} projects but only {len(records)} were "
              f"found in parsed.jsonl. Missing (not yet downloaded?): {sorted(missing)[:20]}")

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
