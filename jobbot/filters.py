"""
Filtros sobre título y ubicación.

Los patrones vienen de `config/sources.yaml` y son regex. Regla: si algo matchea
`exclude`, se descarta aunque también matchee `include`.
"""

import re


def compile_filters(filters):
    return {
        key: [re.compile(p, re.IGNORECASE) for p in filters.get(key) or []]
        for key in ("include", "exclude", "location_hints")
    }


def matches(job, rx):
    text = f"{job.get('title', '')} {job.get('location', '')}".lower()
    if any(p.search(text) for p in rx["exclude"]):
        return False
    if rx["include"] and not any(p.search(text) for p in rx["include"]):
        return False
    if rx["location_hints"] and not any(p.search(text) for p in rx["location_hints"]):
        return False
    return True
