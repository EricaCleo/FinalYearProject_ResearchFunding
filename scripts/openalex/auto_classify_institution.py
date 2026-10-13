"""
Stage 1 of the automated (no manual review) PI matching pipeline, per
supervisor instruction to replace one-by-one manual checking with a
filtering system. Starts with institution matching as the first, strongest
automatic filter.

Rule per PI (grouped by pi_name_raw + rgc_institution):
  - exactly 1 candidate has institution_match=1            -> auto "confirmed"
  - 0 candidates have institution_match=1                  -> auto "not_found"
  - 2+ candidates have institution_match=1                 -> "needs_stage2"
    (institution alone can't resolve it -- goes to the next filter stage,
    e.g. topic overlap, ORCID, exact name match)

This does NOT check affiliation timing (whether the candidate was at that
institution during the award year specifically) -- it only checks whether
the institution appears anywhere in the candidate's OpenAlex affiliation
history. That's a coarser signal than the guide's original manual-review
process used; add a timing-aware stage if too many false positives turn up.

Usage:
    python auto_classify_institution.py --input author_candidates_pilot.csv \
        --out-crosswalk pi_openalex_crosswalk.csv \
        --out-stage2 needs_stage2_filtering.csv \
        --out-not-found not_found.csv
"""
import argparse
import csv
from collections import defaultdict


def classify_pi(rows: list[dict]) -> dict:
    institution_matched = [r for r in rows if r.get("institution_match") == "1"]

    if len(institution_matched) == 1:
        candidate = institution_matched[0]
        return {
            "decision": "confirmed",
            "stage": "institution",
            "candidate_author_id": candidate["candidate_author_id"],
            "candidate_display_name": candidate["candidate_display_name"],
            "candidate_orcid": candidate.get("candidate_orcid", ""),
            "reason": "Single candidate matched the RGC institution",
        }

    if len(institution_matched) == 0:
        return {
            "decision": "not_found",
            "stage": "institution",
            "candidate_author_id": "",
            "candidate_display_name": "",
            "candidate_orcid": "",
            "reason": "No candidate matched the RGC institution",
        }

    return {
        "decision": "needs_stage2",
        "stage": "institution",
        "candidate_author_id": "",
        "candidate_display_name": "",
        "candidate_orcid": "",
        "reason": f"{len(institution_matched)} candidates matched the RGC institution -- institution alone can't resolve this",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="author_candidates_pilot.csv or similar from search_candidates.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk.csv", help="Auto-confirmed matches")
    parser.add_argument("--out-stage2", default="needs_stage2_filtering.csv", help="Ambiguous cases for the next filter stage (full candidate rows kept)")
    parser.add_argument("--out-not-found", default="not_found.csv", help="PIs with zero institution-matched candidates")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_pi = defaultdict(list)
    for row in rows:
        by_pi[(row["pi_name_raw"], row["rgc_institution"])].append(row)

    crosswalk_rows, not_found_rows, stage2_rows = [], [], []
    for (pi_name_raw, rgc_institution), pi_rows in by_pi.items():
        result = classify_pi(pi_rows)
        base = {
            "pi_name_raw": pi_name_raw,
            "rgc_institution": rgc_institution,
            "rgc_project_ids": pi_rows[0].get("rgc_project_ids", ""),
        }

        if result["decision"] == "confirmed":
            crosswalk_rows.append({**base, **result})
        elif result["decision"] == "not_found":
            not_found_rows.append({**base, "reason": result["reason"]})
        else:
            for pi_row in pi_rows:
                stage2_rows.append(pi_row)

    crosswalk_fields = ["pi_name_raw", "rgc_institution", "rgc_project_ids", "decision", "stage",
                         "candidate_author_id", "candidate_display_name", "candidate_orcid", "reason"]
    with open(args.out_crosswalk, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=crosswalk_fields)
        writer.writeheader()
        writer.writerows(crosswalk_rows)

    with open(args.out_not_found, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["pi_name_raw", "rgc_institution", "rgc_project_ids", "reason"])
        writer.writeheader()
        writer.writerows(not_found_rows)

    if stage2_rows:
        with open(args.out_stage2, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(stage2_rows[0].keys()))
            writer.writeheader()
            writer.writerows(stage2_rows)

    n_pis = len(by_pi)
    n_stage2_pis = len(set((r["pi_name_raw"], r["rgc_institution"]) for r in stage2_rows))
    print(f"{n_pis} PIs total")
    print(f"  {len(crosswalk_rows)} confirmed by institution -> {args.out_crosswalk}")
    print(f"  {len(not_found_rows)} not_found (no institution match) -> {args.out_not_found}")
    print(f"  {n_stage2_pis} PIs need stage 2 filtering ({len(stage2_rows)} candidate rows) -> {args.out_stage2}")


if __name__ == "__main__":
    main()
