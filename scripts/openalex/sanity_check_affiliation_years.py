"""
Second sanity check for already-confirmed matches: was this candidate
actually affiliated with the PI's institution during the grant's real
award year(s)? Complements sanity_check_confirmed.py's topic check with a
harder, non-fuzzy signal -- affiliation years are a recorded fact, not a
keyword-overlap judgment call.

Built after a case where the confirmed candidate DID have the right
institution in their history, but only for a brief period years before the
grant was even awarded -- institution_match only checks "did this
institution ever appear", not "was it there at the right time".

Does a live OpenAlex lookup per confirmed PI (affiliation years aren't
cached anywhere), so budget time/quota for a large confirmed set.

Usage:
    python sanity_check_affiliation_years.py \
        --crosswalk crosswalk_stage1.csv --crosswalk crosswalk_stage2.csv ... \
        --rgc-awards rgc_awards.csv \
        --out flagged_for_year_review.csv \
        --tolerance-years 3
"""
import argparse
import csv

from common import openalex_get, short_openalex_id


def split_ids(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    parts = value.split("|") if "|" in value else value.split(",")
    return [p.strip() for p in parts if p.strip()]


def get_affiliation_years(author_id: str, rgc_institution_id: str) -> list[int]:
    # fetch years this author was affiliated with the given institution,
    # from OpenAlex's `affiliations` field: [{institution, years: [...]}]
    data = openalex_get(f"authors/{author_id}")
    years = []
    for affiliation in data.get("affiliations") or []:
        inst = (affiliation.get("institution") or {})
        if short_openalex_id(inst.get("id")) == rgc_institution_id:
            years.extend(affiliation.get("years") or [])
    return years


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--crosswalk", required=True, action="append",
                         help="One or more crosswalk_stageN.csv files to check. Repeat flag for multiple.")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out", default="flagged_for_year_review.csv")
    parser.add_argument("--tolerance-years", type=int, default=3,
                         help="How many years of slack around the grant's award_year still counts as "
                              "plausible (grants run for years after the award, and OpenAlex affiliation "
                              "year data isn't always complete down to the exact year). Default 3.")
    args = parser.parse_args()

    with open(args.rgc_awards, encoding="utf-8-sig") as f:
        rgc_by_id = {row["project_id"]: row for row in csv.DictReader(f)}

    from common import institution_openalex_id

    confirmed_rows = []
    for path in args.crosswalk:
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        confirmed_rows.extend(r for r in rows if r.get("decision", "").startswith("confirmed"))

    print(f"{len(confirmed_rows)} confirmed PIs to check (this does live OpenAlex lookups -- may take a while)")

    flagged, clean, skipped = [], 0, 0
    for i, r in enumerate(confirmed_rows, start=1):
        project_ids = split_ids(r.get("rgc_project_ids", ""))
        award_years = []
        institution_id = ""
        for pid in project_ids:
            award = rgc_by_id.get(pid)
            if award:
                if award.get("award_year", "").strip():
                    award_years.append(int(award["award_year"]))
                if not institution_id:
                    institution_id = institution_openalex_id(award.get("institution_raw", ""))

        if not award_years or not institution_id:
            skipped += 1
            continue

        candidate_ids = split_ids(r.get("openalex_author_ids", ""))
        all_years = []
        for cid in candidate_ids:
            try:
                all_years.extend(get_affiliation_years(cid, institution_id))
            except Exception as exc:
                print(f"  [{i}/{len(confirmed_rows)}] {r['pi_name_raw']}: lookup failed for {cid} ({exc}), skipping")

        if not all_years:
            flagged.append({**r, "award_years": "|".join(map(str, award_years)),
                             "candidate_affiliation_years_at_institution": "(none recorded)"})
            continue

        min_gap = min(abs(ay - cy) for ay in award_years for cy in all_years)
        if min_gap > args.tolerance_years:
            flagged.append({**r, "award_years": "|".join(map(str, award_years)),
                             "candidate_affiliation_years_at_institution": "|".join(map(str, sorted(set(all_years))))})
        else:
            clean += 1

        if i % 10 == 0:
            print(f"  ...{i}/{len(confirmed_rows)} checked")

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["pi_name_raw", "rgc_institution", "stage", "openalex_author_ids",
                      "openalex_display_names", "award_years", "candidate_affiliation_years_at_institution"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flagged)

    print(f"\n{clean} show affiliation years consistent with the grant's award year(s) -- no flag")
    print(f"{skipped} skipped (missing award_year or unrecognized institution)")
    print(f"{len(flagged)} FLAGGED for manual review (no recorded affiliation year near the award year) -> {args.out}")


if __name__ == "__main__":
    main()
