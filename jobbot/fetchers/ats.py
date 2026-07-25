"""
Los tres ATS con API JSON pública: Greenhouse, Lever y Ashby.

Son los casos triviales — una sola llamada GET, sin token ni paginación — y por
eso viven juntos en un archivo. Si la URL de la bolsa contiene
`boards.greenhouse.io`, `jobs.lever.co` o `jobs.ashbyhq.com`, es uno de estos.

⚠️ Escritos pero todavía SIN probar en vivo: falta configurar una empresa real.
Cuando agregues la primera, revisala con `--dry-run` antes de confiar en ella.
"""

import requests

HEADERS = {"User-Agent": "job-alert-bot/1.0 (personal use; contacto@ejemplo.com)"}


def fetch_greenhouse(company, name=None):
    url = f"https://boards-api.greenhouse.io/v1/boards/{company}/jobs"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id": f"gh-{company}-{j['id']}",
            "title": j["title"],
            "location": (j.get("location") or {}).get("name", ""),
            "url": j["absolute_url"],
            "source": name or company,
        }
        for j in r.json().get("jobs", [])
    ]


def fetch_lever(company, name=None):
    url = f"https://api.lever.co/v0/postings/{company}?mode=json"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id": f"lv-{company}-{j['id']}",
            "title": j["text"],
            "location": (j.get("categories") or {}).get("location", ""),
            "url": j["hostedUrl"],
            "source": name or company,
        }
        for j in r.json()
    ]


def fetch_ashby(company, name=None):
    url = f"https://api.ashbyhq.com/posting-api/job-board/{company}"
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    return [
        {
            "id": f"ab-{company}-{j['id']}",
            "title": j["title"],
            "location": j.get("location", ""),
            "url": j["jobUrl"],
            "source": name or company,
        }
        for j in r.json().get("jobs", [])
    ]
