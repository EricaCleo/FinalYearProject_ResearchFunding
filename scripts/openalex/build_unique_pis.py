"""
Builds unique_pis.csv, the input search_candidates.py expects but nothing in
this project actually produced yet: one row per real PERSON, not per grant.
rgc_awards.csv (combine_rgc_data.py's output) has one row per GRANT -- the
same PI with 3 RGC awards appears as 3 separate rows there. Collapsing that
down to one row per PI matters beyond just avoiding repeat OpenAlex
searches: later pipeline stages (Stage 5's publication-title match
especially) check ALL of a PI's project IDs together, so a PI whose current
grant is still ongoing (no completion report, no publications data yet) can
still get resolved automatically through an OLDER, completed grant of
theirs -- but only if this step actually puts every one of their project IDs
into one combined list rather than leaving them split across separate rows.

Grouping key is (clean_person_name(pi_name_raw), normalize_institution(institution_raw))
-- the same light name-cleaning and institution normalization already used
elsewhere in this pipeline (common.py), so "Prof TAN, Siew Chong" and "Dr
TAN, Siew Chong" (same person, inconsistent title scraped across different
years) still merge into one row. This does NOT catch every possible
spelling variant of the same person (that's what Steps 1-4 of the matching
pipeline itself are for) -- it only merges rows whose raw PI name is
already this close to identical, which is the realistic case for the same
person's own repeated grants.

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
        # Keep the first-seen raw spellings -- downstream code (search_candidates.py)
        # re-cleans pi_name_raw itself, so the exact raw string just needs to be A
        # real one that was actually scraped for this person, not a canonical form.
        pi_name_raw = group_rows[0].get("pi_name_raw", "")
        institution_raw = group_rows[0].get("institution_raw", "")

        project_ids = [r.get("project_id", "") for r in group_rows if r.get("project_id")]
        award_years = sorted({r.get("award_year", "") for r in group_rows if r.get("award_year")})
        sample_title = next((r.get("project_title", "") for r in group_rows if r.get("project_title")), "")

        # Real published paper titles (if any), pulled from RGC's own completion-report
        # data across ALL of this PI's grants -- NOT the same as sample_project_title,
        # which is just the grant's own proposed title (see auto_classify_publication_
        # match.py's docstring for why those two are different strings in practice).
        # Carried through here so a human reviewer can cross-check a candidate directly
        # against OpenAlex without having to dig into rgc_awards.csv separately.
        known_titles = []
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
