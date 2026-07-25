"""
Notificación por Telegram.

Sin `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` el bot no falla: imprime por consola.
Práctico para ajustar filtros sin recibir mensajes.
"""

import html
import logging

import requests

from .config import TG_CHAT, TG_TOKEN

log = logging.getLogger("jobbot")


def format_message(job):
    """HTML en vez de Markdown a propósito: los títulos reales traen paréntesis,
    guiones y `&` ("FP&A Analyst", "Support (French, English)") que rompen el
    parser Markdown de Telegram y hacen fallar el envío con 400."""
    esc = html.escape
    extra = " · ".join(x for x in (job.get("location"), job.get("category")) if x)
    return (
        f"🟢 <b>Nueva vacante</b>\n"
        f"<b>{esc(job.get('title', 'Sin título'))}</b>\n"
        f"{esc(extra or '—')} · {esc(job.get('source', ''))}\n"
        f"{esc(job.get('url', ''))}"
    )


def as_plain_text(message):
    """El mismo mensaje pero legible en consola (sin tags ni entidades HTML)."""
    return html.unescape(message.replace("<b>", "").replace("</b>", ""))


def notify(job):
    """Manda la vacante. Devuelve True si se entregó (o si estamos sin Telegram
    configurado, donde 'entregar' es imprimirla). Si Telegram falla, devuelve
    False y la vacante NO se marca como vista: se reintenta en la próxima corrida."""
    text = format_message(job)

    if not (TG_TOKEN and TG_CHAT):
        print(as_plain_text(text))
        return True

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": False},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        log.error("Telegram falló para %s: %s", job.get("id"), exc)
        return False
