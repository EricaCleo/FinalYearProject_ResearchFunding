"""
Stage 7: compares RGC's own `field`/`panel` columns against each tied
candidate's OpenAlex topics. Confirms if exactly one institution-matched
candidate shares 2+ specific keywords with RGC's recorded subject area.

Needs rgc_awards.csv for field/panel by project_id.

Known limitation: RGC's field/panel are broad discipline names while
OpenAlex topics are narrow research niches, so exact-word overlap is weak
and this stage won't resolve most remaining ties by itself.

Bug fixed after a manual spot-check: this stage originally had no
institution check at all (every other stage requires one) and confirmed
on just 1 overlapping keyword. A 5-row sample of its output found 4 of 5
wrong, all matched via one generic shared word to profiles with no real
connection to the PI's institution. Now requires institution_match and 2+
keywords, so it confirms noticeably fewer PIs than before -- most of the
old confirmations were this bug, not real matches.

Usage:
    python auto_classify_field_panel.py --input still_unresolved_stage6.csv \
        --rgc-awards rgc_awards.csv \
        --out-crosswalk pi_openalex_crosswalk_stage7.csv \
        --out-unresolved truly_unresolved_final.csv
"""
import argparse
import csv
import re
from collections import defaultdict

# generic words broad enough to appear in almost any STEM candidate's topics
STOPWORDS = {
    "and", "the", "of", "for", "in", "on", "with", "to", "a", "an", "based",
    "study", "studies", "analysis", "research", "method", "methods", "using",
    "application", "applications", "system", "systems", "model", "models",
    "science", "sciences", "materials", "engineering", "technology",
}


def split_ids(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    parts = value.split("|") if "|" in value else value.split(",")
    return [p.strip() for p in parts if p.strip()]


def topic_keywords(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z]+", (text or "").lower())
    return frozenset(t for t in tokens if len(t) >= 4 and t not in STOPWORDS)


def classify_pi(rows: list[dict], rgc_awards_by_id: dict[str, dict]) -> dict | None:
    project_ids = split_ids(rows[0].get("rgc_project_ids", ""))
    rgc_text_parts = []
    for pid in project_ids:
        award = rgc_awards_by_id.get(pid)
        if award:
            rgc_text_parts.append(award.get("field", ""))
            rgc_text_parts.append(award.get("panel", ""))

    rgc_keywords = topic_keywords(" ".join(rgc_text_parts))
    if not rgc_keywords:
        return None  # no RGC field/panel data to check against -- can't verify this way

    # institution_match + 2 keywords required -- see module docstring for why
    matched = []
    for r in rows:
        if r.get("institution_match") != "1":
            continue
        candidate_keywords = topic_keywords(r.get("candidate_topics", ""))
        overlap = candidate_keywords & rgc_keywords
        if len(overlap) >= 2:
            matched.append((r, overlap))

    if len(matched) == 1:
        candidate, overlap = matched[0]
        return {
            "decision": "confirmed",
            "stage": "field_panel",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": (f"Candidate's OpenAlex topics share {len(overlap)} specific keyword(s) "
                       f"({', '.join(sorted(overlap))}) with RGC's own recorded field/panel for this PI's "
                       f"grant(s), and no other tied candidate's topics overlap this much"),
        }

    return None  # 0 or 2+ candidates overlap -- don't guess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, action="append",
                         help="Unresolved candidate rows. Repeat flag for multiple.")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage7.csv")
    parser.add_argument("--out-unresolved", default="truly_unresolved_final.csv")
    args = parser.parse_args()

    with open(args.rgc_awards, encoding="utf-8-sig") as f:
        rgc_awards_by_id = {row["project_id"]: row for row in csv.DictReader(f)}

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
        result = classify_pi(pi_rows, rgc_awards_by_id)
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
    print(f"{n_pis} PIs entered stage 7")
    print(f"  {len(crosswalk_rows)} confirmed by RGC field/panel match -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs truly unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
