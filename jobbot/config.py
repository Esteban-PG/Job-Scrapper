"""
Configuration: credentials, paths and `sources.yaml`.

Credentials come from the environment or from a `.env` at the project root.
Sources and filters come from `config/sources.yaml`, so that adding a job board
means editing config and not code.
"""

import logging
import os
from pathlib import Path

import yaml

# jobbot/config.py -> jobbot/ -> project root
ROOT = Path(__file__).resolve().parents[1]

log = logging.getLogger("jobbot")


def _load_env_file(path):
    """Loads a simple `.env` (KEY=VALUE) if it exists, so you don't have to
    `export` in every terminal. It doesn't override what's already in the
    environment: real variables win over the file (that way GitHub Actions,
    which injects the secrets as variables, isn't affected)."""
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

SOURCE_PAUSE = 2      # courtesy pause between sources
NOTIFY_PAUSE = 0.5    # Telegram tolerates ~30 msg/s; we stay well below that
FAIL_ALERT_AFTER = 2  # consecutive failed runs before alerting that a source is down

# Safety net, NOT the real configuration: the filters that count are the ones in
# `config/sources.yaml`. These are used only if that file is missing or omits a
# key, so the bot doesn't start with no filters at all and notify anything that
# moves. If you're editing the filters, edit the YAML — touching this changes
# nothing as long as the file exists.
DEFAULT_FILTERS = {
    "include": [r"\bjunior\b", r"\bjr\b", r"\bentry.?level\b", r"\bdata\b",
                r"\bsoftware\b", r"\bqa\b", r"\banalyst\b", r"\bengineer\b"],
    "exclude": [r"\bsenior\b", r"\bstaff\b", r"\bprincipal\b", r"\blead\b",
                r"\bmanager\b", r"\bdirector\b", r"\bsr\.?\b", r"\bhead of\b"],
    "location_hints": [r"remote", r"remoto", r"latam", r"americas",
                       r"costa rica", r"anywhere", r"heredia", r"san jos[eé]"],
    # Words that are technical on their own, used to rescue a posting whose ATS
    # category isn't technical. `software` is left out on purpose: "Software
    # Contract Negotiator" is a procurement role. See jobbot/filters.py.
    "strong_include": [r"\bengineer\b", r"\bdeveloper\b", r"\bdev\b",
                       r"\bprogrammer\b", r"\barchitect\b", r"\bscientist\b",
                       r"\bsre\b", r"\bdevops\b", r"\bqa\b", r"quality assurance",
                       r"\btester\b", r"\btesting\b", r"\btest\b", r"\bsdet\b",
                       r"\bverification\b", r"\bselenium\b", r"\bcypress\b",
                       r"\bappium\b", r"\bjmeter\b",
                       r"\bautomation\b", r"\bcloud\b", r"\bcyber",
                       r"\bdatabase\b", r"\bdba\b", r"\bmachine learning\b",
                       r"\bback.?end\b", r"\bfront.?end\b", r"\bfull.?stack\b",
                       r"\bsysadmin\b", r"\bhelp.?desk\b", r"\bnetwork\b",
                       r"\bservicenow\b", r"\bitil\b", r"\bm365\b"],
    "nontech_categories": [r"accounting", r"finance", r"sourcing", r"procurement",
                           r"human resources", r"talent", r"administration",
                           r"workplace", r"\bsales\b", r"customer",
                           r"manufacturing", r"supply chain", r"business operations",
                           r"legal", r"marketing"],
}


def load_config(path):
    """Reads sources.yaml. If it doesn't exist, runs with the defaults above and
    no sources (better that than blowing up in the cron)."""
    if not Path(path).exists():
        log.warning("%s not found — no sources to check", path)
        return [], DEFAULT_FILTERS

    with open(path, encoding="utf-8") as fh:
        cfg = yaml.safe_load(fh) or {}

    sources = cfg.get("sources") or []
    filters = dict(DEFAULT_FILTERS)
    # `location_hints: []` is a valid choice (don't filter by location), so any
    # key that's present is honored, even if it comes in empty.
    for key, value in (cfg.get("filters") or {}).items():
        if key in filters and value is not None:
            filters[key] = value

    return sources, filters


def source_label(src):
    """Short name of a source, for logs and for the --source flag."""
    return src.get("name") or src.get("company") or src.get("tenant") or src["type"]
