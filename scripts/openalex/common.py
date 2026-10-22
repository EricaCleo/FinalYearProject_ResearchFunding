"""
Shared helpers for the RGC PI -> OpenAlex author-linkage pipeline.

OPENALEX_MAILTO (optional) gets faster responses from OpenAlex's "polite pool".
OPENALEX_API_KEY (optional) is used automatically if set.
"""
import json
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

# OpenAlex institution IDs for the 8 UGC-funded HK universities.
INSTITUTION_OPENALEX_IDS = {
    "City University of Hong Kong": "I168719708",
    "University of Hong Kong": "I889458895",
    "Chinese University of Hong Kong": "I177725633",
    "Hong Kong University of Science and Technology": "I200769079",
    "Hong Kong Polytechnic University": "I14243506",
    "Hong Kong Baptist University": "I141568987",
    "Lingnan University": "I165488957",
    "Education University of Hong Kong": "I4210086892",
}


def institution_openalex_id(institution_raw: str) -> str:
    return INSTITUTION_OPENALEX_IDS.get(normalize_institution(institution_raw), "")


def normalize_unicode(value) -> str:
    if value is None:
        return ""
    return unicodedata.normalize("NFKC", str(value)).strip()


def clean_person_name(name: str) -> str:
    # only flips to "given surname" order if there's a comma, e.g. "CHAN, Tai Man"
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


def extract_titles(publications_raw: str) -> list[str]:
    # publications field is a JSON list of {column_header: value} dicts; grab
    # whatever key has "title" in it since the real header varies
    if not publications_raw:
        return []
    try:
        entries = json.loads(publications_raw)
    except (json.JSONDecodeError, TypeError):
        return []
    if not isinstance(entries, list):
        return []
    titles = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        for key, value in entry.items():
            if "title" in key.lower() and value:
                titles.append(value.strip())
                break
    return titles


_MIN_SECONDS_BETWEEN_REQUESTS = 0.3  # stay under OpenAlex's per-second rate limit
_last_request_time = 0.0


def _pace_requests():
    global _last_request_time
    elapsed = time.monotonic() - _last_request_time
    if elapsed < _MIN_SECONDS_BETWEEN_REQUESTS:
        time.sleep(_MIN_SECONDS_BETWEEN_REQUESTS - elapsed)
    _last_request_time = time.monotonic()


def openalex_get(endpoint: str, params: dict | None = None, max_retries: int = 5):
    params = dict(params or {})
    if API_KEY:
        params["api_key"] = API_KEY
    if MAILTO:
        params["mailto"] = MAILTO

    # a missing User-Agent can get flagged/blocked by itself, so always send one
    headers = {
        "User-Agent": f"RGC-OpenAlex-linkage-pipeline (mailto:{MAILTO})" if MAILTO
        else "RGC-OpenAlex-linkage-pipeline"
    }

    url = f"{BASE_URL}/{endpoint.lstrip('/')}"

    last_detail = "unknown error"
    for attempt in range(max_retries):
        _pace_requests()
        try:
            response = requests.get(url, params=params, headers=headers, timeout=60)
        except requests.RequestException as exc:
            last_detail = f"network error ({exc})"
            print(f"    attempt {attempt + 1}/{max_retries}: {last_detail}, retrying")
            time.sleep(min(2 ** attempt, 30))
            continue

        if response.status_code == 429:
            last_detail = f"HTTP 429 rate limited: {response.text[:300]}"
            print(f"    attempt {attempt + 1}/{max_retries}: {last_detail}, retrying")
            time.sleep(min(2 ** attempt, 30) + 2)
            continue

        if not response.ok:
            last_detail = f"HTTP {response.status_code}: {response.text[:300]}"
            print(f"    attempt {attempt + 1}/{max_retries}: {last_detail}, retrying")
            time.sleep(min(2 ** attempt, 30))
            continue

        return response.json()

    raise RuntimeError(f"OpenAlex request failed after {max_retries} attempts: {url} ({last_detail})")
