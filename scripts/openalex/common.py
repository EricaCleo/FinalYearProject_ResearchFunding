"""
Shared helpers for the RGC PI -> OpenAlex author-linkage pipeline (adapted from the
supervisor's guide: RGC_to_OpenAlex_Author_Linkage_Guide.md).

OpenAlex is free and does not require an account or API key for normal use. Setting
OPENALEX_MAILTO to your email is optional but recommended — OpenAlex gives faster,
more reliable responses ("the polite pool") to requests that identify a contact. If
your supervisor later provides an actual API key, set OPENALEX_API_KEY and it will be
used automatically; it's optional, everything here works without one.
"""
import os
import re
import time
import unicodedata

import requests

BASE_URL = "https://api.openalex.org"
API_KEY = os.getenv("OPENALEX_API_KEY")  # optional
MAILTO = os.getenv("OPENALEX_MAILTO")  # optional but recommended, e.g. export OPENALEX_MAILTO="you@example.com"

TITLE_PATTERN = re.compile(
    r"\b(professor|prof|doctor|dr|mr|mrs|ms|miss)\.?\b",
    flags=re.IGNORECASE,
)
ROLE_PATTERN = re.compile(
    r"\((pi|principal investigator|project coordinator|pc|co-i|co-investigator)\)",
    flags=re.IGNORECASE,
)

INSTITUTION_ALIASES = {
    "city university of hong kong": "City University of Hong Kong",
    "city university hong kong": "City University of Hong Kong",
    "cityu": "City University of Hong Kong",
    "the university of hong kong": "University of Hong Kong",
    "university of hong kong": "University of Hong Kong",
    "hku": "University of Hong Kong",
    "the chinese university of hong kong": "Chinese University of Hong Kong",
    "chinese university of hong kong": "Chinese University of Hong Kong",
    "cuhk": "Chinese University of Hong Kong",
    "hong kong university of science and technology": "Hong Kong University of Science and Technology",
    "hkust": "Hong Kong University of Science and Technology",
    "hong kong polytechnic university": "Hong Kong Polytechnic University",
    "the hong kong polytechnic university": "Hong Kong Polytechnic University",
    "polyu": "Hong Kong Polytechnic University",
    "hong kong baptist university": "Hong Kong Baptist University",
    "hkbu": "Hong Kong Baptist University",
    "lingnan university": "Lingnan University",
    "education university of hong kong": "Education University of Hong Kong",
    "the education university of hong kong": "Education University of Hong Kong",
    "eduhk": "Education University of Hong Kong",
}


def normalize_unicode(value) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def clean_person_name(name: str) -> str:
    """Conservative name cleaning. Does not guess surname order unless the original
    name contains a comma, e.g. 'CHAN, Tai Man'."""
    name = normalize_unicode(name)
    name = ROLE_PATTERN.sub(" ", name)
    name = TITLE_PATTERN.sub(" ", name)
    name = re.sub(r"[*†‡]+", " ", name)  # footnote markers
    name = re.sub(r"\s+", " ", name).strip(" ,;:")

    if name.count(",") == 1:
        surname, given = [part.strip() for part in name.split(",", 1)]
        if surname and given:
            name = f"{given} {surname}"

    name = re.sub(r"[.;:/\\|]+", " ", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name


def generate_name_variants(name: str) -> list[str]:
    cleaned = clean_person_name(name)
    if not cleaned:
        return []

    variants = {cleaned, cleaned.replace("-", " ")}
    tokens = cleaned.split()

    if len(tokens) >= 2:
        variants.add(" ".join([tokens[-1]] + tokens[:-1]))  # surname-first
        if len(tokens) >= 3:
            initial_variant = " ".join([tokens[0]] + [t[0] for t in tokens[1:-1]] + [tokens[-1]])
            variants.add(initial_variant)

    return sorted(v for v in variants if v)


def normalize_institution(value: str) -> str:
    value = normalize_unicode(value).lower()
    value = re.sub(r"[^a-z0-9 ]+", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return INSTITUTION_ALIASES.get(value, value.title())


def short_openalex_id(value) -> str:
    if not value:
        return ""
    return str(value).rstrip("/").split("/")[-1]


def openalex_get(endpoint: str, params: dict | None = None, max_retries: int = 5):
    params = dict(params or {})
    if API_KEY:
        params["api_key"] = API_KEY
    if MAILTO:
        params["mailto"] = MAILTO

    url = f"{BASE_URL}/{endpoint.lstrip('/')}"

    last_detail = "unknown error"
    for attempt in range(max_retries):
        try:
            response = requests.get(url, params=params, timeout=60)
        except requests.RequestException as exc:
            last_detail = f"network error ({exc})"
            print(f"    attempt {attempt + 1}/{max_retries}: {last_detail}, retrying")
            time.sleep(min(2 ** attempt, 30))
            continue

        if response.status_code == 429:
            last_detail = "HTTP 429 rate limited"
            print(f"    attempt {attempt + 1}/{max_retries}: {last_detail}, retrying")
            time.sleep(min(2 ** attempt, 30))
            continue

        if not response.ok:
            last_detail = f"HTTP {response.status_code}: {response.text[:300]}"
            print(f"    attempt {attempt + 1}/{max_retries}: {last_detail}, retrying")
            time.sleep(min(2 ** attempt, 30))
            continue

        return response.json()

    raise RuntimeError(f"OpenAlex request failed after {max_retries} attempts: {url} ({last_detail})")
