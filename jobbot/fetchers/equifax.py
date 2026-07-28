"""
Equifax posting fetcher for the alert bot.

Equifax publishes an XML feed with the COMPLETE catalog of postings:
    https://careers.equifax.com/es/trabajos/xml/

That's used instead of scraping /es/trabajos/. Reason (verified live): on that
page filtering and pagination are client-side — `?location=`, `?country=` and
`?page=` are ignored by the server, which always returns the same 20 postings.
The feed, in a single request, brings all 140 (12 in Costa Rica) with location
and category already structured.

The feed's `referencenumber` (J00178026) is the same code that shows up in the
public URL, so the `efx-J00178026` IDs stay stable.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.equifax
"""

import xml.etree.ElementTree as ET
from datetime import datetime

import requests

from .useragents import BOT_UA

FEED_URL = "https://careers.equifax.com/es/trabajos/xml/"

HEADERS = {
    "User-Agent": BOT_UA,
    "Accept-Language": "es-ES,es;q=0.9",
}

TIMEOUT = 60  # the feed weighs ~700 KB


def _text(job, tag):
    el = job.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _iso_date(raw):
    """'Thu, 12 Feb 2026 00:00:00 GMT' -> '2026-02-12'. If it doesn't parse, it's
    returned raw: the date is optional in the schema, not worth breaking over."""
    try:
        return datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return raw


def _location(job):
    """Builds 'Heredia, Costa Rica' out of whatever is there, no stray commas."""
    city, state, country = _text(job, "city"), _text(job, "state"), _text(job, "country")
    parts = [city]
    if state and state != city:
        parts.append(state)
    if country:
        parts.append(country)
    return ", ".join(p for p in parts if p)


def fetch_equifax(countries=("Costa Rica",)):
    """
    Returns Equifax's postings for the given countries, already normalized.

    `countries=None` brings the full catalog (useful if you want the location
    filtering to be done by the orchestrator alone).
    """
    r = requests.get(FEED_URL, headers=HEADERS, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.content)

    wanted = {c.strip().lower() for c in countries} if countries else None
    jobs = []

    for job in root.findall("job"):
        if wanted and _text(job, "country").lower() not in wanted:
            continue

        code = _text(job, "referencenumber").upper()
        if not code:
            continue  # without a stable code there's no dedupe possible

        jobs.append({
            "id": f"efx-{code}",
            "title": _text(job, "title"),
            "location": _location(job),
            "url": _text(job, "url"),
            "source": "Equifax",
            "category": _text(job, "category"),
            "posted": _iso_date(_text(job, "date")),
        })

    return jobs


if __name__ == "__main__":
    jobs = fetch_equifax()
    print(f"\n{len(jobs)} postings found:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({j['location'] or '—'}{cat})")
        print(f"        {j['url']}")
