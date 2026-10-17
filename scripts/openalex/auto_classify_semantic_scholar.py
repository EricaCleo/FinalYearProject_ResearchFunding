"""
Stage 7 of the automated PI matching pipeline: an automatable equivalent of
manually checking a PI's Google Scholar page to confirm their real research
field, used to arbitrate between tied OpenAlex candidates. Google Scholar
has no API and blocks bulk access, so this uses Semantic Scholar's free,
official API instead -- same idea (does this person's real published work
match the field a candidate claims), just safe to call programmatically.

The institution used to disambiguate the Semantic Scholar author search is
read from EACH PI's own `rgc_institution` value, not hardcoded to any one
university -- RGC PIs are spread across all UGC-funded institutions
(CityU, HKU, CUHK, HKUST, PolyU, HKBU, Lingnan, EdUHK), so a hardcoded
institution would silently fail for PIs anywhere else.

Rule per PI: search Semantic Scholar for the PI's name; if this does not
resolve to exactly one author profile, don't guess (an ambiguous name on
Semantic Scholar is no more trustworthy than an ambiguous name on OpenAlex).
Pull that one profile's real fields of study from their papers, and check
each tied OpenAlex candidate's own `candidate_topics` (already collected by
search_candidates.py) for ANY overlapping field keyword. If exactly one
candidate's topics overlap with the PI's real Semantic Scholar fields,
confirm it; if zero or 2+ overlap, stay unresolved -- this is a yes/no
corroboration check, not a best-match ranking (ranking by similarity score
is exactly the kind of weak evidence this pipeline has avoided elsewhere).

Usage:
    python auto_classify_semantic_scholar.py --input still_unresolved_stage6.csv \
        --out-crosswalk pi_openalex_crosswalk_stage7.csv \
        --out-unresolved truly_unresolved_final.csv
"""
import argparse
import csv
import re
from collections import defaultdict

from common import normalize_institution, semantic_scholar_get

# Generic words that would create false "overlap" between any two research fields.
STOPWORDS = {
    "and", "the", "of", "for", "in", "on", "with", "to", "a", "an", "based",
    "study", "studies", "analysis", "research", "method", "methods", "using",
    "application", "applications", "system", "systems", "model", "models",
}


def topic_keywords(text: str) -> frozenset[str]:
    tokens = re.findall(r"[a-z]+", (text or "").lower())
    return frozenset(t for t in tokens if len(t) >= 4 and t not in STOPWORDS)


def search_semantic_scholar_author(pi_name: str, rgc_institution: str) -> list[dict]:
    data = semantic_scholar_get("author/search", params={
        "query": pi_name,
        "fields": "name,affiliations,paperCount",
    })
    candidates = data.get("data", []) or []
    target = normalize_institution(rgc_institution).lower()
    # Semantic Scholar affiliations are often compound strings (e.g. "Department of
    # Electrical Engineering, City University of Hong Kong"), not just the bare
    # university name -- an exact-equality check against the normalized RGC
    # institution would almost never match, so this checks containment instead.
    matches = [
        a for a in candidates
        if any(target in normalize_institution(aff).lower() for aff in (a.get("affiliations") or []))
    ]
    return matches


def get_author_paper_keywords(semantic_scholar_author_id: str, max_papers: int = 50) -> frozenset[str]:
    """Semantic Scholar's own `fieldsOfStudy` are broad top-level categories (e.g.
    "Materials Science", "Physics") shared by huge numbers of unrelated researchers --
    not specific enough to tell two specialists in the same broad field apart. Paper
    TITLES carry much more specific technical vocabulary (e.g. "metallic glass",
    "amorphous alloy") and are the actual equivalent of what manual review did when
    reading someone's Google Scholar paper list to judge their real field."""
    data = semantic_scholar_get(f"author/{semantic_scholar_author_id}", params={
        "fields": "papers.title",
    })
    keywords = set()
    for paper in (data.get("papers") or [])[:max_papers]:
        keywords |= topic_keywords(paper.get("title", ""))
    return frozenset(keywords)


def classify_pi(rows: list[dict]) -> dict | None:
    pi_name = rows[0].get("pi_name_clean", "")
    rgc_institution = rows[0].get("rgc_institution", "")

    ss_authors = search_semantic_scholar_author(pi_name, rgc_institution)
    if len(ss_authors) != 1:
        return None  # name doesn't resolve to a unique Semantic Scholar profile either -- don't guess

    paper_keywords = get_author_paper_keywords(ss_authors[0]["authorId"])
    if not paper_keywords:
        return None

    # Require 2+ overlapping keywords, not just 1 -- a single shared word (e.g. a
    # common field-level term like "materials") isn't specific enough on its own to
    # tell two candidates in neighboring fields apart.
    matched = []
    for r in rows:
        candidate_keywords = topic_keywords(r.get("candidate_topics", ""))
        overlap = candidate_keywords & paper_keywords
        if len(overlap) >= 2:
            matched.append((r, overlap))

    if len(matched) == 1:
        candidate, overlap = matched[0]
        return {
            "decision": "confirmed",
            "stage": "semantic_scholar_field",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": (f"PI's real Semantic Scholar paper titles share {len(overlap)} specific keywords "
                       f"({', '.join(sorted(overlap))}) with this candidate's OpenAlex topics, and no other "
                       f"tied candidate's topics overlap this much"),
        }

    return None  # 0 or 2+ candidates overlap -- don't guess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, action="append",
                         help="Unresolved candidate rows. Repeat flag for multiple.")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage7.csv")
    parser.add_argument("--out-unresolved", default="truly_unresolved_final.csv")
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
    print(f"{n_pis} PIs entered stage 7")
    print(f"  {len(crosswalk_rows)} confirmed by Semantic Scholar field-check -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs truly unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
