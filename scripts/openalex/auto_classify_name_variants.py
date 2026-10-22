"""
Stage 4: handles three name-formatting gaps exact matching misses.

1. Initials vs. full given name, e.g. "Kannie W. Y. Chan" for RGC's
   "Kannie Wai Yan Chan" -- reduce every token but the surname to its
   first letter on both sides before comparing.
2. Compound given-name splitting, e.g. "Wenxiong" vs. "Wen-Xiong" --
   compare with all non-letter characters stripped, no tokenization.
3. One extra given name on OpenAlex's side not recorded by RGC at all
   (e.g. an added English name like "Rosa Ho Man Chan" for RGC's
   "Ho-man Chan") -- requires every RGC name token to be present, capped
   at exactly one extra token to avoid false-positiving on unrelated names.

A candidate matches if any of the three succeed. Surname must still match
on all of them; only applies to candidates still unresolved after stage 3.

Usage:
    python auto_classify_name_variants.py --input not_found.csv --input2 still_unresolved.csv \
        --out-crosswalk pi_openalex_crosswalk_stage4.csv \
        --out-unresolved truly_unresolved.csv
"""
import argparse
import csv
import re
from collections import defaultdict


def raw_tokens(name: str) -> list[str]:
    return re.findall(r"[a-z]+", (name or "").lower())


def initials_form(name: str) -> frozenset[str]:
    tokens = raw_tokens(name)
    if not tokens:
        return frozenset()
    *given, surname = tokens
    reduced = {t[0] if len(t) > 1 else t for t in given}
    reduced.add(surname)
    return frozenset(reduced)


def concat_form(name: str) -> str:
    return "".join(raw_tokens(name))


def token_set(name: str) -> frozenset[str]:
    return frozenset(raw_tokens(name))


def one_extra_given_name(pi_name_clean: str, candidate_name: str) -> bool:
    pi_tokens = token_set(pi_name_clean)
    candidate_tokens = token_set(candidate_name)
    if not pi_tokens or not pi_tokens.issubset(candidate_tokens):
        return False
    return len(candidate_tokens - pi_tokens) == 1


def names_match(pi_name_clean: str, candidate_name: str) -> str | None:
    if initials_form(pi_name_clean) == initials_form(candidate_name) and initials_form(pi_name_clean):
        return "initials"
    if concat_form(pi_name_clean) == concat_form(candidate_name) and concat_form(pi_name_clean):
        return "concatenated"
    if one_extra_given_name(pi_name_clean, candidate_name):
        return "extra_given_name"
    return None


def classify_pi(rows: list[dict]) -> dict | None:
    pi_clean = rows[0].get("pi_name_clean", "")
    matches = []
    for r in rows:
        if r.get("institution_match") != "1":
            continue
        kind = names_match(pi_clean, r.get("candidate_display_name", ""))
        if kind:
            matches.append((r, kind))

    if len(matches) == 1:
        candidate, kind = matches[0]
        return {
            "decision": "confirmed",
            "stage": "name_variant",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": f"Institution-matched, name matched via {kind} comparison (not exact token match), only one such candidate",
        }

    if len(matches) > 1:
        # same as stage 3: a shared ORCID among the tied matches proves one identity
        orcid_counts = defaultdict(list)
        for r, _ in matches:
            orcid = r.get("candidate_orcid")
            if orcid:
                orcid_counts[orcid].append(r)
        duplicated = [g for g in orcid_counts.values() if len(g) > 1]
        if len(duplicated) == 1:
            group = duplicated[0]
            return {
                "decision": "confirmed",
                "stage": "name_variant",
                "openalex_author_ids": "|".join(r["candidate_author_id"] for r in group),
                "openalex_display_names": "|".join(r["candidate_display_name"] for r in group),
                "openalex_orcid": group[0].get("candidate_orcid", ""),
                "reason": (f"Institution-matched, {len(matches)} candidates matched by name variant, "
                           f"{len(group)} of them share the same ORCID (proven single identity) -- all retained"),
            }

    return None  # 0 matches, or 2+ with no provable shared identity -- don't guess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, action="append",
                         help="One or more input files (not_found.csv, still_unresolved.csv). Repeat flag for multiple.")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage4.csv")
    parser.add_argument("--out-unresolved", default="truly_unresolved.csv")
    args = parser.parse_args()

    rows = []
    for path in args.input:
        with open(path, encoding="utf-8-sig") as f:
            file_rows = list(csv.DictReader(f))
        if file_rows and "candidate_author_id" not in file_rows[0]:
            print(f"  skipping {path}: no candidate rows (already fully resolved file)")
            continue
        rows.extend(file_rows)

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
    print(f"{n_pis} PIs entered stage 4")
    print(f"  {len(crosswalk_rows)} confirmed by name-variant match -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs still unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
