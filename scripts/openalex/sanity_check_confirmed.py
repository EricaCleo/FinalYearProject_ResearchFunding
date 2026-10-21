"""
Cross-cutting sanity check for ALREADY-CONFIRMED matches across every stage
(1-7), built after a manual spot-check caught a real false positive that
none of the stages themselves could have caught: Stage 1 confirmed a PI
purely on institution + exact name-token match, but the confirmed
candidate's actual research area (computational drug discovery /
bioinformatics) had nothing to do with the grant's real subject
(electromagnetics / antenna engineering) -- a genuine name collision
between two different real people who both happened to have some
connection to the same institution.

This does NOT add a new way to CONFIRM anything -- stages 1-4 never had
any topical cross-check at all (by design: name+institution was treated as
sufficient when unambiguous), and this doesn't change that. It only FLAGS
an existing confirmation when the candidate's OpenAlex topics show
essentially zero plausible connection to RGC's own recorded field/panel/
project title, for a human to manually review. A flag is not proof of a
wrong match (RGC's field/panel is broad, see auto_classify_field_panel.py's
own documented low-yield limitation), but zero overlap at all across every
RGC text signal available is a meaningful red flag worth a second look --
cheap insurance against another Man-Hon-Wong-style name collision slipping
through unnoticed.

Looks up each confirmed candidate's topics from the candidate-pool file(s)
that produced them (author_candidates_pilot*.csv) by candidate_author_id --
NOT a live OpenAlex re-fetch, so this is fast and free, but a candidate
confirmed only via Stage 5's rescue path (a brand-new ID never in the
original pool) won't have cached topics and is reported separately as
"no topic data available" rather than silently skipped.

Usage:
    python sanity_check_confirmed.py \
        --crosswalk crosswalk_stage1.csv --crosswalk crosswalk_stage2.csv ... \
        --candidate-pool author_candidates_pilot.csv --candidate-pool author_candidates_pilot2.csv \
        --rgc-awards rgc_awards.csv \
        --out flagged_for_review.csv
"""
import argparse
import csv
import re

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
    parser.add_argument("--crosswalk", required=True, action="append",
                         help="One or more crosswalk_stageN.csv files to check. Repeat flag for multiple.")
    parser.add_argument("--candidate-pool", required=True, action="append",
                         help="One or more author_candidates_pilot*.csv files to look up topics from. Repeat flag for multiple.")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out", default="flagged_for_review.csv")
    args = parser.parse_args()

    topics_by_id = {}
    for path in args.candidate_pool:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                cid = row.get("candidate_author_id", "")
                if cid:
                    topics_by_id[cid] = row.get("candidate_topics", "")

    with open(args.rgc_awards, encoding="utf-8-sig") as f:
        rgc_by_id = {row["project_id"]: row for row in csv.DictReader(f)}

    confirmed_rows = []
    for path in args.crosswalk:
        with open(path, encoding="utf-8-sig") as f:
            rows = list(csv.DictReader(f))
        confirmed_rows.extend(r for r in rows if r.get("decision", "").startswith("confirmed"))

    print(f"{len(confirmed_rows)} confirmed PIs to sanity-check")

    flagged, no_topic_data, clean = [], [], 0
    for r in confirmed_rows:
        project_ids = split_ids(r.get("rgc_project_ids", ""))
        rgc_text_parts = []
        for pid in project_ids:
            award = rgc_by_id.get(pid)
            if award:
                rgc_text_parts.append(award.get("field", ""))
                rgc_text_parts.append(award.get("panel", ""))
                rgc_text_parts.append(award.get("project_title", ""))
        rgc_keywords = topic_keywords(" ".join(rgc_text_parts))

        candidate_ids = split_ids(r.get("openalex_author_ids", ""))
        all_topics = " ".join(topics_by_id.get(cid, "") for cid in candidate_ids)
        if not any(cid in topics_by_id for cid in candidate_ids):
            no_topic_data.append(r)
            continue

        candidate_keywords = topic_keywords(all_topics)
        overlap = candidate_keywords & rgc_keywords
        if not rgc_keywords:
            continue  # no RGC text to compare against either -- nothing to flag against
        if not overlap:
            flagged.append({**r, "candidate_topics": all_topics, "rgc_keywords_checked": " ".join(sorted(rgc_keywords)[:20])})
        else:
            clean += 1

    with open(args.out, "w", encoding="utf-8-sig", newline="") as f:
        fieldnames = ["pi_name_raw", "rgc_institution", "stage", "openalex_author_ids",
                      "openalex_display_names", "candidate_topics", "rgc_keywords_checked"]
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(flagged)

    print(f"  {clean} show at least some topic overlap with RGC's field/panel/project_title -- no flag")
    print(f"  {len(no_topic_data)} have no cached topic data to check (likely a Stage 5 rescue-path ID) -- skipped")
    print(f"  {len(flagged)} FLAGGED for manual review (zero topic overlap at all) -> {args.out}")


if __name__ == "__main__":
    main()
