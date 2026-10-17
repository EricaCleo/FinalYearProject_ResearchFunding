"""
Checks whether RGC's project detail pages contain any field labels we are
NOT currently capturing in parse_details.py's FIELD_KEYWORDS -- e.g. a
project start/commencement date, which supervisor asked about.

Per supervisor instruction, this does NOT re-scrape anything. It re-reads
the HTML files already downloaded under data/raw/rgc/html/ and reports any
label text found on the page that isn't mapped to one of our known fields,
so we know what's available before deciding whether it's worth capturing.

Usage:
    python check_unmapped_fields.py [--sample 50]
Reads from data/raw/rgc/html/ by default; --sample limits how many files to
check (default: all of them).
"""
import argparse
from collections import Counter
from pathlib import Path

from bs4 import BeautifulSoup

from common import REPO_ROOT
from parse_details import FIELD_KEYWORDS, extract_label_value_pairs

HTML_DIR = REPO_ROOT / "data" / "raw" / "rgc" / "html"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample", type=int, default=None, help="Only check this many files (default: all)")
    args = parser.parse_args()

    files = sorted(HTML_DIR.glob("*.html"))
    if args.sample:
        files = files[: args.sample]
    print(f"Checking {len(files)} files in {HTML_DIR}")

    unmapped_labels = Counter()
    example_value = {}

    for path in files:
        html = path.read_text(encoding="utf-8", errors="replace")
        soup = BeautifulSoup(html, "lxml")
        raw_fields = extract_label_value_pairs(soup)
        for label, value in raw_fields.items():
            label_lower = label.lower()
            if any(keyword in label_lower for keyword in FIELD_KEYWORDS):
                continue
            unmapped_labels[label] += 1
            if label not in example_value:
                example_value[label] = value if isinstance(value, str) else str(value)[:100]

    if not unmapped_labels:
        print("\nNo unmapped labels found -- every label on every checked page maps to a known field.")
        print("This means RGC's detail pages do not expose anything beyond what's already in FIELD_KEYWORDS "
              "(no separate start/commencement date field, etc.) across the files checked.")
        return

    print(f"\n{len(unmapped_labels)} distinct unmapped label(s) found (not currently captured):\n")
    for label, count in unmapped_labels.most_common():
        example = example_value[label][:80]
        print(f"  '{label}' -- seen on {count} page(s), example value: {example!r}")


if __name__ == "__main__":
    main()
