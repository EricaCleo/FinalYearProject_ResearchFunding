"""
Builds unique_pis.csv: collapses rgc_awards.csv (one row per grant) into
one row per real person, grouped by cleaned name + normalized institution.
This matters for Stage 5 later -- a PI whose current grant is still
ongoing can still get resolved through an older completed grant of theirs,
but only if all their project IDs are combined into one row first.

Usage:
    python build_unique_pis.py --input rgc_awards.csv --out unique_pis.csv
"""
import argparse
import csv
from collections import defaultdict

from common import clean_person_name, extract_titles, normalize_institution


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out", default="unique_pis.csv")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    groups = defaultdict(list)
    for row in rows:
        key = (clean_person_name(row.get("pi_name_raw", "")), normalize_institution(row.get("institution_raw", "")))
        groups[key].append(row)

    out_rows = []
    for (_pi_clean, _institution_norm), group_rows in groups.items():
        pi_name_raw = group_rows[0].get("pi_name_raw", "")
        institution_raw = group_rows[0].get("institution_raw", "")

        project_ids = [r.get("project_id", "") for r in group_rows if r.get("project_id")]
        award_years = sorted({r.get("award_year", "") for r in group_rows if r.get("award_year")})
        sample_title = next((r.get("project_title", "") for r in group_rows if r.get("project_title")), "")

        known_titles = []  # real published titles across all this PI's grants, if any
        for r in group_rows:
            known_titles.extend(extract_titles(r.get("publications", "")))

        out_rows.append({
            "pi_name_raw": pi_name_raw,
            "institution_raw": institution_raw,
            "n_awards": len(group_rows),
            "award_years": "|".join(award_years),
            "project_ids": "|".join(project_ids),
            "sample_project_title": sample_title,
            "known_publication_titles": "|".join(known_titles),
        })

    fieldnames = ["pi_name_raw", "institution_raw", "n_awards", "award_years", "project_ids",
                  "sample_project_title", "known_publication_titles"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(out_rows)

    n_multi_award = sum(1 for r in out_rows if r["n_awards"] > 1)
    n_with_titles = sum(1 for r in out_rows if r["known_publication_titles"])
    print(f"{len(rows)} grant rows -> {len(out_rows)} unique PIs -> {args.out}")
    print(f"  {n_multi_award} PIs have more than one RGC award (their project_ids are combined)")
    print(f"  {n_with_titles} PIs have at least one known real publication title "
          f"(only completed grants with a submitted completion report carry this)")


if __name__ == "__main__":
    main()
