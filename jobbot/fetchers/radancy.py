#!/usr/bin/env python3
"""
Plantilla de Radancy / TalentBrew para el bot de alertas.

Se reconoce por los assets en `tbcdn.talentbrew.com` y la telemetría a
`radancy.net`. No es un ATS: es la capa de marketing de carreras. El ATS real
está detrás del botón "Aplicar" (en Moody's, SAP SuccessFactors).

    GET https://<sitio>/en/search-jobs/results?CurrentPage=1&RecordsPerPage=50&…

Devuelve JSON con `{filters, results, hasJobs, hasContent}`, donde **`results`
es un fragmento de HTML**, no datos: hay que parsearlo. Los totales viajan como
atributos `data-` de la sección, que es de donde sale la paginación.

⚠️ La trampa que importa
------------------------
El filtro de ubicación **solo funciona si van los cinco parámetros juntos**:
`Location`, `LocationPath`, `Latitude`, `Longitude` y `LocationType=2`. Con
cualquier combinación parcial la API **no falla**: devuelve el catálogo global
(251 vacantes en Moody's contra 22 de Costa Rica). Verificado probando las cinco
combinaciones.

Eso es peligroso callado, porque `location_hints` incluye "remote" y dejaría
pasar vacantes remotas de cualquier país. Por eso `fetch_radancy` **revalida
localmente** que cada vacante mencione el país pedido, y avisa si tuvo que
descartar algo: si eso aparece en los logs, el filtro del servidor se rompió y
hay que revisar los parámetros de ubicación.

Para agregar otra empresa en Radancy hace falta el dominio y el
`OrganizationIds`, ambos visibles en el request de DevTools.

Prueba suelta (imprime lo que encuentra, sin notificar):
    python -m jobbot.fetchers.radancy
"""

import time

import requests
from bs4 import BeautifulSoup

# Verificado: RecordsPerPage=50 trae las 22 de Costa Rica en una sola llamada.
PAGE_SIZE = 50
MAX_PAGES = 20        # tope de seguridad
PAGE_PAUSE = 1.0

# Radancy filtra por nodo geográfico (IDs de GeoNames) + coordenadas, no por el
# nombre. Verificados contra Moody's: cada uno devuelve solo su país, no el
# catálogo global — que es el síntoma de un ID inválido. Chile dio 0 vacantes
# (Moody's no tiene ahí), así que quedó comprobado a medias: si lo usás y ves
# vacantes de otros países, el ID es el sospechoso.
# El LocationPath de un país nuevo se saca filtrándolo en el sitio y mirando la
# query del request en DevTools.
COUNTRY_GEO = {
    "costa rica": {"path": "3624060", "lat": "10.00000", "lon": "-84.00000"},
    "mexico": {"path": "3996063", "lat": "23.00000", "lon": "-102.00000"},
    "colombia": {"path": "3686110", "lat": "4.00000", "lon": "-72.00000"},
    "argentina": {"path": "3865483", "lat": "-34.00000", "lon": "-64.00000"},
    "chile": {"path": "3895114", "lat": "-30.00000", "lon": "-71.00000"},
    "brazil": {"path": "3469034", "lat": "-10.00000", "lon": "-55.00000"},
}

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")

HEADERS = {
    "User-Agent": UA,
    "Accept": "application/json",
    "X-Requested-With": "XMLHttpRequest",
}


def _geo(country):
    geo = COUNTRY_GEO.get(country.strip().lower())
    if not geo:
        raise ValueError(
            f"Radancy filtra por nodo geográfico y no tengo el de {country!r}. "
            f"Agregalo a COUNTRY_GEO en jobbot/fetchers/radancy.py: el "
            f"LocationPath y las coordenadas se ven en la query del request "
            f"cuando filtrás ese país en el sitio."
        )
    return geo


def _params(org_id, country, geo, page, page_size, keywords):
    """Los cinco campos de ubicación van SIEMPRE juntos (ver docstring)."""
    return {
        "ActiveFacetID": 0,
        "CurrentPage": page,
        "RecordsPerPage": page_size,
        "TotalContentResults": "",
        "Distance": 50,
        "RadiusUnitType": 0,
        "Keywords": keywords,
        "Location": country,
        "Latitude": geo["lat"],
        "Longitude": geo["lon"],
        "ShowRadius": "False",
        "IsPagination": "False",
        "CustomFacetName": "",
        "FacetTerm": "",
        "FacetType": 0,
        "SearchResultsModuleName": "Section 6 - Search Results List",
        "SearchFiltersModuleName": "Section 6 - Search Filters",
        "SortCriteria": 0,
        "SortDirection": 0,
        "SearchType": 1,
        "LocationType": 2,
        "LocationPath": geo["path"],
        "OrganizationIds": str(org_id),
        "PostalCode": "",
        "ResultsType": 0,
        "fc": "", "fl": "", "fcf": "", "afc": "", "afl": "", "afcf": "",
    }


def _total_pages(soup):
    section = soup.select_one("#search-results")
    if not section:
        return 1
    try:
        return int(section.get("data-total-pages") or 1)
    except ValueError:
        return 1


def _parse_items(soup, site, label, org_id):
    """Cada vacante es un <li> con el <a> del título y un <li> de ubicación."""
    jobs = []
    for item in soup.select("li.search-results-list__item"):
        link = item.select_one("a.search-results-list__job-link")
        if not link:
            continue
        # El id de vacante está en data-job-id y también como último segmento
        # de la URL; se prefiere el atributo, que no depende del formato de ruta.
        href = link.get("href") or ""
        job_id = link.get("data-job-id") or href.rstrip("/").split("/")[-1]
        if not job_id:
            continue
        loc = item.select_one(".job-location")
        jobs.append({
            # El org_id va en el id igual que el tenant en Workday: así dos
            # empresas en Radancy no pueden colisionar.
            "id": f"rdc-{org_id}-{job_id}",
            "title": link.get_text(strip=True),
            "location": loc.get_text(strip=True) if loc else "",
            "url": site + href if href.startswith("/") else href,
            "source": label,
            # El listado no trae categoría ni fecha; ir a buscarlas costaría un
            # request por vacante y las dos son opcionales en el schema.
            "category": "",
            "posted": "",
        })
    return jobs


def fetch_radancy(site, org_id, countries=("Costa Rica",), name=None,
                  keywords=""):
    """
    Devuelve las vacantes de una bolsa Radancy/TalentBrew, ya normalizadas.

    site       dominio de la bolsa ("https://careers.moodys.com")
    org_id     `OrganizationIds` del request (49841 en Moody's)
    countries  nombres de país; tienen que estar en COUNTRY_GEO
    name       nombre legible para la notificación
    keywords   texto libre; vacío = todo lo del país
    """
    site = site.rstrip("/")
    label = name or site.split("//")[-1]
    url = site + "/en/search-jobs/results"

    session = requests.Session()
    session.headers.update(HEADERS)

    by_id = {}
    leaked = 0

    for country in countries:
        geo = _geo(country)
        needle = country.strip().lower()
        page = 1

        while page <= MAX_PAGES:
            r = session.get(url, timeout=30,
                            params=_params(org_id, country, geo, page,
                                           PAGE_SIZE, keywords))
            r.raise_for_status()
            soup = BeautifulSoup(r.json().get("results") or "", "html.parser")

            found = _parse_items(soup, site, label, org_id)
            if not found:
                break

            for job in found:
                # Revalidación: si el filtro del servidor se cayó, esto evita
                # notificar vacantes de medio mundo (ver docstring).
                if needle not in job["location"].lower():
                    leaked += 1
                    continue
                by_id[job["id"]] = job

            if page >= _total_pages(soup):
                break
            page += 1
            time.sleep(PAGE_PAUSE)

    if leaked:
        print(f"[warn] {label}: {leaked} vacantes descartadas por no ser de "
              f"{list(countries)} — el filtro de ubicación del servidor no está "
              f"aplicando; revisar los parámetros Location*/Latitude/Longitude")

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: bolsas Radancy ya verificadas en vivo
# --------------------------------------------------------------------------
def fetch_moodys(countries=("Costa Rica",), name="Moody's"):
    """Moody's — https://careers.moodys.com (verificado: 22 en Costa Rica)."""
    return fetch_radancy(site="https://careers.moodys.com", org_id="49841",
                         countries=countries, name=name)


# --------------------------------------------------------------------------
# Prueba directa
# --------------------------------------------------------------------------
if __name__ == "__main__":
    jobs = fetch_moodys()
    print(f"\n{len(jobs)} vacantes de Moody's en Costa Rica:\n")
    for j in jobs:
        print(f"  [{j['id']}] {j['title']}  ({j['location'] or '—'})")
        print(f"        {j['url']}")
