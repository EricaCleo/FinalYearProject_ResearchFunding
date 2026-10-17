"""
Stage 3 (final stage) of the automated PI matching pipeline: exact
name-token match + works_count filter.

Stages 1-2 (institution, ORCID) can leave several candidates tied. An
earlier version of this pipeline broke ties with fuzzy name_similarity
(rapidfuzz ratio) and, separately, a topic-keyword-overlap check -- both
were dropped. Fuzzy similarity was tested against the pilot data and found
unreliable: clearly wrong candidates ("Yu Liu" vs "Qiang Liu", "Zhanhu Guo"
vs "Zaiping Guo", "Xing Hua Zheng" vs "Xing Zheng") scored as high as real
matches, because OpenAlex's own alternate-name data is noisy -- no
threshold separates real from false. Topic overlap was dropped because it
leans on an OpenAlex-generated label (the candidate's topics), not
anything scraped from RGC, so it added opinion without adding reliable
evidence once name matching was already exact.

This stage uses an EXACT match instead: the candidate's name, tokenized
and lowercased, must be the exact same SET of words as the PI's cleaned
name (order-independent, so "Hong Yan" matches "Yan Hong"), not just
similar. This had zero false positives across the full 40-PI pilot.

When 2+ candidates are left tied on exact name + institution, works_count
only tells you who's more PROLIFIC, not who's CORRECT -- it's only valid
evidence once we have PROOF the tied candidates are fragments of one real
person, not a guess. The only such proof available is 2+ candidates sharing
the literal SAME non-empty ORCID (self-registered per human, so identical
ORCID guarantees identical person). An earlier version of this script
treated "no conflicting ORCIDs" as safe, which wrongly included cases where
nobody had an ORCID at all, or only one candidate did -- that's missing
information, not proof of a single identity, and is a materially weaker
(and incorrect) standard. Now works_count only breaks a tie WITHIN a group
of candidates proven identical by a shared ORCID; everything else --
including "nobody has an ORCID" -- is left unresolved rather than guessed.

Per supervisor feedback: when 2+ candidates share a proven identity (same
ORCID), don't pick only the highest-works_count one and discard the rest --
retain ALL of them. They're genuinely the same real person, so their
publication records will need to be combined later (deduped by OpenAlex
Work ID) rather than losing whatever the discarded profiles hold. This
script now outputs every ID in a proven group, not just the "winner."

Rule per PI, among institution-matched candidates with an exact name-token
match:
  - exactly 1 exact-name candidate                 -> auto "confirmed",
                                                        1 OpenAlex ID
  - 2+ candidates share one ORCID (proven identity) -> auto "confirmed",
                                                        ALL IDs in that
                                                        proven group kept
                                                        (pipe-separated)
  - no such proven-identity group exists            -> still unresolved
                                                        (including when no
                                                        candidate has an
                                                        ORCID at all)
  - 0 exact-name candidates                         -> still unresolved (e.g.
                                                        the PI's real
                                                        OpenAlex name is
                                                        abbreviated to
                                                        initials)

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
