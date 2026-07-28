"""
Formato de los mensajes de Telegram.

No se prueba el envío: `send()` sale a la red y estos tests corren sin
credenciales. Lo que se prueba es lo que se le manda a Telegram, que es donde
estuvieron los bugs reales — un título con `&` rompía el parser y el envío
fallaba con HTTP 400.
"""

from jobbot.notify import (as_plain_text, format_health_message,
                           format_message, humanize)

LIMITE_TELEGRAM = 4096


# --- vacantes -------------------------------------------------------------

def test_el_mensaje_lleva_titulo_ubicacion_y_enlace():
    msg = format_message({
        "title": "Junior Data Analyst",
        "location": "Heredia, Costa Rica",
        "source": "Equifax",
        "url": "https://careers.equifax.com/j/1",
    })
    assert "Junior Data Analyst" in msg
    assert "Heredia, Costa Rica" in msg
    assert "Equifax" in msg
    assert "https://careers.equifax.com/j/1" in msg


def test_escapa_los_titulos_que_rompian_el_parser():
    """`FP&A Analyst` es un título real: sin escapar, Telegram devuelve 400."""
    msg = format_message({"title": "FP&A Analyst", "url": "", "source": ""})
    assert "FP&amp;A" in msg
    assert "FP&A " not in msg


def test_escapa_html_incrustado_en_el_titulo():
    msg = format_message({"title": "Dev <script>alert(1)</script>",
                          "url": "", "source": ""})
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


def test_tolera_una_vacante_sin_campos_opcionales():
    msg = format_message({})
    assert "Sin título" in msg


def test_as_plain_text_deja_el_mensaje_legible_en_consola():
    """Es lo que se imprime con --dry-run y sin credenciales."""
    plano = as_plain_text(format_message({
        "title": "FP&A Analyst", "location": "Heredia", "source": "Moody's",
        "url": "https://x.com/1",
    }))
    assert "FP&A Analyst" in plano
    assert "<b>" not in plano and "&amp;" not in plano


# --- duraciones -----------------------------------------------------------

def test_humanize_redondea_hacia_unidades_legibles():
    assert humanize(30) == "1 min"       # nunca "0 min"
    assert humanize(2700) == "45 min"
    assert humanize(7200) == "2 h"
    assert humanize(86400) == "1 día"    # singular
    assert humanize(172800) == "2 días"


# --- avisos de fuente caída ----------------------------------------------

def test_aviso_de_una_sola_fuente_caida():
    msg = format_health_message([("moodys", "HTTPError: 503", 2)], [])
    assert "Fuente caída" in as_plain_text(msg)
    assert "moodys" in msg
    assert "503" in msg
    assert "2 corridas" in msg


def test_titulo_en_plural_con_varias_fuentes():
    msg = as_plain_text(format_health_message(
        [("moodys", "err", 2), ("hpe", "err", 2)], []))
    assert "2 fuentes caídas" in msg


def test_aviso_de_recuperacion_incluye_cuanto_estuvo_caida():
    msg = as_plain_text(format_health_message([], [("equifax", 7200)]))
    assert "Fuente recuperada" in msg
    assert "equifax" in msg
    assert "2 h" in msg


def test_caidas_y_recuperaciones_van_en_el_mismo_mensaje():
    msg = as_plain_text(format_health_message(
        [("moodys", "err", 2)], [("equifax", 3600)]))
    assert "moodys" in msg and "equifax" in msg


def test_el_error_se_recorta():
    """Una respuesta de error puede traer un HTML entero."""
    msg = format_health_message([("moodys", "X" * 5000, 2)], [])
    assert len(msg) < 500


def test_el_error_se_escapa_como_html():
    """Un error con HTML adentro rompería el mensaje entero."""
    msg = format_health_message(
        [("moodys", "<html><body>500</body></html>", 2)], [])
    assert "<html>" not in msg
    assert "&lt;html&gt;" in msg


def test_muchas_fuentes_caidas_no_pasan_el_limite_de_telegram():
    """Si se cae la red del runner fallan todas juntas, y es justo cuando no
    querés perder el aviso por un 400."""
    rotas = [(f"fuente-{i}", "HTTPError: 503 " + "x" * 200, 2) for i in range(15)]
    msg = format_health_message(rotas, [])
    assert len(msg) < LIMITE_TELEGRAM
    assert "y 7 más" in as_plain_text(msg)
    assert "fuente-14" in msg          # las que no se detallan igual se nombran
