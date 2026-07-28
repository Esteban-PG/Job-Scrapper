"""
Title and location filters.

The rule that matters most here is precedence: `exclude` beats `include`.
Without that, "Senior Software Engineer" would pass for having "software".
"""

from jobbot.filters import compile_filters, matches

FILTERS = compile_filters({
    "include": [r"\bjunior\b", r"\bsoftware\b", r"\bqa\b"],
    "exclude": [r"\bsenior\b", r"\bmanager\b"],
    "location_hints": [r"costa rica", r"remote"],
})


def job(title, location="Heredia, Costa Rica"):
    return {"title": title, "location": location}


def test_passes_if_it_matches_include_and_location():
    assert matches(job("Junior Data Analyst"), FILTERS)


def test_exclude_beats_include():
    """The case that motivates the rule: matches 'software' but also 'senior'."""
    assert not matches(job("Senior Software Engineer"), FILTERS)


def test_discards_if_it_matches_no_include():
    assert not matches(job("Warehouse Associate"), FILTERS)


def test_discards_if_the_location_gives_no_hints():
    assert not matches(job("Junior Software Engineer", "Bangalore, India"), FILTERS)


def test_is_case_insensitive():
    assert matches(job("JUNIOR SOFTWARE ENGINEER", "COSTA RICA"), FILTERS)


def test_matches_against_title_and_location_together():
    """'remote' usually comes in the location, not in the title."""
    assert matches(job("QA Engineer", "Remote - Americas"), FILTERS)


def test_empty_location_hints_does_not_filter_by_location():
    """`location_hints: []` is a valid choice: the source already comes filtered
    at the origin and there's nothing to demand from the text."""
    no_location = compile_filters({
        "include": [r"\bsoftware\b"], "exclude": [], "location_hints": [],
    })
    assert matches(job("Software Engineer", "Bangalore, India"), no_location)


def test_empty_include_lets_any_title_through():
    location_only = compile_filters({
        "include": [], "exclude": [], "location_hints": [r"costa rica"],
    })
    assert matches(job("Warehouse Associate"), location_only)


def test_word_boundaries_avoid_false_positives():
    """`\\bqa\\b` must not match inside another word."""
    assert not matches(job("Aqua Systems Technician"), FILTERS)


def test_tolerates_postings_without_a_location():
    no_location = compile_filters({
        "include": [r"\bsoftware\b"], "exclude": [], "location_hints": [],
    })
    assert matches({"title": "Software Engineer"}, no_location)
