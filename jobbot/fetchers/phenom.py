"""
Plantilla de Phenom People (Phenom CMS) para el bot de alertas.

Phenom multiplexa TODO por POST a `<sitio>/widgets`; lo que cambia es el
"ddoKey". Las vacantes salen con ddoKey=refineSearch (o alguna variante de
eagerLoad... en la primera carga). El flujo es siempre el mismo:

  1. Abrir sesión y visitar una página del sitio para recibir el cookie
     PLAY_SESSION.
  2. Sacar el x-csrf-token: viaja DENTRO de ese cookie (es un JWT) y/o plano
     en el HTML. Se prueban ambos.
  3. POST de búsqueda paginando con from/size, ya filtrado por país.

Como Phenom sirve la MISMA API para cualquier empresa, este módulo está
parametrizado igual que `workday.py`: los valores propios de cada bolsa
(`site`, `page_id`, `ref_num`, …) salen de `config/sources.yaml`, no del
código. `fetch_pg` y `fetch_cisco` son solo presets con esos valores ya
puestos.

De dónde salen los parámetros (DevTools → pestaña Network → POST a /widgets):
    site        el dominio de la bolsa            https://careers.cisco.com
    page_id     campo `pageId` del payload        page490-prod
    page_name   campo `pageName`                  search
    page_type   campo `pageType`                  search
    ref_num     campo `refNum` (no todos lo usan) CISCISGLOBAL
    lang        campo `lang`                      en_global (HPE usa en_us)
    locale      campo `country` del payload       global    (HPE usa us)
    extra       cualquier campo extra del payload que ese sitio mande
                (P&G manda `rk`/`locationData`, Cisco no)

`locale` es el idioma/mercado del SITIO, no el filtro de país: el país de la
vacante va siempre en `selected_fields.country`.

`page_name`/`page_type` describen la página desde la que la UI dispara la
búsqueda; verificado en vivo que NO cambian los resultados (buscar desde la
categoría "Product and Engineering" o desde el buscador global devuelve lo
mismo). Lo que filtra de verdad es `selected_fields`.

Prueba suelta (imprime lo que encuentra, sin notificar):
    python -m jobbot.fetchers.phenom
"""

import base64
import json
import re
import time

import requests

from .useragents import BROWSER_UA

PAGE_SIZE = 20       # cuántas por llamada (el default del sitio es 5 o 10)
MAX_RESULTS = 400    # tope de seguridad
PAGE_PAUSE = 1.5

# Phenom usa una variante de eagerLoad… en la 1a carga y refineSearch después,
# y el nombre exacto cambia entre versiones (P&G: eagerLoadRefineSearch,
# Cisco: eagerLoadRefineSearchSession). Se prueban todos en la primera página
# y nos quedamos con el que traiga vacantes.
DDO_CANDIDATES = ["refineSearch", "eagerLoadRefineSearch",
                  "eagerLoadRefineSearchSession"]

DEFAULT_ALL_FIELDS = ["category", "country", "state", "city", "type"]

# Algunos sitios (Cisco) exponen el token plano en el HTML además de meterlo
# en el JWT del cookie.
CSRF_RE = re.compile(r'csrf[-_]?token["\'\s:=]+([A-Fa-f0-9]{32})', re.I)


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


def _open_session(warmup_url, label):
    s = requests.Session()
    s.headers.update({"User-Agent": BROWSER_UA, "Accept-Language": "en;q=0.9"})
    token = None
    try:
        r = s.get(warmup_url, timeout=20)
        ps = s.cookies.get("PLAY_SESSION")
        if ps:
            token = _csrf_from_play_session(ps)
        if not token:
            found = CSRF_RE.search(r.text)
            token = found.group(1) if found else None
    except Exception as e:
        print(f"[warn] warmup {label}: {e}")
    return s, token


# --------------------------------------------------------------------------
# Petición de búsqueda
# --------------------------------------------------------------------------
def _build_payload(cfg, ddo_key, from_offset):
    """Payload base común a todo Phenom + los campos propios del sitio."""
    base = {
        "lang": cfg["lang"], "deviceType": "desktop", "country": cfg["locale"],
        "sortBy": "", "subsearch": "", "keywords": "",
        "jobs": True, "counts": True, "global": True,
        "all_fields": cfg["all_fields"],
        "pageName": cfg["page_name"], "pageType": cfg["page_type"],
        "pageId": cfg["page_id"], "siteType": "external",
        "clearAll": False, "jdsource": "facets", "isSliderEnable": False,
        "selected_fields": {"country": list(cfg["countries"])} if cfg["countries"] else {},
    }
    if cfg["ref_num"]:
        base["refNum"] = cfg["ref_num"]

    # `extra` puede pisar cualquiera de los de arriba (ahí van las rarezas de
    # cada sitio); los dinámicos van al final para que nadie los pise.
    return {**base, **cfg["extra"],
            "ddoKey": ddo_key, "from": from_offset, "size": cfg["page_size"]}


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
    for key in DDO_CANDIDATES:
        if key in resp_json:
            block = resp_json[key] or {}
            data = block.get("data", block)
            jobs = data.get("jobs") or block.get("jobs") or []
            total = block.get("totalHits") or data.get("totalHits") or len(jobs)
            if jobs:
                return jobs, total
    jobs = _find_jobs_list(resp_json)
    return jobs, len(jobs)


def _location(j, countries):
    """La ubicación viene con distinto nombre según el sitio.

    Ojo con las vacantes **multi-ubicación**: los campos de arriba muestran solo
    la sede principal, que puede estar en otro país. HPE publica puestos con
    sede en Texas o India que TAMBIÉN se pueden tomar desde Heredia (8 de las 20
    de Costa Rica son así), y `multi_location` lista las ciudades sin el país
    ("Heredia, Heredia, 400803"), así que no hay de dónde sacar el nombre.

    Como el filtro de país lo aplicó la API, sabemos que el país pedido está
    entre las ubicaciones aunque no figure en el texto: se anota. Sin esto el
    filtro de ubicación del bot descartaría vacantes que sí sirven."""
    primary = j.get("cityStateCountry") or j.get("location") or ""
    multi = j.get("multi_location") or []
    if not primary:
        primary = multi[0] if multi else ", ".join(
            p for p in (j.get("city"), j.get("country")) if p)

    others = len(multi) - 1
    if countries and others > 0 and (j.get("country") or "") not in countries:
        plural = "ubicación" if others == 1 else "ubicaciones"
        return f"{primary} (+{others} {plural}, incluye {' o '.join(countries)})"
    return primary


def _category(j):
    if j.get("category"):
        return j["category"]
    multi = j.get("multi_category") or []
    return multi[0] if multi else ""


def _map_job(j, id_prefix, label, countries=()):
    return {
        "id": f"{id_prefix}-{j.get('jobId') or j.get('reqId') or j.get('id')}",
        "title": j.get("title", ""),
        "location": _location(j, countries),
        "category": _category(j),
        "posted": (j.get("postedDate") or "")[:10],   # 2026-07-21T00:00… -> 2026-07-21
        "url": j.get("applyUrl") or j.get("jobUrl") or "",
        "source": label,
    }


def fetch_phenom(site, page_id, page_name, page_type, id_prefix,
                 countries=("Costa Rica",), name=None, warmup_path="/",
                 ref_num=None, all_fields=None, page_size=PAGE_SIZE,
                 lang="en_global", locale="global", extra=None):
    """
    Devuelve las vacantes de una bolsa Phenom, ya normalizadas.

    site         dominio de la bolsa, sin barra final ("https://careers.cisco.com")
    page_id      `pageId` del payload; se ve en el POST a /widgets
    page_name    `pageName` del payload
    page_type    `pageType` del payload ("search", "category", "landingPage"…)
    id_prefix    prefijo del id de dedupe ("cisco" -> "cisco-2005253")
    countries    nombres tal como los muestra el filtro del sitio; None = todos
    name         nombre legible para la notificación (default: id_prefix)
    warmup_path  página que se visita para obtener el cookie/token
    ref_num      `refNum` del payload, si el sitio lo manda
    all_fields   facets que se piden de vuelta; casi nunca hace falta tocarlo
    lang/locale  idioma y mercado del SITIO (no el filtro de país)
    extra        campos extra del payload propios del sitio
    """
    label = name or id_prefix
    cfg = {
        "page_id": page_id, "page_name": page_name, "page_type": page_type,
        "countries": list(countries) if countries else [],
        "ref_num": ref_num, "page_size": page_size,
        "lang": lang, "locale": locale,
        "all_fields": all_fields or DEFAULT_ALL_FIELDS,
        "extra": extra or {},
    }

    widgets_url = site.rstrip("/") + "/widgets"
    warmup_url = site.rstrip("/") + warmup_path
    session, token = _open_session(warmup_url, label)

    headers = {
        "content-type": "application/json",
        "origin": site.rstrip("/"),
        "referer": warmup_url,
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
                r = session.post(widgets_url, headers=headers, timeout=20,
                                 json=_build_payload(cfg, cand, from_offset))
                r.raise_for_status()
                jobs, total = _extract(r.json())
            except Exception as e:
                print(f"[warn] {label} {cand} from={from_offset}: {e}")
                continue
            if jobs:
                ddo = cand           # nos quedamos con el ddoKey que funcionó
                break

        if not jobs:
            break

        for j in jobs:
            m = _map_job(j, id_prefix, label, cfg["countries"])
            by_id[m["id"]] = m

        from_offset += cfg["page_size"]
        if total and from_offset >= total:
            break
        time.sleep(PAGE_PAUSE)

    return list(by_id.values())


# --------------------------------------------------------------------------
# Presets: bolsas Phenom ya verificadas en vivo
# --------------------------------------------------------------------------
def fetch_pg(countries=("Costa Rica",), name="P&G"):
    """P&G — https://www.pgcareers.com (verificado: 2 vacantes en Costa Rica)."""
    return fetch_phenom(
        site="https://www.pgcareers.com",
        warmup_path="/global/en/locations/costa-rica",
        page_id="page103-prod-ds", page_name="Costa Rica",
        page_type="landingPage", id_prefix="pg",
        countries=countries, name=name,
        all_fields=["category", "country", "state", "city", "type",
                    "subCategory", "experienceLevel", "phLocSlider"],
        # P&G manda el bloque del slider de radio y el "rk" de la landing.
        extra={
            "rk": "l-costa-rica", "ak": "", "irs": False,
            "rkstatus": True, "s": "1", "isSliderEnable": True,
            "locationData": {"sliderRadius": 50, "aboveMaxRadius": True,
                             "LocationUnit": "miles"},
        },
    )


def fetch_cisco(countries=("Costa Rica",), name="Cisco"):
    """Cisco — https://careers.cisco.com (verificado: 4 vacantes en Costa Rica).

    El "Aplicar" redirige a Workday (cisco.wd5.myworkdayjobs.com/Cisco_Careers),
    igual que P&G: si algún día se agrega esa bolsa como `type: workday`, hay
    que activar una sola de las dos o cada vacante llega duplicada.
    """
    return fetch_phenom(
        site="https://careers.cisco.com",
        warmup_path="/en/jobs",
        page_id="page490-prod", page_name="search", page_type="search",
        id_prefix="cisco", ref_num="CISCISGLOBAL",
        countries=countries, name=name,
        page_size=100,      # verificado: Cisco acepta size=100 sin quejarse
        all_fields=["category", "raasJobRequisitionType", "country", "state",
                    "city", "type", "RemoteType"],
    )


def fetch_hpe(countries=("Costa Rica",), name="HPE"):
    """HPE — https://careers.hpe.com (verificado: 20 vacantes en Costa Rica).

    Único preset que no corre en `en_global`/`global`: el sitio de HPE es el
    mercado US (`en_us`/`us`). Eso NO limita las vacantes a Estados Unidos —
    el país lo sigue filtrando `selected_fields.country`.

    "Aplicar" redirige a Workday (hpe.wd5.myworkdayjobs.com/Jobsathpe), igual
    que P&G y Cisco: activar esta o la de Workday, no las dos.
    """
    return fetch_phenom(
        site="https://careers.hpe.com",
        warmup_path="/us/en/search-results",
        page_id="page15", page_name="search-results1", page_type="search",
        id_prefix="hpe", ref_num="HPE1US",
        lang="en_us", locale="us",
        countries=countries, name=name,
        page_size=100,      # verificado: HPE acepta size=100
        all_fields=["category", "country", "state", "city", "type",
                    "postalCode", "remote"],
    )


if __name__ == "__main__":
    for fetch in (fetch_pg, fetch_cisco, fetch_hpe):
        jobs = fetch()
        source = jobs[0]["source"] if jobs else fetch.__name__
        print(f"\n{len(jobs)} vacantes de {source} en Costa Rica:\n")
        for j in jobs:
            loc = j["location"] or "—"
            cat = f" · {j['category']}" if j["category"] else ""
            print(f"  [{j['id']}] {j['title']}  ({loc}{cat})")
            if j["url"]:
                print(f"        {j['url']}")
