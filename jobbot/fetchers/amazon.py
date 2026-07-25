#!/usr/bin/env python3
"""
Fetcher de amazon.jobs para el bot de alertas.

Amazon no usa un ATS de terceros: tiene el suyo (`sourceSystem: JobCreator`) y
lo expone en una sola llamada JSON, sin token ni cookies:

    POST https://www.amazon.jobs/api/jobs/search?is_als=true
    body: {"locationFacets": [[{"name": "country", "values": [{"name": "CR"}]}]],
           "query": "", "size": 100, "start": 0, ...}

Respuesta: `{found, start, facets, searchHits: [{fields: {...}}]}`. Ojo con la
forma de `fields`: **cada valor es una lista de un elemento**
(`{"title": ["Designer, …"], "city": ["Heredia"]}`), no un string. Por eso todo
pasa por `_one()` antes de usarse.

Es la única fuente que **filtra por categoría en el origen**, al revés que el
resto (ver "Decisiones de diseño" en el README). El motivo: Amazon publica mucho
que no es de ingeniería — de las 73 vacantes de Costa Rica, 65 son de ventas,
diseño, soporte administrativo y similares. Ojo con acotar de más: la categoría
"Software Development" sola tiene **1** vacante en Costa Rica, porque Amazon
clasifica casi toda la ingeniería bajo "Operations, IT, & Support Engineering".

Tres detalles que ya costaron una vuelta y conviene no volver a descubrir:

- El país va como **código ISO-2** (`CR`), no como nombre. Como el resto de los
  fetchers recibe `countries: ["Costa Rica"]` desde `config/sources.yaml`, acá
  se traduce con `COUNTRY_CODES` para no romper ese contrato.
- El campo `urlNextStep` **no sirve como enlace**: apunta a
  `account.amazon.jobs/jobs/<id>/apply`, que redirige a la pantalla de login.
  La página pública es `www.amazon.jobs/en/jobs/<icimsJobId>` (redirige sola al
  slug con el título).
- Un nombre de categoría mal escrito **no da error**: devuelve cero vacantes en
  silencio. Por eso conviene sacarlos de `--categorias` y no de memoria.

Prueba suelta (imprime lo que encuentra, sin notificar):
    python -m jobbot.fetchers.amazon
    python -m jobbot.fetchers.amazon --categorias   # qué categorías hay
"""

import json
import time
from datetime import datetime, timezone

import requests

SEARCH_URL = "https://www.amazon.jobs/api/jobs/search?is_als=true"
JOB_URL = "https://www.amazon.jobs/en/jobs/{}"

# Verificado: acepta size=100 en una sola llamada (500 también, pero no hace
# falta pedir de más). Se pagina con start si el país tuviera más.
PAGE_SIZE = 100
MAX_RESULTS = 400
PAGE_PAUSE = 1.0

# Amazon filtra por ISO-2 y el YAML habla de nombres. Se agregan a medida que
# hagan falta; cualquier código de 2 letras también se acepta tal cual.
COUNTRY_CODES = {
    "costa rica": "CR",
    "mexico": "MX", "méxico": "MX",
    "colombia": "CO",
    "argentina": "AR",
    "brazil": "BR", "brasil": "BR",
    "chile": "CL",
    "peru": "PE", "perú": "PE",
    "united states": "US", "united states of america": "US",
    "canada": "CA",
    "spain": "ES", "españa": "ES",
}

# Categorías técnicas de Amazon, con el nombre EXACTO del facet (si se escribe
# distinto, el filtro no falla: devuelve cero). Verificadas contra el facet
# `category` de Costa Rica. Para ver las que hay en un país:
#     python -m jobbot.fetchers.amazon --categorias
CATEGORIES_TECH = [
    "Software Development",
    "Operations, IT, & Support Engineering",
    "Business Intelligence",
    "Solutions Architect",
]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Origin": "https://www.amazon.jobs",
    "Referer": "https://www.amazon.jobs/en/search",
}


def _country_code(country):
    """Nombre de país -> ISO-2. Acepta también el código ya escrito."""
    code = COUNTRY_CODES.get(country.strip().lower())
    if code:
        return code
    if len(country.strip()) == 2:
        return country.strip().upper()
    raise ValueError(
        f"Amazon filtra por código ISO-2 y no conozco {country!r}. Agregalo a "
        f"COUNTRY_CODES en jobbot/fetchers/amazon.py o poné el código directo "
        f"en sources.yaml (ej. countries: ['CR'])."
    )


def _payload(codes, query, start, size, categories=()):
    return {
        "accessLevel": "EXTERNAL",
        "contentFilterFacets": [
            {"name": "primarySearchLabel", "requestedFacetCount": 9999}],
        # Sin esto entran las vacantes confidenciales, que no tienen título útil.
        "excludeFacets": [
            {"name": "isConfidential", "values": [{"name": "1"}]},
            {"name": "businessCategory", "values": [{"name": "a-confidential-job"}]},
        ],
        # Filtro de categoría. Vacío = todas (y filtra el bot por título).
        # Amazon es la excepción a "traer todo y filtrar local": publica mucho
        # que no es de ingeniería (ventas, diseño, soporte administrativo), así
        # que acá sí conviene acotar en el origen. Los nombres tienen que ser
        # EXACTOS, tal como los muestra el facet (ver CATEGORIES_TECH).
        "filterFacets": [{"name": "category", "requestedFacetCount": 9999,
                          "values": [{"name": c} for c in categories]}]
        if categories else [],
        "includeFacets": [],
        "jobTypeFacets": [],
        "locationFacets": [[
            {"name": "country", "requestedFacetCount": 9999,
             "values": [{"name": c} for c in codes]},
            {"name": "normalizedStateName", "requestedFacetCount": 9999},
            {"name": "normalizedCityName", "requestedFacetCount": 9999},
        ]],
        "query": query,
        "size": size,
        "start": start,
        "treatment": "OM",
        "sort": {"sortOrder": "DESCENDING", "sortType": "SCORE"},
    }


def _one(fields, key, default=""):
    """En `fields` cada valor viene envuelto en una lista de un elemento."""
    value = fields.get(key)
    if isinstance(value, list):
        return value[0] if value else default
    return value if value is not None else default


def _posted(fields):
    """createdDate es un epoch en segundos, como string."""
    raw = _one(fields, "createdDate")
    try:
        return datetime.fromtimestamp(int(raw), timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _location(fields, country_names):
    """`normalizedLocation` viene como "Heredia, Heredia, CRI" — con el ISO-3,
    no con el nombre del país. Se rearma con el nombre para que el filtro de
    ubicación del bot (`location_hints`) tenga contra qué matchear."""
    city = _one(fields, "city") or _one(fields, "normalizedCityName")
    state = _one(fields, "normalizedStateName")
    parts = [p for p in (city, state) if p]
    # Se dedupe "Heredia, Heredia" -> "Heredia".
    if len(parts) == 2 and parts[0] == parts[1]:
        parts = parts[:1]
    parts += country_names
    return ", ".join(parts) or _one(fields, "normalizedLocation")


def _map_job(hit, country_names):
    fields = hit.get("fields") or {}
    job_id = _one(fields, "icimsJobId")
    return {
        "id": f"amz-{job_id}",
        "title": _one(fields, "title"),
        "location": _location(fields, country_names),
        "category": _one(fields, "category"),
        "posted": _posted(fields),
        "url": JOB_URL.format(job_id) if job_id else "",
        "source": "Amazon",
    }


def fetch_amazon(countries=("Costa Rica",), name="Amazon", query="",
                 categories=CATEGORIES_TECH):
    """
    Devuelve las vacantes de amazon.jobs, ya normalizadas.

    countries   nombres de país (se traducen a ISO-2) o códigos ISO-2 directos
    name        nombre legible para la notificación
    query       texto libre del buscador; vacío = todo lo del país
    categories  categorías de Amazon a traer; [] o None = todas
    """
    countries = list(countries)
    codes = [_country_code(c) for c in countries]
    # Para mostrar: si vino el código, no hay nombre lindo que poner.
    country_names = [c for c in countries if len(c.strip()) > 2]

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    start = 0
    found = None

    while start < MAX_RESULTS:
        r = session.post(SEARCH_URL, timeout=30,
                         json=_payload(codes, query, start, PAGE_SIZE,
                                       categories or ()))
        r.raise_for_status()
        payload = r.json()

        hits = payload.get("searchHits") or []
        if not hits:
            break
        if found is None:
            found = payload.get("found") or 0

        for hit in hits:
            m = _map_job(hit, country_names)
            if m["id"] != "amz-":
                by_id[m["id"]] = m

        start += PAGE_SIZE
        if found and start >= found:
            break
        time.sleep(PAGE_PAUSE)

    return list(by_id.values())


# --------------------------------------------------------------------------
# Prueba directa
# --------------------------------------------------------------------------
if __name__ == "__main__":
    import sys

    if "--categorias" in sys.argv:
        # Para elegir qué poner en `categories`: lista las categorías que
        # Amazon tiene abiertas en el país, con su conteo y el nombre exacto.
        session = requests.Session()
        session.headers.update(HEADERS)
        r = session.post(SEARCH_URL, timeout=30,
                         json=_payload(["CR"], "", 0, 1))
        r.raise_for_status()
        facets = {f["name"]: f for f in (r.json().get("facets") or [])}
        values = (facets.get("category") or {}).get("values") or []
        print(f"\n{len(values)} categorías con vacantes en Costa Rica:\n")
        for v in sorted(values, key=lambda x: -x["count"]):
            mark = "*" if v["name"] in CATEGORIES_TECH else " "
            print(f"  {mark} {v['count']:3}  {v['name']}")
        print("\n  (*) las que trae el bot hoy, según CATEGORIES_TECH")
        sys.exit(0)

    jobs = fetch_amazon()
    print(f"\n{len(jobs)} vacantes de Amazon en Costa Rica "
          f"(categorías: {', '.join(CATEGORIES_TECH)}):\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({j['location']}{cat}) · {j['posted']}")
        print(f"        {j['url']}")
