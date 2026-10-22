"""
Stage 2: ORCID tiebreak. Among candidates that already passed stage 1
(institution + exact name match), confirms if exactly one has an ORCID.
ORCID presence is corroborating evidence of a real, established profile,
not proof on its own -- it's only ever used on top of the stage 1 filter.

Rule: exactly 1 candidate has an ORCID -> confirmed; 0 or 2+ -> stage 3.

Usage:
    python auto_classify_orcid.py --input needs_stage2_filtering.csv \
        --out-crosswalk pi_openalex_crosswalk_stage2.csv \
        --out-stage3 needs_stage3_filtering.csv
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
    with_orcid = [r for r in exact_matches if (r.get("candidate_orcid") or "").strip()]

    if len(with_orcid) == 1:
        candidate = with_orcid[0]
        return {
            "decision": "confirmed",
            "stage": "orcid",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": f"Institution+exact-name-matched; only this candidate (of {len(exact_matches)}) has an ORCID",
        }

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="needs_stage2_filtering.csv from auto_classify_institution.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage2.csv", help="Newly confirmed matches")
    parser.add_argument("--out-stage3", default="needs_stage3_filtering.csv", help="Still-ambiguous PIs (full candidate rows kept)")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_pi = defaultdict(list)
    for row in rows:
        by_pi[(row["pi_name_raw"], row["rgc_institution"])].append(row)

    crosswalk_rows, stage3_rows = [], []
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
            stage3_rows.extend(pi_rows)

    crosswalk_fields = ["pi_name_raw", "rgc_institution", "rgc_project_ids", "decision", "stage",
                         "openalex_author_ids", "openalex_display_names", "openalex_orcid", "reason"]
    with open(args.out_crosswalk, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=crosswalk_fields)
        writer.writeheader()
        writer.writerows(crosswalk_rows)

    if stage3_rows:
        with open(args.out_stage3, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(stage3_rows[0].keys()))
            writer.writeheader()
            writer.writerows(stage3_rows)

    n_pis = len(by_pi)
    n_stage3_pis = len(set((r["pi_name_raw"], r["rgc_institution"]) for r in stage3_rows))
    print(f"{n_pis} PIs entered stage 2")
    print(f"  {len(crosswalk_rows)} confirmed by ORCID -> {args.out_crosswalk}")
    print(f"  {n_stage3_pis} PIs still unresolved ({len(stage3_rows)} candidate rows) -> {args.out_stage3}")


if __name__ == "__main__":
    main()
