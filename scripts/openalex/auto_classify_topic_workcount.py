"""
Stage 3 of the automated PI matching pipeline: combined topic-overlap +
works-count filter.

Takes the PIs that stages 1 (institution) and 2 (ORCID) couldn't resolve, and
applies the same reasoning used to manually confirm CAI Wenlong: among
institution-matched, EXACT-name-matched candidates, the correct one is
usually both (a) the most complete/established profile (highest works_count
-- duplicate/fragment profiles tend to be small) AND (b) topically relevant
to the actual grant (shared keywords between OpenAlex topics and the RGC
project title).

Name matching here uses an EXACT name-token match (same set of words,
order-independent), not the fuzzy name_similarity score. rapidfuzz's ratio()
was tested against the pilot data and found unreliable for this dataset:
clearly wrong candidates ("Kai You Wang", "Zhong Lin Wang") scored as high as
100% against completely different real PIs, because the scoring function
(in common.py's get_name_similarity) takes the max across an author's
OpenAlex display_name AND all of their display_name_alternatives, and that
alternates list is itself noisy. An earlier version of this script used a
fuzzy floor instead and nearly auto-confirmed the wrong person for
"Prof LIN, Carol Sze Ki" as a result -- see git history. Exact token
matching had zero false positives in the same pilot data.

Rule per PI, among their institution-matched, exact-name-matched candidates:
  - exactly one candidate is BOTH the highest works_count AND has at least
    one shared keyword with the project title  -> auto "confirmed"
  - otherwise                                   -> still unresolved, needs stage 4

Topic overlap is a simple keyword check, not semantic similarity: lowercase,
strip punctuation, drop a short stopword list, keep words of 4+ characters,
and look for any word appearing in both the candidate's topics and the
project title. This is deliberately conservative -- a real but partial
overlap (e.g. different but related subfields) will NOT auto-confirm here,
and falls through to stage 4 / closer inspection instead.

Usage:
    python auto_classify_topic_workcount.py --input needs_stage3_filtering.csv \
        --out-crosswalk pi_openalex_crosswalk_stage3.csv \
        --out-stage4 needs_stage4_filtering.csv
"""
import argparse
import csv
import re
from collections import defaultdict

STOPWORDS = {
    "the", "and", "for", "with", "from", "that", "this", "into", "their",
    "based", "using", "study", "studies", "analysis", "approach", "effects",
    "effect", "role", "development", "research", "novel", "new", "via",
    "towards", "toward", "between", "among", "across", "under", "over",
}


def tokenize(text: str) -> set[str]:
    words = re.findall(r"[a-zA-Z]{4,}", (text or "").lower())
    return {w for w in words if w not in STOPWORDS}


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", (name or "").lower()))


def classify_pi(rows: list[dict]) -> dict | None:
    pi_tokens = name_tokens(rows[0].get("pi_name_clean", ""))
    if not pi_tokens:
        return None

    # Institution match alone isn't enough to even consider a candidate here --
    # a prolific, same-institution researcher with a DIFFERENT name can
    # otherwise beat the real, smaller-profile match on works_count alone
    # (caught in the pilot: "C. Jeffrey Brinker" beat the correct
    # "Carol Sze Ki Lin" purely on works_count, under an earlier version of
    # this script that used fuzzy name_similarity instead of exact matching).
    candidates = [
        r for r in rows
        if r.get("institution_match") == "1"
        and name_tokens(r.get("candidate_display_name", "")) == pi_tokens
    ]
    if not candidates:
        return None

    title_tokens = tokenize(rows[0].get("sample_project_title", ""))

    best_works = max(int(r.get("works_count") or 0) for r in candidates)
    qualifying = []
    for r in candidates:
        works_count = int(r.get("works_count") or 0)
        if works_count != best_works:
            continue
        topic_tokens = tokenize(r.get("candidate_topics", ""))
        shared = title_tokens & topic_tokens
        if shared:
            qualifying.append((r, shared))

    if len(qualifying) == 1:
        candidate, shared = qualifying[0]
        return {
            "decision": "confirmed",
            "stage": "topic_workcount",
            "candidate_author_id": candidate["candidate_author_id"],
            "candidate_display_name": candidate["candidate_display_name"],
            "candidate_orcid": candidate.get("candidate_orcid", ""),
            "reason": f"Exact name-token match, highest works_count ({best_works}) "
                      f"among institution+exact-name-matched candidates, shared topic keywords with project title: "
                      f"{', '.join(sorted(shared))}",
        }

    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="needs_stage3_filtering.csv from auto_classify_orcid.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage3.csv", help="Newly confirmed matches")
    parser.add_argument("--out-stage4", default="needs_stage4_filtering.csv", help="Still-ambiguous PIs (full candidate rows kept)")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    by_pi = defaultdict(list)
    for row in rows:
        by_pi[(row["pi_name_raw"], row["rgc_institution"])].append(row)

    crosswalk_rows, stage4_rows = [], []
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
            stage4_rows.extend(pi_rows)

    crosswalk_fields = ["pi_name_raw", "rgc_institution", "rgc_project_ids", "decision", "stage",
                         "candidate_author_id", "candidate_display_name", "candidate_orcid", "reason"]
    with open(args.out_crosswalk, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=crosswalk_fields)
        writer.writeheader()
        writer.writerows(crosswalk_rows)

    if stage4_rows:
        with open(args.out_stage4, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(stage4_rows[0].keys()))
            writer.writeheader()
            writer.writerows(stage4_rows)

    n_pis = len(by_pi)
    n_stage4_pis = len(set((r["pi_name_raw"], r["rgc_institution"]) for r in stage4_rows))
    print(f"{n_pis} PIs entered stage 3")
    print(f"  {len(crosswalk_rows)} confirmed by topic+workcount -> {args.out_crosswalk}")
    print(f"  {n_stage4_pis} PIs still unresolved ({len(stage4_rows)} candidate rows) -> {args.out_stage4}")


if __name__ == "__main__":
    main()
