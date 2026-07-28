"""
Orchestrator: wires the four pieces together and decides what gets notified.

For each configured source: fetch the postings (fetchers), drop the ones already
seen (storage), filter by title/location (filters) and alert (notify).
"""

import argparse
import logging
import time

from .config import (CONFIG_PATH, DB_PATH, FAIL_ALERT_AFTER, NOTIFY_PAUSE,
                     SOURCE_PAUSE, TG_CHAT, TG_TOKEN, load_config, source_label)
from .fetchers import FETCHERS
from .filters import compile_filters, matches
from .notify import (as_plain_text, format_health_message, format_message,
                     notify, send)
from .storage import (already_seen, init_db, is_empty, mark_seen,
                      record_failure, record_success)

log = logging.getLogger("jobbot")


def run_source(src, con, rx, first_run, dry_run):
    """Processes one source. Returns (total, new, notified)."""
    label = source_label(src)
    fetcher = FETCHERS.get(src["type"])
    if fetcher is None:
        raise KeyError(f"unknown source type: {src['type']!r}")

    jobs = fetcher(src)
    new_jobs = [j for j in jobs if not already_seen(con, j["id"])]

    if first_run:
        # First run: we fill the database with everything but do NOT notify, or
        # the bot starts by vomiting 40 old postings.
        if not dry_run:
            mark_seen(con, [j["id"] for j in new_jobs])
        log.info("%-18s %3d jobs · %3d new · seeding (no notifications)",
                 label, len(jobs), len(new_jobs))
        return len(jobs), len(new_jobs), 0

    to_notify = [j for j in new_jobs if matches(j, rx)]
    # The ones that don't pass the filter get marked anyway: we already
    # evaluated them, there's no need to ever look at them again.
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

    log.info("%-18s %3d jobs · %3d new · %3d notified",
             label, len(jobs), len(new_jobs), notified)
    return len(jobs), len(new_jobs), notified


def main():
    ap = argparse.ArgumentParser(description="Job alert bot")
    ap.add_argument("--dry-run", action="store_true",
                    help="print instead of notifying and don't touch the database")
    ap.add_argument("--no-seed", action="store_true",
                    help="with an empty database, notify everything that passes "
                         "the filter instead of seeding silently")
    ap.add_argument("--source", metavar="NAME",
                    help="run only the sources whose type or name matches")
    ap.add_argument("--config", default=CONFIG_PATH, help="path to sources.yaml")
    ap.add_argument("-v", "--verbose", action="store_true", help="DEBUG logging")
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
            log.error("no source matches %r", args.source)
            return 1

    if not sources:
        log.error("no sources configured in %s", args.config)
        return 1

    con = init_db(DB_PATH)
    empty_db = is_empty(con)
    # --no-seed disables the first-run shortcut: it's there to see (or receive)
    # the already-published postings once, before the database writes them off as
    # seen. After that run the database is no longer empty and the flag stops
    # having any effect.
    first_run = empty_db and not args.no_seed

    if first_run:
        log.info("empty database: first run, seeding without notifying")
    elif empty_db:
        log.info("empty database and --no-seed: notifying everything that passes the filter")
    if args.dry_run:
        log.info("dry-run mode: nothing is notified and the database isn't written")
    if not (TG_TOKEN and TG_CHAT):
        log.warning("no TELEGRAM_TOKEN/TELEGRAM_CHAT_ID: postings go to stdout")

    totals = {"jobs": 0, "new": 0, "notified": 0}
    failed = []
    broken, recovered = [], []

    for i, src in enumerate(sources):
        label = source_label(src)
        try:
            jobs, new, notified = run_source(src, con, rx, first_run, args.dry_run)
            totals["jobs"] += jobs
            totals["new"] += new
            totals["notified"] += notified
            if not args.dry_run:
                downtime = record_success(con, label)
                if downtime is not None:
                    recovered.append((label, downtime))
        except Exception as exc:
            # A source that's down can't take the whole run with it.
            failed.append(label)
            log.error("%-18s failed: %s: %s", label, type(exc).__name__, exc)
            if not args.dry_run:
                should_alert, fails = record_failure(con, label, FAIL_ALERT_AFTER)
                if should_alert:
                    broken.append((label, f"{type(exc).__name__}: {exc}", fails))

        if i < len(sources) - 1:
            time.sleep(SOURCE_PAUSE)

    # A single alert at the end: if the runner's network goes down, every source
    # fails at once and six messages in a row say no more than one.
    if broken or recovered:
        send(format_health_message(broken, recovered), "health alert")

    con.close()

    log.info("total: %d jobs · %d new · %d notified · %d/%d sources ok",
             totals["jobs"], totals["new"], totals["notified"],
             len(sources) - len(failed), len(sources))
    if failed:
        log.warning("sources with errors: %s", ", ".join(failed))

    # If ALL of them failed, we exit with an error so it shows up in cron/Actions.
    return 1 if failed and len(failed) == len(sources) else 0
