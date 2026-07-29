"""
IBM careers fetcher for the alert bot.

IBM doesn't use a third-party ATS: the careers widget is fed by IBM's own
unified search endpoint, and the "Apply" link goes to its own portal
(`careers.ibm.com/careers/JobDetail?jobId=<id>`, a Kenexa/BrassRing-style
internal ATS). It is not Greenhouse, Lever, Ashby, Workday, Phenom or Jibe.

    POST https://www-api.ibm.com/search/api/v2
    body: {"appId": "careers", "scopes": ["careers2"],
           "post_filter": {"term": {"field_keyword_05": "Costa Rica"}}, ...}

The response is Elasticsearch-shaped: `{took, hits: {total: {value}, hits: [
{_source: {...}}]}}`. The postings are not in the HTML — the page loads them
over XHR.

No CSRF token and no special headers: `Content-Type` and `Accept` are all the
site itself sends, and `BOT_UA` gets a 200 (verified).

The opaque field names, mapped
------------------------------
    field_keyword_05   country          "Costa Rica"
    field_keyword_08   business area    "Infrastructure & Technology", "Cloud"
    field_keyword_17   work model       "Hybrid"
    field_keyword_18   level            "Professional", "Internship"
    field_keyword_19   city             "Heredia, CR"

Three things worth not rediscovering
------------------------------------
- **An unknown country returns `total: 0`, not an error.** There is no way to
  tell "IBM isn't hiring here" from "you misspelled the country" by looking at
  the response. So the country is validated first against the aggregation that
  lists every country in the index — the same trick `workday.py` uses with its
  facet catalog, and the reason a typo raises instead of going quiet forever.
- **Dropping `post_filter` returns the global catalog** (296 postings against 5
  for Costa Rica), so a filter that silently stops applying means notifying the
  whole world. `field_keyword_05` is revalidated locally per posting.
- **`field_keyword_19` carries the ISO-2, not the country** ("Heredia, CR"), so
  `location_hints` would have nothing to match "costa rica" against. The
  location is rebuilt with the country name, exactly like `amazon.py` does.

The `aggs` block the browser sends is only there to paint the facet counts in
the sidebar; the search works without it. Only the country aggregation is kept,
and only to validate the name.

Standalone check (prints what it finds, without notifying):
    python -m jobbot.fetchers.ibm
"""

import time

import requests

from .useragents import BOT_UA

SEARCH_URL = "https://www-api.ibm.com/search/api/v2"
JOB_URL = "https://careers.ibm.com/careers/JobDetail?jobId={}"

PAGE_SIZE = 30       # mirrors the site's "items per page" selector
MAX_RESULTS = 400    # safety cap
PAGE_PAUSE = 1.0

COUNTRY_FIELD = "field_keyword_05"

HEADERS = {
    "User-Agent": BOT_UA,
    "Content-Type": "application/json",
    "Accept": "application/json, text/plain, */*",
}

SOURCE_FIELDS = ["_id", "title", "url", "field_keyword_05", "field_keyword_08",
                 "field_keyword_17", "field_keyword_18", "field_keyword_19"]


def _country_filter(countries):
    """One country is a `term`; several become a `bool.should`, which is what
    the site itself sends when you tick more than one box."""
    terms = [{"term": {COUNTRY_FIELD: c}} for c in countries]
    return terms[0] if len(terms) == 1 else {"bool": {"should": terms}}


def _payload(countries, offset, size, keywords="", with_country_agg=False):
    body = {
        "appId": "careers",
        "scopes": ["careers2"],
        "query": {"bool": {"must": [{"query_string": {"query": keywords}}]
                           if keywords else []}},
        "size": size,
        "from": offset,
        "sort": [{"_score": "desc"}, {"pageviews": "desc"}],
        "lang": "zz",
        "localeSelector": {},
        "sm": {"query": keywords, "lang": "zz"},
        "_source": SOURCE_FIELDS,
    }
    if countries:
        body["post_filter"] = _country_filter(countries)
    if with_country_agg:
        # Every country in the index, to validate the configured names.
        body["aggs"] = {"all_countries": {
            "filter": {"match_all": {}},
            "aggs": {COUNTRY_FIELD: {"terms": {"field": COUNTRY_FIELD,
                                               "size": 1000}}}}}
    return body


def _known_countries(payload):
    agg = ((payload.get("aggregations") or {}).get("all_countries") or {})
    buckets = (agg.get(COUNTRY_FIELD) or {}).get("buckets") or []
    return {b["key"] for b in buckets if b.get("key")}


def _job_id(source):
    """The stable code is the `jobId` of the detail URL (…?jobId=120944). The
    `_id` of the hit is a 64-char hash — stable too, but opaque in a
    notification and useless for looking the posting up by hand."""
    url = source.get("url") or ""
    _, sep, tail = url.partition("jobId=")
    if sep and tail:
        return tail.split("&")[0].strip()
    return (source.get("_id") or "")[:16]


def _location(source):
    """"Heredia, CR" -> "Heredia, Costa Rica", so `location_hints` has the
    country name to match against."""
    city = (source.get("field_keyword_19") or "").strip()
    country = (source.get(COUNTRY_FIELD) or "").strip()
    if not city:
        return country
    # Drop a trailing ISO-2 ("Heredia, CR") before appending the real name.
    head = city.rsplit(",", 1)
    if len(head) == 2 and len(head[1].strip()) == 2:
        city = head[0].strip()
    if country and country.lower() not in city.lower():
        return f"{city}, {country}"
    return city


def _map_job(source, label):
    job_id = _job_id(source)
    level = (source.get("field_keyword_18") or "").strip()
    area = (source.get("field_keyword_08") or "").strip()
    return {
        "id": f"ibm-{job_id}",
        "title": source.get("title", ""),
        "location": _location(source),
        # The business area is what the category gate reads. The level
        # (Professional / Internship) rides along because it is the closest
        # thing this source gives to seniority.
        "category": " · ".join(x for x in (area, level) if x),
        "url": source.get("url") or (JOB_URL.format(job_id) if job_id else ""),
        "source": label,
        # The search index carries no posting date, and `posted` is optional.
        "posted": "",
    }


def fetch_ibm(countries=("Costa Rica",), name="IBM", keywords="",
              page_size=PAGE_SIZE):
    """
    Returns IBM's postings, already normalized.

    countries  country names as IBM's own filter shows them ("Costa Rica").
               Validated against the index, so a typo raises instead of
               quietly returning zero.
    name       readable name for the notification
    keywords   free text for the search box; empty = everything in the country
    """
    countries = list(countries)
    session = requests.Session()
    session.headers.update(HEADERS)

    def search(offset, with_agg=False):
        r = session.post(SEARCH_URL, timeout=30,
                         json=_payload(countries, offset, page_size, keywords,
                                       with_agg))
        r.raise_for_status()
        return r.json()

    payload = search(0, with_agg=True)

    if countries:
        known = _known_countries(payload)
        unknown = [c for c in countries if c not in known]
        if known and unknown:
            raise ValueError(
                f"IBM has no country named {unknown!r} in its index. A wrong "
                f"name doesn't fail, it just returns zero postings forever. "
                f"Use the name exactly as the site's filter shows it."
            )

    wanted = {c.strip().lower() for c in countries}
    hits_total = ((payload.get("hits") or {}).get("total") or {})
    total = hits_total.get("value", 0) if isinstance(hits_total, dict) else hits_total

    by_id = {}
    discarded = 0
    offset = 0

    while offset < min(total or MAX_RESULTS, MAX_RESULTS):
        if offset:
            payload = search(offset)
            time.sleep(PAGE_PAUSE)

        hits = (payload.get("hits") or {}).get("hits") or []
        if not hits:
            break

        for hit in hits:
            source = {**(hit.get("_source") or {}), "_id": hit.get("_id")}
            job = _map_job(source, name)
            if job["id"] == "ibm-":
                continue
            # Same defence as radancy/jibe: without `post_filter` this endpoint
            # returns the global catalog, so never trust it blindly.
            if wanted and (source.get(COUNTRY_FIELD) or "").strip().lower() not in wanted:
                discarded += 1
                continue
            by_id[job["id"]] = job

        offset += page_size

    if discarded:
        print(f"[warn] {name}: {discarded} postings discarded for not being in "
              f"{countries} — the server's country filter isn't being applied; "
              f"check `post_filter`")

    return list(by_id.values())


if __name__ == "__main__":
    jobs = fetch_ibm()
    print(f"\n{len(jobs)} IBM postings in Costa Rica:\n")
    for j in jobs:
        cat = f" · {j['category']}" if j["category"] else ""
        print(f"  [{j['id']}] {j['title']}  ({j['location']}{cat})")
        print(f"        {j['url']}")
