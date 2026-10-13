"""
Stage 4 of the automated PI matching pipeline: exact name-token match +
works_count filter.

Stages 1-3 used fuzzy name_similarity (rapidfuzz ratio), which can score a
clearly different name highly just for sharing a surname and similar length
-- caught in the pilot: "Yu Liu" scored high against "Qiang Liu", and
"Zhanhu Guo" / "Xing Hua Zheng" (extra name tokens) scored high against
"Zaiping Guo" / "Xing Zheng". This stage uses an exact match instead: the
candidate's name, tokenized and lowercased, must be the EXACT SAME SET of
words as the PI's cleaned name (order-independent, so "Hong Yan" matches
"Yan Hong"), not just similar.

Rule per PI, among institution-matched candidates with an exact name-token
match:
  - exactly 1 exact-name candidate              -> auto "confirmed"
  - 2+ exact-name candidates                    -> auto-confirm the one with
                                                    the highest works_count,
                                                    ONLY if it's not tied
  - 0 exact-name candidates                     -> still unresolved

Usage:
    python auto_classify_exact_name.py --input needs_stage4_filtering.csv \
        --out-crosswalk pi_openalex_crosswalk_stage4.csv \
        --out-unresolved still_unresolved.csv
"""
import argparse
import csv
import re
from collections import defaultdict


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", (name or "").lower()))


def classify_pi(rows: list[dict]) -> dict | None:
    pi_tokens = name_tokens(rows[0].get("pi_name_clean", ""))
    if not pi_tokens:
        return None

    exact_matches = [
        r for r in rows
        if r.get("institution_match") == "1"
        and name_tokens(r.get("candidate_display_name", "")) == pi_tokens
    ]
    if not exact_matches:
        return None

    if len(exact_matches) == 1:
        candidate = exact_matches[0]
        reason = "Exact name-token match (institution-matched), only one such candidate"
    else:
        works_counts = [int(r.get("works_count") or 0) for r in exact_matches]
        best = max(works_counts)
        if works_counts.count(best) > 1:
            return None  # genuine tie even among exact-name matches, don't guess
        candidate = exact_matches[works_counts.index(best)]
        reason = f"Exact name-token match ({len(exact_matches)} candidates), highest works_count ({best})"

    return {
        "decision": "confirmed",
        "stage": "exact_name",
        "candidate_author_id": candidate["candidate_author_id"],
        "candidate_display_name": candidate["candidate_display_name"],
        "candidate_orcid": candidate.get("candidate_orcid", ""),
        "reason": reason,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="needs_stage4_filtering.csv from auto_classify_topic_workcount.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage4.csv", help="Newly confirmed matches")
    parser.add_argument("--out-unresolved", default="still_unresolved.csv", help="PIs no automated filter could resolve")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_pi = defaultdict(list)
    for row in rows:
        by_pi[(row["pi_name_raw"], row["rgc_institution"])].append(row)

    crosswalk_rows, unresolved_rows = [], []
    for (pi_name_raw, rgc_institution), pi_rows in by_pi.items():
        result = classify_pi(pi_rows)
        if result:
            crosswalk_rows.append({
                "pi_name_raw": pi_name_raw,
                "rgc_institution": rgc_institution,
                "rgc_project_ids": pi_rows[0].get("rgc_project_ids", ""),
                **result,
            })
        else:
            unresolved_rows.extend(pi_rows)

    crosswalk_fields = ["pi_name_raw", "rgc_institution", "rgc_project_ids", "decision", "stage",
                         "candidate_author_id", "candidate_display_name", "candidate_orcid", "reason"]
    with open(args.out_crosswalk, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=crosswalk_fields)
        writer.writeheader()
        writer.writerows(crosswalk_rows)

    if unresolved_rows:
        with open(args.out_unresolved, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(unresolved_rows[0].keys()))
            writer.writeheader()
            writer.writerows(unresolved_rows)

    n_pis = len(by_pi)
    n_unresolved_pis = len(set((r["pi_name_raw"], r["rgc_institution"]) for r in unresolved_rows))
    print(f"{n_pis} PIs entered stage 4")
    print(f"  {len(crosswalk_rows)} confirmed by exact name match -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs still unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
