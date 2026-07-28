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

MAX_DETALLADAS = 8    # fuentes caídas que se listan con su error, ver format_health_message


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
    for tag in ("<b>", "</b>", "<code>", "</code>"):
        message = message.replace(tag, "")
    return html.unescape(message)


def humanize(seconds):
    """Duración aproximada para los avisos ('40 min', '3 h', '2 días')."""
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    days = seconds // 86400
    return f"{days} día" if days == 1 else f"{days} días"


def format_health_message(broken, recovered):
    """Aviso de fuentes caídas y recuperadas.

    `broken` son tuplas (fuente, error, corridas_fallando) y `recovered`
    (fuente, segundos_caída). Va todo en un solo mensaje: si se cae la red del
    runner fallan las 6 fuentes a la vez y no tiene sentido mandar 6 avisos.
    """
    esc = html.escape
    partes = []

    if broken:
        titulo = "Fuente caída" if len(broken) == 1 else f"{len(broken)} fuentes caídas"
        lineas = [f"🔴 <b>{titulo}</b>"]
        # Telegram corta en 4096 caracteres y rechaza el mensaje entero si se
        # pasa. Con muchas fuentes rotas a la vez importa más saber cuáles que
        # leer el error de cada una, así que se listan las primeras y se cuenta
        # el resto: el detalle completo siempre queda en el log de la corrida.
        for fuente, error, fallas in broken[:MAX_DETALLADAS]:
            # El error puede traer un HTML entero de respuesta: se recorta.
            detalle = " ".join(str(error).split())[:180]
            lineas.append(f"\n<b>{esc(fuente)}</b> · {fallas} corridas fallando\n"
                          f"<code>{esc(detalle)}</code>")
        sobran = len(broken) - MAX_DETALLADAS
        if sobran > 0:
            resto = ", ".join(esc(f) for f, _, _ in broken[MAX_DETALLADAS:])
            lineas.append(f"\n\n…y {sobran} más: {resto}")
        partes.append("".join(lineas))

    if recovered:
        lineas = ["🟩 <b>Fuente recuperada</b>" if len(recovered) == 1
                  else f"🟩 <b>{len(recovered)} fuentes recuperadas</b>"]
        for fuente, caida in recovered:
            lineas.append(f"\n<b>{esc(fuente)}</b> · volvió después de {humanize(caida)}")
        partes.append("".join(lineas))

    return "\n\n".join(partes)


def send(text, what=""):
    """Manda un mensaje ya formateado. Devuelve True si se entregó (o si estamos
    sin Telegram configurado, donde 'entregar' es imprimirlo)."""
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
        log.error("Telegram falló%s: %s", f" para {what}" if what else "", exc)
        return False


def notify(job):
    """Manda la vacante. Si Telegram falla devuelve False y la vacante NO se
    marca como vista: se reintenta en la próxima corrida."""
    return send(format_message(job), job.get("id"))
