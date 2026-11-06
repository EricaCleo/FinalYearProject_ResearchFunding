"""
Grant -> Publication -> OpenAlex Work matching.

For each publication listed under a grant's `publications` field: extract a
DOI if the raw text has one and resolve it directly; otherwise search
OpenAlex by title. Either way, the match is cross-checked before being
trusted -- a resolved DOI whose OpenAlex title doesn't actually match the
raw citation is flagged, not accepted blindly, and a title-search match is
corroborated against publication year and author name.

Usage:
    python match_publications.py --rgc-awards rgc_awards.csv --out publication_matches.csv --sample 100
    python match_publications.py --rgc-awards rgc_awards.csv --out publication_matches.csv   # full dataset
"""
import argparse
import csv
import json
import random
import re
from difflib import SequenceMatcher

from common import BudgetExhausted, clean_person_name, openalex_get

DOI_PATTERN = re.compile(r"10\.\d{4,9}/[^\s\"'<>\\]+")
YEAR_PATTERN = re.compile(r"\b(19|20)\d{2}\b")
YEAR_TOLERANCE = 1  # print year vs online-first year can differ by a year

MATCH_COLUMNS = [
    "raw_title", "raw_year", "raw_authors", "doi_extracted", "match_method",
    "matched_work_id", "matched_title", "matched_year", "title_similarity",
    "year_match", "author_match", "flag",
]


def normalize_title(title: str) -> str:
    title = (title or "").lower()
    title = re.sub(r"[^a-z0-9 ]+", " ", title)
    return re.sub(r"\s+", " ", title).strip()


def title_similarity(a: str, b: str) -> float:
    a, b = normalize_title(a), normalize_title(b)
    if not a or not b:
        return 0.0
    return SequenceMatcher(None, a, b).ratio()


def extract_doi(text: str) -> str:
    m = DOI_PATTERN.search(text or "")
    if not m:
        return ""
    return m.group(0).rstrip(".,;:\"')")


def parse_publication_entries(publications_raw: str) -> list[dict]:
    if not publications_raw:
        return []
    try:
        entries = json.loads(publications_raw)
    except (json.JSONDecodeError, TypeError):
        return []
    return entries if isinstance(entries, list) else []


def field_like(entry: dict, substring: str) -> str:
    # RGC's own column headers for this JSON blob are inconsistently spaced/
    # cased ("Title and Journal/Book" vs "Titleand Journal/Book"), so match
    # loosely by substring rather than an exact key.
    for key, value in entry.items():
        if substring in key.lower().replace(" ", ""):
            return (value or "").strip()
    return ""


def extract_authors(author_text: str) -> list[str]:
    # "LU, Z G, CHEN, H L, ..." / "Lee, Joanna Wai Ying ; Ng, Mee Kam ; Tang, Wing Shing*"
    parts = re.split(r"[;,]", author_text or "")
    surnames = []
    for part in parts:
        part = re.sub(r"[*†‡]", "", part).strip()
        if len(part) >= 2 and part.isupper() or (part and part[0].isupper() and part.isalpha()):
            surnames.append(part.lower())
    return surnames


def lookup_by_doi(doi: str) -> dict | None:
    try:
        return openalex_get(f"works/doi:{doi}")
    except BudgetExhausted:
        raise
    except RuntimeError:
        return None


_SHRINK_FRACTIONS = (1.0, 0.8, 0.6, 0.45, 0.3)


def search_by_title(title: str, per_page: int = 3) -> tuple[list[dict], str]:
    # The raw "title" field from RGC is really "title + journal + volume/pages"
    # all run together, and OpenAlex's title search ANDs every word together --
    # one stray journal-name or page-number token is enough to return zero
    # results. Shrink from the full string down to just a leading fraction of
    # its words until something matches; this finds roughly where the real
    # title ends without having to parse the citation format, which varies.
    # Returns (results, the cleaned candidate text that actually got the hit)
    # -- similarity should be checked against THAT, not the raw messy field,
    # or a correct match looks like a bad one just because of leftover junk.
    words = title.split()
    if not words:
        return [], ""
    for fraction in _SHRINK_FRACTIONS:
        n = max(4, round(len(words) * fraction))
        candidate = " ".join(words[:n]).strip(" ,.;:-")
        # "*" is a wildcard in OpenAlex's filter syntax, not a literal character --
        # scraped author/title text sometimes carries one as a corresponding-author
        # marker, which OpenAlex then rejects outright (400) rather than ignoring.
        candidate = candidate.replace("*", " ")
        # "," separates filter clauses in OpenAlex's own filter mini-language, even
        # inside one filter's value -- "...Volume: 111,Issue: 2..." gets read as
        # "end this filter, start a new one named Issue", which isn't a real field.
        candidate = candidate.replace(",", " ")
        candidate = re.sub(r"\s+", " ", candidate).strip()
        if len(candidate) < 3:
            continue
        data = openalex_get("works", {
            "filter": f"title.search:{candidate}",
            "sort": "relevance_score:desc",
            "per_page": per_page,
        })
        results = data.get("results", [])
        if results:
            return results, candidate
    return [], ""


def work_author_surnames(work: dict) -> list[str]:
    names = []
    for a in work.get("authorships", []):
        name = (a.get("author") or {}).get("display_name", "")
        if name:
            names.append(name.split()[-1].lower())
    return names


def match_one_publication(entry: dict, pi_name_raw: str) -> dict:
    raw_title = field_like(entry, "title")
    raw_year_text = field_like(entry, "yearofpublication") or field_like(entry, "year")
    raw_year_match = YEAR_PATTERN.search(raw_year_text)
    raw_year = raw_year_match.group(0) if raw_year_match else ""
    raw_authors_text = field_like(entry, "author")
    raw_authors = extract_authors(raw_authors_text) or extract_authors(clean_person_name(pi_name_raw))

    row = {
        "raw_title": raw_title, "raw_year": raw_year, "raw_authors": "|".join(raw_authors),
        "doi_extracted": "", "match_method": "no_match", "matched_work_id": "",
        "matched_title": "", "matched_year": "", "title_similarity": "",
        "year_match": "", "author_match": "", "flag": "no_doi_no_title",
    }

    doi = extract_doi(raw_title) or extract_doi(json.dumps(entry))
    row["doi_extracted"] = doi

    if doi:
        try:
            work = lookup_by_doi(doi)
        except BudgetExhausted as exc:
            row["match_method"] = "doi_failed"
            row["flag"] = "review_budget_exhausted"
            print(f"    budget exhausted on DOI lookup {doi}: {exc}")
            return row
        if work is None:
            row["match_method"] = "doi_failed"
            row["flag"] = "review_doi_not_found"
            return row
        sim = title_similarity(raw_title, work.get("title", ""))
        row.update({
            "match_method": "doi", "matched_work_id": work.get("id", ""),
            "matched_title": work.get("title", ""), "matched_year": work.get("publication_year", ""),
            "title_similarity": round(sim, 3),
        })
        row["flag"] = "ok" if sim >= 0.6 else "review_title_mismatch"
        return row

    if not raw_title:
        return row

    try:
        candidates, cleaned_query = search_by_title(raw_title)
    except BudgetExhausted as exc:
        row["match_method"] = "title_search_failed"
        row["flag"] = "review_budget_exhausted"
        print(f"    budget exhausted on title search: {exc}")
        return row
    except RuntimeError as exc:
        row["match_method"] = "title_search_failed"
        row["flag"] = "review_search_error"
        print(f"    search failed for \"{raw_title[:60]}\": {exc}")
        return row
    if not candidates:
        row["match_method"] = "title_search"
        row["flag"] = "review_no_candidates"
        return row

    # Rank by actual title similarity to the cleaned query, not search
    # relevance order -- otherwise a near-duplicate paper in the same
    # author's series (sharing most of the same leading words) can outrank
    # the real match once the query's been shrunk down to that shared prefix.
    top = max(candidates, key=lambda c: title_similarity(cleaned_query, c.get("title", "")))
    sim = title_similarity(cleaned_query, top.get("title", ""))
    year_match = bool(raw_year) and abs(int(top.get("publication_year") or 0) - int(raw_year)) <= YEAR_TOLERANCE
    cand_authors = work_author_surnames(top)
    author_match = bool(raw_authors) and any(a in cand_authors for a in raw_authors)

    row.update({
        "match_method": "title_search", "matched_work_id": top.get("id", ""),
        "matched_title": top.get("title", ""), "matched_year": top.get("publication_year", ""),
        "title_similarity": round(sim, 3), "year_match": year_match, "author_match": author_match,
    })

    if sim >= 0.85 and (year_match or author_match):
        row["flag"] = "ok"
    elif sim >= 0.85:
        row["flag"] = "review_no_corroboration"  # title looks right but year/author don't back it up
    else:
        row["flag"] = "review_low_similarity"
    return row


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out", default="publication_matches.csv",
                         help="Output CSV (single file). Ignored if --split-by-year is set.")
    parser.add_argument("--out-dir", default=".",
                         help="Directory for the per-year CSVs when --split-by-year is set.")
    parser.add_argument("--split-by-year", action="store_true",
                         help="Write one CSV per award_year (named <out-dir>/<year>.csv) instead of "
                              "a single combined file -- one sheet per year, as requested for the "
                              "real run, instead of the single-file mode used for sample testing.")
    parser.add_argument("--match-status", default="",
                         help="Only actually run OpenAlex matching for projects with this exact "
                              "status (e.g. 'Completed') -- projects with any other status still "
                              "appear in the output with every original field, just with the match "
                              "columns left blank (no API calls spent on them; nothing to find yet "
                              "for e.g. an On-going project).")
    parser.add_argument("--year-start", type=int, default=0, help="Only award_year >= this (inclusive).")
    parser.add_argument("--year-end", type=int, default=0, help="Only award_year <= this (inclusive).")
    parser.add_argument("--sample", type=int, default=0, help="Random sample of N projects (0 = full dataset)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--batch-count", type=int, default=0,
                         help="Split the sample into this many equal, non-overlapping chunks "
                              "(e.g. 3 so three people can each run their own third in parallel "
                              "on their own API key/budget, with no duplicate work).")
    parser.add_argument("--batch-index", type=int, default=0,
                         help="Which chunk to run (0-based). Requires --batch-count.")
    parser.add_argument("--offset", type=int, default=0,
                         help="Skip this many projects into the sample before starting -- for "
                              "uneven splits across people (e.g. 40/30/30) that --batch-count "
                              "can't do, since it only cuts equal-sized chunks.")
    parser.add_argument("--limit", type=int, default=0,
                         help="Process at most this many projects after --offset. Requires --offset's "
                              "counterpart on this call to define the slice; 0 = everything from --offset on.")
    args = parser.parse_args()

    if args.batch_count and not (0 <= args.batch_index < args.batch_count):
        parser.error(f"--batch-index must be between 0 and {args.batch_count - 1}")
    if args.batch_count and (args.offset or args.limit):
        parser.error("use either --batch-count/--batch-index or --offset/--limit, not both")

    with open(args.rgc_awards, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        original_fieldnames = reader.fieldnames
        rows = list(reader)

    with_pubs = sum(1 for r in rows if parse_publication_entries(r.get("publications", "")))
    print(f"{len(rows)} projects total, {with_pubs} with reported publications "
          f"({len(rows) - with_pubs} with none -- kept in the output, flagged, not dropped)")

    if args.year_start or args.year_end:
        def in_year_range(r):
            try:
                y = int(r.get("award_year", ""))
            except ValueError:
                return False
            return (not args.year_start or y >= args.year_start) and (not args.year_end or y <= args.year_end)
        rows = [r for r in rows if in_year_range(r)]
        print(f"Filtered to award_year {args.year_start or 'any'}-{args.year_end or 'any'}: {len(rows)} projects")

    if args.sample:
        random.seed(args.seed)
        rows = random.sample(rows, min(args.sample, len(rows)))
        print(f"Sampled {len(rows)} projects (seed={args.seed})")

    if args.offset or args.limit:
        # same seed -> everyone samples the identical 100 before slicing, so
        # agreed-upon, non-overlapping offset/limit ranges (e.g. 0-40, 40-70,
        # 70-100) cover it exactly with no gaps or duplicates
        end = args.offset + args.limit if args.limit else len(rows)
        rows = rows[args.offset:end]
        print(f"Running rows {args.offset}-{args.offset + len(rows) - 1} of the sample ({len(rows)} projects)")

    if args.batch_count:
        # same seed -> everyone samples the identical 100 before slicing, so
        # the three chunks are guaranteed non-overlapping and cover it exactly
        chunk_size = -(-len(rows) // args.batch_count)  # ceil division
        start = args.batch_index * chunk_size
        rows = rows[start:start + chunk_size]
        print(f"Running batch {args.batch_index + 1}/{args.batch_count}: "
              f"{len(rows)} projects (rows {start}-{start + len(rows) - 1} of the sample)")

    # Full schema = every original scraped column (so nothing is lost) plus
    # the match-derived ones, no duplicates -- project_id/pi_name_raw already
    # exist in the original columns, so they're not repeated.
    full_columns = list(original_fieldnames) + MATCH_COLUMNS
    blank_match = {col: "" for col in MATCH_COLUMNS}

    # Written one row at a time (and flushed) rather than held in memory and
    # saved at the end -- a budget cutoff or Ctrl+C partway through still
    # leaves every row matched so far safely on disk.
    flag_counts = {}
    total_rows = 0
    writers = {}  # award_year -> (file handle, DictWriter), only used when --split-by-year
    single_file = None

    def get_writer(award_year: str):
        nonlocal single_file
        if not args.split_by_year:
            if single_file is None:
                single_file = open(args.out, "w", encoding="utf-8-sig", newline="")
                w = csv.DictWriter(single_file, fieldnames=full_columns, extrasaction="ignore")
                w.writeheader()
                writers["_single"] = (single_file, w)
            return writers["_single"][1], single_file
        if award_year not in writers:
            import os
            os.makedirs(args.out_dir, exist_ok=True)
            path = os.path.join(args.out_dir, f"{award_year or 'unknown_year'}.csv")
            f = open(path, "w", encoding="utf-8-sig", newline="")
            w = csv.DictWriter(f, fieldnames=full_columns, extrasaction="ignore")
            w.writeheader()
            writers[award_year] = (f, w)
            print(f"  opened {path}")
        return writers[award_year][1], writers[award_year][0]

    try:
        for i, project in enumerate(rows, start=1):
            award_year = project.get("award_year", "")
            writer, handle = get_writer(award_year)
            do_match = (not args.match_status) or (project.get("status", "") == args.match_status)

            if not do_match:
                row = dict(project)
                row.update(blank_match)
                writer.writerow(row)
                handle.flush()
                total_rows += 1
                flag_counts["(unmatched status)"] = flag_counts.get("(unmatched status)", 0) + 1
                if i % 10 == 0:
                    print(f"  ...{i}/{len(rows)} projects processed, {total_rows} rows written so far")
                continue

            entries = [e for e in parse_publication_entries(project["publications"]) if isinstance(e, dict)]

            if not entries:
                # not dropped -- flagged for a later stage that matches the PI
                # directly to an OpenAlex Author and pulls their publications
                row = dict(project)
                row.update(blank_match)
                row.update({"match_method": "no_publications_reported", "flag": "no_publications_reported"})
                writer.writerow(row)
                handle.flush()
                total_rows += 1
                flag_counts[row["flag"]] = flag_counts.get(row["flag"], 0) + 1
                if i % 10 == 0:
                    print(f"  ...{i}/{len(rows)} projects processed, {total_rows} rows written so far")
                continue

            for entry in entries:
                match = match_one_publication(entry, project.get("pi_name_raw", ""))
                row = dict(project)
                row.update(match)
                writer.writerow(row)
                handle.flush()
                total_rows += 1
                flag_counts[match["flag"]] = flag_counts.get(match["flag"], 0) + 1
            if i % 10 == 0:
                print(f"  ...{i}/{len(rows)} projects processed, {total_rows} rows written so far")
    except KeyboardInterrupt:
        print(f"\nInterrupted -- {total_rows} rows already saved, safe to re-run later")
    finally:
        for f, _ in writers.values():
            f.close()

    out_desc = args.out_dir if args.split_by_year else args.out
    print(f"\nWrote {total_rows} rows -> {out_desc}")
    print("Flag breakdown:")
    for flag, count in sorted(flag_counts.items(), key=lambda kv: -kv[1]):
        pct = 100 * count / total_rows if total_rows else 0
        print(f"  {flag}: {count} ({pct:.1f}%)")
    if flag_counts.get("review_budget_exhausted"):
        print(f"\n{flag_counts['review_budget_exhausted']} rows hit the daily budget limit -- "
              f"re-run once it resets (midnight UTC) to fill those in, no need to redo the rest")


if __name__ == "__main__":
    main()
