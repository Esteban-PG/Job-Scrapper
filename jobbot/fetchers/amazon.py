"""
amazon.jobs fetcher for the alert bot.

Amazon doesn't use a third-party ATS: it has its own (`sourceSystem:
JobCreator`) and exposes it in a single JSON call, with no token and no cookies:

    POST https://www.amazon.jobs/api/jobs/search?is_als=true
    body: {"locationFacets": [[{"name": "country", "values": [{"name": "CR"}]}]],
           "query": "", "size": 100, "start": 0, ...}

Response: `{found, start, facets, searchHits: [{fields: {...}}]}`. Watch the
shape of `fields`: **each value is a single-element list**
(`{"title": ["Designer, …"], "city": ["Heredia"]}`), not a string. That's why
everything goes through `_first()` before being used.

It's the only source that **filters by category at the origin**, unlike the rest
(see "Design decisions" in the README). The reason: Amazon publishes a lot that
isn't engineering — of the 73 Costa Rica postings, 65 are sales, design,
administrative support and the like. Careful not to narrow it too much: the
"Software Development" category alone has **1** posting in Costa Rica, because
Amazon classifies nearly all of engineering under "Operations, IT, & Support
Engineering".

Three details that already cost one debugging round and are worth not
rediscovering:

- The country goes in as an **ISO-2 code** (`CR`), not as a name. Since the rest
  of the fetchers receive `countries: ["Costa Rica"]` from `config/sources.yaml`,
  it's translated here with `COUNTRY_CODES` so that contract isn't broken.
- The `urlNextStep` field is **useless as a link**: it points to
  `account.amazon.jobs/jobs/<id>/apply`, which redirects to the login screen.
  The public page is `www.amazon.jobs/en/jobs/<icimsJobId>` (which redirects on
  its own to the slug with the title).
- A misspelled category name **doesn't error out**: it silently returns zero
  postings. That's why you should take them from `--categories` and not from
  memory.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.amazon
    python -m jobbot.fetchers.amazon --categories   # which categories exist
"""

import time
from datetime import datetime, timezone

import requests

from .useragents import BROWSER_UA

SEARCH_URL = "https://www.amazon.jobs/api/jobs/search?is_als=true"
JOB_URL = "https://www.amazon.jobs/en/jobs/{}"

# Verified: it accepts size=100 in a single call (500 too, but there's no need
# to ask for more). It paginates with start in case the country had more.
PAGE_SIZE = 100
MAX_RESULTS = 400
PAGE_PAUSE = 1.0

# Amazon filters by ISO-2 and the YAML talks in names. They're added as needed;
# any 2-letter code is also accepted as-is.
COUNTRY_CODES = {
    "costa rica": "CR",
    "mexico": "MX", "méxico": "MX",
    "colombia": "CO",
    "argentina": "AR",
    "brazil": "BR", "brasil": "BR",
    "chile": "CL",
    "peru": "PE", "perú": "PE",
    "united states": "US", "united states of america": "US",
    "canada": "CA",
    "spain": "ES", "españa": "ES",
}

# Amazon's technical categories, with the EXACT facet name (if it's spelled
# differently the filter doesn't fail: it returns zero). Verified against Costa
# Rica's `category` facet. To see the ones available in a country:
#     python -m jobbot.fetchers.amazon --categories
CATEGORIES_TECH = [
    "Software Development",
    "Operations, IT, & Support Engineering",
    "Business Intelligence",
    "Solutions Architect",
]

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.amazon.jobs",
    "Referer": "https://www.amazon.jobs/en/search",
}


def _country_code(country):
    """Country name -> ISO-2. Also accepts the code already written out."""
    code = COUNTRY_CODES.get(country.strip().lower())
    if code:
        return code
    if len(country.strip()) == 2:
        return country.strip().upper()
    raise ValueError(
        f"Amazon filters by ISO-2 code and I don't know {country!r}. Add it to "
        f"COUNTRY_CODES in jobbot/fetchers/amazon.py or put the code directly "
        f"in sources.yaml (e.g. countries: ['CR'])."
    )


def _payload(codes, query, start, size, categories=()):
    return {
        "accessLevel": "EXTERNAL",
        "contentFilterFacets": [
            {"name": "primarySearchLabel", "requestedFacetCount": 9999}],
        # Without this the confidential postings get in, and they have no useful
        # title.
        "excludeFacets": [
            {"name": "isConfidential", "values": [{"name": "1"}]},
            {"name": "businessCategory", "values": [{"name": "a-confidential-job"}]},
        ],
        # Category filter. Empty = all of them (and the bot filters by title).
        # Amazon is the exception to "fetch everything and filter locally": it
        # publishes a lot that isn't engineering (sales, design, administrative
        # support), so here it does pay to narrow at the origin. The names have
        # to be EXACT, just as the facet shows them (see CATEGORIES_TECH).
        "filterFacets": [{"name": "category", "requestedFacetCount": 9999,
                          "values": [{"name": c} for c in categories]}]
        if categories else [],
        "includeFacets": [],
        "jobTypeFacets": [],
        "locationFacets": [[
            {"name": "country", "requestedFacetCount": 9999,
             "values": [{"name": c} for c in codes]},
            {"name": "normalizedStateName", "requestedFacetCount": 9999},
            {"name": "normalizedCityName", "requestedFacetCount": 9999},
        ]],
        "query": query,
        "size": size,
        "start": start,
        "treatment": "OM",
        "sort": {"sortOrder": "DESCENDING", "sortType": "SCORE"},
    }


def _first(fields, key, default=""):
    """In `fields` each value comes wrapped in a single-element list."""
    value = fields.get(key)
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def _posted(fields):
    """createdDate is an epoch in seconds, as a string."""
    raw = _first(fields, "createdDate")
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _location(fields, country_names):
    """`normalizedLocation` comes as "Heredia, Heredia, CRI" — with the ISO-3,
    not with the country name. It's rebuilt with the name so that the bot's
    location filter (`location_hints`) has something to match against."""
    city = _first(fields, "city") or _first(fields, "normalizedCityName")
    state = _first(fields, "normalizedStateName")
    parts = [p for p in (city, state) if p]
    # "Heredia, Heredia" gets deduped to "Heredia".
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    parts += country_names
    return ", ".join(parts) or _first(fields, "normalizedLocation")


def _map_job(hit, country_names, label):
    fields = hit.get("fields") or {}
    job_id = _first(fields, "icimsJobId")
    return {
        "id": f"amz-{job_id}",
        "title": _first(fields, "title"),
        "location": _location(fields, country_names),
        "category": _first(fields, "category"),
        "posted": _posted(fields),
        "url": JOB_URL.format(job_id) if job_id else "",
        "source": label,
    }


def fetch_amazon(countries=("Costa Rica",), name="Amazon", query="",
                 categories=CATEGORIES_TECH):
    """
    Returns amazon.jobs postings, already normalized.

    countries   country names (translated to ISO-2) or ISO-2 codes directly
    name        readable name for the notification
    query       free text for the search box; empty = everything in the country
    categories  Amazon categories to fetch; [] or None = all of them
    """
    countries = list(countries)
    codes = [_country_code(c) for c in countries]
    # For display: if a code came in, there's no pretty name to show.
    country_names = [c for c in countries if len(c.strip()) > 2]

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    start = 0
    found = None

    while start < MAX_RESULTS:
        r = session.post(SEARCH_URL, timeout=30,
                         json=_payload(codes, query, start, PAGE_SIZE,
                                       categories or ()))
        r.raise_for_status()
        payload = r.json()

        hits = payload.get("searchHits") or []
        if not hits:
            break
        if found is None:
            found = payload.get("found") or 0

        for hit in hits:
            m = _map_job(hit, country_names, name)
            if m["id"] != "amz-":
                by_id[m["id"]] = m

        start += PAGE_SIZE
        if found and start >= found:
            break
        time.sleep(PAGE_PAUSE)

    return list(by_id.values())


if __name__ == "__main__":
    import sys

    if "--categories" in sys.argv:
        # To decide what to put in `categories`: lists the categories Amazon has
        # open in the country, with their count and the exact name.
        session = requests.Session()
        session.headers.update(HEADERS)
        r = session.post(SEARCH_URL, timeout=30,
                         json=_payload(["CR"], "", 0, 1))
        r.raise_for_status()
        facets = {f["name"]: f for f in (r.json().get("facets") or [])}
        values = (facets.get("category") or {}).get("values") or []
        print(f"\n{len(values)} categories with postings in Costa Rica:\n")
        for v in sorted(values, key=lambda x: -x["count"]):
            mark = "*" if v["name"] in CATEGORIES_TECH else " "
            print(f"  {mark} {v['count']:3}  {v['name']}")
        print("\n  (*) the ones the bot fetches today, per CATEGORIES_TECH")
        sys.exit(0)

    jobs = fetch_amazon()
    print(f"\n{len(jobs)} Amazon postings in Costa Rica "
          f"(categories: {', '.join(CATEGORIES_TECH)}):\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({j['location']}{cat}) · {j['posted']}")
        print(f"        {j['url']}")
