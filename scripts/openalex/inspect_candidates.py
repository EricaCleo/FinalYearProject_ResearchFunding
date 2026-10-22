"""
Manual-review helper: for one PI, ranks their candidate OpenAlex profiles by
how much their topics overlap with that PI's grant text, plus (if
sentence-transformers is installed) a semantic similarity score.

Read-only -- never auto-confirms anything, just prints a ranked comparison
for a human to judge. Keyword overlap alone only catches literal shared
words ("fault detection" vs "anomaly diagnosis" scores 0 even though
they're the same topic); the semantic score embeds both sides and compares
by meaning instead, so results are sorted by it when available.

Needs `pip install sentence-transformers` for the semantic score (~80MB
model download, cached after first use) -- falls back to keyword-only
ranking if not installed.

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


def load_embedding_model():
    # returns a loaded model, or None if sentence-transformers isn't installed
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError:
        print("(sentence-transformers not installed -- skipping semantic similarity score, "
              "keyword-overlap-only ranking. Run `pip install sentence-transformers` to enable it.)")
        print()
        return None
    return SentenceTransformer("all-MiniLM-L6-v2")


def cosine_similarity(a, b) -> float:
    import numpy as np
    a, b = np.asarray(a), np.asarray(b)
    denom = (np.linalg.norm(a) * np.linalg.norm(b))
    return float(np.dot(a, b) / denom) if denom else 0.0


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

    rgc_text = " ".join(t for t in text_parts if t.strip())

    print(f"PI: {args.pi}")
    print(f"RGC project(s): {', '.join(project_ids)}")
    print(f"RGC text keywords ({len(rgc_keywords)} total): {sorted(rgc_keywords)[:40]}")
    print()

    model = load_embedding_model()
    rgc_embedding = model.encode(rgc_text) if (model and rgc_text.strip()) else None

    ranked = []
    for r in pi_rows:
        candidate_keywords = topic_keywords(r.get("candidate_topics", ""))
        overlap = candidate_keywords & rgc_keywords
        semantic_score = None
        if rgc_embedding is not None and r.get("candidate_topics", "").strip():
            candidate_embedding = model.encode(r["candidate_topics"])
            semantic_score = cosine_similarity(rgc_embedding, candidate_embedding)
        sort_key = semantic_score if semantic_score is not None else (len(overlap) / 100)
        ranked.append((sort_key, semantic_score, len(overlap), overlap, r))
    ranked.sort(key=lambda x: x[0], reverse=True)

    for _, semantic_score, n_overlap, overlap, r in ranked:
        score_label = f"semantic={semantic_score:.3f}" if semantic_score is not None else "semantic=n/a"
        print(f"[{score_label}, {n_overlap} keyword overlap] {r.get('candidate_author_id')} -- "
              f"{r.get('candidate_display_name')}")
        print(f"    works_count={r.get('works_count')}  orcid={r.get('candidate_orcid') or '(none)'}  "
              f"institution_match={r.get('institution_match')}")
        print(f"    topics: {r.get('candidate_topics', '')}")
        if overlap:
            print(f"    overlapping words: {sorted(overlap)}")
        print()


if __name__ == "__main__":
    main()
