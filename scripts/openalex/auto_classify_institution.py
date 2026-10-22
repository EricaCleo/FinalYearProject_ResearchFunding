"""
Stage 1: confirm a PI when exactly one candidate matches both the RGC
institution and an exact name-token match (same words, order-independent).

Rule per PI:
  - exactly 1 match -> confirmed
  - 0 matches        -> not_found
  - 2+ matches       -> needs_stage2 (next filter, e.g. ORCID)

Doesn't check affiliation timing, just whether the institution appears
anywhere in the candidate's history.

Usage:
    python auto_classify_institution.py --input author_candidates_pilot.csv \
        --out-crosswalk pi_openalex_crosswalk.csv \
        --out-stage2 needs_stage2_filtering.csv \
        --out-not-found not_found.csv \
        --out-no-exact-match no_exact_match_candidates.csv
"""
import argparse
import csv
import re
from collections import defaultdict


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", (name or "").lower()))


def classify_pi(rows: list[dict]) -> dict:
    pi_tokens = name_tokens(rows[0].get("pi_name_clean", ""))
    matched = [
        r for r in rows
        if r.get("institution_match") == "1"
        and name_tokens(r.get("candidate_display_name", "")) == pi_tokens
    ]

    if len(matched) == 1:
        candidate = matched[0]
        return {
            "decision": "confirmed",
            "stage": "institution",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": "Single candidate matched both the RGC institution and an exact name-token match",
        }

    if len(matched) == 0:
        return {
            "decision": "not_found",
            "stage": "institution",
            "openalex_author_ids": "",
            "openalex_display_names": "",
            "openalex_orcid": "",
            "reason": "No candidate matched both the RGC institution and an exact name-token match",
        }

    return {
        "decision": "needs_stage2",
        "stage": "institution",
        "openalex_author_ids": "",
        "openalex_display_names": "",
        "openalex_orcid": "",
        "reason": f"{len(matched)} candidates matched both institution and exact name -- can't resolve at this stage",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="author_candidates_pilot.csv or similar from search_candidates.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk.csv", help="Auto-confirmed matches")
    parser.add_argument("--out-stage2", default="needs_stage2_filtering.csv", help="Ambiguous cases for the next filter stage (full candidate rows kept)")
    parser.add_argument("--out-not-found", default="not_found.csv", help="PIs with zero institution-matched candidates (summary)")
    parser.add_argument("--out-no-exact-match", default="no_exact_match_candidates.csv",
                         help="Same PIs as --out-not-found, but with full candidate rows kept for a later, looser-matching stage")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_pi = defaultdict(list)
    for row in rows:
        by_pi[(row["pi_name_raw"], row["rgc_institution"])].append(row)

    crosswalk_rows, not_found_rows, no_exact_match_rows, stage2_rows = [], [], [], []
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
            no_exact_match_rows.extend(pi_rows)
        else:
            for pi_row in pi_rows:
                stage2_rows.append(pi_row)

    crosswalk_fields = ["pi_name_raw", "rgc_institution", "rgc_project_ids", "decision", "stage",
                         "openalex_author_ids", "openalex_display_names", "openalex_orcid", "reason"]
    with open(args.out_crosswalk, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=crosswalk_fields)
        writer.writeheader()
        writer.writerows(crosswalk_rows)

    with open(args.out_not_found, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["pi_name_raw", "rgc_institution", "rgc_project_ids", "reason"])
        writer.writeheader()
        writer.writerows(not_found_rows)

    if no_exact_match_rows:
        with open(args.out_no_exact_match, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(no_exact_match_rows[0].keys()))
            writer.writeheader()
            writer.writerows(no_exact_match_rows)

    if stage2_rows:
        with open(args.out_stage2, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(stage2_rows[0].keys()))
            writer.writeheader()
            writer.writerows(stage2_rows)

    n_pis = len(by_pi)
    n_stage2_pis = len(set((r["pi_name_raw"], r["rgc_institution"]) for r in stage2_rows))
    print(f"{n_pis} PIs total")
    print(f"  {len(crosswalk_rows)} confirmed by institution -> {args.out_crosswalk}")
    print(f"  {len(not_found_rows)} not_found (no exact institution+name match) -> {args.out_not_found} "
          f"(full candidate rows kept in {args.out_no_exact_match} for a later looser-matching stage)")
    print(f"  {n_stage2_pis} PIs need stage 2 filtering ({len(stage2_rows)} candidate rows) -> {args.out_stage2}")


if __name__ == "__main__":
    main()
