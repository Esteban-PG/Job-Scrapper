"""
Phenom People (Phenom CMS) template for the alert bot.

Phenom multiplexes EVERYTHING through a POST to `<site>/widgets`; what changes
is the "ddoKey". Postings come back with ddoKey=refineSearch (or some
eagerLoad... variant on the first load). The flow is always the same:

  1. Open a session and visit a page of the site to receive the PLAY_SESSION
     cookie.
  2. Pull out the x-csrf-token: it travels INSIDE that cookie (which is a JWT)
     and/or in plain text in the HTML. Both are tried.
  3. POST the search, paginating with from/size, already filtered by country.

Since Phenom serves the SAME API for every company, this module is parameterized
just like `workday.py`: the values specific to each board (`site`, `page_id`,
`ref_num`, …) come from `config/sources.yaml`, not from the code. `fetch_pg` and
`fetch_cisco` are just presets with those values already filled in.

Where the parameters come from (DevTools → Network tab → POST to /widgets):
    site        the board's domain                 https://careers.cisco.com
    page_id     payload's `pageId` field           page490-prod
    page_name   payload's `pageName` field         search
    page_type   payload's `pageType` field         search
    ref_num     payload's `refNum` (not all use it) CISCISGLOBAL
    lang        payload's `lang` field             en_global (HPE uses en_us)
    locale      payload's `country` field          global    (HPE uses us)
    extra       any extra payload field that site happens to send
                (P&G sends `rk`/`locationData`, Cisco doesn't)

`locale` is the SITE's language/market, not the country filter: the posting's
country always goes in `selected_fields.country`.

`page_name`/`page_type` describe the page the UI fires the search from; verified
live that they do NOT change the results (searching from the "Product and
Engineering" category or from the global search box returns the same thing).
What actually filters is `selected_fields`.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.phenom
"""

import base64
import json
import re
import time

import requests

from .useragents import BROWSER_UA

PAGE_SIZE = 20       # how many per call (the site's default is 5 or 10)
MAX_RESULTS = 400    # safety cap
PAGE_PAUSE = 1.5

# Phenom uses an eagerLoad… variant on the 1st load and refineSearch afterwards,
# and the exact name changes between versions (P&G: eagerLoadRefineSearch,
# Cisco: eagerLoadRefineSearchSession). All of them are tried on the first page
# and we keep the one that brings back postings.
DDO_CANDIDATES = ["refineSearch", "eagerLoadRefineSearch",
                  "eagerLoadRefineSearchSession"]

DEFAULT_ALL_FIELDS = ["category", "country", "state", "city", "type"]

# Some sites (Cisco) expose the token in plain text in the HTML on top of
# putting it inside the cookie's JWT.
CSRF_RE = re.compile(r'csrf[-_]?token["\'\s:=]+([A-Fa-f0-9]{32})', re.I)


# --------------------------------------------------------------------------
# Session + token
# --------------------------------------------------------------------------
def _csrf_from_play_session(play_session_cookie):
    """PLAY_SESSION is a JWT: header.payload.signature. The csrfToken lives in
    payload.data.csrfToken. We decode it without any extra library."""
    try:
        payload_b64 = play_session_cookie.split(".")[1]
        payload_b64 += "=" * (-len(payload_b64) % 4)      # base64 padding
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
# Search request
# --------------------------------------------------------------------------
def _build_payload(cfg, ddo_key, from_offset):
    """Base payload common to all of Phenom + the site's own fields."""
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

    # `extra` may override any of the ones above (that's where each site's
    # quirks go); the dynamic ones go last so nothing can override them.
    return {**base, **cfg["extra"],
            "ddoKey": ddo_key, "from": from_offset, "size": cfg["page_size"]}


def _find_jobs_list(obj):
    """Recursively looks for a list under the 'jobs' key (in case the response
    structure changes between Phenom versions)."""
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
    """Returns (jobs, total)."""
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
    """The location comes under a different name depending on the site.

    Watch out for **multi-location** postings: the fields above show only the
    primary site, which may be in another country. HPE publishes roles based in
    Texas or India that can ALSO be taken from Heredia (8 of the 20 in Costa
    Rica are like that), and `multi_location` lists the cities without the
    country ("Heredia, Heredia, 400803"), so there's nowhere to get the name
    from.

    Since the country filter was applied by the API, we know the requested
    country is among the locations even if it isn't in the text: we annotate it.
    Without this the bot's location filter would discard postings that are
    actually a good fit."""
    primary = j.get("cityStateCountry") or j.get("location") or ""
    multi = j.get("multi_location") or []
    if not primary:
        primary = multi[0] if multi else ", ".join(
            p for p in (j.get("city"), j.get("country")) if p)

    others = len(multi) - 1
    if countries and others > 0 and (j.get("country") or "") not in countries:
        plural = "location" if others == 1 else "locations"
        return f"{primary} (+{others} {plural}, includes {' or '.join(countries)})"
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
    Returns the postings of a Phenom board, already normalized.

    site         board's domain, no trailing slash ("https://careers.cisco.com")
    page_id      payload's `pageId`; visible in the POST to /widgets
    page_name    payload's `pageName`
    page_type    payload's `pageType` ("search", "category", "landingPage"…)
    id_prefix    prefix of the dedupe id ("cisco" -> "cisco-2005253")
    countries    names exactly as the site's filter shows them; None = all
    name         readable name for the notification (default: id_prefix)
    warmup_path  page visited to obtain the cookie/token
    ref_num      payload's `refNum`, if the site sends it
    all_fields   facets requested back; you almost never need to touch this
    lang/locale  the SITE's language and market (not the country filter)
    extra        extra payload fields specific to the site
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
                ddo = cand           # we keep the ddoKey that worked
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
# Presets: Phenom boards already verified live
# --------------------------------------------------------------------------
def fetch_pg(countries=("Costa Rica",), name="P&G"):
    """P&G — https://www.pgcareers.com (verified: 2 postings in Costa Rica)."""
    return fetch_phenom(
        site="https://www.pgcareers.com",
        warmup_path="/global/en/locations/costa-rica",
        page_id="page103-prod-ds", page_name="Costa Rica",
        page_type="landingPage", id_prefix="pg",
        countries=countries, name=name,
        all_fields=["category", "country", "state", "city", "type",
                    "subCategory", "experienceLevel", "phLocSlider"],
        # P&G sends the radius slider block and the landing page's "rk".
        extra={
            "rk": "l-costa-rica", "ak": "", "irs": False,
            "rkstatus": True, "s": "1", "isSliderEnable": True,
            "locationData": {"sliderRadius": 50, "aboveMaxRadius": True,
                             "LocationUnit": "miles"},
        },
    )


def fetch_cisco(countries=("Costa Rica",), name="Cisco"):
    """Cisco — https://careers.cisco.com (verified: 4 postings in Costa Rica).

    "Apply" redirects to Workday (cisco.wd5.myworkdayjobs.com/Cisco_Careers),
    same as P&G: if that board is ever added as `type: workday`, only one of the
    two can be enabled or every posting arrives twice.
    """
    return fetch_phenom(
        site="https://careers.cisco.com",
        warmup_path="/en/jobs",
        page_id="page490-prod", page_name="search", page_type="search",
        id_prefix="cisco", ref_num="CISCISGLOBAL",
        countries=countries, name=name,
        page_size=100,      # verified: Cisco accepts size=100 without complaining
        all_fields=["category", "raasJobRequisitionType", "country", "state",
                    "city", "type", "RemoteType"],
    )


def fetch_hpe(countries=("Costa Rica",), name="HPE"):
    """HPE — https://careers.hpe.com (verified: 20 postings in Costa Rica).

    The only preset that doesn't run on `en_global`/`global`: HPE's site is the
    US market (`en_us`/`us`). That does NOT limit the postings to the United
    States — the country is still filtered by `selected_fields.country`.

    "Apply" redirects to Workday (hpe.wd5.myworkdayjobs.com/Jobsathpe), same as
    P&G and Cisco: enable this one or the Workday one, not both.
    """
    return fetch_phenom(
        site="https://careers.hpe.com",
        warmup_path="/us/en/search-results",
        page_id="page15", page_name="search-results1", page_type="search",
        id_prefix="hpe", ref_num="HPE1US",
        lang="en_us", locale="us",
        countries=countries, name=name,
        page_size=100,      # verified: HPE accepts size=100
        all_fields=["category", "country", "state", "city", "type",
                    "postalCode", "remote"],
    )


def fetch_bcg(countries=("Costa Rica",), name="BCG"):
    """BCG — https://careers.bcg.com (verified: 13 postings in Costa Rica, out of
    879 globally).

    Classic Phenom payload on `page17-ds`, with two extra facets in `all_fields`
    (`company`, `jobType`) that this tenant returns. `irs: false` rides along in
    `extra` because the site sends it.

    The browser filters by putting the country in `keywords`, URL-encoded inside
    the JSON ("Costa%20Rica"). This preset uses `selected_fields.country`
    instead — the structured facet every other Phenom tenant uses, and the one
    that doesn't depend on the country appearing in the text.
    """
    return fetch_phenom(
        site="https://careers.bcg.com",
        warmup_path="/search-results",
        page_id="page17-ds", page_name="search-results",
        page_type="search-results", id_prefix="bcg",
        countries=countries, name=name,
        page_size=30,
        all_fields=["country", "city", "category", "company", "type", "jobType"],
        extra={"irs": False, "locationData": {}},
    )


def fetch_mastercard(countries=("Costa Rica",), name="Mastercard"):
    """Mastercard — https://careers.mastercard.com (verified: 5 postings in
    Costa Rica).

    The classic Phenom payload, same shape as Cisco and HPE — `pageId`,
    `all_fields`, `jdsource: facets` — so nothing here but the site's own values.
    Runs on the US market (`en_us`/`us`) like HPE; that does not limit the
    postings to the States, the country is still filtered by
    `selected_fields.country`.

    One of the five is filed in Bogotá with Costa Rica among its six sites, so it
    arrives annotated rather than dropped (see `_location`).
    """
    return fetch_phenom(
        site="https://careers.mastercard.com",
        warmup_path="/search-results",
        page_id="page11", page_name="search", page_type="search",
        id_prefix="mc",
        lang="en_us", locale="us",
        countries=countries, name=name,
        page_size=30,
        extra={"locationData": {}},
    )


def fetch_roche(countries=("Costa Rica",), name="Roche"):
    """Roche — https://careers.roche.com (verified: 19 postings in Costa Rica,
    out of 1230 globally).

    A newer Phenom skin (CareerConnect) whose payload differs from the P&G /
    Cisco / HPE one, which is what `extra` is for: it names the tenant
    `clientName` instead of `refNum`, the language `cultureName` instead of
    `lang`, and sends no `pageId` at all.

    Two things that cost a round of debugging:

    - The payload the browser sends when you tick a facet has **no `jobs: True`**
      and comes back with `hits: 0`, `totalHits: 19` and no job array at all —
      only facet counts. It looks like the right call and returns nothing usable.
      `_build_payload` already sends `jobs`/`counts`, which is what makes the
      same `refineSearch` return the 19 postings.
    - `keyword` is **ignored**: searching "Costa Rica" returns the same 1230 as
      an empty keyword. The country is filtered by `selected_fields.country`,
      exactly as on the other Phenom tenants.
    """
    return fetch_phenom(
        site="https://careers.roche.com",
        warmup_path="/global/en/search-results",
        # This variant doesn't use pageId; the field rides along empty.
        page_id="", page_name="search-results", page_type="search-results",
        id_prefix="roche",
        countries=countries, name=name,
        page_size=30,
        extra={
            "clientName": "ROCHGLOBAL",
            "cultureName": "en_global",
            "eventType": "search",
            "globalSearch": True,
            "sortBy": "Most relevant",
            "keyword": "", "location": "", "locationData": {},
            "jdsource": "facet",
        },
    )


if __name__ == "__main__":
    for fetch in (fetch_pg, fetch_cisco, fetch_hpe, fetch_roche):
        jobs = fetch()
        source = jobs[0]["source"] if jobs else fetch.__name__
        print(f"\n{len(jobs)} {source} postings in Costa Rica:\n")
        for j in jobs:
            loc = j["location"] or "—"
            cat = f" · {j['category']}" if j["category"] else ""
            print(f"  [{j['id']}] {j['title']}  ({loc}{cat})")
            if j["url"]:
                print(f"        {j['url']}")
