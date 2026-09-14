# Funding Size and Research Outcomes — RGC Data Collection

Collects completed RGC-funded projects (2000–present) by downloading each project's
official detail page HTML and parsing it into JSON, per the project plan (see `data/`
layout below). NIH and NSF collection will follow the same raw → parsed → linked
pattern once RGC is working.

## Data layout

```
data/
  raw/rgc/
    search_pages/   # saved HTML of search-results pages
    html/            # one file per project detail page, downloaded verbatim, never edited
    parsed.jsonl      # one JSON record per project, generated from html/
  linked/            # later: grant + OpenAlex outcome linkage
  audit/
    collection_log.jsonl   # every fetch attempt, success or failure
```

Raw/parsed data is git-ignored (see `.gitignore`) — only the code and folder structure
are committed. Everyone regenerates their own local copy.

## Setup (VS Code, run locally — not in this cloud session)

The RGC site (`cerg1.ugc.edu.hk`) isn't reachable from this cloud sandbox's network
policy, so steps 2–4 below must run on your own machine.

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
4. Open the folder in VS Code (`code .`), open a terminal there for the steps below.

## Running the RGC crawler

All commands run from `scripts/rgc/`.

1. **Search manually in your browser** at the RGC Project Enquiry page
   (`cerg1.ugc.edu.hk/cergprod/...`), e.g. filter by year/scheme/status. Save the
   results page (`File > Save Page As...` → HTML only) or copy its URL if it's a plain
   GET link.
2. **Extract detail-page links:**
   ```
   python fetch_search.py --file path/to/saved_results.html --out links.txt
   ```
   Open `links.txt` — if it's empty, open the saved HTML, find a real project link's
   `href`, and adjust `LINK_PATTERN` in `fetch_search.py` to match it.
3. **Download each project's HTML:**
   ```
   python download_details.py --links links.txt
   ```
   Safe to re-run — already-downloaded files are skipped. Failures are logged to
   `data/audit/collection_log.jsonl`.
4. **Parse into JSON:**
   ```
   python parse_details.py
   ```
   Inspect a few lines of `data/raw/rgc/parsed.jsonl`. If `title`/`pi`/`institution`/
   `amount` are empty but `raw_fields` has the data under different labels, fix
   `FIELD_KEYWORDS` in `parse_details.py`.

## Next steps

- Repeat search + download across all target years/schemes to cover 2000–present.
- Once a sample of real detail-page HTML exists, share it so the parser's field
  mapping can be corrected precisely instead of guessed.
- Validate collected counts against RGC's summary PDFs.
- Cross-reference outputs against OpenAlex (see project plan, later stage).
