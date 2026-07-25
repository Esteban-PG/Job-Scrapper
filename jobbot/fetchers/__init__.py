"""
Registro de fetchers: `type` de `sources.yaml` -> función que trae las vacantes.

Cada fetcher devuelve una lista de dicts con el MISMO schema, y no sabe nada de
filtros ni de notificaciones. Ese contrato es lo que permite que el orquestador
no tenga que saber de qué plataforma vino cada vacante:

    {
        "id":       "efx-J00178026",   # único y ESTABLE, con prefijo de fuente
        "title":    "Billing Analyst - Junior",
        "location": "Heredia, Costa Rica",
        "url":      "https://...",
        "source":   "Equifax",
        "category": "Accounting",      # opcional
        "posted":   "2026-07-20",      # opcional
    }

Para agregar una plataforma nueva: un módulo acá con su `fetch_<algo>()`, y una
entrada en FETCHERS. Nada más se toca.
"""

from .ats import fetch_ashby, fetch_greenhouse, fetch_lever
from .equifax import fetch_equifax
from .generic_html import fetch_html
from .phenom import fetch_pg
from .workday import fetch_workday

FETCHERS = {
    "greenhouse": lambda s: fetch_greenhouse(s["company"], s.get("name")),
    "lever": lambda s: fetch_lever(s["company"], s.get("name")),
    "ashby": lambda s: fetch_ashby(s["company"], s.get("name")),
    "html": fetch_html,
    "equifax": lambda s: fetch_equifax(countries=s.get("countries", ["Costa Rica"])),
    "pg": lambda s: fetch_pg(),
    "workday": lambda s: fetch_workday(
        tenant=s["tenant"],
        site=str(s["site"]),
        dc=s.get("dc", "wd5"),
        countries=s.get("countries", ["Costa Rica"]),
        name=s.get("name"),
    ),
}

__all__ = ["FETCHERS"]
