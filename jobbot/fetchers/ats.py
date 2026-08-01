"""
The three ATSs with a public JSON API: Greenhouse, Lever and Ashby.

They're the trivial cases — a single GET call, no token and no pagination — and
that's why they live together in one file. If the board's URL contains
`boards.greenhouse.io`, `jobs.lever.co` or `jobs.ashbyhq.com`, it's one of these.

None of the three filters by location on the server — the board's own UI does it
in the browser after downloading everything. Greenhouse says so plainly: the
response carries `meta.total` and every posting, with no `page`/`offset` to be
found. So **the country filter has to happen here**. Without it the fetcher would
hand the orchestrator all 141 West Monroe postings, and since `location_hints`
includes "remote" a remote US role would sail straight through the location gate.
Discarding the other 135 is the normal path, not a failure, so unlike
`radancy.py` it doesn't warn about it.

⚠️ Greenhouse is verified live (West Monroe). **Lever and Ashby are still
untested** — no real company configured yet. When you add the first one, check it
with `--dry-run` before trusting it.
"""

import requests

from .useragents import BOT_UA

HEADERS = {"User-Agent": BOT_UA}


def _in_countries(location, countries):
    """Substring match against the location text, which is also what makes
    multi-site postings work: Greenhouse writes them as one string,
    "Boston; Chicago; Dallas; …"."""
    if not countries:
        return True
    text = (location or "").lower()
    return any(c.strip().lower() in text for c in countries)


def fetch_greenhouse(company, name=None, countries=("Costa Rica",)):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id": f"gh-{company}-{j['id']}",
            "title": j["title"],
            "location": (j.get("location") or {}).get("name", ""),
            "url": j["absolute_url"],
            "source": name or company,
            # `metadata` carries "Recruiting Division" and "Job Type", but both
            # are business unit rather than discipline — West Monroe files a
            # Senior Software Developer under "Corporate" — so mapping either
            # into `category` would only feed the category gate noise. An absent
            # category skips that gate, which is the right outcome here.
            "category": "",
        }
        for j in r.json().get("jobs", [])
        if _in_countries((j.get("location") or {}).get("name", ""), countries)
    ]


def fetch_lever(company, name=None, countries=("Costa Rica",)):
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id": f"lv-{company}-{j['id']}",
            "title": j["text"],
            "location": (j.get("categories") or {}).get("location", ""),
            "url": j["hostedUrl"],
            "source": name or company,
        }
        for j in r.json()
        if _in_countries((j.get("categories") or {}).get("location", ""), countries)
    ]


def fetch_ashby(company, name=None, countries=("Costa Rica",)):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id": f"ab-{company}-{j['id']}",
            "title": j["title"],
            "location": j.get("location", ""),
            "url": j["jobUrl"],
            "source": name or company,
        }
        for j in r.json().get("jobs", [])
        if _in_countries(j.get("location", ""), countries)
    ]
