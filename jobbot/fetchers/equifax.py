#!/usr/bin/env python3
"""
Fetcher de vacantes de Equifax para el bot de alertas.

Equifax publica un feed XML con el catálogo COMPLETO de vacantes:
    https://careers.equifax.com/es/trabajos/xml/

Se usa eso en vez de scrapear /es/trabajos/. Razón (verificado en vivo): en esa
página el filtrado y la paginación son client-side — `?location=`, `?country=` y
`?page=` los ignora el servidor y devuelve siempre las mismas 20 vacantes. El
feed, en una sola petición, trae las 140 (12 de Costa Rica) con ubicación y
categoría ya estructuradas.

El `referencenumber` del feed (J00178026) es el mismo código que aparece en la
URL pública, así que los IDs `efx-J00178026` siguen siendo estables.

Prueba suelta (imprime lo que encuentra, sin notificar):
    python -m jobbot.fetchers.equifax
"""

import xml.etree.ElementTree as ET
from datetime import datetime

import requests

FEED_URL = "https://careers.equifax.com/es/trabajos/xml/"

HEADERS = {
    "User-Agent": "job-alert-bot/1.0 (uso personal; contacto@ejemplo.com)",
    "Accept-Language": "es-ES,es;q=0.9",
}

TIMEOUT = 60  # el feed pesa ~700 KB


def _text(job, tag):
    el = job.find(tag)
    return (el.text or "").strip() if el is not None and el.text else ""


def _iso_date(raw):
    """'Thu, 12 Feb 2026 00:00:00 GMT' -> '2026-02-12'. Si no parsea, se
    devuelve crudo: la fecha es opcional en el schema, no vale romper por ella."""
    try:
        return datetime.strptime(raw, "%a, %d %b %Y %H:%M:%S %Z").strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        return raw


def _location(job):
    """Arma 'Heredia, Costa Rica' con lo que haya, sin comas sueltas."""
    city, state, country = _text(job, "city"), _text(job, "state"), _text(job, "country")
    parts = [city]
    if state and state != city:
        parts.append(state)
    if country:
        parts.append(country)
    return ", ".join(p for p in parts if p)


def fetch_equifax(countries=("Costa Rica",)):
    """
    Devuelve las vacantes de Equifax de los países dados, ya normalizadas.

    `countries=None` trae el catálogo completo (útil si querés que el filtro de
    ubicación lo haga solo el orquestador).
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
            continue  # sin código estable no hay dedupe posible

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


# --------------------------------------------------------------------------
# Prueba directa
# --------------------------------------------------------------------------
if __name__ == "__main__":
    jobs = fetch_equifax()
    print(f"\n{len(jobs)} vacantes encontradas:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({j['location'] or '—'}{cat})")
        print(f"        {j['url']}")
