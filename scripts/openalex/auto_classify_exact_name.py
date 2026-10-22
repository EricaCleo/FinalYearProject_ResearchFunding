"""
Stage 3: exact name-token match, with a shared-ORCID tiebreak for
fragmented profiles. Fuzzy name similarity and topic overlap were both
tried and dropped here -- fuzzy similarity let clearly wrong candidates
score as high as real matches, and topic overlap leans on OpenAlex's own
labels rather than RGC data.

Rule, among institution-matched candidates with an exact name-token match:
  - exactly 1 candidate       -> confirmed
  - 2+ share the same ORCID   -> confirmed, all IDs kept (proof of one
                                   person split across OpenAlex profiles;
                                   works_count only breaks ties within such
                                   a proven group, never used alone)
  - otherwise                 -> still unresolved

Usage:
    python auto_classify_exact_name.py --input needs_stage3_filtering.csv \
        --out-crosswalk pi_openalex_crosswalk_stage3.csv \
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
        group = exact_matches
        reason = "Exact name-token match (institution-matched), only one such candidate"
    else:
        # A group is only resolvable with PROOF the tied candidates are the
        # same real person, not a guess. The only positive proof available
        # is 2+ candidates sharing the literal SAME non-empty ORCID (ORCID
        # is self-registered per human, so identical ORCID = same human,
        # guaranteed). Absence of a conflict is NOT the same as proof: if
        # nobody has an ORCID, or only one candidate happens to have one,
        # that's missing information, not evidence of one person -- treating
        # it as "safe" was an earlier bug here. Only resolve a group that
        # shares a duplicated ORCID, and keep every member of that group
        # (not just the one with the most works) since they're all genuinely
        # the same person and their publication records will be combined
        # downstream.
        orcid_counts = defaultdict(list)
        for r in exact_matches:
            orcid = r.get("candidate_orcid")
            if orcid:
                orcid_counts[orcid].append(r)
        duplicated = [g for g in orcid_counts.values() if len(g) > 1]
        if len(duplicated) != 1:
            return None  # no proven single identity among the tied candidates

        group = duplicated[0]
        reason = f"Exact name-token match, {len(group)} candidates share the same ORCID (proven single identity) -- all retained"

    return {
        "decision": "confirmed",
        "stage": "exact_name",
        "openalex_author_ids": "|".join(r["candidate_author_id"] for r in group),
        "openalex_display_names": "|".join(r["candidate_display_name"] for r in group),
        "openalex_orcid": group[0].get("candidate_orcid", ""),
        "reason": reason,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="needs_stage3_filtering.csv from auto_classify_orcid.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage3.csv", help="Newly confirmed matches")
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
                         "openalex_author_ids", "openalex_display_names", "openalex_orcid", "reason"]
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
    print(f"{n_pis} PIs entered stage 3")
    print(f"  {len(crosswalk_rows)} confirmed by exact name match -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs still unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
