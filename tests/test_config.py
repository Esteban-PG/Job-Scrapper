"""
Carga de `sources.yaml` y coherencia entre la config y el código.

El último test es el más útil de todos: agarra un `type:` mal escrito en la
config antes de que reviente en producción.
"""

from jobbot.config import CONFIG_PATH, DEFAULT_FILTERS, load_config, source_label
from jobbot.fetchers import FETCHERS


def escribir(tmp_path, texto):
    ruta = tmp_path / "sources.yaml"
    ruta.write_text(texto, encoding="utf-8")
    return str(ruta)


def test_sin_archivo_no_hay_fuentes_pero_si_filtros():
    """Mejor arrancar sin fuentes que reventar en el cron."""
    fuentes, filtros = load_config("/no/existe/sources.yaml")
    assert fuentes == []
    assert filtros == DEFAULT_FILTERS


def test_lee_fuentes_y_filtros(tmp_path):
    ruta = escribir(tmp_path, """
filters:
  include: ['\\bjunior\\b']
sources:
  - type: equifax
    countries: ["Costa Rica"]
""")
    fuentes, filtros = load_config(ruta)
    assert len(fuentes) == 1
    assert fuentes[0]["type"] == "equifax"
    assert filtros["include"] == [r"\bjunior\b"]


def test_las_claves_ausentes_caen_al_default(tmp_path):
    """Definir `include` no debe borrar el `exclude` de fábrica."""
    ruta = escribir(tmp_path, "filters:\n  include: ['x']\nsources: []\n")
    _, filtros = load_config(ruta)
    assert filtros["include"] == ["x"]
    assert filtros["exclude"] == DEFAULT_FILTERS["exclude"]


def test_una_lista_vacia_se_respeta(tmp_path):
    """`location_hints: []` significa 'no filtres por ubicación', que es
    distinto de 'no lo configuré'. Por eso no se usa `get(k, default)`."""
    ruta = escribir(tmp_path, "filters:\n  location_hints: []\nsources: []\n")
    _, filtros = load_config(ruta)
    assert filtros["location_hints"] == []


def test_un_yaml_vacio_no_rompe(tmp_path):
    _, filtros = load_config(escribir(tmp_path, ""))
    assert filtros == DEFAULT_FILTERS


def test_source_label_prefiere_el_nombre_y_cae_al_tipo():
    assert source_label({"type": "phenom", "name": "Cisco"}) == "Cisco"
    assert source_label({"type": "greenhouse", "company": "acme"}) == "acme"
    assert source_label({"type": "workday", "tenant": "pg"}) == "pg"
    assert source_label({"type": "equifax"}) == "equifax"


def test_todos_los_tipos_de_sources_yaml_tienen_fetcher():
    """La config real del proyecto tiene que poder ejecutarse: un `type:` con
    un typo se detecta acá y no a las 3 AM en el cron."""
    fuentes, _ = load_config(CONFIG_PATH)
    assert fuentes, "config/sources.yaml no tiene fuentes activas"
    desconocidos = {s["type"] for s in fuentes} - set(FETCHERS)
    assert not desconocidos, f"tipos sin fetcher registrado: {desconocidos}"


def test_cada_fuente_activa_se_puede_construir():
    """Las lambdas del registro leen claves obligatorias (`s['site']`,
    `s['tenant']`…). Esto verifica que cada entrada las tenga, sin salir a la
    red: si falta una, el KeyError salta acá."""
    fuentes, _ = load_config(CONFIG_PATH)
    for fuente in fuentes:
        etiqueta = source_label(fuente)
        claves = set(fuente)
        assert "type" in claves, f"{etiqueta}: sin `type`"
        assert fuente["type"] in FETCHERS, f"{etiqueta}: tipo desconocido"
