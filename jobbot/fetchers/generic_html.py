"""
Plain HTML template: last resort, when the board exposes no API at all.

Before falling back to this, check the browser's Network tab: most of the sites
that "look like" plain HTML actually request the postings from a JSON endpoint,
and that is always more stable than a CSS selector.
"""

import requests
from bs4 import BeautifulSoup

from .useragents import BOT_UA

HEADERS = {"User-Agent": BOT_UA}


def fetch_html(src):
    """
    Reads the postings off a page using a CSS selector.

    The `id` comes from the posting's URL, not from the title or its position in
    the list: if the site reorders things or tweaks the copy, the dedupe has to
    hold up.
    """
    r = requests.get(src["url"], headers=HEADERS, timeout=20)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")

    base = (src.get("base_url") or "").rstrip("/")
    slug = src.get("name", src["url"])
    jobs = {}

    for a in soup.select(src["item_selector"]):
        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        if href.startswith("/"):
            href = base + href
        jobs[href] = {
            "id": f"html-{slug}-{href}",
            "title": title,
            "location": src.get("location", ""),
            "url": href,
            "source": slug,
        }

    return list(jobs.values())
