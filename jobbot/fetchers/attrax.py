"""
Attrax template for the alert bot.

Attrax is a careers-site platform, not an ATS: the apply button hands off to
whatever the company runs underneath (Experian keeps it in-house, at
`/Workflow?workflowId=<uuid>&vacancyId=<id>`). Recognizable by the `attrax-*`
class names in the markup.

There is no JSON endpoint. The postings are server-rendered into the search page
itself, and searching reloads the whole document rather than firing an XHR:

    GET https://<site>/jobs?q=Costa_Rica&options=&page=1

So this is one of the rare cases where parsing HTML is the right answer rather
than a last resort — there is nothing else to call. Everything else in the
network tab is analytics (Matomo, GA4, reCAPTCHA, Google Maps).

The markup is generous, which is what makes it worth a template instead of the
generic `html` fetcher:

    div.attrax-vacancy-tile[data-jobid]           one per posting, stable id
    a.attrax-vacancy-tile__title                  title + link
    .attrax-vacancy-tile__location-freetext       "Heredia, Costa Rica"
    .attrax-vacancy-tile__option-department-…     "Information Technology & Systems"

`generic_html.py` would technically work but would take the href as the id, take
the location from a static config value, and carry no category at all.

⚠️ `q` is a keyword search, not a country facet
-----------------------------------------------
There is no structured country filter, so `q=Costa_Rica` searches text. It can
therefore match a posting that merely mentions the country, and could miss one
that spells its location differently. Every posting is revalidated against the
tile's own location field, which is the only structured location on offer.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.attrax
"""

import time

import requests
from bs4 import BeautifulSoup

from .useragents import BOT_UA

MAX_PAGES = 20       # safety cap
PAGE_PAUSE = 1.0

HEADERS = {"User-Agent": BOT_UA, "Accept": "text/html"}

TILE = "div.attrax-vacancy-tile"
TITLE = "a.attrax-vacancy-tile__title"
LOCATION = ".attrax-vacancy-tile__location-freetext .attrax-vacancy-tile__item-value"
DEPARTMENT = ".attrax-vacancy-tile__option-department-valueset"


def _text(tile, selector):
    el = tile.select_one(selector)
    return " ".join(el.get_text(strip=True).split()) if el else ""


def _parse_tiles(soup, site, id_prefix, label):
    jobs = []
    for tile in soup.select(TILE):
        job_id = (tile.get("data-jobid") or "").strip()
        link = tile.select_one(TITLE)
        if not job_id or not link:
            continue
        href = link.get("href") or ""
        jobs.append({
            "id": f"{id_prefix}-{job_id}",
            "title": " ".join(link.get_text(strip=True).split()),
            "location": _text(tile, LOCATION),
            "category": _text(tile, DEPARTMENT),
            "url": site + href if href.startswith("/") else href,
            "source": label,
            # The tile shows an expiry date but no posting date.
            "posted": "",
        })
    return jobs


def fetch_attrax(site, countries=("Costa Rica",), id_prefix="attrax", name=None,
                 path="/jobs"):
    """
    Returns the postings of an Attrax careers site, already normalized.

    site       the board's origin ("https://jobs.experian.com")
    countries  country names; used as the search keyword AND revalidated
               against each tile's location
    id_prefix  prefix of the dedupe id; keep it unique across sources
    name       readable name for the notification
    path       the search path, if a tenant doesn't use /jobs
    """
    site = site.rstrip("/")
    label = name or id_prefix

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    discarded = 0

    for country in countries:
        needle = country.strip().lower()
        page = 1
        while page <= MAX_PAGES:
            r = session.get(site + path, timeout=40, params={
                # The site writes spaces as underscores in `q`.
                "q": country.strip().replace(" ", "_"),
                "options": "",
                "page": page,
            })
            r.raise_for_status()
            found = _parse_tiles(BeautifulSoup(r.text, "html.parser"),
                                 site, id_prefix, label)
            if not found:
                break

            new_on_page = 0
            for job in found:
                # `q` is a text search, so the country has to be confirmed.
                if needle not in job["location"].lower():
                    discarded += 1
                    continue
                if job["id"] not in by_id:
                    new_on_page += 1
                by_id[job["id"]] = job

            # No "total pages" marker in the markup; a page that adds nothing
            # new means the site is repeating itself.
            if new_on_page == 0:
                break
            page += 1
            time.sleep(PAGE_PAUSE)

    if discarded:
        print(f"[warn] {label}: {discarded} postings discarded for not being in "
              f"{list(countries)} — expected, since `q` is a text search and not "
              f"a country filter")

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: Attrax sites already verified live
# --------------------------------------------------------------------------
def fetch_experian_jobs(countries=("Costa Rica",), name="Experian"):
    """Experian — jobs.experian.com (verified: 12 postings in Costa Rica).

    Note the bot already has an `equifax` source; these are different companies
    with confusingly similar names and separate boards.
    """
    return fetch_attrax(site="https://jobs.experian.com", countries=countries,
                        id_prefix="exp", name=name)


if __name__ == "__main__":
    jobs = fetch_experian_jobs()
    print(f"\n{len(jobs)} Experian postings in Costa Rica:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title'][:60]}")
        print(f"        {j['location']}{cat}")
        print(f"        {j['url']}")
