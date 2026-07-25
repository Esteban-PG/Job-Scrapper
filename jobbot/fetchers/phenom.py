#!/usr/bin/env python3
"""
Fetcher de vacantes de P&G (plataforma Phenom People) para el bot de alertas.

Phenom multiplexa todo por POST a /widgets; lo que cambia es el "ddoKey".
Las vacantes salen con ddoKey=refineSearch (o eagerLoadRefineSearch en la
primera carga). Este módulo:
  1. Abre una sesión y visita una página de pgcareers para recibir el cookie
     PLAY_SESSION.
  2. Extrae el x-csrf-token que viaja DENTRO de ese cookie (es un JWT).
  3. Hace el POST de búsqueda paginando con from/size, ya filtrado a Costa Rica.

Como Phenom sirve la MISMA API para cualquier empresa, reutilizás esto para
otras compañías en Phenom cambiando CLIENT (careerSiteUrl), PAGE_* y el
filtro de país. P&G es solo la primera instancia.

Prueba suelta (imprime lo que encuentra, sin notificar):
    python -m jobbot.fetchers.phenom
"""

import json
import base64
import time
import requests

# --------------------------------------------------------------------------
# Config específica de P&G  (esto es lo que cambiás para otra empresa Phenom)
# --------------------------------------------------------------------------
SITE = "https://www.pgcareers.com"
WIDGETS_URL = SITE + "/widgets"
WARMUP_URL = SITE + "/global/en/locations/costa-rica"   # para obtener cookie/token
PAGE_ID = "page103-prod-ds"
PAGE_NAME = "Costa Rica"
RK = "l-costa-rica"
COUNTRY_FILTER = ["Costa Rica"]        # selected_fields.country
SUBSEARCH = ""                          # "" = todas las vacantes (sin palabra clave)

PAGE_SIZE = 20                          # cuántas por llamada (subimos desde el 5 default)
MAX_RESULTS = 400                       # tope de seguridad
PAGE_PAUSE = 1.5

# Phenom usa eagerLoadRefineSearch en la 1a carga y refineSearch después.
# Probamos ambos en la primera página y nos quedamos con el que traiga vacantes.
DDO_CANDIDATES = ["refineSearch", "eagerLoadRefineSearch"]

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36")


# --------------------------------------------------------------------------
# Sesión + token
# --------------------------------------------------------------------------
def _csrf_from_play_session(play_session_cookie):
    """El PLAY_SESSION es un JWT: header.payload.firma. El csrfToken vive en
    payload.data.csrfToken. Lo decodificamos sin librerías extra."""
    try:
        payload_b64 = play_session_cookie.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)      # padding base64
        data = json.loads(base64.urlsafe_b64decode(payload_b64))
        return (data.get("data") or {}).get("csrfToken")
    except Exception:
        return None


def _open_session():
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Accept-Language": "en;q=0.9"})
    token = None
    try:
        s.get(WARMUP_URL, timeout=20)
        ps = s.cookies.get("PLAY_SESSION")
        if ps:
            token = _csrf_from_play_session(ps)
    except Exception as e:
        print(f"[warn] warmup P&G: {e}")
    return s, token


# --------------------------------------------------------------------------
# Petición de búsqueda
# --------------------------------------------------------------------------
def _build_payload(ddo_key, from_offset):
    return {
        "lang": "en_global", "deviceType": "desktop", "country": "global",
        "pageName": PAGE_NAME, "ddoKey": ddo_key, "sortBy": "",
        "subsearch": SUBSEARCH, "from": from_offset,
        "irs": False, "jobs": True, "counts": True,
        "all_fields": ["category", "country", "state", "city", "type",
                       "subCategory", "experienceLevel", "phLocSlider"],
        "pageType": "landingPage", "size": PAGE_SIZE, "rk": RK, "ak": "",
        "clearAll": False, "jdsource": "facets", "isSliderEnable": True,
        "pageId": PAGE_ID, "siteType": "external", "keywords": SUBSEARCH,
        "global": True, "selected_fields": {"country": COUNTRY_FILTER},
        "locationData": {"sliderRadius": 50, "aboveMaxRadius": True,
                         "LocationUnit": "miles"},
        "rkstatus": True, "s": "1",
    }


def _find_jobs_list(obj):
    """Busca recursivamente una lista bajo la clave 'jobs' (por si la
    estructura de respuesta cambia entre versiones de Phenom)."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k == "jobs" and isinstance(v, list):
                return v
            found = _find_jobs_list(v)
            if found:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = _find_jobs_list(item)
            if found:
                return found
    return []


def _extract(resp_json):
    """Devuelve (jobs, total)."""
    for key in ("refineSearch", "eagerLoadRefineSearch"):
        if key in resp_json:
            block = resp_json[key] or {}
            data = block.get("data", block)
            jobs = data.get("jobs") or block.get("jobs") or []
            total = block.get("totalHits") or data.get("totalHits") or len(jobs)
            if jobs:
                return jobs, total
    jobs = _find_jobs_list(resp_json)
    return jobs, len(jobs)


def _map_job(j):
    return {
        "id": f"pg-{j.get('jobId') or j.get('id')}",
        "title": j.get("title", ""),
        "location": j.get("cityStateCountry") or j.get("location") or "",
        "category": j.get("category", ""),
        "posted": j.get("postedDate", ""),
        "url": j.get("applyUrl") or j.get("jobUrl") or "",
        "source": "P&G",
    }


def fetch_pg():
    session, token = _open_session()
    headers = {
        "content-type": "application/json",
        "origin": SITE,
        "referer": WARMUP_URL,
    }
    if token:
        headers["x-csrf-token"] = token

    ddo = None
    from_offset = 0
    by_id = {}

    while from_offset < MAX_RESULTS:
        candidates = [ddo] if ddo else DDO_CANDIDATES
        jobs, total = [], 0

        for cand in candidates:
            try:
                r = session.post(WIDGETS_URL, headers=headers,
                                 json=_build_payload(cand, from_offset), timeout=20)
                r.raise_for_status()
                jobs, total = _extract(r.json())
            except Exception as e:
                print(f"[warn] P&G {cand} from={from_offset}: {e}")
                continue
            if jobs:
                ddo = cand           # nos quedamos con el ddoKey que funcionó
                break

        if not jobs:
            break

        for j in jobs:
            m = _map_job(j)
            by_id[m["id"]] = m

        from_offset += PAGE_SIZE
        if total and from_offset >= total:
            break
        time.sleep(PAGE_PAUSE)

    return list(by_id.values())


# --------------------------------------------------------------------------
# Prueba directa
# --------------------------------------------------------------------------
if __name__ == "__main__":
    jobs = fetch_pg()
    print(f"\n{len(jobs)} vacantes de P&G en Costa Rica:\n")
    for j in jobs:
        loc = j["location"] or "—"
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({loc}{cat})")
        if j["url"]:
            print(f"        {j['url']}")
