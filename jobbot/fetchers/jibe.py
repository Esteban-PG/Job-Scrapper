"""
Jibe / iCIMS Talent Cloud template for the alert bot.

Recognizable by the assets on `app.jibecdn.com` / `cms.jibecdn.com` and a
`domain=<tenant>.jibeapply.com` parameter. Jibe is only the careers front-end;
the real ATS behind the "Apply" button is iCIMS (`ats_code: icims` in the
payload). It is not Greenhouse, Lever, Ashby, Workday or Phenom — there is no
`phApp.ddo` and no `/widgets` endpoint.

The postings are NOT in the HTML: the initial document carries none of them and
the client fetches them over XHR when the search component mounts. So a quick
look at the page source finds nothing.

    GET https://<site>/api/jobs?location=Costa%20Rica&page=1&limit=100&...

Returns `{jobs: [{data: {...}}], totalCount, count, locations, filter}`. A plain
GET — no POST, no body, no CSRF token, and `BOT_UA` is enough (verified: the
honest User-Agent gets a 200, no need to pose as a browser).

Two traps worth not rediscovering
---------------------------------
- `apply_url` is **useless as a link**: it points at
  `careers-teknowledge.icims.com/jobs/<req_id>/login`, which is the login
  screen. The public page is `<site>/jobs/<req_id>` (verified: 200). Same shape
  of trap as Amazon's `urlNextStep`.
- An unknown country does **not** return an empty list: the response comes back
  HTTP 200 carrying `{"error": ...}` and no `jobs` key at all. Left unchecked
  that reads exactly like "this company has no openings here", forever. Hence
  `_check_error`.

Unlike Radancy, the location filter is not all-or-nothing: `location=<country>`
on its own filters correctly (verified against `woe`/`regionCode`/`stretch`
combinations — all four returned the same 6 postings, while dropping `location`
altogether returned the global catalog of 43 across 6 countries). Since a missing
filter silently means "the whole world", `fetch_jibe` revalidates the country
locally, the same way `radancy.py` does.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.jibe
"""

import time

import requests

from .useragents import BOT_UA

PAGE_SIZE = 100      # the site's selector defaults to 10; 100 comes back fine
MAX_PAGES = 20       # safety cap
PAGE_PAUSE = 1.0

HEADERS = {
    "User-Agent": BOT_UA,
    "Accept": "application/json",
}


def _check_error(payload, label, countries):
    """An unknown country answers 200 with `{"error": ...}` and no `jobs`."""
    if "error" in payload and "jobs" not in payload:
        raise RuntimeError(
            f"Jibe {label} rejected the query for {list(countries)}: "
            f"{payload['error']!r}. The country name has to match the one the "
            f"site's own location filter shows."
        )


def _location(data):
    """`full_location` already comes assembled ("San Pedro de Montes de Oca,
    Costa Rica"), but some postings repeat it separated by ';' when the role has
    several sites. Falls back to building it from the parts."""
    raw = data.get("full_location") or data.get("short_location") or ""
    if raw:
        seen = []
        for part in (p.strip() for p in raw.split(";")):
            if part and part not in seen:
                seen.append(part)
        return " · ".join(seen)

    parts = [data.get("city"), data.get("state"), data.get("country")]
    out = []
    for p in parts:
        if p and p not in out:
            out.append(p)
    return ", ".join(out)


def _category(data):
    for cat in data.get("categories") or []:
        if cat.get("name"):
            return cat["name"].strip()
    return ""


def _map_job(data, site, id_prefix, label):
    req_id = str(data.get("req_id") or data.get("slug") or "")
    return {
        "id": f"{id_prefix}-{req_id}",
        "title": data.get("title", ""),
        "location": _location(data),
        "category": _category(data),
        # 2026-05-19T17:36:00+0000 -> 2026-05-19
        "posted": (data.get("posted_date") or "")[:10],
        # NOT apply_url: that one is the iCIMS login screen (see docstring).
        "url": f"{site}/jobs/{req_id}" if req_id else site,
        "source": label,
    }


def fetch_jibe(site, countries=("Costa Rica",), id_prefix="jibe", name=None,
               domain=None, keywords="", page_size=PAGE_SIZE):
    """
    Returns the postings of a Jibe/iCIMS board, already normalized.

    site       board's domain ("https://careers.teknowledge.com")
    countries  country names as the site's location filter shows them
    id_prefix  prefix of the dedupe id; keep it unique across sources
    name       readable name for the notification
    domain     the `domain=<tenant>.jibeapply.com` parameter. Verified optional
               — the endpoint answers the same without it — but sent anyway to
               mirror what the browser does.
    keywords   free text; empty = everything in the country
    """
    site = site.rstrip("/")
    label = name or id_prefix
    url = f"{site}/api/jobs"

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    discarded = 0

    for country in countries:
        needle = country.strip().lower()
        page = 1

        while page <= MAX_PAGES:
            params = {
                "location": country,
                "page": page,
                "limit": page_size,
                "keywords": keywords,
                "sortBy": "relevance",
                "internal": "false",
            }
            if domain:
                params["domain"] = domain

            r = session.get(url, params=params, timeout=30)
            r.raise_for_status()
            payload = r.json()
            _check_error(payload, label, countries)

            jobs = payload.get("jobs") or []
            if not jobs:
                break

            for entry in jobs:
                job = _map_job(entry.get("data") or {}, site, id_prefix, label)
                if not job["id"].endswith("-"):
                    # Same defence as radancy.py: dropping `location` returns
                    # the global catalog, so if the filter ever stops applying
                    # this keeps postings from half the world out.
                    if needle not in job["location"].lower():
                        discarded += 1
                        continue
                    by_id[job["id"]] = job

            total = payload.get("totalCount") or 0
            if len(jobs) < page_size or page * page_size >= total:
                break
            page += 1
            time.sleep(PAGE_PAUSE)

    if discarded:
        print(f"[warn] {label}: {discarded} postings discarded for not being in "
              f"{list(countries)} — the server's location filter isn't being "
              f"applied; check the `location` parameter")

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: Jibe boards already verified live
# --------------------------------------------------------------------------
def fetch_teknowledge(countries=("Costa Rica",), name="TeKnowledge"):
    """TeKnowledge — https://careers.teknowledge.com (verified: 6 in Costa Rica,
    out of a global catalog of 43)."""
    return fetch_jibe(site="https://careers.teknowledge.com",
                      domain="ynvgroup.jibeapply.com",
                      id_prefix="tek", countries=countries, name=name)


if __name__ == "__main__":
    jobs = fetch_teknowledge()
    print(f"\n{len(jobs)} TeKnowledge postings in Costa Rica:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({j['location']}{cat}) · {j['posted']}")
        print(f"        {j['url']}")
