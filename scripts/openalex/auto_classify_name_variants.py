"""
Stage 4 of the automated PI matching pipeline: handles two specific name-
formatting gaps that exact name-token matching (stages 1-3) correctly
declines to guess, found in the pilot:

Pattern 1 -- initials vs. full given name. OpenAlex sometimes stores a
middle/given name as initials instead of spelling it out, e.g.
"Kannie W. Y. Chan" for RGC's "Kannie Wai Yan Chan", or "S.Y.R. Hui" for
"Ron Shu-Yuen Hui". Handled by reducing every token except the surname (the
last token, by this project's existing convention) to its first letter on
BOTH sides before comparing -- "wai"/"yan" -> "w"/"y" matches "w"/"y" on the
OpenAlex side directly.

Pattern 2 -- compound given-name splitting. RGC may spell a given name as
one word ("Wenxiong") while OpenAlex splits it into two ("Wen-Xiong").
Handled by also comparing the two names with ALL non-letter characters
stripped and no tokenization at all (so "wenxiong wang" and "wen-xiong
wang" both become "wenxiongwang").

A candidate counts as a match if EITHER comparison succeeds. This is
intentionally still strict: it does not touch surname matching (which
stays exact), and it does not accept initials unless the number of
remaining given-name tokens lines up. It is only applied to candidates
institution-matched but left unresolved by stages 1-3 -- never loosens
anything the stricter stages already decided.

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


def names_match(pi_name_clean: str, candidate_name: str) -> str | None:
    if initials_form(pi_name_clean) == initials_form(candidate_name) and initials_form(pi_name_clean):
        return "initials"
    if concat_form(pi_name_clean) == concat_form(candidate_name) and concat_form(pi_name_clean):
        return "concatenated"
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

    if len(matches) != 1:
        return None  # 0 -> still no match; 2+ -> ambiguous, don't guess

    candidate, kind = matches[0]
    return {
        "decision": "confirmed",
        "stage": "name_variant",
        "openalex_author_ids": candidate["candidate_author_id"],
        "openalex_display_names": candidate["candidate_display_name"],
        "openalex_orcid": candidate.get("candidate_orcid", ""),
        "reason": f"Institution-matched, name matched via {kind} comparison (not exact token match), only one such candidate",
    }


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
