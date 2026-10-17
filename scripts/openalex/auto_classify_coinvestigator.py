"""
Stage 6 of the automated PI matching pipeline: resolves PIs still tied after
stages 1-5 by cross-referencing RGC's own `co_investigators` field (scraped
per project, independent of anything OpenAlex itself asserts) against each
tied candidate's REAL co-authors on OpenAlex.

Rule: for each tied candidate, fetch their actual OpenAlex co-authors (from
their own works). If exactly one candidate's co-author list contains an
exact name-token match to one of the PI's real RGC co-investigators, that's
strong independent corroboration -- confirm it. If zero or 2+ candidates
show this overlap, stay unresolved (don't guess).

Name comparison is intentionally strict (exact token-set match only, same
as stages 1-3) -- this stage is corroborating evidence from a second
independent source, not a place to loosen matching rules.

Requires a copy of rgc_awards.csv (output of combine_rgc_data.py) to look up
each PI's co_investigators by project_id -- that field is RGC's own
free-text list of co-investigator names (not sourced from OpenAlex at all).

Usage:
    python auto_classify_coinvestigator.py --input still_unresolved_stage5.csv \
        --rgc-awards rgc_awards.csv \
        --out-crosswalk pi_openalex_crosswalk_stage6.csv \
        --out-unresolved still_unresolved_stage6.csv
"""
import argparse
import csv
import re
from collections import defaultdict

from common import openalex_get


def split_ids(value: str) -> list[str]:
    value = (value or "").strip()
    if not value:
        return []
    parts = value.split("|") if "|" in value else value.split(",")
    return [p.strip() for p in parts if p.strip()]


def name_tokens(name: str) -> frozenset[str]:
    return frozenset(re.findall(r"[a-z]+", (name or "").lower()))


def extract_coinvestigator_names(co_investigators_raw: str) -> list[str]:
    """RGC's co_investigators field is free text, e.g. "CHAN, Tai Man; WONG, Siu Ming"
    or "Tai Man Chan and Siu Ming Wong" -- split on the delimiters actually seen in
    practice (semicolon, comma, newline, or the word "and") rather than assuming one
    fixed format."""
    raw = co_investigators_raw or ""
    parts = re.split(r";|\n|\band\b", raw)
    return [p.strip(" ,.;") for p in parts if p.strip(" ,.;")]


def fetch_coauthor_names(author_id: str, max_works: int = 50) -> set[str]:
    data = openalex_get("works", params={
        "filter": f"authorships.author.id:{author_id}",
        "per_page": max_works,
    })
    names = set()
    for work in data.get("results", []) or []:
        for authorship in work.get("authorships", []) or []:
            name = (authorship.get("author") or {}).get("display_name")
            if name:
                names.add(name)
    return names


def classify_pi(rows: list[dict], rgc_awards_by_id: dict[str, dict]) -> dict | None:
    project_ids = split_ids(rows[0].get("rgc_project_ids", ""))
    rgc_coinv_names = set()
    for pid in project_ids:
        award = rgc_awards_by_id.get(pid)
        if award:
            rgc_coinv_names.update(extract_coinvestigator_names(award.get("co_investigators", "")))

    if not rgc_coinv_names:
        return None  # no co-investigator data to check against -- can't verify this way

    rgc_coinv_tokensets = [t for t in (name_tokens(n) for n in rgc_coinv_names) if t]
    if not rgc_coinv_tokensets:
        return None

    matched = []
    for r in rows:
        coauthor_names = fetch_coauthor_names(r["candidate_author_id"])
        coauthor_tokensets = {name_tokens(n) for n in coauthor_names}
        overlap = [t for t in rgc_coinv_tokensets if t in coauthor_tokensets]
        if overlap:
            matched.append((r, overlap))

    if len(matched) == 1:
        candidate, overlap = matched[0]
        return {
            "decision": "confirmed",
            "stage": "coinvestigator",
            "openalex_author_ids": candidate["candidate_author_id"],
            "openalex_display_names": candidate["candidate_display_name"],
            "openalex_orcid": candidate.get("candidate_orcid", ""),
            "reason": (f"Candidate's real OpenAlex co-authors include {len(overlap)} name(s) exactly matching "
                       f"RGC's own co_investigators field for this PI's project(s) -- only candidate with this overlap"),
        }

    return None  # 0 or 2+ candidates overlap -- don't guess


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, action="append",
                         help="Unresolved candidate rows. Repeat flag for multiple.")
    parser.add_argument("--rgc-awards", required=True, help="rgc_awards.csv from combine_rgc_data.py")
    parser.add_argument("--out-crosswalk", default="pi_openalex_crosswalk_stage6.csv")
    parser.add_argument("--out-unresolved", default="still_unresolved_stage6.csv")
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
    print(f"{n_pis} PIs entered stage 6")
    print(f"  {len(crosswalk_rows)} confirmed by co-investigator cross-check -> {args.out_crosswalk}")
    print(f"  {n_unresolved_pis} PIs still unresolved ({len(unresolved_rows)} candidate rows) -> {args.out_unresolved}")


if __name__ == "__main__":
    main()
