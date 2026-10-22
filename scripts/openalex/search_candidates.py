"""
Step 1: search OpenAlex for candidate author profiles for each RGC PI.
Doesn't decide who's correct, just gathers evidence (name similarity,
institution match, topics, search rank) for the next stages / manual review.

Usage:
    python search_candidates.py --input unique_pis.csv --pilot-size 40 \
        --out-candidates author_candidates_pilot.csv \
        --out-review author_candidates_for_review.csv
"""
import argparse
import csv

from rapidfuzz.fuzz import ratio
from tqdm import tqdm

from common import (
    clean_person_name,
    generate_name_variants,
    institution_openalex_id,
    normalize_institution,
    openalex_get,
    short_openalex_id,
)


def search_authors_by_name(name: str, per_page: int = 10) -> list[dict]:
    data = openalex_get("authors", params={"search": name, "per_page": per_page})
    return data.get("results", [])


def search_authors_by_name_at_institution(name: str, institution_id: str, per_page: int = 10) -> list[dict]:
    # a global name search only returns the top-K globally-relevant results, so a
    # common name's correct candidate at the right institution can rank below that
    # cutoff and never show up -- searching within the institution directly avoids this.
    # Uses affiliations.institution.id (full career history) rather than
    # last_known_institutions (current institution only), since a PI who's since
    # moved elsewhere would otherwise be missed.
    data = openalex_get("authors", params={
        "search": name,
        "filter": f"affiliations.institution.id:{institution_id}",
        "per_page": per_page,
    })
    return data.get("results", [])


def collect_author_candidates(pi_name_raw: str, institution_raw: str = "", per_variant: int = 10,
                               per_institution_variant: int = 50) -> list[dict]:
    candidates = {}

    def add_results(results, query_name):
        for rank, author in enumerate(results, start=1):
            author_id = short_openalex_id(author.get("id"))
            if author_id not in candidates:
                candidates[author_id] = {"author": author, "query_names": [], "best_search_rank": rank}
            candidates[author_id]["query_names"].append(query_name)
            candidates[author_id]["best_search_rank"] = min(candidates[author_id]["best_search_rank"], rank)

    institution_id = institution_openalex_id(institution_raw)
    for query_name in generate_name_variants(pi_name_raw):
        add_results(search_authors_by_name(query_name, per_variant), query_name)
        if institution_id:
            # wider cap here since it's already scoped to one institution, so
            # a higher per_page is free and helps with very common names
            add_results(search_authors_by_name_at_institution(query_name, institution_id, per_institution_variant),
                        query_name)

    return list(candidates.values())


def get_name_similarity(pi_name_clean: str, author: dict) -> float:
    names = [author.get("display_name", "")]
    names.extend(author.get("display_name_alternatives") or [])
    scores = [ratio(pi_name_clean.lower(), clean_person_name(n).lower()) for n in names if n]
    return max(scores) if scores else 0


def extract_affiliation_names(author: dict) -> list[str]:
    names = set()
    for affiliation in author.get("affiliations") or []:
        name = (affiliation.get("institution") or {}).get("display_name")
        if name:
            names.add(normalize_institution(name))
    for institution in author.get("last_known_institutions") or []:
        name = institution.get("display_name")
        if name:
            names.add(normalize_institution(name))
    return sorted(names)


def institution_match(rgc_institution: str, author: dict) -> int:
    return int(normalize_institution(rgc_institution) in extract_affiliation_names(author))


def extract_topic_names(author: dict, n: int = 10) -> list[str]:
    return [t.get("display_name", "") for t in (author.get("topics") or [])[:n]]


def candidate_summary(pi_row: dict, candidate_record: dict) -> dict:
    author = candidate_record["author"]
    pi_name_clean = clean_person_name(pi_row["pi_name_raw"])
    return {
        "pi_name_raw": pi_row["pi_name_raw"],
        "pi_name_clean": pi_name_clean,
        "rgc_institution": pi_row["institution_raw"],
        "n_rgc_awards": pi_row.get("n_awards", ""),
        "rgc_award_years": pi_row.get("award_years", ""),
        "rgc_project_ids": pi_row.get("project_ids", ""),
        "sample_project_title": pi_row.get("sample_project_title", ""),
        "known_publication_titles": pi_row.get("known_publication_titles", ""),
        "candidate_author_id": short_openalex_id(author.get("id")),
        "candidate_display_name": author.get("display_name"),
        "candidate_orcid": author.get("orcid"),
        "candidate_institutions": " | ".join(extract_affiliation_names(author)),
        "candidate_topics": " | ".join(extract_topic_names(author)),
        "works_count": author.get("works_count"),
        "cited_by_count": author.get("cited_by_count"),
        "h_index": (author.get("summary_stats") or {}).get("h_index"),
        "name_similarity": get_name_similarity(pi_name_clean, author),
        "institution_match": institution_match(pi_row["institution_raw"], author),
        "best_search_rank": candidate_record["best_search_rank"],
        "query_names": " | ".join(candidate_record["query_names"]),
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="unique_pis.csv from combine_rgc_data.py")
    parser.add_argument("--pilot-size", type=int, default=40)
    parser.add_argument("--offset", type=int, default=0,
                         help="Skip this many PIs before taking --pilot-size, e.g. --offset 40 runs PIs 41-80")
    parser.add_argument("--out-candidates", default="author_candidates_pilot.csv")
    parser.add_argument("--out-review", default="author_candidates_for_review.csv")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8-sig") as f:
        all_pis = list(csv.DictReader(f))
    pis = all_pis[args.offset: args.offset + args.pilot_size]
    print(f"{len(pis)} PIs in this pilot batch (offset {args.offset}, of {len(all_pis)} total unique PIs)")

    candidate_rows = []
    no_candidates = []
    for pi_row in tqdm(pis):
        candidates = collect_author_candidates(pi_row["pi_name_raw"], pi_row["institution_raw"])
        if not candidates:
            no_candidates.append(pi_row["pi_name_raw"])
            continue
        for candidate in candidates:
            candidate_rows.append(candidate_summary(pi_row, candidate))

    if not candidate_rows:
        print("No candidates found for any PI in this batch — check your network connection "
              "and that OpenAlex is reachable.")
        return

    fieldnames = list(candidate_rows[0].keys())
    with open(args.out_candidates, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(candidate_rows)
    print(f"Wrote {len(candidate_rows)} candidate rows -> {args.out_candidates}")

    review_columns = ["topic_match", "historical_affiliation_match", "orcid_verified",
                       "sample_works_checked", "reviewer_decision", "reviewer_confidence", "reviewer_notes"]
    for row in candidate_rows:
        for col in review_columns:
            row[col] = ""
    with open(args.out_review, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames + review_columns)
        writer.writeheader()
        writer.writerows(candidate_rows)
    print(f"Wrote review spreadsheet -> {args.out_review}")

    if no_candidates:
        print(f"\n{len(no_candidates)} PI(s) had ZERO OpenAlex candidates found at all "
              f"(mark these 'not_found' during review): {no_candidates}")


if __name__ == "__main__":
    main()
