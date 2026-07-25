"""
Dedupe: SQLite con los IDs de vacante ya vistos.

Sin esto el bot repetiría las mismas vacantes en cada corrida. La clave es el
`id` de la vacante, que cada fetcher deriva del código de la fuente y por eso es
estable entre corridas.
"""

import sqlite3
import time
from pathlib import Path


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, ts INTEGER)")
    con.commit()
    return con


def is_empty(con):
    """Base vacía = primera corrida = se siembra sin notificar."""
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
