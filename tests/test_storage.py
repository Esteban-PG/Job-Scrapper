"""
Estado persistente: dedupe (`seen`) y salud de las fuentes (`source_health`).

Cada test arma su propia base en un archivo temporal, así que nunca tocan
`data/seen_jobs.db`.
"""

import sqlite3

import pytest

from jobbot.storage import (already_seen, init_db, is_empty, mark_seen,
                            record_failure, record_success)


@pytest.fixture
def con(tmp_path):
    conexion = init_db(tmp_path / "test.db")
    yield conexion
    conexion.close()


# --- dedupe ---------------------------------------------------------------

def test_base_nueva_esta_vacia(con):
    """Base vacía es lo que el orquestador lee como 'primera corrida'."""
    assert is_empty(con)


def test_marcar_una_vacante_la_deja_vista(con):
    assert not already_seen(con, "efx-J001")
    mark_seen(con, ["efx-J001"])
    assert already_seen(con, "efx-J001")
    assert not is_empty(con)


def test_marcar_dos_veces_no_rompe(con):
    """`mark_seen` corre con IDs que pueden ya estar: no debe reventar por la
    PRIMARY KEY."""
    mark_seen(con, ["efx-J001", "efx-J002"])
    mark_seen(con, ["efx-J001", "efx-J003"])
    assert con.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 3


def test_marcar_lista_vacia_no_hace_nada(con):
    mark_seen(con, [])
    assert is_empty(con)


def test_los_ids_no_se_confunden_entre_fuentes(con):
    """El prefijo de fuente es lo que evita que dos bolsas colisionen."""
    mark_seen(con, ["pg-R000151170"])
    assert not already_seen(con, "wd-pg-R000151170")


def test_init_db_es_idempotente(tmp_path):
    """Se llama en cada corrida sobre la misma base."""
    ruta = tmp_path / "test.db"
    primera = init_db(ruta)
    mark_seen(primera, ["efx-J001"])
    primera.close()

    segunda = init_db(ruta)
    assert already_seen(segunda, "efx-J001")
    segunda.close()


def test_init_db_agrega_source_health_a_una_base_vieja(tmp_path):
    """Migración: la caché de Actions guarda bases creadas antes de que
    existiera `source_health`. La tabla tiene que aparecer sola."""
    ruta = tmp_path / "vieja.db"
    vieja = sqlite3.connect(ruta)
    vieja.execute("CREATE TABLE seen (id TEXT PRIMARY KEY, ts INTEGER)")
    vieja.execute("INSERT INTO seen VALUES ('efx-J001', 0)")
    vieja.commit()
    vieja.close()

    con = init_db(ruta)
    assert already_seen(con, "efx-J001")          # no se perdió nada
    assert record_failure(con, "equifax", 1) == (True, 1)   # la tabla existe
    con.close()


# --- salud de las fuentes -------------------------------------------------

def test_la_primera_falla_no_avisa(con):
    """Un timeout suelto no debe disparar un aviso."""
    avisar, fallas = record_failure(con, "moodys", 2)
    assert not avisar
    assert fallas == 1


def test_avisa_al_llegar_al_umbral(con):
    record_failure(con, "moodys", 2)
    avisar, fallas = record_failure(con, "moodys", 2)
    assert avisar
    assert fallas == 2


def test_no_repite_el_aviso_mientras_sigue_caida(con):
    """Lo que evita un mensaje cada 30 minutos durante días."""
    record_failure(con, "moodys", 2)
    record_failure(con, "moodys", 2)          # acá avisó
    for _ in range(5):
        avisar, _ = record_failure(con, "moodys", 2)
        assert not avisar


def test_umbral_de_uno_avisa_en_la_primera(con):
    assert record_failure(con, "moodys", 1) == (True, 1)


def test_las_fuentes_se_cuentan_por_separado(con):
    record_failure(con, "moodys", 2)
    avisar, fallas = record_failure(con, "hpe", 2)
    assert not avisar and fallas == 1


def test_una_fuente_sana_no_avisa_recuperacion(con):
    """El caso normal de cada corrida: nunca estuvo caída."""
    assert record_success(con, "moodys") is None


def test_avisa_la_recuperacion_solo_si_habia_avisado_la_caida(con):
    record_failure(con, "moodys", 2)
    record_failure(con, "moodys", 2)          # acá avisó
    caida = record_success(con, "moodys")
    assert caida is not None and caida >= 0


def test_una_caida_corta_se_recupera_en_silencio(con):
    """Falló una vez, no llegó al umbral y volvió: nadie se enteró, y está
    bien que nadie se entere."""
    record_failure(con, "moodys", 2)
    assert record_success(con, "moodys") is None


def test_recuperarse_limpia_el_estado(con):
    """Si no, la próxima caída arrancaría con el contador viejo."""
    record_failure(con, "moodys", 2)
    record_failure(con, "moodys", 2)
    record_success(con, "moodys")

    avisar, fallas = record_failure(con, "moodys", 2)
    assert not avisar and fallas == 1


def test_la_salud_no_ensucia_el_dedupe(con):
    """`is_empty` mira solo `seen`: una fuente caída no debe hacer que el bot
    crea que ya sembró."""
    record_failure(con, "moodys", 2)
    assert is_empty(con)
