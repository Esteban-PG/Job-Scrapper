"""
Loading `sources.yaml` and consistency between the config and the code.

The last test is the most useful of them all: it catches a misspelled `type:` in
the config before it blows up in production.
"""

from jobbot.config import CONFIG_PATH, DEFAULT_FILTERS, load_config, source_label
from jobbot.fetchers import FETCHERS


def write(tmp_path, text):
    path = tmp_path / "sources.yaml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_no_file_means_no_sources_but_still_filters():
    """Better to start with no sources than to blow up in the cron."""
    sources, filters = load_config("/does/not/exist/sources.yaml")
    assert sources == []
    assert filters == DEFAULT_FILTERS


def test_reads_sources_and_filters(tmp_path):
    path = write(tmp_path, """
filters:
  include: ['\\bjunior\\b']
sources:
  - type: equifax
    countries: ["Costa Rica"]
""")
    sources, filters = load_config(path)
    assert len(sources) == 1
    assert sources[0]["type"] == "equifax"
    assert filters["include"] == [r"\bjunior\b"]


def test_absent_keys_fall_back_to_the_default(tmp_path):
    """Defining `include` must not wipe out the factory `exclude`."""
    path = write(tmp_path, "filters:\n  include: ['x']\nsources: []\n")
    _, filters = load_config(path)
    assert filters["include"] == ["x"]
    assert filters["exclude"] == DEFAULT_FILTERS["exclude"]


def test_an_empty_list_is_honored(tmp_path):
    """`location_hints: []` means 'don't filter by location', which is different
    from 'I didn't configure it'. That's why `get(k, default)` isn't used."""
    path = write(tmp_path, "filters:\n  location_hints: []\nsources: []\n")
    _, filters = load_config(path)
    assert filters["location_hints"] == []


def test_an_empty_yaml_does_not_break(tmp_path):
    _, filters = load_config(write(tmp_path, ""))
    assert filters == DEFAULT_FILTERS


def test_source_label_prefers_the_name_and_falls_back_to_the_type():
    assert source_label({"type": "phenom", "name": "Cisco"}) == "Cisco"
    assert source_label({"type": "greenhouse", "company": "acme"}) == "acme"
    assert source_label({"type": "workday", "tenant": "pg"}) == "pg"
    assert source_label({"type": "equifax"}) == "equifax"


def test_every_type_in_sources_yaml_has_a_fetcher():
    """The project's real config has to be runnable: a `type:` with a typo is
    caught here and not at 3 AM in the cron."""
    sources, _ = load_config(CONFIG_PATH)
    assert sources, "config/sources.yaml has no active sources"
    unknown = {s["type"] for s in sources} - set(FETCHERS)
    assert not unknown, f"types with no registered fetcher: {unknown}"


def test_every_active_source_can_be_built():
    """The registry's lambdas read required keys (`s['site']`, `s['tenant']`…).
    This verifies each entry has them, without hitting the network: if one is
    missing, the KeyError surfaces here."""
    sources, _ = load_config(CONFIG_PATH)
    for source in sources:
        label = source_label(source)
        keys = set(source)
        assert "type" in keys, f"{label}: no `type`"
        assert source["type"] in FETCHERS, f"{label}: unknown type"
