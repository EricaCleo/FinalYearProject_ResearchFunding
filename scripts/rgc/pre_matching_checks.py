"""
Section 4A of the supervisor's guide: pre-matching data checks, required BEFORE
any OpenAlex matching work continues. Produces four figures and one
duplicate-record table from the collected RGC per-year CSVs (output of
scripts/rgc/to_csv.py), so collection problems are caught before they're baked
into the PI-matching pipeline.

Usage:
    python pre_matching_checks.py --input-dir path/to/per-year/csvs --out-dir report/

Each input file's award year is read from its filename, same convention as
combine_rgc_data.py. This does not modify or combine the source CSVs — it only
reads them and writes figures/tables to --out-dir.
"""
import argparse
import re
from collections import Counter
from datetime import date, datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

YEAR_RE = re.compile(r"(20\d{2})")

CATEGORICAL_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]
SEQUENTIAL_CMAP = "Blues"

MISSINGNESS_COLUMNS = ["grant_id", "project_number", "pi", "institution", "amount", "title", "abstract",
                        "end_date", "exercise_year"]
ID_COLUMN = "grant_id"


def year_from_filename(path: Path) -> int:
    m = YEAR_RE.search(path.stem)
    if not m:
        raise ValueError(f"Can't find a 4-digit year in filename: {path.name}")
    return int(m.group(1))


def load_all_years(input_dir: Path) -> pd.DataFrame:
    frames = []
    for path in sorted(input_dir.glob("*.csv")):
        award_year = year_from_filename(path)
        frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)
        frame["award_year"] = award_year
        frame["source_file"] = path.name
        frames.append(frame)
        print(f"  {path.name}: award_year={award_year}, {len(frame)} rows")
    return pd.concat(frames, ignore_index=True)


def parse_amount(value: str) -> float | None:
    value = (value or "").strip().replace(",", "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def figure_annual_counts(df: pd.DataFrame, out_dir: Path):
    by_year = df.groupby("award_year").agg(
        raw_rows=(ID_COLUMN, "size"),
        distinct_projects=(ID_COLUMN, "nunique"),
    ).reset_index()

    fig, ax = plt.subplots(figsize=(10, 5))
    x = by_year["award_year"]
    width = 0.38
    ax.bar(x - width / 2, by_year["raw_rows"], width, label="Raw rows", color=CATEGORICAL_PALETTE[0])
    ax.bar(x + width / 2, by_year["distinct_projects"], width, label="Distinct projects", color=CATEGORICAL_PALETTE[1])
    ax.set_xlabel("Award year")
    ax.set_ylabel("Count")
    ax.set_title("Figure 1: Annual project counts (raw rows vs. distinct project IDs)")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "fig1_annual_counts.png", dpi=150)
    plt.close(fig)

    by_year.to_csv(out_dir / "fig1_annual_counts.csv", index=False)
    return by_year


def figure_missingness(df: pd.DataFrame, out_dir: Path):
    years = sorted(df["award_year"].unique())
    missing_rate = pd.DataFrame(index=years, columns=MISSINGNESS_COLUMNS, dtype=float)

    for year in years:
        year_df = df[df["award_year"] == year]
        for col in MISSINGNESS_COLUMNS:
            if col not in year_df.columns:
                missing_rate.loc[year, col] = float("nan")
                continue
            blank = year_df[col].astype(str).str.strip().eq("")
            missing_rate.loc[year, col] = blank.mean() * 100

    fig, ax = plt.subplots(figsize=(8, max(4, len(years) * 0.35)))
    im = ax.imshow(missing_rate.values, aspect="auto", cmap=SEQUENTIAL_CMAP, vmin=0, vmax=100)
    ax.set_xticks(range(len(MISSINGNESS_COLUMNS)))
    ax.set_xticklabels(MISSINGNESS_COLUMNS, rotation=45, ha="right")
    ax.set_yticks(range(len(years)))
    ax.set_yticklabels(years)
    ax.set_title("Figure 2: Missing-rate heatmap by year and field (%)")
    fig.colorbar(im, ax=ax, label="% missing")
    fig.tight_layout()
    fig.savefig(out_dir / "fig2_missingness_heatmap.png", dpi=150)
    plt.close(fig)

    missing_rate.to_csv(out_dir / "fig2_missingness_heatmap.csv")
    return missing_rate


def figure_category_distribution(df: pd.DataFrame, out_dir: Path):
    for category_col, fig_name, fig_title in [
        ("scheme", "fig3a_scheme_by_year.png", "Figure 3a: RGC scheme by year"),
        ("panel", "fig3b_panel_by_year.png", "Figure 3b: RGC panel by year"),
    ]:
        if category_col not in df.columns:
            continue
        pivot = df.pivot_table(index="award_year", columns=category_col, values=ID_COLUMN, aggfunc="count", fill_value=0)
        pivot.to_csv(out_dir / fig_name.replace(".png", ".csv"))

        fig, ax = plt.subplots(figsize=(10, 5))
        bottom = pd.Series(0, index=pivot.index)
        for i, category in enumerate(pivot.columns):
            color = CATEGORICAL_PALETTE[i % len(CATEGORICAL_PALETTE)]
            ax.bar(pivot.index, pivot[category], bottom=bottom, label=category, color=color)
            bottom = bottom + pivot[category]
        ax.set_xlabel("Award year")
        ax.set_ylabel("Count")
        ax.set_title(fig_title)
        ax.legend(frameon=False, bbox_to_anchor=(1.02, 1), loc="upper left", fontsize=8)
        ax.spines[["top", "right"]].set_visible(False)
        fig.tight_layout()
        fig.savefig(out_dir / fig_name, dpi=150)
        plt.close(fig)


def figure_funding_distribution(df: pd.DataFrame, out_dir: Path):
    df = df.copy()
    df["amount_parsed"] = df["amount"].apply(parse_amount)

    n_missing = df["amount_parsed"].isna().sum()
    n_zero = (df["amount_parsed"] == 0).sum()
    n_negative = (df["amount_parsed"] < 0).sum()
    n_positive = (df["amount_parsed"] > 0).sum()

    summary = pd.DataFrame([{
        "n_total": len(df), "n_missing_amount": n_missing, "n_zero_amount": n_zero,
        "n_negative_amount": n_negative, "n_positive_amount": n_positive,
    }])
    summary.to_csv(out_dir / "fig4_funding_amount_summary.csv", index=False)
    print(f"  Amount field: {n_positive} positive, {n_zero} zero, {n_negative} negative, {n_missing} missing")

    positive = df[df["amount_parsed"] > 0]
    years = sorted(positive["award_year"].unique())
    data_by_year = [positive.loc[positive["award_year"] == y, "amount_parsed"] for y in years]

    fig, ax = plt.subplots(figsize=(10, 5))
    bp = ax.boxplot(data_by_year, tick_labels=years, patch_artist=True)
    for box in bp["boxes"]:
        box.set_facecolor(CATEGORICAL_PALETTE[0])
        box.set_alpha(0.5)
    ax.set_yscale("log")
    ax.set_xlabel("Award year")
    ax.set_ylabel("Amount (log scale, positive values only)")
    ax.set_title("Figure 4: Funding amount distribution by year")
    plt.setp(ax.get_xticklabels(), rotation=45, ha="right")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "fig4_funding_distribution.png", dpi=150)
    plt.close(fig)


def duplicate_table(df: pd.DataFrame, out_dir: Path):
    rows_out = []
    for year in sorted(df["award_year"].unique()):
        year_df = df[df["award_year"] == year]
        raw_rows = len(year_df)
        unique_keys = year_df[ID_COLUMN].nunique()
        key_counts = year_df[ID_COLUMN].value_counts()
        duplicate_key_rows = int((key_counts[key_counts > 1]).sum())
        exact_duplicate_rows = int(year_df.duplicated(keep=False).sum())
        rows_out.append({
            "award_year": year, "raw_rows": raw_rows, "unique_grant_ids": unique_keys,
            "duplicate_key_rows": duplicate_key_rows, "exact_duplicate_rows": exact_duplicate_rows,
        })

    total_raw = len(df)
    total_unique = df[ID_COLUMN].nunique()
    key_counts_all = df[ID_COLUMN].value_counts()
    cross_year_dupe_ids = key_counts_all[key_counts_all > 1].index.tolist()
    rows_out.append({
        "award_year": "ALL", "raw_rows": total_raw, "unique_grant_ids": total_unique,
        "duplicate_key_rows": int((key_counts_all[key_counts_all > 1]).sum()),
        "exact_duplicate_rows": int(df.duplicated(keep=False).sum()),
    })

    table = pd.DataFrame(rows_out)
    table.to_csv(out_dir / "duplicate_record_table.csv", index=False)

    print(f"\n  Expected unique key: grant_id (RGC's own project number), scoped within an award_year file.")
    print(f"  Total raw rows: {total_raw}, total unique grant_id: {total_unique}")
    if cross_year_dupe_ids:
        print(f"  WARNING: {len(cross_year_dupe_ids)} grant_id values appear under more than one award_year "
              f"file — these need manual explanation (re-upload mistake vs. genuine cross-year listing).")
        pd.Series(cross_year_dupe_ids, name="grant_id").to_csv(out_dir / "cross_year_duplicate_ids.csv", index=False)
    return table


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, help="Directory of per-year RGC CSVs (output of to_csv.py)")
    parser.add_argument("--out-dir", default="pre_matching_report")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading per-year CSVs from {input_dir}")
    df = load_all_years(input_dir)

    years = sorted(df["award_year"].unique())
    header = (
        f"# RGC pre-matching data check\n\n"
        f"- Source: RGC Project Enquiry (cerg1.ugc.edu.hk), scraped via scripts/rgc/\n"
        f"- Collection filter: Award Year search, status in {{Completed, On-going, Terminated, Withdrawn}} "
        f"combined per year (see scripts/rgc/search_rgc.py --status)\n"
        f"- Year range covered: {years[0]}-{years[-1]}\n"
        f"- Extraction date: see 'collected_at' column in source CSVs (per-row scrape timestamp)\n"
        f"- Report generated: {date.today().isoformat()}\n"
        f"- Observation unit: one row per RGC project (grant_id)\n"
    )
    (out_dir / "README.md").write_text(header, encoding="utf-8")
    print(header)

    print("\nFigure 1: annual counts")
    figure_annual_counts(df, out_dir)

    print("\nFigure 2: missingness heatmap")
    figure_missingness(df, out_dir)

    print("\nFigure 3: category distribution (scheme, panel)")
    figure_category_distribution(df, out_dir)

    print("\nFigure 4: funding distribution")
    figure_funding_distribution(df, out_dir)

    print("\nDuplicate-record table")
    duplicate_table(df, out_dir)

    print(f"\nAll outputs written to {out_dir}/")


if __name__ == "__main__":
    main()
