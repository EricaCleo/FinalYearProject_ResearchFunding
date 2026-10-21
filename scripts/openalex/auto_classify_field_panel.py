"""
Stage 7 of the automated PI matching pipeline: for PIs still tied after
stages 1-6, compares RGC's OWN scraped `field` and `panel` columns (the
subject area and broad discipline RGC itself recorded for the grant)
against each tied candidate's OpenAlex-assigned topics. If exactly one
candidate's topics share enough specific keywords with RGC's own stated
field/panel, confirm it.

This replaces an earlier version of this stage that used Semantic
Scholar's API to pull a PI's real paper titles (as an automatable
equivalent of manually checking Google Scholar) and compared THOSE
against OpenAlex topics. That worked for the one case tested, but didn't
actually use anything scraped from RGC at all -- both sides of the
comparison were external data (Semantic Scholar, OpenAlex). That breaks
this project's own rule that automated filtering should be grounded in
data RGC itself provided, the same reasoning that got an earlier
topic/work-count stage dropped entirely (auto_classify_topic_workcount.py,
removed earlier in this project). This version fixes that: RGC's
`field`/`panel` columns are the actual ground truth being checked against.
A candidate's own OpenAlex topics are still used (there's no way around
that -- it's the only per-candidate data available to compare), but they
describe the candidate being evaluated, not an independent "truth" source
standing in for RGC's.

Requires a copy of rgc_awards.csv (output of combine_rgc_data.py) to look
up each PI's field/panel by project_id.

Known limitation, found while building this: RGC's `field`/`panel` values
are broad discipline names ("Materials Science", "Engineering"), while a
candidate's OpenAlex `candidate_topics` are narrow research niches
("Metallic Glasses", "High Entropy Alloys"). Exact-word overlap between
those two vocabularies is weak -- in practice the only shared word between
an RGC field and either a correct or incorrect candidate's topics is often
a generic term like "materials" itself, which doesn't distinguish anyone
(both candidates can plausibly carry it). There's also no stemming, so
"metallurgy" vs "metallurgical" won't match even when they name the same
discipline.

REAL BUG, found via manual spot-check (not just a theoretical risk): this
stage was the only one in the entire pipeline (1-6 all require it) that
never checked institution_match at all -- it only required ONE overlapping
keyword, with no institution-match gate to catch a wrong candidate at all.
Combined with the weak-keyword-vocabulary problem above, this produced
real false positives in practice: a 5-row random spot-check against
already-"confirmed" field_panel matches found 4 of 5 WRONG, every one of
them a massive conflated OpenAlex profile (many different unrelated real
people merged into one ID by OpenAlex, each with a huge inflated
works_count) that shared one generic word ("mechanical", "medicine",
"health") with RGC's field/panel and had ZERO actual connection to the
PI's real institution. Fixed by (1) requiring institution_match == 1
before a candidate counts at all, same baseline every other stage already
enforces, and (2) raising the overlap requirement from 1 to 2 keywords as
additional insurance, since a single generic word is still weak evidence
even with institution confirmed. This stage stays SAFE in its *remaining*
design (ambiguous or absent overlap still just declines rather than
guesses), but expect it to confirm noticeably fewer PIs than before this
fix -- most of its previous "confirmations" were the bug, not real
matches.

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

# Generic words that would create false "overlap" between any two research fields.
# "materials"/"engineering" are included because they're broad enough to appear in
# almost any STEM candidate's topics regardless of their actual specific niche --
# sharing just that word with RGC's field/panel isn't evidence of anything.
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

    # institution_match is required here -- same baseline every other stage in
    # this pipeline already enforces. Its absence was a real bug (see module
    # docstring): without it, a candidate with zero actual connection to the
    # PI's institution could still get confirmed purely on a coincidental
    # shared keyword, and in practice this is exactly what happened.
    #
    # Requires 2+ overlapping keywords (raised from 1) as additional insurance
    # -- a single generic word is weak evidence even with institution now
    # confirmed, and the spot-check false positives found live all matched on
    # just one generic term ("mechanical", "medicine", "health").
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
