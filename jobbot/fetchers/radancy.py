"""
Radancy / TalentBrew template for the alert bot.

Recognizable by the assets on `tbcdn.talentbrew.com` and the telemetry to
`radancy.net`. It isn't an ATS: it's the careers marketing layer. The real ATS
sits behind the "Apply" button (at Moody's, SAP SuccessFactors).

    GET https://<site>/en/search-jobs/results?CurrentPage=1&RecordsPerPage=50&…

Returns JSON with `{filters, results, hasJobs, hasContent}`, where **`results`
is a fragment of HTML**, not data: it has to be parsed. The totals travel as
`data-` attributes of the section, which is where the pagination comes from.

⚠️ The trap that matters
------------------------
The location filter **only works if all five parameters go together**:
`Location`, `LocationPath`, `Latitude`, `Longitude` and `LocationType=2`. With
any partial combination the API **doesn't fail**: it returns the global catalog
(251 postings at Moody's against 22 in Costa Rica). Verified by trying all five
combinations.

That is dangerous when silent, because `location_hints` includes "remote" and
would let through remote postings from any country. That's why `fetch_radancy`
**revalidates locally** that each posting mentions the requested country, and
warns if it had to discard anything: if that shows up in the logs, the server's
filter broke and the location parameters need a look.

Two tenant shapes, both handled
-------------------------------
Not every tenant answers that JSON endpoint. Citi returns it with `results`
empty and instead **renders the postings into the search page itself**, whose
path carries the filters:

    GET /search-jobs/{keyword}/{orgId}/{subId}/{geoId}/{lat}/{lon}/{radius}/{page}

So `_fetch_page` asks the JSON endpoint first — cheaper and a more explicit
contract — and falls back to that server-rendered page when it comes back empty.
Same idea as `phenom.py` cycling its ddoKey candidates and keeping whichever one
returns postings.

The markup differs too: Moody's serves `search-results-list__*` classes and Citi
the newer `sr-*` ones, for identical data. `_parse_items` tries both skins. A
tenant that renders a third skin would parse as zero postings, which the
down-source alert would not catch — it isn't an error, just an empty list.

Adding another company on Radancy takes the domain and the `OrganizationIds`,
both visible in the DevTools request.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.radancy
"""

import time
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

from .useragents import BROWSER_UA

# Verified: RecordsPerPage=50 brings the 22 Costa Rica postings in a single call.
PAGE_SIZE = 50
MAX_PAGES = 20        # safety cap
DISTANCE = 50         # radius, in the unit the site expects (miles)
PAGE_PAUSE = 1.0

# Radancy filters by geographic node (GeoNames IDs) + coordinates, not by name.
# Verified against Moody's: each one returns only its country, not the global
# catalog — which is the symptom of an invalid ID. Chile returned 0 postings
# (Moody's has none there), so it's only half-confirmed: if you use it and see
# postings from other countries, the ID is the suspect.
# The LocationPath of a new country comes from filtering it on the site and
# looking at the request's query in DevTools.
COUNTRY_GEO = {
    "costa rica": {"path": "3624060", "lat": "10.00000", "lon": "-84.00000"},
    "mexico": {"path": "3996063", "lat": "23.00000", "lon": "-102.00000"},
    "colombia": {"path": "3686110", "lat": "4.00000", "lon": "-72.00000"},
    "argentina": {"path": "3865483", "lat": "-34.00000", "lon": "-64.00000"},
    "chile": {"path": "3895114", "lat": "-30.00000", "lon": "-71.00000"},
    "brazil": {"path": "3469034", "lat": "-10.00000", "lon": "-55.00000"},
}

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}

# The server-rendered page, used when the JSON endpoint comes back empty.
HTML_HEADERS = {"User-Agent": BROWSER_UA, "Accept": "text/html"}

# Two HTML skins seen live for the same platform and the same data. Moody's
# serves the older one, Citi the newer `sr-` one.
SKINS = (
    {"item": "li.search-results-list__item",
     "link": "a.search-results-list__job-link",
     "location": ".job-location"},
    {"item": "li.sr-job-item",
     "link": "a.sr-job-item__link",
     "location": ".sr-job-location"},
)


def _geo(country):
    geo = COUNTRY_GEO.get(country.strip().lower())
    if not geo:
        raise ValueError(
            f"Radancy filters by geographic node and I don't have the one for "
            f"{country!r}. Add it to COUNTRY_GEO in jobbot/fetchers/radancy.py: "
            f"the LocationPath and the coordinates show up in the request's "
            f"query when you filter that country on the site."
        )
    return geo


def _params(org_id, country, geo, page, page_size, keywords):
    """The five location fields ALWAYS go together (see the module docstring)."""
    return {
        "ActiveFacetID": 0,
        "CurrentPage": page,
        "RecordsPerPage": page_size,
        "TotalContentResults": "",
        "Distance": DISTANCE,
        "RadiusUnitType": 0,
        "Keywords": keywords,
        "Location": country,
        "Latitude": geo["lat"],
        "Longitude": geo["lon"],
        "ShowRadius": "False",
        "IsPagination": "False",
        "CustomFacetName": "",
        "FacetTerm": "",
        "FacetType": 0,
        "SearchResultsModuleName": "Section 6 - Search Results List",
        "SearchFiltersModuleName": "Section 6 - Search Filters",
        "SortCriteria": 0,
        "SortDirection": 0,
        "SearchType": 1,
        "LocationType": 2,
        "LocationPath": geo["path"],
        "OrganizationIds": str(org_id),
        "PostalCode": "",
        "ResultsType": 0,
        "fc": "", "fl": "", "fcf": "", "afc": "", "afl": "", "afcf": "",
    }


def _total_pages(soup):
    section = soup.select_one("#search-results")
    if not section:
        return 1
    try:
        return int(section.get("data-total-pages") or 1)
    except ValueError:
        return 1


def _parse_items(soup, site, label, org_id):
    """Each posting is an <li> with the title's <a> and a location element.

    Radancy serves two HTML skins for the same data — Moody's the older
    `search-results-list__*` one, Citi the newer `sr-*` one — so both selector
    sets are tried and the first that finds anything wins.
    """
    for skin in SKINS:
        jobs = _parse_skin(soup, site, label, org_id, skin)
        if jobs:
            return jobs
    return []


def _parse_skin(soup, site, label, org_id, skin):
    jobs = []
    for item in soup.select(skin["item"]):
        link = item.select_one(skin["link"])
        if not link:
            continue
        # The job id is in data-job-id and also as the last segment of the URL;
        # the attribute is preferred, since it doesn't depend on the path format.
        href = link.get("href") or ""
        job_id = link.get("data-job-id") or href.rstrip("/").split("/")[-1]
        if not job_id:
            continue
        loc = item.select_one(skin["location"])
        jobs.append({
            # The org_id goes in the id just like the tenant does on Workday:
            # that way two companies on Radancy can't collide.
            "id": f"rdc-{org_id}-{job_id}",
            "title": link.get_text(strip=True),
            "location": loc.get_text(strip=True) if loc else "",
            "url": site + href if href.startswith("/") else href,
            "source": label,
            # The listing carries no category or date; going to fetch them would
            # cost one request per posting and both are optional in the schema.
            "category": "",
            "posted": "",
        })
    return jobs


def _ssr_url(site, org_id, sub_id, country, geo, page):
    """The server-rendered search page, whose path carries the filters:
        /search-jobs/{keyword}/{orgId}/{subId}/{geoId}/{lat}/{lon}/{radius}/{page}
    Some tenants (Citi) render the postings straight into this document and
    return nothing from the JSON endpoint.
    """
    return (f"{site}/search-jobs/{quote(country)}/{org_id}/{sub_id}/"
            f"{geo['path']}/{geo['lat']}/{geo['lon']}/{int(DISTANCE)}/{page}")


def _fetch_page(session, site, org_id, sub_id, country, geo, page, page_size,
                keywords):
    """Returns the soup of one results page.

    The JSON endpoint is tried first because it is the cheaper, more explicit
    contract. If it answers with an empty `results` the server-rendered page is
    tried instead — same idea as `phenom.py` cycling its ddoKey candidates and
    keeping whichever one returns postings.
    """
    r = session.get(site + "/en/search-jobs/results", timeout=30,
                    headers=HEADERS,
                    params=_params(org_id, country, geo, page, page_size, keywords))
    r.raise_for_status()
    html = r.json().get("results") or ""
    if html.strip():
        return BeautifulSoup(html, "html.parser"), "json"

    r = session.get(_ssr_url(site, org_id, sub_id, country, geo, page),
                    timeout=30, headers=HTML_HEADERS)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser"), "html"


def fetch_radancy(site, org_id, countries=("Costa Rica",), name=None,
                  keywords="", sub_id=2):
    """
    Returns the postings of a Radancy/TalentBrew board, already normalized.

    site       board's domain ("https://careers.moodys.com")
    org_id     the request's `OrganizationIds` (49841 at Moody's)
    countries  country names; they have to be in COUNTRY_GEO
    name       readable name for the notification
    keywords   free text; empty = everything in the country
    """
    site = site.rstrip("/")
    label = name or site.split("//")[-1]
    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    discarded = 0

    for country in countries:
        geo = _geo(country)
        needle = country.strip().lower()
        page = 1

        while page <= MAX_PAGES:
            soup, via = _fetch_page(session, site, org_id, sub_id, country, geo,
                                    page, PAGE_SIZE, keywords)

            found = _parse_items(soup, site, label, org_id)
            if not found:
                break

            for job in found:
                # Revalidation: if the server's filter fell over, this avoids
                # notifying postings from half the world (see the docstring).
                if needle not in job["location"].lower():
                    discarded += 1
                    continue
                by_id[job["id"]] = job

            if page >= _total_pages(soup):
                break
            page += 1
            time.sleep(PAGE_PAUSE)

    if discarded:
        print(f"[warn] {label}: {discarded} postings discarded for not being in "
              f"{list(countries)} — the server's location filter isn't being "
              f"applied; check the Location*/Latitude/Longitude parameters")

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: Radancy boards already verified live
# --------------------------------------------------------------------------
def fetch_moodys(countries=("Costa Rica",), name="Moody's"):
    """Moody's — https://careers.moodys.com (verified: 22 in Costa Rica)."""
    return fetch_radancy(site="https://careers.moodys.com", org_id="49841",
                         countries=countries, name=name)


if __name__ == "__main__":
    jobs = fetch_moodys()
    print(f"\n{len(jobs)} Moody's postings in Costa Rica:\n")
    for j in jobs:
        print(f"  [{j['id']}] {j['title']}  ({j['location'] or '—'})")
        print(f"        {j['url']}")
