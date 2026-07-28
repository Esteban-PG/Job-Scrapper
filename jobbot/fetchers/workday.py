"""
Workday template for the alert bot.

Workday exposes a public, stable JSON API behind every `*.myworkdayjobs.com`
board:

    POST https://<tenant>.<dc>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
    body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

The three values have to be pulled out of the board's URL. For P&G,
`https://pg.wd5.myworkdayjobs.com/1000` gives: tenant=`pg`, dc=`wd5`, site=`1000`.

Country filtering without hardcoding GUIDs
------------------------------------------
Workday filters by facet, and facets are opaque IDs
(Costa Rica = 99abe7e6bb3f4c108aebebf01a369ec5 at P&G). Instead of pasting them
into the config, the first response already carries the facet catalog: the
country NAME is resolved against that catalog and only then is the filtered
search requested. That way the same template works for any tenant without
hunting down GUIDs by hand.

Verified live against pg.wd5/1000: `limit` caps at 20 (100 returns HTTP 400),
the offset paginates correctly, and the country facet returns the same 2 Costa
Rica postings the Phenom fetcher reports.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.workday
"""

import time

import requests

from .useragents import BROWSER_UA

# Workday rejects limit > 20 with HTTP 400.
PAGE_SIZE = 20
MAX_RESULTS = 400  # safety cap
PAGE_PAUSE = 1.0

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _cxs_url(tenant, site, dc):
    return f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"


def _site_url(tenant, site, dc):
    return f"https://{tenant}.{dc}.myworkdayjobs.com/{site}"


def _search(session, url, applied, offset, search_text):
    r = session.post(url, headers=HEADERS, timeout=30, json={
        "appliedFacets": applied,
        "limit": PAGE_SIZE,
        "offset": offset,
        "searchText": search_text,
    })
    r.raise_for_status()

    # When Workday decides you're a bot it does NOT respond 403: it returns 200
    # with an HTML page. Without this check the error you see is a cryptic
    # JSONDecodeError instead of the real cause. If it shows up, lower the
    # frequency and wait: the block is temporary.
    if "application/json" not in r.headers.get("content-type", ""):
        raise RuntimeError(
            f"Workday returned {r.headers.get('content-type')} instead of JSON "
            f"(probably a rate limit or a temporary block)"
        )

    return r.json()


def _resolve_country_facets(payload, countries):
    """Translates country names -> facet IDs, reading the catalog that comes in
    the response itself. Returns the list of IDs found."""
    wanted = {c.strip().lower() for c in countries}
    ids = []

    for facet in payload.get("facets", []):
        # Countries hang off a 'locationMainGroup' group with subgroups
        # (Country / State / City); we take the locationCountry facetParameter.
        groups = facet.get("values") or []
        for group in groups:
            if group.get("facetParameter") != "locationCountry":
                continue
            for value in group.get("values") or []:
                if (value.get("descriptor") or "").strip().lower() in wanted:
                    ids.append(value["id"])
        if facet.get("facetParameter") == "locationCountry":
            for value in facet.get("values") or []:
                if (value.get("descriptor") or "").strip().lower() in wanted:
                    ids.append(value["id"])

    return ids


def _req_id(posting):
    """The job code (R000154991) comes in bulletFields. If it's missing, we fall
    back to externalPath, which is also stable."""
    bullets = posting.get("bulletFields") or []
    if bullets and bullets[0]:
        return bullets[0]
    return (posting.get("externalPath") or "").rstrip("/").split("/")[-1]


def fetch_workday(tenant, site, dc="wd5", countries=("Costa Rica",),
                  name=None, search_text=""):
    """
    Returns the postings of a Workday board, already normalized.

    tenant/site/dc  come from the URL: https://<tenant>.<dc>.myworkdayjobs.com/<site>
    countries       names exactly as the site's filter shows them; None = all
    name            readable name for the notification (default: the tenant)
    search_text     normally empty: we fetch everything and filter locally
    """
    label = name or tenant
    url = _cxs_url(tenant, site, dc)
    base = _site_url(tenant, site, dc)

    session = requests.Session()

    # 1st call with no filter: it's what lets us resolve the country facets.
    first = _search(session, url, {}, 0, search_text)

    applied = {}
    if countries:
        ids = _resolve_country_facets(first, countries)
        if ids:
            applied = {"locationCountry": ids}
        else:
            print(f"[warn] Workday {label}: no country facet found for "
                  f"{list(countries)}; fetching all and letting the orchestrator filter")

    # If a filter was applied, the first response is no longer usable: repeat it.
    payload = first if not applied else _search(session, url, applied, 0, search_text)
    total = payload.get("total") or 0

    by_id = {}
    offset = 0

    while offset < min(total or MAX_RESULTS, MAX_RESULTS):
        if offset:
            payload = _search(session, url, applied, offset, search_text)
            time.sleep(PAGE_PAUSE)

        postings = payload.get("jobPostings") or []
        if not postings:
            break

        for p in postings:
            code = _req_id(p)
            if not code:
                continue
            path = p.get("externalPath") or ""
            by_id[f"wd-{tenant}-{code}"] = {
                "id": f"wd-{tenant}-{code}",
                "title": p.get("title", ""),
                "location": p.get("locationsText", ""),
                "url": base + path if path else base,
                "source": label,
                # Workday gives the date as a relative string ("Posted 14 Days
                # Ago"). It's left as-is: it's informational and `posted` is
                # optional in the schema.
                "posted": p.get("postedOn", ""),
            }

        offset += PAGE_SIZE

    return list(by_id.values())


if __name__ == "__main__":
    jobs = fetch_workday(tenant="pg", site="1000", dc="wd5",
                         countries=("Costa Rica",), name="P&G (Workday)")
    print(f"\n{len(jobs)} postings found:\n")
    for j in jobs:
        print(f"  [{j['id']}] {j['title']}  ({j['location'] or '—'}) · {j['posted']}")
        print(f"        {j['url']}")
