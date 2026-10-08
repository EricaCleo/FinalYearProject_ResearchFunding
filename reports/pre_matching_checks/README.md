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
Investigated and resolved -- NOT a collection gap. RGC's project pages have two
separate classification fields: Panel (broad) and Subject Area (narrow,
stored in this project's `field` column). Confirmed directly against a live
RGC project detail page (Project 149008, Award Year 2008/09): it literally
prints `Panel: Humanities, Social Sciences` and `Subject Area: Business
Studies`. Cross-checked against the scraped data: all 8 project IDs from an
RGC site search for Award Year 2008/09 + Panel=Business Studies + Funding
Scheme=General Research Fund (149008, 149808, 640808, 642908, 643908, 644008,
741608, 755108) are present with exactly this panel/field combination. Same
pattern confirmed for 2009 (87 records) and 2010 (113 records). RGC only made
Business Studies its own top-level Panel value from ~2011 onward; before that
it only ever appears as a Subject Area under the Humanities, Social Sciences
panel.

Note: RGC's own search form is inconsistent here -- its "Panel" dropdown
actually searches across both Panel and Subject Area (that's how the above
search found pre-2011 records despite their stored Panel value being
"Humanities, Social Sciences"), even though the field label implies it only
searches the Panel column. This is a quirk of RGC's site, not of this
project's collection or parsing.

Consequence for analysis: a panel-only breakdown undercounts Business Studies
for 2008-2010. Figure 3c (`fig3c_panel_harmonized_by_year.png`) reclassifies
any record with Subject Area = "Business Studies" as Panel = "Business
Studies" for charting purposes, so Business Studies reads consistently across
the full 2006-2026 range. Figure 3b is left untouched as RGC's literal,
unmodified Panel column.
