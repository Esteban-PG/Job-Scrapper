"""
Filtros de título y ubicación.

La regla que más importa acá es la precedencia: `exclude` gana sobre `include`.
Sin eso, "Senior Software Engineer" pasaría por tener "software".
"""

from jobbot.filters import compile_filters, matches

FILTROS = compile_filters({
    "include": [r"\bjunior\b", r"\bsoftware\b", r"\bqa\b"],
    "exclude": [r"\bsenior\b", r"\bmanager\b"],
    "location_hints": [r"costa rica", r"remote"],
})


def job(title, location="Heredia, Costa Rica"):
    return {"title": title, "location": location}


def test_pasa_si_matchea_include_y_ubicacion():
    assert matches(job("Junior Data Analyst"), FILTROS)


def test_exclude_gana_sobre_include():
    """El caso que motiva la regla: matchea 'software' pero también 'senior'."""
    assert not matches(job("Senior Software Engineer"), FILTROS)


def test_descarta_si_no_matchea_ningun_include():
    assert not matches(job("Warehouse Associate"), FILTROS)


def test_descarta_si_la_ubicacion_no_da_pistas():
    assert not matches(job("Junior Software Engineer", "Bangalore, India"), FILTROS)


def test_es_insensible_a_mayusculas():
    assert matches(job("JUNIOR SOFTWARE ENGINEER", "COSTA RICA"), FILTROS)


def test_matchea_contra_titulo_y_ubicacion_juntos():
    """'remote' suele venir en la ubicación, no en el título."""
    assert matches(job("QA Engineer", "Remote - Americas"), FILTROS)


def test_location_hints_vacio_no_filtra_por_ubicacion():
    """`location_hints: []` es una elección válida: la fuente ya viene filtrada
    desde el origen y no hay que exigir nada del texto."""
    sin_ubicacion = compile_filters({
        "include": [r"\bsoftware\b"], "exclude": [], "location_hints": [],
    })
    assert matches(job("Software Engineer", "Bangalore, India"), sin_ubicacion)


def test_include_vacio_deja_pasar_cualquier_titulo():
    solo_ubicacion = compile_filters({
        "include": [], "exclude": [], "location_hints": [r"costa rica"],
    })
    assert matches(job("Warehouse Associate"), solo_ubicacion)


def test_los_limites_de_palabra_evitan_falsos_positivos():
    """`\\bqa\\b` no debe matchear dentro de otra palabra."""
    assert not matches(job("Aqua Systems Technician"), FILTROS)


def test_tolera_vacantes_sin_ubicacion():
    sin_ubicacion = compile_filters({
        "include": [r"\bsoftware\b"], "exclude": [], "location_hints": [],
    })
    assert matches({"title": "Software Engineer"}, sin_ubicacion)
