# RGC pre-matching data check

- Source: RGC Project Enquiry (cerg1.ugc.edu.hk), scraped via scripts/rgc/
- Collection filter: Award Year search, status in {Completed, On-going, Terminated, Withdrawn} combined per year (see scripts/rgc/search_rgc.py --status)
- Year range covered: 2006-2026
- Extraction date: see 'collected_at' column in source CSVs (per-row scrape timestamp)
- Report generated: 2026-10-08
- Observation unit: one row per RGC project (grant_id)
