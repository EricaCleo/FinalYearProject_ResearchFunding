"""
Stage 1 of the automated (no manual review) PI matching pipeline, per
supervisor instruction to replace one-by-one manual checking with a
filtering system. The rule is name + institution + unique candidate, per
supervisor's framing -- confirmed this way to validate accuracy before
applying it to the full dataset.

An earlier version of this script only checked institution_match, without
also requiring an exact name-token match -- so a candidate whose name was
only a loose/fuzzy match to the search query, but happened to be the only
one at the right institution, could have been auto-confirmed. Fixed: now
requires BOTH institution match AND an exact name-token match (same set of
words, order-independent) before counting a candidate at all.

Rule per PI (grouped by pi_name_raw + rgc_institution):
  - exactly 1 candidate has institution+exact-name match   -> auto "confirmed"
  - 0 candidates have institution+exact-name match          -> auto "not_found"
  - 2+ candidates have institution+exact-name match          -> "needs_stage2"
    (name+institution alone can't resolve it -- goes to the next filter
    stage, e.g. ORCID)

This does NOT check affiliation timing (whether the candidate was at that
institution during the award year specifically) -- it only checks whether
the institution appears anywhere in the candidate's OpenAlex affiliation
history. That's a coarser signal than the guide's original manual-review
process used; add a timing-aware stage if too many false positives turn up.

A "not_found" PI's full candidate rows are also written to --out-no-exact-match
(not just the PI name + reason in --out-not-found), so a later stage can
still search them with a looser name comparison (e.g. initials vs. spelled-
out given names) without re-querying OpenAlex.

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
