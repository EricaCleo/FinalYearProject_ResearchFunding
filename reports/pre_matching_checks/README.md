# RGC pre-matching data check

- Source: RGC Project Enquiry (cerg1.ugc.edu.hk), scraped via scripts/rgc/
- Collection filter: Award Year search, status in {Completed, On-going, Terminated, Withdrawn} combined per year (see scripts/rgc/search_rgc.py --status)
- Year range covered: 2006-2026
- Extraction date: see 'collected_at' column in source CSVs (per-row scrape timestamp)
- Report generated: 2026-10-08
- Observation unit: one row per RGC project (grant_id)

## Investigated findings (Figure 3a, 3b)

**Early Career Scheme and HSSPFS (Figure 3a) show zero count before ~2011/2012.**
Explained: `search_rgc.py`'s funding-scheme code "1" means General Research Fund
only for Award Years 2006-2011, but means "ALL" schemes combined (GRF + ECS +
HSSPFS) from 2012 onward. This is RGC's own search-code behavior, not a
collection gap -- pre-2012 data in this project is GRF-only by design.

**"Business Studies" panel (Figure 3b) shows zero count before 2011.**
Investigated and resolved -- NOT a collection gap. Verified against RGC's live
site (Award Year 2008/09, Panel = Business Studies, Funding Scheme = General
Research Fund returns 8 records) and cross-checked against the scraped data:
all 8 project IDs (149008, 149808, 640808, 642908, 643908, 644008, 741608,
755108) are present. They are recorded with `panel = "Humanities, Social
Sciences"` and `field = "Business Studies"`, exactly as shown on RGC's own
project detail pages for that era -- Business Studies was a sub-field under
the Humanities, Social Sciences panel before RGC split it into its own
top-level panel (~2011 onward). Same pattern confirmed for 2009 (87 records)
and 2010 (113 records), all under `field = "Business Studies"`.

Consequence for analysis: a panel-only breakdown undercounts Business Studies
for 2008-2010. Any analysis that needs a consistent panel grouping across the
full 2006-2026 range should treat `field == "Business Studies"` as equivalent
to `panel == "Business Studies"` for those years, or otherwise harmonize the
two columns rather than using `panel` alone.
