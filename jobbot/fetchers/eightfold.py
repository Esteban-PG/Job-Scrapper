"""
Eightfold.ai (PCSX career sites) template for the alert bot.

Recognizable by the `/api/pcsx/` endpoints and the `pcsx_job_search` namespace.
Big tenants put it on their own domain rather than an Eightfold subdomain —
Microsoft serves it from `apply.careers.microsoft.com` — so the URL alone won't
give the platform away.

    GET https://<site>/api/pcsx/search?domain=<domain>&location=Costa+Rica&start=0&num=10

Everything travels in the query string; there is no POST and no body. No CSRF
token, no auth, no cookies — a plain GET with `BOT_UA` answers 200.

The list does not show up as an XHR on a full page load, because it's resolved
server-side. The XHRs you do see afterwards (`position_details`, `match_details`,
`position_insights`, `similar_positions`) only load the detail pane of whichever
posting you clicked, and `/api/suggest` is the search box's autocomplete.

Field shapes worth knowing
--------------------------
- `locations` is **"Country, State, City"**, country first — the opposite of
  most sources — and unset levels come back as the literal string
  "Multiple Locations": `"Costa Rica, Multiple Locations, Multiple Locations"`.
  `_location` flips it into the project's usual "City, Country" and drops the
  placeholders.
- `standardizedLocations` carries the ISO-2 (`["CR"]`).
- `displayJobId`/`atsJobId` is the public code (200045281); `id` is a 16-digit
  internal number that also appears in `positionUrl`.
- `postedTs` is an epoch in seconds.

Two traps
---------
- **`num` is capped at 10.** Asking for 50 still returns 10 while `count` reports
  the real total, so a fetcher that trusts `num` silently keeps only the first
  page. Pagination steps `start` by 10.
- **An unknown location returns `count: 0`, not an error** — same shape as IBM.
  There is no way to tell "Microsoft isn't hiring here" from a misspelled
  country by looking at the response, so the country name has to be right the
  first time. Dropping `location` altogether returns the global catalog (1807
  postings), which is why each posting is revalidated locally.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.eightfold
"""

import time
from datetime import datetime, timezone

import requests

from .useragents import BOT_UA

PAGE_SIZE = 10       # the API caps `num` here regardless of what you ask for
MAX_RESULTS = 400    # safety cap
PAGE_PAUSE = 1.0

PLACEHOLDER = "multiple locations"

HEADERS = {"User-Agent": BOT_UA, "Accept": "application/json"}


def _location(position):
    """"Costa Rica, San José, San José" -> "San José, Costa Rica".

    Country comes first here, and levels the tenant didn't fill are the literal
    "Multiple Locations". Left as-is, a posting reading "Costa Rica, Multiple
    Locations, Multiple Locations" is ugly, and one reduced to "Multiple
    Locations" would match nothing in `location_hints`.
    """
    raw = (position.get("locations") or [""])[0]
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    parts = [p for p in parts if p.lower() != PLACEHOLDER]
    if not parts:
        return ""

    country, rest = parts[0], parts[1:]
    # Drop repeated levels ("San José, San José") and put the country last.
    seen = []
    for p in rest:
        if p not in seen:
            seen.append(p)
    return ", ".join(seen + [country])


def _in_countries(position, countries):
    """The API already filtered, but dropping `location` returns the global
    catalog, so never trust it blindly — same defence as radancy/jibe/ibm."""
    if not countries:
        return True
    raw = " ".join(position.get("locations") or []).lower()
    return any(c.strip().lower() in raw for c in countries)


def _posted(position):
    try:
        return datetime.fromtimestamp(int(position["postedTs"]),
                                      timezone.utc).strftime("%Y-%m-%d")
    except (KeyError, TypeError, ValueError):
        return ""


def _map_job(position, site, id_prefix, label):
    job_id = str(position.get("displayJobId") or position.get("atsJobId") or "")
    url = position.get("positionUrl") or ""
    return {
        "id": f"{id_prefix}-{job_id}",
        "title": position.get("name", ""),
        "location": _location(position),
        "category": (position.get("department") or "").strip(),
        "posted": _posted(position),
        "url": site + url if url.startswith("/") else (url or site),
        "source": label,
    }


def fetch_eightfold(site, domain, countries=("Costa Rica",), id_prefix="ef",
                    name=None, query="", include_remote=True):
    """
    Returns the postings of an Eightfold/PCSX board, already normalized.

    site            board's origin ("https://apply.careers.microsoft.com")
    domain          the `domain=` parameter ("microsoft.com")
    countries       country names as the site's own location box expects them.
                    A wrong one returns zero postings silently — see the module
                    docstring.
    id_prefix       prefix of the dedupe id; keep it unique across sources
    name            readable name for the notification
    query           free text; empty = everything in the country
    include_remote  passes `filter_include_remote`; verified not to widen the
                    country filter on Microsoft's tenant
    """
    site = site.rstrip("/")
    label = name or id_prefix
    url = f"{site}/api/pcsx/search"

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    discarded = 0

    for country in countries:
        start = 0
        total = None

        while start < MAX_RESULTS:
            r = session.get(url, timeout=30, params={
                "domain": domain,
                "query": query,
                "location": country,
                "start": start,
                "num": PAGE_SIZE,
                "sort_by": "timestamp",
                "filter_include_remote": 1 if include_remote else 0,
            })
            r.raise_for_status()
            data = r.json().get("data") or {}

            positions = data.get("positions") or []
            if not positions:
                break
            if total is None:
                total = data.get("count") or 0

            for position in positions:
                job = _map_job(position, site, id_prefix, label)
                if job["id"].endswith("-"):
                    continue
                if not _in_countries(position, [country]):
                    discarded += 1
                    continue
                by_id[job["id"]] = job

            start += PAGE_SIZE
            if total and start >= total:
                break
            time.sleep(PAGE_PAUSE)

    if discarded:
        print(f"[warn] {label}: {discarded} postings discarded for not being in "
              f"{list(countries)} — the server's location filter isn't being "
              f"applied; check the `location` parameter")

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: Eightfold boards already verified live
# --------------------------------------------------------------------------
def fetch_microsoft(countries=("Costa Rica",), name="Microsoft"):
    """Microsoft — apply.careers.microsoft.com (verified: 6 postings in Costa
    Rica, out of 1807 globally)."""
    return fetch_eightfold(site="https://apply.careers.microsoft.com",
                           domain="microsoft.com", id_prefix="msft",
                           countries=countries, name=name)


if __name__ == "__main__":
    jobs = fetch_microsoft()
    print(f"\n{len(jobs)} Microsoft postings in Costa Rica:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title'][:58]}")
        print(f"        {j['location']}{cat} · {j['posted']}")
        print(f"        {j['url']}")
