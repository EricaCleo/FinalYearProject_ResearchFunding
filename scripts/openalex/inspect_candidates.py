"""
Manual-review helper: for one PI, ranks their candidate OpenAlex profiles by
how much each candidate's OpenAlex topics overlap with that PI's grant text
(RGC's own project_title/abstract/layman_summary/completion-report fields).

This does NOT auto-confirm anything -- it's a read-only diagnostic to support
manual review, printing a ranked comparison for a human to read and judge.
An earlier attempt (auto_classify_text_match.py, Stage 8) tried to use this
same keyword-overlap idea to auto-decide matches and was dropped after real
bugs turned up live: it confirmed only when exactly one candidate cleared a
threshold (not whoever had the MOST overlap), so two topically-similar
candidates both clearing the bar silently killed a real match, and generic
engineering/CS terms inflated unrelated candidates' scores. None of that
matters here, since this script never decides anything -- it just ranks and
shows the evidence, including for genuinely unresolvable cases (e.g.
suspected-but-unprovable OpenAlex profile fragmentation, where there's no
ORCID available to prove several thin profiles are the same real person, but
topic overlap across all of them can still support that read for a written-up
manual decision).

Usage:
    python inspect_candidates.py --pi "Prof Tan, Siew Chong" \
        --input unresolved_stage7.csv \
        --rgc-awards rgc_awards.csv

    # Multiple candidate files can be searched at once (useful since a PI's
    # row may only exist in one particular unresolved_stageN.csv):
    python inspect_candidates.py --pi "Prof WANG, Wei" \
        --input unresolved_stage7.csv --input author_candidates_pilot.csv \
        --rgc-awards rgc_awards.csv
"""
import argparse
import csv
import re

TEXT_FIELDS = [
    "project_title", "abstract", "layman_summary", "realisation_of_objectives",
    "objectives_addressed", "major_findings", "potential_development",
]

# Same stopword list as the dropped Stage 8, kept here since it's still useful
# for ranking even without an auto-decision threshold riding on it.
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
    "advanced", "networks", "control", "dynamics", "uncertain", "learning",
    "adversarial", "identification", "information", "risk", "high", "multi",
    "domain",
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


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pi", required=True, help="pi_name_raw to inspect, e.g. 'Prof Tan, Siew Chong'")
    parser.add_argument("--input", required=True, action="append",
                         help="Candidate CSV(s) to search for this PI's rows -- repeat flag for multiple files")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    args = parser.parse_args()

    pi_rows = []
    seen_candidate_ids = set()
    for path in args.input:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row.get("pi_name_raw", "").strip().lower() != args.pi.strip().lower():
                    continue
                cid = row.get("candidate_author_id", "")
                if cid and cid in seen_candidate_ids:
                    continue
                seen_candidate_ids.add(cid)
                pi_rows.append(row)

    if not pi_rows:
        print(f"No candidate rows found for PI '{args.pi}' in: {', '.join(args.input)}")
        return

    with open(args.rgc_awards, encoding="utf-8-sig") as f:
        rgc_awards_by_id = {row["project_id"]: row for row in csv.DictReader(f)}

    project_ids = split_ids(pi_rows[0].get("rgc_project_ids", ""))
    text_parts = []
    for pid in project_ids:
        award = rgc_awards_by_id.get(pid)
        if award:
            for field in TEXT_FIELDS:
                text_parts.append(award.get(field, ""))
    rgc_keywords = topic_keywords(" ".join(text_parts))

    print(f"PI: {args.pi}")
    print(f"RGC project(s): {', '.join(project_ids)}")
    print(f"RGC text keywords ({len(rgc_keywords)} total): {sorted(rgc_keywords)[:40]}")
    print()

    ranked = []
    for r in pi_rows:
        candidate_keywords = topic_keywords(r.get("candidate_topics", ""))
        overlap = candidate_keywords & rgc_keywords
        ranked.append((len(overlap), overlap, r))
    ranked.sort(key=lambda x: x[0], reverse=True)

    for n_overlap, overlap, r in ranked:
        print(f"[{n_overlap} overlap] {r.get('candidate_author_id')} -- {r.get('candidate_display_name')}")
        print(f"    works_count={r.get('works_count')}  orcid={r.get('candidate_orcid') or '(none)'}  "
              f"institution_match={r.get('institution_match')}")
        print(f"    topics: {r.get('candidate_topics', '')}")
        if overlap:
            print(f"    overlapping words: {sorted(overlap)}")
        print()


if __name__ == "__main__":
    main()
