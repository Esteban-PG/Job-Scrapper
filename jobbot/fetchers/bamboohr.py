"""
BambooHR template for the alert bot.

Recognizable because the "Apply" link points at
`<company>.bamboohr.com/careers/<id>`, even when the postings are painted on the
company's own domain. Gorilla Logic renders them server-side into
`gorillalogic.com/careers/open-roles/`, so watching the browser's network tab
shows no XHR at all — the page arrives with the jobs already in it.

There is no need to scrape that HTML. BambooHR publishes the same list as JSON,
and it's the endpoint the company's own server is calling:

    GET https://<company>.bamboohr.com/careers/list

Returns `{meta: {totalCount}, result: [{id, jobOpeningName, departmentLabel,
employmentStatusLabel, location, atsLocation, isRemote, locationType}]}`. A plain
GET, no token, no cookies, and `BOT_UA` is enough. No pagination either: the
whole board comes in one response.

⚠️ The trap
-----------
**Every structured location field comes back null** — `location.city`,
`location.state`, all four of `atsLocation`, and `isRemote`. Verified against
Gorilla Logic's ten postings. The country lives only inside the title text:

    "Senior, DevOps Engineer (AWS), Remote: Colombia - Costa Rica, Full Time, …"

So a fetcher that filters on `atsLocation.country`, which is the obvious thing to
write, returns zero postings forever and looks exactly like a company that isn't
hiring. The country filter here has to read the title, and `_location` digs the
"Remote: …" segment out of it so `location_hints` has something to match.

That also means the filtering is only as good as the company's title convention.
If a tenant stops writing the country into its titles, this fetcher goes quiet —
and, as with Radancy's skins, an empty list is not an error, so the down-source
alert won't catch it.

`departmentLabel` ("Engineering", "Administrative-COL") is the closest thing to a
category and feeds the category gate.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.bamboohr
"""

import re

import requests

from .useragents import BOT_UA

HEADERS = {"User-Agent": BOT_UA, "Accept": "application/json"}

# "…, Remote: Colombia - Costa Rica, Full Time, …" -> "Remote: Colombia - Costa Rica"
LOCATION_RE = re.compile(r"(remote\s*:\s*[^,]+)", re.IGNORECASE)


def _list_url(company):
    return f"https://{company}.bamboohr.com/careers/list"


def _job_url(company, job_id):
    return f"https://{company}.bamboohr.com/careers/{job_id}"


def _location(job):
    """The structured fields are null, so the location is whatever the title
    says. Falls back to the structured ones in case a tenant does fill them."""
    found = LOCATION_RE.search(job.get("jobOpeningName") or "")
    if found:
        return " ".join(found.group(1).split())

    ats = job.get("atsLocation") or {}
    loc = job.get("location") or {}
    parts = [ats.get("city") or loc.get("city"),
             ats.get("state") or ats.get("province") or loc.get("state"),
             ats.get("country")]
    return ", ".join(p for p in parts if p)


def _in_countries(job, countries):
    """Matched against the title, because that is the only place the country
    appears. `location` alone isn't enough — it's empty on tenants that don't
    use the "Remote: …" convention."""
    if not countries:
        return True
    text = f"{job.get('jobOpeningName') or ''} {_location(job)}".lower()
    return any(c.strip().lower() in text for c in countries)


def fetch_bamboohr(company, countries=("Costa Rica",), name=None):
    """
    Returns the postings of a BambooHR board, already normalized.

    company    the subdomain: `gorillalogic` for gorillalogic.bamboohr.com
    countries  country names, matched against the title text
    name       readable name for the notification
    """
    label = name or company
    r = requests.get(_list_url(company), headers=HEADERS, timeout=20)
    r.raise_for_status()

    jobs = []
    for job in r.json().get("result") or []:
        job_id = str(job.get("id") or "")
        if not job_id or not _in_countries(job, countries):
            continue
        jobs.append({
            # The company goes in the id because BambooHR numbers postings per
            # tenant and they're small integers: "35" would collide instantly.
            "id": f"bhr-{company}-{job_id}",
            "title": job.get("jobOpeningName", "").strip(),
            "location": _location(job),
            "category": (job.get("departmentLabel") or "").strip(),
            "url": _job_url(company, job_id),
            "source": label,
            # The listing carries no posting date.
            "posted": "",
        })
    return jobs


# --------------------------------------------------------------------------
# Presets: BambooHR boards already verified live
# --------------------------------------------------------------------------
def fetch_gorillalogic(countries=("Costa Rica",), name="Gorilla Logic"):
    """Gorilla Logic — gorillalogic.bamboohr.com (verified: 10 postings, all of
    them open to Colombia and Costa Rica)."""
    return fetch_bamboohr("gorillalogic", countries=countries, name=name)


if __name__ == "__main__":
    jobs = fetch_gorillalogic()
    print(f"\n{len(jobs)} Gorilla Logic postings in Costa Rica:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title'][:64]}")
        print(f"        {j['location']}{cat}")
        print(f"        {j['url']}")
