"""
Plantilla de Workday para el bot de alertas.

Workday expone una API JSON pública y estable detrás de todas las bolsas
`*.myworkdayjobs.com`:

    POST https://<tenant>.<dc>.myworkdayjobs.com/wday/cxs/<tenant>/<site>/jobs
    body: {"appliedFacets": {}, "limit": 20, "offset": 0, "searchText": ""}

Los tres datos que hay que sacar de la URL de la bolsa. Para P&G,
`https://pg.wd5.myworkdayjobs.com/1000` da: tenant=`pg`, dc=`wd5`, site=`1000`.

Filtro de país sin hardcodear GUIDs
-----------------------------------
Workday filtra por facet, y los facets son IDs opacos
(Costa Rica = 99abe7e6bb3f4c108aebebf01a369ec5 en P&G). En vez de pegarlos en la
config, la primera respuesta ya trae el catálogo de facets: se resuelve el
NOMBRE del país contra ese catálogo y recién ahí se pide la búsqueda filtrada.
Así la misma plantilla sirve para cualquier tenant sin ir a buscar GUIDs a mano.

Verificado en vivo contra pg.wd5/1000: `limit` topa en 20 (100 devuelve HTTP
400), el offset pagina bien, y el facet de país devuelve las mismas 2 vacantes
de Costa Rica que reporta el fetcher de Phenom.

Prueba suelta (imprime lo que encuentra, sin notificar):
    python -m jobbot.fetchers.workday
"""

import time

import requests

from .useragents import BROWSER_UA

# Workday rechaza limit > 20 con HTTP 400.
PAGE_SIZE = 20
MAX_RESULTS = 400  # tope de seguridad
PAGE_PAUSE = 1.0

HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/json",
    "Content-Type": "application/json",
}


def _cxs_url(tenant, site, dc):
    return f"https://{tenant}.{dc}.myworkdayjobs.com/wday/cxs/{tenant}/{site}/jobs"


def _site_url(tenant, site, dc):
    return f"https://{tenant}.{dc}.myworkdayjobs.com/{site}"


def _search(session, url, applied, offset, search_text):
    r = session.post(url, headers=HEADERS, timeout=30, json={
        "appliedFacets": applied,
        "limit": PAGE_SIZE,
        "offset": offset,
        "searchText": search_text,
    })
    r.raise_for_status()

    # Cuando Workday decide que sos un bot NO responde 403: devuelve 200 con una
    # página HTML. Sin este chequeo el error que se ve es un JSONDecodeError
    # críptico en vez de la causa real. Si aparece, bajá la frecuencia y esperá:
    # el bloqueo es temporal.
    if "application/json" not in r.headers.get("content-type", ""):
        raise RuntimeError(
            f"Workday devolvió {r.headers.get('content-type')} en vez de JSON "
            f"(probable rate-limit o bloqueo temporal)"
        )

    return r.json()


def _resolve_country_facets(payload, countries):
    """Traduce nombres de país -> IDs de facet, leyendo el catálogo que viene
    en la propia respuesta. Devuelve la lista de IDs encontrados."""
    wanted = {c.strip().lower() for c in countries}
    ids = []

    for facet in payload.get("facets", []):
        # Los países cuelgan de un grupo 'locationMainGroup' con subgrupos
        # (Country / State / City); tomamos el de facetParameter locationCountry.
        groups = facet.get("values") or []
        for group in groups:
            if group.get("facetParameter") != "locationCountry":
                continue
            for value in group.get("values") or []:
                if (value.get("descriptor") or "").strip().lower() in wanted:
                    ids.append(value["id"])
        if facet.get("facetParameter") == "locationCountry":
            for value in facet.get("values") or []:
                if (value.get("descriptor") or "").strip().lower() in wanted:
                    ids.append(value["id"])

    return ids


def _req_id(posting):
    """El código de vacante (R000154991) viene en bulletFields. Si faltara,
    caemos al externalPath, que también es estable."""
    bullets = posting.get("bulletFields") or []
    if bullets and bullets[0]:
        return bullets[0]
    return (posting.get("externalPath") or "").rstrip("/").split("/")[-1]


def fetch_workday(tenant, site, dc="wd5", countries=("Costa Rica",),
                  name=None, search_text=""):
    """
    Devuelve las vacantes de una bolsa Workday, ya normalizadas.

    tenant/site/dc  salen de la URL: https://<tenant>.<dc>.myworkdayjobs.com/<site>
    countries       nombres tal como los muestra el filtro del sitio; None = todas
    name            nombre legible para la notificación (default: el tenant)
    search_text     normalmente vacío: traemos todo y filtramos local
    """
    label = name or tenant
    url = _cxs_url(tenant, site, dc)
    base = _site_url(tenant, site, dc)

    session = requests.Session()

    # 1ª llamada sin filtro: sirve para resolver los facets de país.
    first = _search(session, url, {}, 0, search_text)

    applied = {}
    if countries:
        ids = _resolve_country_facets(first, countries)
        if ids:
            applied = {"locationCountry": ids}
        else:
            print(f"[warn] Workday {label}: no se encontró facet de país para "
                  f"{list(countries)}; se traen todas y filtra el orquestador")

    # Si hubo filtro, la primera respuesta ya no sirve: hay que repetir.
    payload = first if not applied else _search(session, url, applied, 0, search_text)
    total = payload.get("total") or 0

    by_id = {}
    offset = 0

    while offset < min(total or MAX_RESULTS, MAX_RESULTS):
        if offset:
            payload = _search(session, url, applied, offset, search_text)
            time.sleep(PAGE_PAUSE)

        postings = payload.get("jobPostings") or []
        if not postings:
            break

        for p in postings:
            code = _req_id(p)
            if not code:
                continue
            path = p.get("externalPath") or ""
            by_id[f"wd-{tenant}-{code}"] = {
                "id": f"wd-{tenant}-{code}",
                "title": p.get("title", ""),
                "location": p.get("locationsText", ""),
                "url": base + path if path else base,
                "source": label,
                # Workday da la fecha en relativo ("Posted 14 Days Ago"). Se deja
                # tal cual: es informativo y `posted` es opcional en el schema.
                "posted": p.get("postedOn", ""),
            }

        offset += PAGE_SIZE

    return list(by_id.values())


if __name__ == "__main__":
    jobs = fetch_workday(tenant="pg", site="1000", dc="wd5",
                         countries=("Costa Rica",), name="P&G (Workday)")
    print(f"\n{len(jobs)} vacantes encontradas:\n")
    for j in jobs:
        print(f"  [{j['id']}] {j['title']}  ({j['location'] or '—'}) · {j['posted']}")
        print(f"        {j['url']}")
