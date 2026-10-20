"""
Stage 5 of the automated PI matching pipeline: resolves PIs still tied after
stages 1-4 by searching OpenAlex for the actual grant-resulting publication
(RGC's own `publications` field, scraped per project) and reading the real
author ID straight off that paper's authorship list.

This is the single most reliable manual technique used during pilot review
-- it is what resolved Tan Siew Chong (whose correct candidate WAS in the
original pool, just not exact-name-matched) and, in an extended form below,
Wei Wang and Li Ying (whose correct candidates were NEVER in the original
search-candidate pool at all -- a candidate-GENERATION failure, not a
classification one). This stage automates both instead of leaving them as
one-off manual steps.

A plain intersection against the existing candidate rows (the first check
below) only rescues cases like Tan Siew Chong's. For cases like Wei Wang's
and Li Ying's, where no row for the correct author exists to intersect
against at all, `find_new_author_by_name_and_institution` instead reads the
matched paper's own authorship list directly for a name+institution match
and introduces that as a brand-new confirmed ID (stage
"publication_match_new_candidate") -- never run against an unconflicting
answer from the first check, so it only fires when there's truly nothing in
the existing pool to confirm.

Requires a copy of rgc_awards.csv (output of combine_rgc_data.py) to look up
each PI's publications by project_id. The `publications` column there is a
JSON-encoded list of {column_header: value} dicts straight from RGC's own
Research Output table (see scripts/rgc/parse_details.py) -- whatever the
scraped header happened to be, so this reads any key containing "title"
rather than assuming one exact column name.

Confirmed from real scraped data (2015_results.csv) that this field is
usually headed "Title and Journal/Book" and its value is a COMBINED
citation string -- the real title followed directly by the journal name,
volume, and pages, e.g. "Recent Advances in ... Neurodegeneration.
Frontiers in Aging Neuroscience 9: 128." -- not a pure title. Exact-equality
comparison against OpenAlex's own (pure) title would therefore never match
anything real. The real title is consistently the LEADING portion of this
combined string across every citation format seen (period-separated,
comma-separated, or quoted), so a candidate counts as confirmed if their
candidate_author_id appears in the real authorship list of a paper whose
normalized OpenAlex title is a PREFIX of the normalized scraped citation
string -- still not fuzzy/approximate matching (the comparison is exact
after normalization, just anchored at the start rather than the whole
string), so an unrelated paper with a different title still can't match.

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
    """This project's own convention is pipe-separated (|) for multi-value fields
    (see openalex_author_ids). Comma is accepted as a fallback in case
    unique_pis.csv was built with that delimiter instead."""
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
    """rgc_citation may be a pure title or a combined "title + journal/volume/pages"
    citation string (see module docstring) -- either way the real title is always
    the leading portion, so this checks prefix containment rather than equality.
    Requires a reasonably long title (>= 15 normalized chars) before trusting a
    prefix match at all, so a short/generic OpenAlex title can't spuriously match
    the start of an unrelated citation."""
    openalex_norm = normalize_title(openalex_title)
    if len(openalex_norm) < 15:
        return False
    return normalize_title(rgc_citation).startswith(openalex_norm)


def extract_search_title(citation: str) -> str:
    """RGC's `publications` field stores the full citation (title + journal name +
    volume/pages, sometimes "(Early Access)" -- see module docstring), not a bare
    title. Searching OpenAlex with the WHOLE citation attached was found live to
    return ZERO results for papers that DO exist and match instantly on the bare
    title alone (confirmed: "...Parabolic-Distributed Parameter Processes. IEEE
    Transactions on Cybernetics. (Early Access)" found nothing, but the title alone
    found the exact paper at rank 1) -- OpenAlex's `search` param needs reasonably
    coherent query text, and appending unrelated journal/status words drags down
    the match badly enough to lose it entirely. This approximates the bare title:
    the quoted portion if the citation is quoted, otherwise the text before the
    first ". " (titles can themselves contain a period, but titles_match() still
    verifies the real match afterward against the UNTRUNCATED citation, so cutting
    too aggressively here only risks a missed search, never a wrong confirmation)."""
    stripped = citation.strip()
    quote_match = re.match(r'^[“"\'](.+?)[”"\']', stripped)
    if quote_match:
        return quote_match.group(1)
    period_idx = stripped.find(". ")
    if period_idx > 15:
        return stripped[:period_idx]
    return stripped


def search_work_by_title(title: str, max_results: int = 5) -> list[dict]:
    """OpenAlex's filter syntax (filter=title.search:...) uses a bare comma to
    separate multiple filters within one filter string -- a literal comma inside the
    title text (very common in real paper titles, e.g. "Title: A Study of X, Y, and
    Z") breaks the request with an HTTP 400. Found live running this against real RGC
    publication data; quoting the value (OpenAlex's own documented escape mechanism)
    did NOT fix it in practice -- the edge proxy appears to split on commas before
    any quote-aware parsing. Sidesteps the whole escaping problem by using OpenAlex's
    plain top-level `search` parameter instead of the filter mini-language: it isn't
    comma-delimited at all, so normal URL-encoding (which requests already does
    correctly) just works. This searches title+abstract+fulltext rather than title
    only, a broader net than before, but that's safe here -- classify_pi's own
    titles_match() still verifies the returned work's actual title before accepting
    it, so a broader initial search can't cause a wrong match, only find the right
    one that a title-only filter might have required exact escaping to reach.

    One more real-world wrinkle found live: OpenAlex's `search` param treats a
    literal "*" or "?" in the query text as wildcard syntax ("Wildcards require
    exact (no-stem) search"), and real paper titles can genuinely contain either
    (a trailing "?" on a question-style title is common; RGC's own data also uses
    "*" as a footnote marker that occasionally leaks into scraped title text).
    Stripped before searching -- this is only the candidate-retrieval query, not
    the final decision, so losing those characters here doesn't weaken the actual
    match verification titles_match() still does against the real returned title."""
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
    """Rescue path for PIs whose correct OpenAlex author was never in the original
    search-candidate pool at all (a candidate-GENERATION failure, not a classification
    one -- see README "Known limitations"). This happened in the pilot for very common
    names (e.g. Li Ying, Wei Wang): manual resolution found the correct author by
    searching the grant paper's title directly and reading the author off its real
    authorship list, same as the rest of this stage, but that author's ID was never a
    row in the input candidate CSV to begin with. Checks the paper's OWN authorship
    entries (name exact-token match to the PI, institution as recorded on THAT
    authorship, not the author's broader profile) rather than assuming a candidate row
    already exists. Only returns a result when exactly one authorship entry matches
    both -- same "don't guess" standard as everywhere else in this pipeline."""
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


MAX_TITLES_PER_PI = 50  # see classify_pi's docstring note below


def classify_pi(rows: list[dict], rgc_awards_by_id: dict[str, dict]) -> dict | None:
    """Checks each of the PI's recorded publication titles, live, against OpenAlex --
    with no cap, a PI with 80-90+ recorded papers (not unusual for a senior professor
    with many grants) means 80-90+ live network calls just for them. Deduping repeated
    titles (the same paper is often recorded once per completion report it appears in)
    and capping at MAX_TITLES_PER_PI bounds the worst case. An earlier version of this
    capped at 20 in RGC's own (arbitrary) list order -- found live to miss a real,
    verifiable match for a prolific PI (Li Han-Xiong) whose confirming title sat at
    position 77 of 84. Sorting by title length first (longer titles tend to be more
    distinctive, so more likely to produce a clean, unambiguous OpenAlex match) and
    raising the cap to 50 catches that case; this still reduces how much corroborating/
    conflicting evidence is gathered for extremely prolific PIs, but never flips a
    confirmed match into a wrong one (titles_match still verifies each one
    individually)."""
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
