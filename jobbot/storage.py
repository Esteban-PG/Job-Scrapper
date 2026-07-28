"""
Estado que sobrevive entre corridas, en SQLite.

Dos cosas, en dos tablas:

- `seen`: los IDs de vacante ya vistos. Sin esto el bot repetiría las mismas
  vacantes en cada corrida. La clave es el `id` de la vacante, que cada fetcher
  deriva del código de la fuente y por eso es estable entre corridas.
- `source_health`: qué fuentes vienen fallando. Sirve para avisar una sola vez
  que una bolsa se rompió, en vez de en cada corrida o —peor— nunca.
"""

import sqlite3
import time
from pathlib import Path


def init_db(path):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE IF NOT EXISTS seen (id TEXT PRIMARY KEY, ts INTEGER)")
    # `IF NOT EXISTS` también hace de migración: una base vieja (o la caché de
    # Actions, que es la misma base) gana esta tabla sola en la próxima corrida.
    con.execute("""CREATE TABLE IF NOT EXISTS source_health (
                       source   TEXT PRIMARY KEY,
                       fails    INTEGER NOT NULL,   -- corridas seguidas fallando
                       since    INTEGER NOT NULL,   -- desde cuándo
                       notified INTEGER NOT NULL    -- ya se avisó por Telegram
                   )""")
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


def record_failure(con, source, alert_after):
    """Suma una corrida fallada. Devuelve `(avisar, corridas_fallando)`.

    `avisar` es True una sola vez por caída: en la corrida número `alert_after`.
    El umbral existe para que un timeout suelto no dispare un aviso — a `*/30`
    una fuente que falla dos veces seguidas ya lleva media hora caída.
    """
    row = con.execute("SELECT fails, since, notified FROM source_health WHERE source = ?",
                      (source,)).fetchone()
    now = int(time.time())
    fails, since, notified = (row[0] + 1, row[1], row[2]) if row else (1, now, 0)

    avisar = fails >= alert_after and not notified
    con.execute("INSERT OR REPLACE INTO source_health VALUES (?, ?, ?, ?)",
                (source, fails, since, 1 if (avisar or notified) else 0))
    con.commit()
    return avisar, fails


def record_success(con, source):
    """Da la fuente por sana. Devuelve hace cuántos segundos se cayó si hay que
    avisar que volvió, o None (que es el caso normal: nunca estuvo caída, o la
    caída fue tan corta que nunca se avisó)."""
    row = con.execute("SELECT since, notified FROM source_health WHERE source = ?",
                      (source,)).fetchone()
    if row is None:
        return None

    con.execute("DELETE FROM source_health WHERE source = ?", (source,))
    con.commit()
    return int(time.time()) - row[0] if row[1] else None
