"""
Fetcher registry: `type` from `sources.yaml` -> function that fetches postings.

Every fetcher returns a list of dicts with the SAME schema, and knows nothing
about filters or notifications. That contract is what lets the orchestrator not
care which platform each posting came from:

    {
        "id":       "efx-J00178026",   # unique and STABLE, prefixed by source
        "title":    "Billing Analyst - Junior",
        "location": "Heredia, Costa Rica",
        "url":      "https://...",
        "source":   "Equifax",
        "category": "Accounting",      # optional
        "posted":   "2026-07-20",      # optional
    }

To add a new platform: a module here with its `fetch_<something>()`, and an
entry in FETCHERS. Nothing else gets touched.
"""

from .amazon import CATEGORIES_TECH, fetch_amazon
from .ats import fetch_ashby, fetch_greenhouse, fetch_lever
from .bamboohr import fetch_bamboohr, fetch_gorillalogic
from .eightfold import fetch_eightfold, fetch_microsoft
from .equifax import fetch_equifax
from .generic_html import fetch_html
from .ibm import fetch_ibm
from .jibe import fetch_jibe, fetch_teknowledge
from .phenom import (fetch_bcg, fetch_cisco, fetch_hpe, fetch_mastercard,
                     fetch_pg, fetch_phenom, fetch_roche)
from .radancy import fetch_moodys, fetch_radancy
from .workday import fetch_workday

FETCHERS = {
    # These three have no server-side location filter; `countries` is applied
    # locally by the fetcher. `countries: []` brings the whole board.
    "greenhouse": lambda s: fetch_greenhouse(
        s["company"], s.get("name"), s.get("countries", ["Costa Rica"])),
    "lever": lambda s: fetch_lever(
        s["company"], s.get("name"), s.get("countries", ["Costa Rica"])),
    "ashby": lambda s: fetch_ashby(
        s["company"], s.get("name"), s.get("countries", ["Costa Rica"])),
    "html": fetch_html,
    "equifax": lambda s: fetch_equifax(countries=s.get("countries", ["Costa Rica"])),
    "amazon": lambda s: fetch_amazon(
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name", "Amazon"),
        query=s.get("query", ""),
        # `categories` absent = the technical ones by default; `categories: []` =
        # all of them (two different things, hence no s.get(k, default)).
        categories=(s["categories"] if "categories" in s else CATEGORIES_TECH),
    ),
    "pg": lambda s: fetch_pg(countries=s.get("countries", ["Costa Rica"])),
    "cisco": lambda s: fetch_cisco(countries=s.get("countries", ["Costa Rica"])),
    "hpe": lambda s: fetch_hpe(countries=s.get("countries", ["Costa Rica"])),
    "roche": lambda s: fetch_roche(countries=s.get("countries", ["Costa Rica"])),
    "mastercard": lambda s: fetch_mastercard(
        countries=s.get("countries", ["Costa Rica"])),
    "bcg": lambda s: fetch_bcg(countries=s.get("countries", ["Costa Rica"])),
    "gorillalogic": lambda s: fetch_gorillalogic(
        countries=s.get("countries", ["Costa Rica"])),
    "microsoft": lambda s: fetch_microsoft(
        countries=s.get("countries", ["Costa Rica"])),
    # Any other Eightfold/PCSX board: site + the `domain=` parameter.
    "eightfold": lambda s: fetch_eightfold(
        site=s["site"],
        domain=s["domain"],
        countries=s.get("countries", ["Costa Rica"]),
        id_prefix=s.get("id_prefix") or s["type"],
        name=s.get("name"),
        query=s.get("query", ""),
    ),
    # Any other BambooHR board: only the subdomain is needed.
    "bamboohr": lambda s: fetch_bamboohr(
        company=s["company"],
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name"),
    ),
    "moodys": lambda s: fetch_moodys(countries=s.get("countries", ["Costa Rica"])),
    "ibm": lambda s: fetch_ibm(
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name", "IBM"),
        keywords=s.get("keywords", ""),
    ),
    "teknowledge": lambda s: fetch_teknowledge(
        countries=s.get("countries", ["Costa Rica"])),
    # Any other Jibe/iCIMS board: it comes from sources.yaml.
    "jibe": lambda s: fetch_jibe(
        site=s["site"],
        countries=s.get("countries", ["Costa Rica"]),
        id_prefix=s.get("id_prefix") or s["type"],
        name=s.get("name"),
        domain=s.get("domain"),
        keywords=s.get("keywords", ""),
    ),
    # Any other Radancy/TalentBrew board: it comes from sources.yaml.
    "radancy": lambda s: fetch_radancy(
        site=s["site"],
        org_id=s["org_id"],
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name"),
        keywords=s.get("keywords", ""),
    ),
    # Any other Phenom board: the values come from sources.yaml.
    "phenom": lambda s: fetch_phenom(
        site=s["site"],
        page_id=s["page_id"],
        page_name=s.get("page_name", "search"),
        page_type=s.get("page_type", "search"),
        id_prefix=s.get("id_prefix") or s["type"],
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name"),
        warmup_path=s.get("warmup_path", "/"),
        ref_num=s.get("ref_num"),
        all_fields=s.get("all_fields"),
        extra=s.get("extra"),
    ),
    "workday": lambda s: fetch_workday(
        tenant=s["tenant"],
        site=str(s["site"]),
        dc=s.get("dc", "wd5"),
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name"),
    ),
}

__all__ = ["FETCHERS"]
