"""
Exploratory charts to help understand the collected RGC data, beyond the
required Section 4A checks (see pre_matching_checks.py for those). Requested
by the supervisor as general "understand the data better" visualizations.

Usage:
    python exploratory_charts.py --input-dir path/to/per-year/csvs --out-dir exploratory_report/
"""
import argparse
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

YEAR_RE = re.compile(r"(20\d{2})")
CATEGORICAL_PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#4a3aa7", "#e34948"]


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
        frames.append(frame)
    df = pd.concat(frames, ignore_index=True)
    df["amount_parsed"] = df["amount"].str.replace(",", "", regex=False).replace("", None).astype(float)
    return df


def figure_total_funding_by_year(df: pd.DataFrame, out_dir: Path):
    positive = df[df["amount_parsed"] > 0]
    by_year = positive.groupby("award_year")["amount_parsed"].sum() / 1_000_000  # HK$ millions
    by_year.to_csv(out_dir / "figA_total_funding_by_year.csv", header=["total_amount_hkd_millions"])

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.bar(by_year.index, by_year.values, color=CATEGORICAL_PALETTE[0])
    ax.set_xlabel("Award year")
    ax.set_ylabel("Total funding (HK$ millions)")
    ax.set_title("Figure A: Total RGC funding awarded by year")
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "figA_total_funding_by_year.png", dpi=150)
    plt.close(fig)


def figure_funding_by_institution(df: pd.DataFrame, out_dir: Path):
    positive = df[df["amount_parsed"] > 0]
    by_inst = positive.groupby("institution").agg(
        total_amount_hkd_millions=("amount_parsed", lambda s: s.sum() / 1_000_000),
        n_grants=("amount_parsed", "size"),
    ).sort_values("total_amount_hkd_millions", ascending=True)
    by_inst.to_csv(out_dir / "figB_funding_by_institution.csv")

    fig, ax = plt.subplots(figsize=(9, 5))
    ax.barh(by_inst.index, by_inst["total_amount_hkd_millions"], color=CATEGORICAL_PALETTE[1])
    ax.set_xlabel("Total funding (HK$ millions), 2006-2026 combined")
    ax.set_title("Figure B: Total RGC funding by institution")
    ax.spines[["top", "right"]].set_visible(False)
    for i, (total, n) in enumerate(zip(by_inst["total_amount_hkd_millions"], by_inst["n_grants"])):
        ax.text(total, i, f"  {n} grants", va="center", fontsize=8, color="#52514e")
    fig.tight_layout()
    fig.savefig(out_dir / "figB_funding_by_institution.png", dpi=150)
    plt.close(fig)


def figure_grant_size_trend(df: pd.DataFrame, out_dir: Path):
    positive = df[df["amount_parsed"] > 0]
    by_year = positive.groupby("award_year")["amount_parsed"].agg(["mean", "median"])
    by_year.to_csv(out_dir / "figC_grant_size_trend.csv")

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(by_year.index, by_year["mean"], marker="o", markersize=4, color=CATEGORICAL_PALETTE[0], label="Mean")
    ax.plot(by_year.index, by_year["median"], marker="o", markersize=4, color=CATEGORICAL_PALETTE[1], label="Median")
    ax.set_xlabel("Award year")
    ax.set_ylabel("Grant amount (HK$)")
    ax.set_title("Figure C: Mean and median grant size by year")
    ax.legend(frameon=False)
    ax.spines[["top", "right"]].set_visible(False)
    fig.tight_layout()
    fig.savefig(out_dir / "figC_grant_size_trend.png", dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", required=True, help="Directory of per-year RGC CSVs (output of to_csv.py)")
    parser.add_argument("--out-dir", default="exploratory_report")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Loading per-year CSVs from {input_dir}")
    df = load_all_years(input_dir)
    print(f"{len(df)} rows loaded, award years {df['award_year'].min()}-{df['award_year'].max()}")

    print("\nFigure A: total funding by year")
    figure_total_funding_by_year(df, out_dir)

    print("Figure B: funding by institution")
    figure_funding_by_institution(df, out_dir)

    print("Figure C: mean/median grant size trend")
    figure_grant_size_trend(df, out_dir)

    print(f"\nAll outputs written to {out_dir}/")


if __name__ == "__main__":
    main()
