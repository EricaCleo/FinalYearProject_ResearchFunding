"""
Stage 5: for PIs still tied after stages 1-4, searches OpenAlex for the
actual grant-resulting publication (RGC's own `publications` field) and
reads the real author ID off that paper's authorship list.

Needs rgc_awards.csv to look up each PI's publications by project_id. That
field is RGC's own Research Output table, a JSON list of {column_header:
value} dicts -- reads any key containing "title" since the header varies.

RGC's title field is usually a combined citation string (title + journal +
volume/pages), not a pure title, so matching uses prefix containment
against the normalized OpenAlex title rather than exact equality.

Two ways a candidate gets confirmed: if their ID is already in the
candidate pool (the exact-name stages just didn't match them), or, if
nobody in the pool matches at all, by reading the matched paper's own
authorship list directly for a name+institution match and introducing them
as a new candidate.

Usage:
    python auto_classify_publication_match.py --input truly_unresolved.csv \
        --rgc-awards rgc_awards.csv \
        --out-crosswalk pi_openalex_crosswalk_stage5.csv \
        --out-unresolved still_unresolved_stage5.csv
"""
import argparse
import csv
import re
from collections import defaultdict

from common import extract_titles, normalize_institution, openalex_get, short_openalex_id


def split_ids(value: str) -> list[str]:
    # pipe-separated is this project's convention; comma is a fallback
    value = (value or "").strip()
    if not value:
        return []
    parts = value.split("|") if "|" in value else value.split(",")
    return [p.strip() for p in parts if p.strip()]


def normalize_title(title: str) -> str:
    title = (title or "").lower()
    title = re.sub(r"[^a-z0-9]+", "", title)
    return title


def titles_match(openalex_title: str, rgc_citation: str) -> bool:
    # prefix match since rgc_citation can have journal/volume/pages tacked on;
    # require >=15 chars so a short title can't spuriously match
    openalex_norm = normalize_title(openalex_title)
    if len(openalex_norm) < 15:
        return False
    return normalize_title(rgc_citation).startswith(openalex_norm)


def extract_search_title(citation: str) -> str:
    # searching OpenAlex with the full citation (title + journal name) attached
    # can return zero results even when the bare title finds the paper instantly,
    # so approximate the bare title: quoted portion if quoted, else text before
    # the first ". " -- titles_match() still verifies against the full citation
    # after, so an over-aggressive cut here only risks a missed search
    stripped = citation.strip()
    quote_match = re.match(r'^[“"\'](.+?)[”"\']', stripped)
    if quote_match:
        return quote_match.group(1)
    period_idx = stripped.find(". ")
    if period_idx > 15:
        return stripped[:period_idx]
    return stripped


def search_work_by_title(title: str, max_results: int = 5) -> list[dict]:
    # uses the plain `search` param rather than filter=title.search:... -- a comma
    # in the title breaks the filter mini-language's parsing with an HTTP 400.
    # Also strips * and ? since OpenAlex treats them as wildcard syntax;
    # titles_match() still verifies the real result afterward either way.
    search_text = extract_search_title(title).replace("*", " ").replace("?", " ")
    data = openalex_get("works", params={"search": search_text, "per_page": max_results})
    return data.get("results", [])


def extract_work_author_ids(work: dict) -> set[str]:
    ids = set()
    for authorship in work.get("authorships", []) or []:
        author_id = short_openalex_id((authorship.get("author") or {}).get("id"))
        if author_id:
            ids.add(author_id)
    return ids


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", (name or "").lower()))


def find_new_author_by_name_and_institution(work: dict, pi_name_clean: str, rgc_institution: str) -> dict | None:
    # rescue path for PIs whose correct author was never in the candidate pool at
    # all -- checks the paper's own authorship entries for a name+institution
    # match instead. Only returns a result if exactly one entry matches both.
    pi_tokens = name_tokens(pi_name_clean)
    if not pi_tokens:
        return None
    target_institution = normalize_institution(rgc_institution)

    matches = []
    for authorship in work.get("authorships", []) or []:
        author = authorship.get("author") or {}
        if name_tokens(author.get("display_name", "")) != pi_tokens:
            continue
        institutions = {
            normalize_institution(inst.get("display_name", ""))
            for inst in (authorship.get("institutions") or [])
        }
        if target_institution in institutions:
            matches.append(author)

    if len(matches) == 1:
        return matches[0]
    return None


MAX_TITLES_PER_PI = 50  # cap network calls for prolific PIs; sorted longest-first below


def classify_pi(rows: list[dict], rgc_awards_by_id: dict[str, dict]) -> dict | None:
    project_ids = split_ids(rows[0].get("rgc_project_ids", ""))
    titles = []
    for pid in project_ids:
        award = rgc_awards_by_id.get(pid)
        if award:
            titles.extend(extract_titles(award.get("publications", "")))

    titles = sorted(dict.fromkeys(titles), key=len, reverse=True)[:MAX_TITLES_PER_PI]  # dedupe, longest first, cap

    if not titles:
        return None  # no publication data to check against -- can't verify this way

    pi_name_clean = rows[0].get("pi_name_clean", "")
    rgc_institution = rows[0].get("rgc_institution", "")

    matched_candidate_ids = set()
    new_author_candidates = {}  # author_id -> author dict, for IDs not already in `rows`
    checked_titles = []
    for title in titles:
        works = search_work_by_title(title)
        for work in works:
            if titles_match(work.get("title", ""), title):
                checked_titles.append(title)
                author_ids = extract_work_author_ids(work)
                for r in rows:
                    if r.get("candidate_author_id") in author_ids:
                        matched_candidate_ids.add(r["candidate_author_id"])

                # Rescue path: the correct author may never have been in the
                # original candidate pool at all (a candidate-GENERATION
                # failure, e.g. an extremely common name) -- check the paper's
                # own authorship list directly for a name+institution match.
                new_author = find_new_author_by_name_and_institution(work, pi_name_clean, rgc_institution)
                if new_author:
                    new_id = short_openalex_id(new_author.get("id"))
                    if new_id:
                        new_author_candidates[new_id] = new_author
                break  # only the first title-match work counts per title

    if len(matched_candidate_ids) == 1 and not (new_author_candidates.keys() - matched_candidate_ids):
        author_id = next(iter(matched_candidate_ids))
        candidate = next(r for r in rows if r["candidate_author_id"] == author_id)
        return {
            "decision": "confirmed",
            "stage": "publication_match",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": (f"Candidate's OpenAlex ID found in the real authorship list of a grant-resulting "
                       f"publication found via title match ({len(checked_titles)} title(s) checked)"),
        }

    if not matched_candidate_ids and len(new_author_candidates) == 1:
        new_id, author = next(iter(new_author_candidates.items()))
        return {
            "decision": "confirmed",
            "stage": "publication_match_new_candidate",
            "openalex_author_ids": new_id,
            "openalex_display_names": author.get("display_name", ""),
            "openalex_orcid": author.get("orcid", "") or "",
            "reason": (f"Author not in the original candidate pool at all (candidate-generation gap), but "
                       f"found by name+institution match on the real authorship list of a grant-resulting "
                       f"publication found via title match ({len(checked_titles)} title(s) checked)"),
        }

    return None  # 0 or 2+ candidates, or conflicting evidence -- don't guess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, action="append",
                         help="Unresolved candidate rows (e.g. truly_unresolved.csv). Repeat flag for multiple.")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage5.csv")
    parser.add_argument("--out-unresolved", default="still_unresolved_stage5.csv")
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
    print(f"{n_pis} PIs entered stage 5")
    print(f"  {len(crosswalk_rows)} confirmed by publication match -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs still unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
