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

## Next steps

- Continue year by year through the full 2006–2026 range.
- Validate collected counts against RGC's summary PDFs.
- Cross-reference outputs against OpenAlex (see project plan, later stage).
- Same raw → parsed → CSV pattern for NIH and NSF once RGC is complete.
