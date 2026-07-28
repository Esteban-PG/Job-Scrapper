"""
State that survives between runs, in SQLite.

Two things, in two tables:

- `seen`: the posting IDs already seen. Without this the bot would repeat the
  same postings on every run. The key is the posting's `id`, which each fetcher
  derives from the source's own code and is therefore stable between runs.
- `source_health`: which sources have been failing. It's what lets us alert
  once that a board broke, instead of on every run or — worse — never.
"""

import sqlite3
import time
from pathlib import Path


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, ts INTEGER)")
    # `IF NOT EXISTS` doubles as a migration: an old database (or the Actions
    # cache, which is the same database) gains this table on its own next run.
    con.execute("""CREATE TABLE IF NOT EXISTS source_health (
                       source   TEXT PRIMARY KEY,
                       fails    INTEGER NOT NULL,   -- consecutive failed runs
                       since    INTEGER NOT NULL,   -- failing since when
                       notified INTEGER NOT NULL    -- already alerted on Telegram
                   )""")
    con.commit()
    return con


def is_empty(con):
    """Empty database = first run = seed without notifying."""
    return con.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 0


def already_seen(con, job_id):
    return con.execute("SELECT 1 FROM seen WHERE id = ?", (job_id,)).fetchone() is not None


def mark_seen(con, job_ids):
    if not job_ids:
        return
    now = int(time.time())
    con.executemany("INSERT OR IGNORE INTO seen VALUES (?, ?)",
                    [(jid, now) for jid in job_ids])
    con.commit()


def record_failure(con, source, alert_after):
    """Adds one failed run. Returns `(should_alert, failing_runs)`.

    `should_alert` is True exactly once per outage: on run number `alert_after`.
    The threshold exists so that a one-off timeout doesn't fire an alert — at
    `*/30`, a source that fails twice in a row has already been down half an
    hour.
    """
    row = con.execute("SELECT fails, since, notified FROM source_health WHERE source = ?",
                      (source,)).fetchone()
    now = int(time.time())
    fails, since, notified = (row[0] + 1, row[1], row[2]) if row else (1, now, 0)

    should_alert = fails >= alert_after and not notified
    con.execute("INSERT OR REPLACE INTO source_health VALUES (?, ?, ?, ?)",
                (source, fails, since, 1 if (should_alert or notified) else 0))
    con.commit()
    return should_alert, fails


def record_success(con, source):
    """Marks the source as healthy. Returns how many seconds ago it went down if
    we have to announce that it's back, or None (which is the normal case: it
    was never down, or the outage was so short that nothing was ever
    announced)."""
    row = con.execute("SELECT since, notified FROM source_health WHERE source = ?",
                      (source,)).fetchone()
    if row is None:
        return None

    con.execute("DELETE FROM source_health WHERE source = ?", (source,))
    con.commit()
    return int(time.time()) - row[0] if row[1] else None
