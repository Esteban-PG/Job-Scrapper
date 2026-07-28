"""
Las funciones puras de los fetchers: parseo, normalización y traducción.

No hay red acá. Cada caso viene de una rareza real que ya costó una vuelta de
depuración y está documentada en el docstring del módulo correspondiente.
"""

import base64
import json
from xml.etree import ElementTree as ET

import pytest

from jobbot.fetchers import amazon, equifax, phenom, radancy, workday


# --- Amazon ---------------------------------------------------------------

def test_amazon_traduce_el_nombre_de_pais_a_iso2():
    """La API filtra por `CR`, pero sources.yaml habla de 'Costa Rica'."""
    assert amazon._country_code("Costa Rica") == "CR"
    assert amazon._country_code("costa rica") == "CR"
    assert amazon._country_code("méxico") == "MX"


def test_amazon_acepta_el_codigo_ya_escrito():
    assert amazon._country_code("CR") == "CR"
    assert amazon._country_code("cr") == "CR"


def test_amazon_explica_el_error_con_un_pais_desconocido():
    with pytest.raises(ValueError, match="ISO-2"):
        amazon._country_code("Wakanda")


def test_amazon_desenvuelve_los_valores_en_lista():
    """En `fields` cada valor viene envuelto: {"title": ["Designer"]}."""
    assert amazon._first({"title": ["Designer"]}, "title") == "Designer"
    assert amazon._first({"title": []}, "title") == ""
    assert amazon._first({}, "title", "—") == "—"
    assert amazon._first({"title": "plano"}, "title") == "plano"


def test_amazon_no_repite_la_ciudad_cuando_coincide_con_el_estado():
    """'Heredia, Heredia, Costa Rica' se lee mal."""
    campos = {"city": ["Heredia"], "normalizedStateName": ["Heredia"]}
    assert amazon._location(campos, ["Costa Rica"]) == "Heredia, Costa Rica"


def test_amazon_agrega_el_nombre_del_pais_para_el_filtro_de_ubicacion():
    """`normalizedLocation` trae ISO-3 ('CRI'), contra el que
    `location_hints` no puede matchear."""
    campos = {"city": ["San Jose"], "normalizedStateName": ["San Jose"]}
    assert "Costa Rica" in amazon._location(campos, ["Costa Rica"])


def test_amazon_convierte_el_epoch_a_fecha():
    assert amazon._posted({"createdDate": ["1769472000"]}) == "2026-01-27"


def test_amazon_tolera_una_fecha_invalida():
    assert amazon._posted({"createdDate": ["no es fecha"]}) == ""
    assert amazon._posted({}) == ""


# --- Equifax --------------------------------------------------------------

def test_equifax_convierte_la_fecha_del_feed_a_iso():
    assert equifax._iso_date("Thu, 12 Feb 2026 00:00:00 GMT") == "2026-02-12"


def test_equifax_devuelve_la_fecha_cruda_si_no_parsea():
    """`posted` es opcional: no vale romper la corrida por una fecha rara."""
    assert equifax._iso_date("ayer") == "ayer"


def test_equifax_arma_la_ubicacion_sin_comas_sueltas():
    job = ET.fromstring(
        "<job><city>Heredia</city><state></state><country>Costa Rica</country></job>")
    assert equifax._location(job) == "Heredia, Costa Rica"


def test_equifax_no_repite_ciudad_y_estado_iguales():
    job = ET.fromstring(
        "<job><city>Heredia</city><state>Heredia</state>"
        "<country>Costa Rica</country></job>")
    assert equifax._location(job) == "Heredia, Costa Rica"


# --- Phenom ---------------------------------------------------------------

def jwt_falso(payload):
    """PLAY_SESSION tiene forma de JWT: header.payload.firma, y el payload va
    en base64url sin padding."""
    crudo = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return f"header.{crudo.rstrip('=')}.firma"


def test_phenom_saca_el_csrf_de_adentro_del_cookie():
    """El token no viaja en una cabecera: está dentro del PLAY_SESSION."""
    cookie = jwt_falso({"data": {"csrfToken": "abc123"}})
    assert phenom._csrf_from_play_session(cookie) == "abc123"


def test_phenom_devuelve_none_si_el_cookie_no_sirve():
    assert phenom._csrf_from_play_session("cualquier cosa") is None
    assert phenom._csrf_from_play_session(jwt_falso({"data": {}})) is None


def test_phenom_anota_las_vacantes_multi_ubicacion():
    """HPE publica puestos con sede en Texas que también se toman desde
    Heredia. Sin la anotación, `location_hints` los descartaría en silencio."""
    vacante = {"cityStateCountry": "Austin, Texas, United States",
               "country": "United States",
               "multi_location": ["Austin", "Heredia"]}
    ubicacion = phenom._location(vacante, ["Costa Rica"])
    assert "Costa Rica" in ubicacion
    assert "+1 ubicación" in ubicacion


def test_phenom_no_anota_si_la_sede_principal_ya_es_del_pais():
    vacante = {"cityStateCountry": "Heredia, Costa Rica",
               "country": "Costa Rica",
               "multi_location": ["Heredia", "San Jose"]}
    assert phenom._location(vacante, ["Costa Rica"]) == "Heredia, Costa Rica"


def test_phenom_encuentra_las_vacantes_aunque_cambie_la_estructura():
    """La respuesta cambia de forma entre versiones de Phenom."""
    assert phenom._find_jobs_list({"a": {"b": {"jobs": [{"id": 1}]}}}) == [{"id": 1}]
    assert phenom._find_jobs_list({"sin": "nada"}) == []


def test_phenom_usa_la_categoria_multiple_si_no_hay_simple():
    assert phenom._category({"category": "Engineering"}) == "Engineering"
    assert phenom._category({"multi_category": ["IT", "Data"]}) == "IT"
    assert phenom._category({}) == ""


# --- Radancy --------------------------------------------------------------

def test_radancy_conoce_el_nodo_geografico_de_costa_rica():
    geo = radancy._geo("Costa Rica")
    assert geo["path"] and geo["lat"] and geo["lon"]


def test_radancy_falla_claro_con_un_pais_que_no_tiene():
    """Mejor un error explícito que mandar el request sin ubicación, porque
    la API devolvería el catálogo global sin avisar."""
    with pytest.raises(ValueError, match="COUNTRY_GEO"):
        radancy._geo("Wakanda")


def test_radancy_manda_los_cinco_campos_de_ubicacion_juntos():
    """Con una combinación parcial la API no falla: devuelve el catálogo
    global. Los cinco van o no va ninguno."""
    params = radancy._params("49841", "Costa Rica", radancy._geo("Costa Rica"),
                             1, 50, "")
    for campo in ("Location", "LocationPath", "Latitude", "Longitude", "LocationType"):
        assert params.get(campo) not in (None, "")


# --- Workday --------------------------------------------------------------

def test_workday_resuelve_el_facet_de_pais_desde_la_respuesta():
    """Los IDs son GUIDs opacos y distintos en cada tenant: se resuelven
    contra el catálogo que viene en la propia respuesta."""
    payload = {"facets": [{"values": [{
        "facetParameter": "locationCountry",
        "values": [{"descriptor": "Costa Rica", "id": "99abe7e6"},
                   {"descriptor": "Mexico", "id": "otro"}],
    }]}]}
    assert workday._resolve_country_facets(payload, ["Costa Rica"]) == ["99abe7e6"]


def test_workday_no_encuentra_facet_para_un_pais_ausente():
    payload = {"facets": [{"values": [{
        "facetParameter": "locationCountry",
        "values": [{"descriptor": "Mexico", "id": "x"}],
    }]}]}
    assert workday._resolve_country_facets(payload, ["Costa Rica"]) == []


def test_workday_saca_el_codigo_de_vacante_de_bulletfields():
    assert workday._req_id({"bulletFields": ["R000154991"]}) == "R000154991"


def test_workday_cae_al_externalpath_si_no_hay_bulletfields():
    """El fallback también tiene que dar un ID estable."""
    posting = {"bulletFields": [], "externalPath": "/job/Heredia/Analyst_R000154991"}
    assert workday._req_id(posting) == "Analyst_R000154991"
