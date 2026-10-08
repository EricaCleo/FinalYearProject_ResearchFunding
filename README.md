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
real OpenAlex author profile. Since many people share a name, this is NOT automatic — the
guide this is built from (`RGC_to_OpenAlex_Author_Linkage_Guide.md`) requires a human to
review and classify every match. All scripts live in `scripts/openalex/`.

1. **Combine** (`combine_rgc_data.py`) — merges all per-year RGC CSVs into one
   `rgc_awards.csv`, deduped by `project_id`, with `award_year` taken from the filename
   (not the unreliable "Exercise Year" field — see script docstring).
2. **Search candidates** (`search_candidates.py`) — for each unique PI, searches OpenAlex
   by name variants and gathers evidence (name similarity, institution match, topics,
   ORCID, works/citation counts) for every candidate author found. This does NOT decide
   who's correct — it only collects evidence. Outputs `author_candidates_pilot.csv` and
   `author_candidates_for_review.csv` (same data plus empty columns for your decisions).
3. **Triage** (`triage_candidates.py`) — optional helper that groups the review CSV by PI
   and flags each as `likely_confirmed` (one clear institution-matched candidate) or
   `needs_review` (multiple candidates share the institution — these need the full manual
   check), so review time goes to the ambiguous PIs first.
4. **Manual review** — for each PI, open the flagged candidate(s) on openalex.org, check
   institution/ORCID/actual paper topics against the grant, and fill in
   `reviewer_decision` (confirmed/probable/ambiguous/not_found) in
   `author_candidates_for_review.csv`. This step cannot be automated — see the guide.
5. **(Next, not yet built)** — for confirmed matches, download each author's full works
   list and citation counts from OpenAlex, then join against `rgc_awards.csv` by PI to
   analyze funding size vs. research output.

```
python combine_rgc_data.py --input-dir path/to/per-year/csvs --out rgc_awards.csv
python search_candidates.py --input unique_pis.csv --pilot-size 40
python triage_candidates.py --input author_candidates_for_review.csv --out triage_summary.csv
```

OpenAlex needs no account for normal use. Optionally set `OPENALEX_MAILTO` (your email)
for faster, more reliable responses, or `OPENALEX_API_KEY` if your supervisor provides one.

## Next steps

- RGC collection (2006–2026) and Section 4A pre-matching checks are done — see
  `reports/pre_matching_checks/`.
- Finish manual review of the OpenAlex pilot batch, discuss open questions with supervisor
  (scope: solo vs. group PIs, handling multiple grants per PI, probable/ambiguous criteria).
- Scale the matching pipeline to all PIs once the pilot process is validated.
- Build the publication/citation download step for confirmed matches.
- Same raw → parsed → CSV pattern for NIH and NSF once RGC is complete.
