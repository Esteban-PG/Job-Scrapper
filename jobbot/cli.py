"""
Orquestador: junta las cuatro piezas y decide qué se notifica.

Por cada fuente configurada: trae las vacantes (fetchers), descarta las ya
vistas (storage), filtra por título/ubicación (filters) y avisa (notify).
"""

import argparse
import logging
import time

from .config import (CONFIG_PATH, DB_PATH, NOTIFY_PAUSE, SOURCE_PAUSE, TG_CHAT,
                     TG_TOKEN, load_config, source_label)
from .fetchers import FETCHERS
from .filters import compile_filters, matches
from .notify import as_plain_text, format_message, notify
from .storage import already_seen, init_db, is_empty, mark_seen

log = logging.getLogger("jobbot")


def run_source(src, con, rx, first_run, dry_run):
    """Procesa una fuente. Devuelve (total, nuevas, notificadas)."""
    label = source_label(src)
    fetcher = FETCHERS.get(src["type"])
    if fetcher is None:
        raise KeyError(f"tipo de fuente desconocido: {src['type']!r}")

    jobs = fetcher(src)
    new_jobs = [j for j in jobs if not already_seen(con, j["id"])]

    if first_run:
        # Primera corrida: llenamos la base con todo pero NO notificamos, o el
        # bot arranca vomitando 40 vacantes viejas.
        if not dry_run:
            mark_seen(con, [j["id"] for j in new_jobs])
        log.info("%-18s %3d vacantes · %3d nuevas · sembrando (sin notificar)",
                 label, len(jobs), len(new_jobs))
        return len(jobs), len(new_jobs), 0

    to_notify = [j for j in new_jobs if matches(j, rx)]
    # Las que no pasan el filtro se marcan igual: ya las evaluamos, no hay que
    # volver a mirarlas nunca.
    notify_ids = {j["id"] for j in to_notify}
    settled = [j["id"] for j in new_jobs if j["id"] not in notify_ids]
    notified = 0

    for job in to_notify:
        if dry_run:
            print(as_plain_text(format_message(job)))
            notified += 1
            continue
        if notify(job):
            settled.append(job["id"])
            notified += 1
        time.sleep(NOTIFY_PAUSE)

    if not dry_run:
        mark_seen(con, settled)

    log.info("%-18s %3d vacantes · %3d nuevas · %3d notificadas",
             label, len(jobs), len(new_jobs), notified)
    return len(jobs), len(new_jobs), notified


def main():
    ap = argparse.ArgumentParser(description="Bot de alertas de empleo")
    ap.add_argument("--dry-run", action="store_true",
                    help="imprime en vez de notificar y no toca la base")
    ap.add_argument("--source", metavar="NOMBRE",
                    help="corre solo las fuentes cuyo tipo o nombre coincida")
    ap.add_argument("--config", default=CONFIG_PATH, help="ruta al sources.yaml")
    ap.add_argument("-v", "--verbose", action="store_true", help="logging DEBUG")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )

    sources, filters = load_config(args.config)
    rx = compile_filters(filters)

    if args.source:
        needle = args.source.lower()
        sources = [s for s in sources
                   if needle in (s.get("type", "") + " " + source_label(s)).lower()]
        if not sources:
            log.error("ninguna fuente coincide con %r", args.source)
            return 1

    if not sources:
        log.error("no hay fuentes configuradas en %s", args.config)
        return 1

    con = init_db(DB_PATH)
    first_run = is_empty(con)

    if first_run:
        log.info("base vacía: primera corrida, se siembra sin notificar")
    if args.dry_run:
        log.info("modo dry-run: no se notifica ni se escribe la base")
    if not (TG_TOKEN and TG_CHAT):
        log.warning("sin TELEGRAM_TOKEN/TELEGRAM_CHAT_ID: las vacantes van a stdout")

    totals = {"jobs": 0, "new": 0, "notified": 0}
    failed = []

    for i, src in enumerate(sources):
        label = source_label(src)
        try:
            jobs, new, notified = run_source(src, con, rx, first_run, args.dry_run)
            totals["jobs"] += jobs
            totals["new"] += new
            totals["notified"] += notified
        except Exception as exc:
            # Una fuente caída no puede tumbar la corrida entera.
            failed.append(label)
            log.error("%-18s falló: %s: %s", label, type(exc).__name__, exc)

        if i < len(sources) - 1:
            time.sleep(SOURCE_PAUSE)

    con.close()

    log.info("total: %d vacantes · %d nuevas · %d notificadas · %d/%d fuentes ok",
             totals["jobs"], totals["new"], totals["notified"],
             len(sources) - len(failed), len(sources))
    if failed:
        log.warning("fuentes con error: %s", ", ".join(failed))

    # Si TODAS fallaron, salimos en error para que se note en el cron/Actions.
    return 1 if failed and len(failed) == len(sources) else 0
