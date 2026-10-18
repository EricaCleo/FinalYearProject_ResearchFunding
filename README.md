# Funding Size and Research Outcomes — RGC Data Collection

Collects completed RGC-funded projects by year (2006–present is what RGC's own search
supports; the site is not reachable further back) into structured JSON/CSV. NIH and NSF
collection will follow the same pattern once RGC is fully done.

## How the scraping actually works

RGC's Project Enquiry site (`cerg1.ugc.edu.hk`) has no API — everything is an old
JSP application from the early 2000s. There is **no manual browser step and no
per-page HTML saving by hand**. The whole pipeline is automated:

1. **Search** (`search_rgc.py`) — RGC's search results and "next page" links turn out
   to be a JavaScript function that fills in a hidden form and POSTs it. This script
   replicates that POST directly, for every page of a given Award Year's results, and
   collects every project's ID from them. It also saves a copy of each raw
   search-results page under `data/raw/rgc/search_pages/` purely as an audit trail —
   this is not the primary way any data gets collected, just a record of what was
   searched.
2. **Download** (`download_details.py`) — for each project ID found, this does one
   plain HTTP GET of that project's own detail page and saves the raw HTML under
   `data/raw/rgc/html/<proj_id>.html`. This is the actual "one file per project"
   download step — there is no separate concept of downloading search-result pages
   here, only individual project pages.
3. **Parse** (`parse_details.py`) — reads every saved detail-page HTML file and
   extracts structured fields (title, PI, institution, amount, status, dates,
   abstract, and — for completed projects with a submitted report — publications and
   conference presentations as structured lists) into one combined
   `data/raw/rgc/parsed.jsonl`.
4. **Export** (`to_csv.py`) — converts `parsed.jsonl` into a spreadsheet-friendly CSV,
   filtered to one Award Year at a time via that year's `links_<year>.txt` file (the
   authoritative record of which projects were found under that specific search).

Both `search_rgc.py` and `download_details.py` retry transient network errors (this is
an old, occasionally flaky government server) before giving up on a single page/project
— they don't abort the whole run over one bad request.

## Data layout

```
data/
  raw/rgc/
    search_pages/    # audit copies of raw search-results pages (not primary data)
    html/            # one file per project detail page, downloaded verbatim, never edited
    parsed.jsonl      # one JSON record per project, generated from html/ (cumulative, all years)
    parsed_<year>.csv # one CSV per Award Year, for opening in Excel/Numbers/Sheets
  linked/            # later: grant + OpenAlex outcome linkage
  audit/
    collection_log.jsonl   # every fetch attempt, success or failure
```

Raw/parsed data and CSVs are git-ignored — only the code and folder structure are
committed. Everyone collecting data regenerates their own local copy.

## Setup (VS Code, run locally)

The RGC site isn't reachable from a cloud sandbox's network policy, so this must run on
your own machine.

1. Install [VS Code](https://code.visualstudio.com/) and the Python extension.
2. Clone the repo and check out this branch:
   ```
   git clone https://github.com/EricaCleo/FinalYearProject_ResearchFunding
   cd FinalYearProject_ResearchFunding
   git checkout claude/relaxed-babbage-3pbdwl
   ```
3. Create a virtual environment and install dependencies:
   ```
   python -m venv .venv
   source .venv/bin/activate   # Windows: .venv\Scripts\activate
   pip install -r requirements.txt
   ```
4. Open the folder in VS Code (`code .`), open a terminal in `scripts/rgc/` for the
   commands below.

## Running the RGC crawler, one Award Year at a time

```
python search_rgc.py --years 2016 --status C --out links_2016.txt
caffeinate -i python download_details.py --links links_2016.txt   # caffeinate: don't let the Mac sleep mid-run
python parse_details.py
python to_csv.py --links links_2016.txt
```

- `--status C` = Completed projects only (matches this project's scope: completed
  awards with official results). Use `--status ""` for every status.
- `--years` also accepts a range, e.g. `--years 2006-2026`, to search multiple years in
  one command — used per-year here so each year's collection can be checked before
  moving to the next.
- Repeat this same four-command block for each year. `download_details.py` skips
  anything already downloaded, so re-running any step is always safe.

## Pre-matching data checks (Section 4A of the supervisor's guide)

Required before any OpenAlex matching work: four diagnostic figures plus a
duplicate-record table, run directly against the collected per-year RGC CSVs.
Script: `scripts/rgc/pre_matching_checks.py`. Outputs are committed (not
git-ignored, unlike raw data) to `reports/pre_matching_checks/`, since these
figures are themselves a deliverable.

```
cd scripts/rgc
python pre_matching_checks.py --input-dir path/to/per-year/csvs --out-dir ../../reports/pre_matching_checks
```

Produces: annual project counts (Fig 1), a year-by-field missing-rate heatmap
(Fig 2), scheme and panel category distribution by year (Fig 3a/3b, plus a
harmonized Fig 3c — see below), funding-amount distribution by year (Fig 4),
and a duplicate-record table. See `reports/pre_matching_checks/README.md` for
the full write-up of findings, including two investigated-and-explained
anomalies: Early Career Scheme/HSSPFS show zero count before 2011/2012
(RGC's funding-scheme search code meant GRF-only pre-2012), and the
"Business Studies" panel shows zero count before 2011 (those projects are
correctly captured under `field = "Business Studies"` rather than `panel`,
since RGC only split it into its own top-level panel around 2011 — verified
against RGC's live site). Neither is a collection error.

## Exploratory charts

Supervisor-requested charts for general understanding of the collected data,
separate from the mandatory Section 4A checks above. Script:
`scripts/rgc/exploratory_charts.py`. Outputs committed to
`reports/exploratory_charts/`.

```
cd scripts/rgc
python exploratory_charts.py --input-dir path/to/per-year/csvs --out-dir ../../reports/exploratory_charts
```

Produces: total funding awarded by year (Fig A), total funding and grant
count by institution (Fig B), and mean/median grant size trend by year (Fig C).

## Phase 2: matching RGC PIs to OpenAlex authors

RGC gives a PI's name on paper; to measure what they actually published, we need their
real OpenAlex author profile. Since many people share a name, this can't be done by name
alone — the pipeline below (built from `RGC_to_OpenAlex_Author_Linkage_Guide.md` plus
lessons from manual pilot review) runs a sequence of automated, no-manual-decision
filter stages, each stricter than the last, and only leaves a PI unresolved when none of
them can prove a single identity. All scripts live in `scripts/openalex/`.

Candidate **generation** (search by name) and candidate **classification** (deciding
which one is correct) are different problems — for very common names, the right
candidate can be entirely absent from the top search results, which no downstream
classification logic can fix. That's a known, open gap; see "Known limitations" below.

0. **Combine** (`combine_rgc_data.py`) — merges all per-year RGC CSVs into one
   `rgc_awards.csv`, deduped by `project_id`, with `award_year` taken from the filename
   (not the unreliable "Exercise Year" field — see script docstring). Also carries
   RGC's own `co_investigators` and `publications` fields through, used by stages 5–6.
1. **Search candidates** (`search_candidates.py`) — for each unique PI, searches OpenAlex
   by name variants and gathers evidence (name similarity, institution match, topics,
   ORCID, works/citation counts) for every candidate author found. This does NOT decide
   who's correct — it only collects evidence. Outputs `author_candidates_pilot.csv`.
2. **Stage 1 — institution + exact name** (`auto_classify_institution.py`) — confirms a
   PI when exactly one candidate matches BOTH the RGC institution and an exact
   name-token match. Also writes full candidate rows for PIs with 0 matches
   (`--out-no-exact-match`) so stage 4 can still use them.
3. **Stage 2 — ORCID among exact-name matches** (`auto_classify_orcid.py`) — for PIs
   still tied after stage 1, confirms when exactly one of the institution+exact-name
   candidates carries a non-empty ORCID.
4. **Stage 3 — proven ORCID duplicates** (`auto_classify_exact_name.py`) — for PIs still
   tied, confirms (retaining ALL of them — needed later to dedupe combined publication
   records) when 2+ tied candidates share the literal same ORCID, which is proof they're
   the same real person split across OpenAlex profiles. Does NOT use works_count as a
   tie-breaker — "no ORCID conflict" is not proof of identity.
5. **Stage 4 — name-formatting variants** (`auto_classify_name_variants.py`) — handles
   two gaps exact-token matching correctly declines to guess: initials vs. spelled-out
   given names (e.g. "S.Y.R. Hui" vs "Ron Shu-Yuen Hui"), and compound given-name
   splitting (e.g. "Wenxiong" vs "Wen-Xiong"). Same proven-ORCID-duplicate handling as
   stage 3 for ties.
6. **Stage 5 — publication-title match** (`auto_classify_publication_match.py`) —
   for PIs still tied, searches OpenAlex for the actual grant-resulting paper (from
   RGC's own scraped `publications` field) by exact normalized title, and reads the
   correct author ID straight off that paper's real authorship list. Needs
   `rgc_awards.csv` (`--rgc-awards`).
7. **Stage 6 — co-investigator cross-check** (`auto_classify_coinvestigator.py`) — for
   PIs still tied, cross-references RGC's own `co_investigators` field against each
   tied candidate's real OpenAlex co-authors; confirms only when exactly one candidate
   overlaps. Needs `rgc_awards.csv` (`--rgc-awards`).
8. **Stage 7 — Semantic Scholar field-check** (`auto_classify_semantic_scholar.py`) — an
   automatable equivalent of manually checking a PI's Google Scholar page (which has no
   API and blocks bulk access). Looks up the PI on Semantic Scholar using their own
   `rgc_institution` (dynamic per PI — RGC PIs span all 8 UGC-funded universities, not
   just one), and checks whether a tied candidate's OpenAlex topics share enough
   specific keywords with the PI's real paper titles to arbitrate between them.
9. **Still unresolved after stage 7** — true manual review, same as the pilot: open the
   candidate(s) on openalex.org and check institution/ORCID/paper topics by hand.
10. **(Next, not yet built)** — for confirmed matches, download each author's full works
    list and citation counts from OpenAlex, then join against `rgc_awards.csv` by PI to
    analyze funding size vs. research output.

```
python combine_rgc_data.py --input-dir path/to/per-year/csvs --out rgc_awards.csv
python search_candidates.py --input unique_pis.csv --pilot-size 40
python auto_classify_institution.py --input author_candidates_pilot.csv
python auto_classify_orcid.py --input needs_stage2_filtering.csv
python auto_classify_exact_name.py --input still_needs_stage3.csv   # see each script's own --help for its exact in/out flags
python auto_classify_name_variants.py --input no_exact_match_candidates.csv --input still_unresolved.csv
python auto_classify_publication_match.py --input truly_unresolved.csv --rgc-awards rgc_awards.csv
python auto_classify_coinvestigator.py --input still_unresolved_stage5.csv --rgc-awards rgc_awards.csv
python auto_classify_semantic_scholar.py --input still_unresolved_stage6.csv
```

OpenAlex needs no account for normal use. Optionally set `OPENALEX_MAILTO` (your email)
for faster, more reliable responses, or `OPENALEX_API_KEY` if your supervisor provides one.
Stage 7 additionally calls the free Semantic Scholar API (no account needed either).

### Known limitations

- **Candidate generation gap**: for extremely common names, the correct OpenAlex
  profile can be missing from `search_candidates.py`'s results entirely (a
  merged/garbage profile with an inflated works_count can outrank it). Stage 5 now
  partially covers this: if the grant-resulting publication's title match finds a
  paper whose own authorship list has exactly one author matching the PI by name
  AND institution, it confirms that author as a brand-new candidate (decision stage
  `publication_match_new_candidate`) even though no row for them existed in the
  original search-candidate pool — this is exactly how Wei Wang and Li Ying were
  resolved manually in the pilot. It only helps when the PI has a scraped,
  OpenAlex-findable publication, though — a PI with no usable `publications` data
  and a missing candidate still needs a manual ORCID lookup from their institutional
  page.
- Stages 5–7 assume `rgc_project_ids` is pipe-separated (`|`), this project's existing
  convention for multi-value fields (comma is accepted as a fallback).
- `triage_candidates.py` (grouping the review CSV into `likely_confirmed`/`needs_review`)
  predates the staged pipeline above and is kept for ad hoc manual spot-checks, not as a
  pipeline step.

## Next steps

- RGC collection (2006–2026) and Section 4A pre-matching checks are done — see
  `reports/pre_matching_checks/`.
- Finish manual review of the OpenAlex pilot batch, discuss open questions with supervisor
  (scope: solo vs. group PIs, handling multiple grants per PI, probable/ambiguous criteria).
- Scale the matching pipeline to all PIs once the pilot process is validated.
- Build the publication/citation download step for confirmed matches.
- Same raw → parsed → CSV pattern for NIH and NSF once RGC is complete.
