"""
Shared helpers for the RGC PI -> OpenAlex author-linkage pipeline (adapted from the
supervisor's guide: RGC_to_OpenAlex_Author_Linkage_Guide.md).

OpenAlex is free and does not require an account or API key for normal use. Setting
OPENALEX_MAILTO to your email is optional but recommended — OpenAlex gives faster,
more reliable responses ("the polite pool") to requests that identify a contact. If
your supervisor later provides an actual API key, set OPENALEX_API_KEY and it will be
used automatically; it's optional, everything here works without one.
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

# OpenAlex's own institution IDs for the 8 UGC-funded HK universities, keyed by the
# same canonical names INSTITUTION_ALIASES normalizes to. Looked up directly via
# OpenAlex (search_entities, entity_type=institutions) rather than guessed.
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
    """Looks up the OpenAlex institution ID for an RGC-scraped institution string, via
    the same name normalization already used for institution_match comparisons. Returns
    "" if the institution isn't one of the 8 UGC-funded universities this project
    covers (or wasn't scraped close enough to one of INSTITUTION_ALIASES' known forms)."""
    return INSTITUTION_OPENALEX_IDS.get(normalize_institution(institution_raw), "")


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


def extract_titles(publications_raw: str) -> list[str]:
    """RGC's `publications` field (rgc_awards.csv, from parse_details.py's completion-
    report Research Output table) is a JSON-encoded list of {column_header: value}
    dicts -- reads any key containing "title" rather than assuming one exact column
    name, since the real header is usually "Title and Journal/Book" (a combined
    citation string, not a pure title -- see auto_classify_publication_match.py)."""
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


_MIN_SECONDS_BETWEEN_REQUESTS = 0.3  # ~3.3 req/sec -- loosened from 0.15 (~6.5/sec) after hitting
# real 429s even at the tighter pacing; OpenAlex's 10/sec cap is a ceiling the whole
# pipeline should stay well under, not a target to approach
_last_request_time = 0.0


def _pace_requests():
    """Scripts in this pipeline (search_candidates.py especially) fire several
    OpenAlex requests back-to-back per PI with no delay between them -- bursts can
    trip OpenAlex's rate limiter even while comfortably under its per-day cap, since
    the limit is also enforced per-second. This keeps every call to openalex_get at
    least _MIN_SECONDS_BETWEEN_REQUESTS apart, regardless of which script is calling."""
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

    # OpenAlex's own docs ask for a descriptive User-Agent alongside mailto, and some
    # requests with no User-Agent at all (the plain "python-requests/x.y" default) get
    # flagged and blocked before request volume is even a factor -- seen in practice as
    # a persistent 429 on literally the first request of a run, not a burst pattern.
    headers = {
        "User-Agent": f"RGC-OpenAlex-linkage-pipeline (mailto:{MAILTO})" if MAILTO
        else "RGC-OpenAlex-linkage-pipeline (no contact email set -- see OPENALEX_MAILTO in common.py)"
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
            # Include the response body -- OpenAlex's 429s distinguish a transient
            # per-second limit from an exhausted daily budget (e.g. a prior
            # "dailyRemainingUsd":0 response), and that distinction was previously
            # being thrown away, making every 429 look identical and undebuggable.
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
