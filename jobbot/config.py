"""
Configuración: credenciales, rutas y `sources.yaml`.

Las credenciales salen del entorno o de un `.env` en la raíz del proyecto. Las
fuentes y los filtros salen de `config/sources.yaml`, para que agregar una bolsa
sea editar config y no código.
"""

import logging
import os
from pathlib import Path

import yaml

# jobbot/config.py -> jobbot/ -> raíz del proyecto
ROOT = Path(__file__).resolve().parents[1]

log = logging.getLogger("jobbot")


def _load_env_file(path):
    """Carga un `.env` sencillo (KEY=VALOR) si existe, para no tener que hacer
    `export` en cada terminal. No pisa lo que ya esté en el entorno: las
    variables reales mandan sobre el archivo (así GitHub Actions, que inyecta
    los secrets como variables, no se ve afectado)."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_env_file(ROOT / ".env")

DB_PATH = os.getenv("JOBBOT_DB", str(ROOT / "data" / "seen_jobs.db"))
CONFIG_PATH = os.getenv("JOBBOT_SOURCES", str(ROOT / "config" / "sources.yaml"))
TG_TOKEN = os.getenv("TELEGRAM_TOKEN")
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID")

SOURCE_PAUSE = 2      # cortesía entre fuentes
NOTIFY_PAUSE = 0.5    # Telegram tolera ~30 msg/s; vamos muy por debajo
FAIL_ALERT_AFTER = 2  # corridas seguidas fallando antes de avisar que una fuente se cayó

# Red de seguridad, NO la configuración real: los filtros que manda son los de
# `config/sources.yaml`. Estos se usan solo si ese archivo falta o si omite una
# clave, para que el bot no arranque sin ningún filtro y notifique cualquier
# cosa. Si editás los filtros, editá la YAML — tocar esto no cambia nada
# mientras el archivo exista.
DEFAULT_FILTERS = {
    "include": [r"\bjunior\b", r"\bjr\b", r"\bentry.?level\b", r"\bdata\b",
                r"\bsoftware\b", r"\bqa\b", r"\banalyst\b", r"\bengineer\b"],
    "exclude": [r"\bsenior\b", r"\bstaff\b", r"\bprincipal\b", r"\blead\b",
                r"\bmanager\b", r"\bdirector\b", r"\bsr\.?\b", r"\bhead of\b"],
    "location_hints": [r"remote", r"remoto", r"latam", r"americas",
                       r"costa rica", r"anywhere", r"heredia", r"san jos[eé]"],
}


def load_config(path):
    """Lee sources.yaml. Si no existe, corre con los defaults de arriba y sin
    fuentes (mejor eso que reventar en el cron)."""
    if not Path(path).exists():
        log.warning("no se encontró %s — sin fuentes que revisar", path)
        return [], DEFAULT_FILTERS

    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    sources = cfg.get("sources") or []
    filters = dict(DEFAULT_FILTERS)
    # `location_hints: []` es una elección válida (no filtrar por ubicación),
    # así que se respeta cualquier clave presente, aunque venga vacía.
    for key, value in (cfg.get("filters") or {}).items():
        if key in filters and value is not None:
            filters[key] = value

    return sources, filters


def source_label(src):
    """Nombre corto de una fuente, para logs y para el flag --source."""
    return src.get("name") or src.get("company") or src.get("tenant") or src["type"]
