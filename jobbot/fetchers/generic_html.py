"""
Plantilla de HTML plano: último recurso, cuando la bolsa no expone ninguna API.

Antes de caer acá, revisá la pestaña Network del navegador: la mayoría de los
sitios que "parecen" HTML plano en realidad piden las vacantes a un endpoint
JSON, y eso siempre es más estable que un selector CSS.
"""

import requests
from bs4 import BeautifulSoup

from .useragents import BOT_UA

HEADERS = {"User-Agent": BOT_UA}


def fetch_html(src):
    """
    Lee las vacantes de una página con un selector CSS.

    El `id` sale de la URL de la vacante, no del título ni de la posición en la
    lista: si el sitio reordena o retoca el copy, el dedupe tiene que aguantar.
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
