"""
Oracle Recruiting Cloud (Oracle HCM, "recruitingCE") template for the alert bot.

The careers page is a shell; the postings come from a REST call to Oracle Fusion
Apps on `*.fa.*.oraclecloud.com`. Each tenant is identified by a `siteNumber`
(Oracle's own is `CX_45001`).

    GET https://<host>/hcmRestApi/resources/latest/recruitingCEJobRequisitions
        ?onlyData=true&expand=…&finder=findReqs;siteNumber=CX_45001,limit=25,offset=0

Everything travels in Oracle's "finder" syntax: `finder=findReqs;key=value,key=value`
— a semicolon after the finder name, commas between parameters. A plain public
GET: no CSRF, no auth, no cookies, `Accept: application/json` is all it wants.

Sibling endpoints that are NOT the postings and should be ignored:
`recruitingCESearchAutoSuggestions` (search autocomplete), `recruitingCEEvents`
(events) and `recruitingCEUserTrackings` (analytics POST).

⚠️ The location filter is an opaque numeric ID
----------------------------------------------
`selectedLocationsFacet` (and `locationId`) take Oracle's internal geography id,
not a country name — the same shape of problem as Workday's GUIDs. Worse, the
response's `locationsFacet` only lists the **18 most common** locations, so
Costa Rica isn't in it and there's nothing to resolve the name against the way
`workday.py` does. So the ids have to be carried in config, one per source.

**The ids are per tenant**, unlike Workday's, which turned out to be global.
Verified by crossing them: Akamai's Costa Rica id returns 0 on Oracle's tenant
and Oracle's returns 0 on Akamai's. So `location_ids` is a per-source mapping,
not a module-wide table — a shared table would have handed the second tenant the
first one's id and quietly returned nothing.

And it fails quietly in both directions: an invalid id returns
`TotalJobsCount: 0` — indistinguishable from "this company isn't hiring here" —
while dropping the filter returns the global catalog (2321 postings on Oracle's
tenant). So the ids are verified one by one, unknown countries raise, and every
posting is revalidated locally against `PrimaryLocation`.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.oraclecloud
"""

import time
from urllib.parse import quote

import requests

from .useragents import BOT_UA

PAGE_SIZE = 25
MAX_RESULTS = 400    # safety cap
PAGE_PAUSE = 1.0

DEFAULT_HOST = "https://eeho.fa.us2.oraclecloud.com"
API_PATH = "/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
EXPAND = "requisitionList.workLocation,requisitionList.secondaryLocations"

HEADERS = {"User-Agent": BOT_UA, "Accept": "application/json"}


def _location_id(country, location_ids):
    """Per tenant, deliberately: see the module docstring."""
    location_id = (location_ids or {}).get(country.strip().lower())
    if not location_id:
        raise ValueError(
            f"Oracle filters by an opaque geography id and this source has none "
            f"for {country!r}. A wrong or missing id doesn't fail, it returns "
            f"zero postings forever. Ids are per tenant, so it can't be borrowed "
            f"from another company: filter that country on this board and read "
            f"`locationId`/`selectedLocationsFacet` from the request's query."
        )
    return location_id


def _finder(site_number, location_id, offset, limit, keywords=""):
    """Oracle's finder syntax: `findReqs;key=value,key=value`. The `;` and `,`
    are structural, so they are left unencoded while the values are not."""
    parts = [
        f"siteNumber={site_number}",
        "facetsList=LOCATIONS;CATEGORIES;POSTING_DATES",
        f"limit={limit}",
        f"offset={offset}",
        "sortBy=POSTING_DATES_DESC",
        f"selectedLocationsFacet={location_id}",
    ]
    if keywords:
        parts.append(f"keyword={keywords}")
    return "findReqs;" + ",".join(parts)


def _job_url(host, site_number, job_id):
    """The candidate-experience page, derived from the tenant's siteNumber."""
    return (f"{host}/hcmUI/CandidateExperience/en/sites/{site_number}"
            f"/job/{job_id}")


def _map_job(req, host, site_number, id_prefix, label):
    job_id = str(req.get("Id") or "")
    return {
        "id": f"{id_prefix}-{job_id}",
        "title": (req.get("Title") or "").strip(),
        "location": (req.get("PrimaryLocation") or "").strip(),
        # JobFamily, JobFunction, Department and Organization all come back null
        # on this tenant, so there is no category to feed the gate with. An
        # absent category skips it, which is the right outcome.
        "category": (req.get("JobFamily") or req.get("Department") or "").strip(),
        # Already ISO ("2026-07-20"), unlike most sources.
        "posted": (req.get("PostedDate") or "")[:10],
        "url": _job_url(host, site_number, job_id),
        "source": label,
    }


def fetch_oraclecloud(site_number, location_ids, countries=("Costa Rica",),
                      host=DEFAULT_HOST, id_prefix="orc", name=None,
                      keywords=""):
    """
    Returns the postings of an Oracle Recruiting Cloud board, already normalized.

    site_number  the tenant's site ("CX_45001")
    location_ids {country_name_lowercase: geography_id} for THIS tenant; the
                 ids are not portable between companies
    countries    country names; they have to be keys of `location_ids`
    host         the Fusion Apps origin serving the REST API
    id_prefix    prefix of the dedupe id; keep it unique across sources
    name         readable name for the notification
    keywords     free text; empty = everything in the country
    """
    host = host.rstrip("/")
    label = name or id_prefix
    url = host + API_PATH

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    discarded = 0

    for country in countries:
        location_id = _location_id(country, location_ids)
        needle = country.strip().lower()
        offset = 0
        total = None

        while offset < MAX_RESULTS:
            finder = _finder(site_number, location_id, offset, PAGE_SIZE, keywords)
            r = session.get(f"{url}?onlyData=true&expand={EXPAND}"
                            f"&finder={quote(finder, safe='=,;')}", timeout=40)
            r.raise_for_status()

            items = r.json().get("items") or []
            if not items:
                break
            block = items[0]
            requisitions = block.get("requisitionList") or []
            if not requisitions:
                break
            if total is None:
                total = block.get("TotalJobsCount") or 0

            for req in requisitions:
                job = _map_job(req, host, site_number, id_prefix, label)
                if job["id"].endswith("-"):
                    continue
                # Dropping the location filter returns the global catalog, so
                # the server's answer is never trusted blindly.
                if needle not in job["location"].lower():
                    discarded += 1
                    continue
                by_id[job["id"]] = job

            offset += PAGE_SIZE
            if total and offset >= total:
                break
            time.sleep(PAGE_PAUSE)

    if discarded:
        print(f"[warn] {label}: {discarded} postings discarded for not being in "
              f"{list(countries)} — the server's location filter isn't being "
              f"applied; check `selectedLocationsFacet`")

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: Oracle Recruiting Cloud boards already verified live
# --------------------------------------------------------------------------
def fetch_oracle(countries=("Costa Rica",), name="Oracle"):
    """Oracle — careers.oracle.com, siteNumber CX_45001 (verified: 2 postings in
    Costa Rica, out of 2321 globally)."""
    return fetch_oraclecloud(site_number="CX_45001",
                             location_ids={"costa rica": "300000000106785"},
                             countries=countries, id_prefix="orc", name=name)


def fetch_akamai(countries=("Costa Rica",), name="Akamai"):
    """Akamai — jobs.akamai.com, siteNumber CX_1 on its own Fusion host
    (verified: 10 postings in Costa Rica).

    Its Costa Rica id is NOT Oracle's: crossing them returns 0 on both sides.
    """
    return fetch_oraclecloud(
        site_number="CX_1",
        location_ids={"costa rica": "300000000469120"},
        host="https://fa-extu-saasfaprod1.fa.ocs.oraclecloud.com",
        countries=countries, id_prefix="akamai", name=name)


if __name__ == "__main__":
    jobs = fetch_oracle()
    print(f"\n{len(jobs)} Oracle postings in Costa Rica:\n")
    for j in jobs:
        print(f"  [{j['id']}] {j['title'][:58]}")
        print(f"        {j['location']} · {j['posted']}")
        print(f"        {j['url']}")
