"""
The three ATSs with a public JSON API: Greenhouse, Lever and Ashby.

They're the trivial cases — a single GET call, no token and no pagination — and
that's why they live together in one file. If the board's URL contains
`boards.greenhouse.io`, `jobs.lever.co` or `jobs.ashbyhq.com`, it's one of these.

⚠️ Written but NOT yet tested live: no real company configured yet. When you add
the first one, check it with `--dry-run` before trusting it.
"""

import requests

from .useragents import BOT_UA

HEADERS = {"User-Agent": BOT_UA}


def fetch_greenhouse(company, name=None):
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
        }
        for j in r.json().get("jobs", [])
    ]


def fetch_lever(company, name=None):
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
    ]


def fetch_ashby(company, name=None):
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
    ]
