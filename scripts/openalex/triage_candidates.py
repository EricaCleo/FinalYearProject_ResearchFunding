"""
Pre-triage for author_candidates_for_review.csv: groups candidate rows by PI and
flags each PI as likely-confirmed, needs-review, or no-candidate, based on
institution_match and name_similarity. This does NOT make the final decision —
it only tells you where to spend your manual-review time first. You still fill
in reviewer_decision yourself per RGC_to_OpenAlex_Author_Linkage_Guide.md.

Usage:
    python triage_candidates.py --input author_candidates_for_review.csv \
        --out triage_summary.csv
"""
import argparse
import csv
from collections import defaultdict

NAME_SIMILARITY_THRESHOLD = 80


def triage_pi(rows: list[dict]) -> dict:
    institution_matched = [r for r in rows if r.get("institution_match") == "1"]

    if len(institution_matched) == 1:
        candidate = institution_matched[0]
        if float(candidate.get("name_similarity") or 0) >= NAME_SIMILARITY_THRESHOLD:
            return {
                "triage_bucket": "likely_confirmed",
                "suggested_candidate_id": candidate["candidate_author_id"],
                "suggested_candidate_name": candidate["candidate_display_name"],
                "reason": "Only candidate with institution match, high name similarity",
            }

    if len(institution_matched) > 1:
        return {
            "triage_bucket": "needs_review",
            "suggested_candidate_id": "",
            "suggested_candidate_name": "",
            "reason": f"{len(institution_matched)} candidates share the RGC institution",
        }

    if len(institution_matched) == 0:
        return {
            "triage_bucket": "needs_review",
            "suggested_candidate_id": "",
            "suggested_candidate_name": "",
            "reason": "No candidate matched the RGC institution — check manually, may be not_found",
        }

    return {
        "triage_bucket": "needs_review",
        "suggested_candidate_id": "",
        "suggested_candidate_name": "",
        "reason": "Unclear evidence, review manually",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="author_candidates_for_review.csv or _pilot.csv")
    parser.add_argument("--out", default="triage_summary.csv")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_pi = defaultdict(list)
    for row in rows:
        by_pi[(row["pi_name_raw"], row["rgc_institution"])].append(row)

    summary_rows = []
    for (pi_name_raw, rgc_institution), pi_rows in by_pi.items():
        triage = triage_pi(pi_rows)
        summary_rows.append({
            "pi_name_raw": pi_name_raw,
            "rgc_institution": rgc_institution,
            "n_candidates": len(pi_rows),
            "n_institution_matched": sum(1 for r in pi_rows if r.get("institution_match") == "1"),
            **triage,
        })

    summary_rows.sort(key=lambda r: (r["triage_bucket"] != "needs_review", r["pi_name_raw"]))

    fieldnames = ["pi_name_raw", "rgc_institution", "n_candidates", "n_institution_matched",
                  "triage_bucket", "suggested_candidate_id", "suggested_candidate_name", "reason"]
    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(summary_rows)

    n_likely = sum(1 for r in summary_rows if r["triage_bucket"] == "likely_confirmed")
    n_needs_review = len(summary_rows) - n_likely
    print(f"{len(summary_rows)} PIs total")
    print(f"  {n_likely} likely_confirmed (quick check + rubber-stamp)")
    print(f"  {n_needs_review} needs_review (do the full manual check)")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
