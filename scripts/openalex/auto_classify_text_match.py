"""
Stage 8 of the automated PI matching pipeline: for PIs still tied after
stages 1-7, pools several of RGC's own scraped free-text fields for each
grant (project title, abstract, layman's summary, and completion-report
narrative fields) and compares the combined text against each tied
candidate's OpenAlex-assigned topics. If exactly one candidate's topics
share enough specific keywords with that combined text, confirm it.

This is a sharper version of Stage 7's field/panel comparison. RGC's
`field`/`panel` columns are broad discipline names ("Engineering") that
barely discriminate between candidates in the same broad area -- that
stage's own docstring documents this as a known low-yield limitation. A
grant's own narrative text is specific research content (methods,
mechanisms, named sub-topics), so it should discriminate far better
between two same-institution, same-broad-field candidates -- exactly the
case Stage 7 can't resolve (e.g. an extremely common name with several
same-institution, same-discipline candidates).

This originally compared `abstract` alone (confirmed to cover ~77% of
rgc_awards.csv rows). Pooling in the other fields below adds real extra
coverage, not just redundancy -- each field is populated independently of
the others, so a project with no abstract can still have a layman_summary,
etc. Real coverage, confirmed from the raw per-year RGC CSVs (not yet
carried into rgc_awards.csv until combine_rgc_data.py was extended for
this): project_title 100%, abstract ~77%, layman_summary ~76%,
realisation_of_objectives/objectives_addressed/major_findings/
potential_development ~47-48% each. `objectives` (0% populated) and
`other_impact` (~11%, too sparse to be worth it) are excluded.

Requires a copy of rgc_awards.csv (output of combine_rgc_data.py, with its
extended OUTPUT_COLUMNS) to look up each PI's text fields by project_id.

Usage:
    python auto_classify_text_match.py --input truly_unresolved_final.csv \
        --rgc-awards rgc_awards.csv \
        --out-crosswalk pi_openalex_crosswalk_stage8.csv \
        --out-unresolved truly_unresolved_stage8.csv
"""
import argparse
import csv
import re
from collections import defaultdict

# The RGC text fields pooled together per grant. Each is populated independently
# of the others (see module docstring for real coverage figures), so combining
# them adds real extra signal, not just redundant repetition.
TEXT_FIELDS = [
    "project_title", "abstract", "layman_summary", "realisation_of_objectives",
    "objectives_addressed", "major_findings", "potential_development",
]

# Generic grant-writing and STEM filler words that would create false "overlap"
# between RGC's text and almost any candidate's topics, regardless of actual
# subject match. Broader than Stage 7's STOPWORDS since prose carries a lot more
# connective/boilerplate language than a short field/panel label.
STOPWORDS = {
    "and", "the", "of", "for", "in", "on", "with", "to", "a", "an", "based",
    "study", "studies", "analysis", "research", "method", "methods", "using",
    "application", "applications", "system", "systems", "model", "models",
    "science", "sciences", "materials", "engineering", "technology",
    "project", "proposed", "propose", "proposal", "aim", "aims", "aimed",
    "objective", "objectives", "develop", "developed", "developing",
    "development", "investigate", "investigation", "investigated",
    "significant", "significantly", "important", "importance", "novel",
    "paper", "results", "result", "data", "approach", "approaches", "work",
    "will", "can", "shall", "this", "that", "these", "those", "which", "from",
    "into", "such", "also", "more", "most", "many", "some", "between",
    "among", "than", "further", "provide", "provides", "provided", "new",
    "understanding", "understand", "process", "processes", "design",
    "performance", "effect", "effects", "impact", "impacts", "key", "field",
    "related", "various", "different", "potential", "current", "general",
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
    text_parts = []
    for pid in project_ids:
        award = rgc_awards_by_id.get(pid)
        if award:
            for field in TEXT_FIELDS:
                text_parts.append(award.get(field, ""))

    rgc_keywords = topic_keywords(" ".join(text_parts))
    if not rgc_keywords:
        return None  # no RGC text data to check against -- can't verify this way

    # Unlike Stage 7's field/panel (short, so even 1 overlap is meaningful), this
    # pooled text is full prose with dozens of content words -- a single shared
    # word is much more likely to be coincidental. Requiring 2+ distinct
    # overlapping keywords keeps this stage as safe as the others
    # (ambiguous/thin overlap just means it declines, same as everywhere else
    # in this pipeline).
    matched = []
    for r in rows:
        candidate_keywords = topic_keywords(r.get("candidate_topics", ""))
        overlap = candidate_keywords & rgc_keywords
        if len(overlap) >= 2:
            matched.append((r, overlap))

    if len(matched) == 1:
        candidate, overlap = matched[0]
        return {
            "decision": "confirmed",
            "stage": "text_match",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": (f"Candidate's OpenAlex topics share {len(overlap)} specific keyword(s) "
                       f"({', '.join(sorted(overlap))}) with RGC's own recorded grant text "
                       f"(title/abstract/summary/completion-report fields), "
                       f"and no other tied candidate's topics overlap this much"),
        }

    return None  # 0 or 2+ candidates overlap -- don't guess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, action="append",
                         help="Unresolved candidate rows. Repeat flag for multiple.")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage8.csv")
    parser.add_argument("--out-unresolved", default="truly_unresolved_stage8.csv")
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
    print(f"{n_pis} PIs entered stage 8")
    print(f"  {len(crosswalk_rows)} confirmed by text match -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs truly unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
