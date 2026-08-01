"""
The pure functions of the fetchers: parsing, normalization and translation.

There's no network here. Every case comes from a real quirk that already cost a
debugging round and is documented in the corresponding module's docstring.
"""

import base64
import json
from xml.etree import ElementTree as ET

import pytest

from jobbot.fetchers import (amazon, ats, bamboohr, eightfold, equifax, ibm,
                             jibe, oraclecloud, phenom, radancy, workday)


# --- Amazon ---------------------------------------------------------------

def test_amazon_translates_the_country_name_to_iso2():
    """The API filters by `CR`, but sources.yaml talks about 'Costa Rica'."""
    assert amazon._country_code("Costa Rica") == "CR"
    assert amazon._country_code("costa rica") == "CR"
    assert amazon._country_code("méxico") == "MX"


def test_amazon_accepts_the_code_already_written_out():
    assert amazon._country_code("CR") == "CR"
    assert amazon._country_code("cr") == "CR"


def test_amazon_explains_the_error_on_an_unknown_country():
    with pytest.raises(ValueError, match="ISO-2"):
        amazon._country_code("Wakanda")


def test_amazon_unwraps_the_values_in_lists():
    """In `fields` each value comes wrapped: {"title": ["Designer"]}."""
    assert amazon._first({"title": ["Designer"]}, "title") == "Designer"
    assert amazon._first({"title": []}, "title") == ""
    assert amazon._first({}, "title", "—") == "—"
    assert amazon._first({"title": "flat"}, "title") == "flat"


def test_amazon_does_not_repeat_the_city_when_it_matches_the_state():
    """'Heredia, Heredia, Costa Rica' reads badly."""
    fields = {"city": ["Heredia"], "normalizedStateName": ["Heredia"]}
    assert amazon._location(fields, ["Costa Rica"]) == "Heredia, Costa Rica"


def test_amazon_adds_the_country_name_for_the_location_filter():
    """`normalizedLocation` carries the ISO-3 ('CRI'), which `location_hints`
    can't match against."""
    fields = {"city": ["San Jose"], "normalizedStateName": ["San Jose"]}
    assert "Costa Rica" in amazon._location(fields, ["Costa Rica"])


def test_amazon_converts_the_epoch_to_a_date():
    assert amazon._posted({"createdDate": ["1769472000"]}) == "2026-01-27"


def test_amazon_tolerates_an_invalid_date():
    assert amazon._posted({"createdDate": ["not a date"]}) == ""
    assert amazon._posted({}) == ""


# --- Equifax --------------------------------------------------------------

def test_equifax_converts_the_feed_date_to_iso():
    assert equifax._iso_date("Thu, 12 Feb 2026 00:00:00 GMT") == "2026-02-12"


def test_equifax_returns_the_raw_date_if_it_does_not_parse():
    """`posted` is optional: not worth breaking the run over an odd date."""
    assert equifax._iso_date("yesterday") == "yesterday"


def test_equifax_builds_the_location_without_stray_commas():
    job = ET.fromstring(
        "<job><city>Heredia</city><state></state><country>Costa Rica</country></job>")
    assert equifax._location(job) == "Heredia, Costa Rica"


def test_equifax_does_not_repeat_an_identical_city_and_state():
    job = ET.fromstring(
        "<job><city>Heredia</city><state>Heredia</state>"
        "<country>Costa Rica</country></job>")
    assert equifax._location(job) == "Heredia, Costa Rica"


# --- Oracle Recruiting Cloud ----------------------------------------------

def test_oracle_location_ids_are_per_source():
    """Verified by crossing them live: Akamai's Costa Rica id returns 0 on
    Oracle's tenant and vice versa. A module-wide table would have handed the
    second tenant the first one's id and quietly returned nothing."""
    assert oraclecloud._location_id(
        "Costa Rica", {"costa rica": "300000000469120"}) == "300000000469120"


def test_oracle_raises_on_a_country_the_source_has_no_id_for():
    """A wrong id returns TotalJobsCount 0, which reads exactly like "this
    company isn't hiring here" — so it has to fail loudly instead."""
    with pytest.raises(ValueError, match="per tenant"):
        oraclecloud._location_id("Wakanda", {"costa rica": "1"})
    with pytest.raises(ValueError):
        oraclecloud._location_id("Costa Rica", None)


def test_oracle_builds_the_finder_syntax():
    """`;` after the finder name, `,` between parameters."""
    finder = oraclecloud._finder("CX_1", "300000000469120", 25, 25)
    assert finder.startswith("findReqs;siteNumber=CX_1,")
    assert "offset=25" in finder and "limit=25" in finder
    assert "selectedLocationsFacet=300000000469120" in finder


def test_oracle_job_url_is_derived_from_the_site_number():
    assert oraclecloud._job_url("https://x.oraclecloud.com", "CX_1", "3578") == \
        "https://x.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_1/job/3578"


# --- Eightfold / PCSX -----------------------------------------------------

def test_eightfold_puts_the_country_last():
    """`locations` reads "Country, State, City" — the opposite of every other
    source — so it has to be flipped into the project's usual shape."""
    assert eightfold._location(
        {"locations": ["Costa Rica, San José, San José"]}) == "San José, Costa Rica"


def test_eightfold_drops_the_multiple_locations_placeholder():
    """Unset levels come back as that literal string. Left in, a posting would
    read "Costa Rica, Multiple Locations, Multiple Locations"."""
    assert eightfold._location(
        {"locations": ["Costa Rica, Multiple Locations, Multiple Locations"]}) \
        == "Costa Rica"


def test_eightfold_tolerates_a_missing_location():
    assert eightfold._location({}) == ""
    assert eightfold._location({"locations": [""]}) == ""


def test_eightfold_revalidates_the_country():
    """Dropping `location` returns the global catalog (1807 postings), so the
    server's filter is never trusted blindly."""
    job = {"locations": ["Costa Rica, San José, San José"]}
    assert eightfold._in_countries(job, ["Costa Rica"])
    assert not eightfold._in_countries(job, ["Mexico"])
    assert eightfold._in_countries(job, [])


def test_eightfold_converts_the_epoch_to_a_date():
    assert eightfold._posted({"postedTs": 1785352757}) == "2026-07-29"
    assert eightfold._posted({}) == ""
    assert eightfold._posted({"postedTs": "not a date"}) == ""


# --- BambooHR -------------------------------------------------------------

JOB_BHR = {"id": "184",
           "jobOpeningName": ".Net/C# Engineer - AA, Remote: Colombia - Costa Rica, Full Time, GP",
           "departmentLabel": "Engineering",
           "location": {"city": None, "state": None},
           "atsLocation": {"country": None, "state": None, "province": None,
                           "city": None},
           "isRemote": None}


def test_bamboohr_reads_the_location_out_of_the_title():
    """Every structured field is null — verified live — so the title is the only
    place the country appears."""
    assert bamboohr._location(JOB_BHR) == "Remote: Colombia - Costa Rica"


def test_bamboohr_falls_back_to_the_structured_fields_when_filled():
    job = {"jobOpeningName": "Backend Engineer",
           "atsLocation": {"city": "Heredia", "state": None, "province": None,
                           "country": "Costa Rica"}}
    assert bamboohr._location(job) == "Heredia, Costa Rica"


def test_bamboohr_filters_the_country_against_the_title():
    """Filtering on `atsLocation.country`, which is the obvious thing to write,
    would return zero postings forever and look like a company not hiring."""
    assert bamboohr._in_countries(JOB_BHR, ["Costa Rica"])
    assert not bamboohr._in_countries(JOB_BHR, ["Mexico"])


def test_bamboohr_without_countries_keeps_everything():
    assert bamboohr._in_countries(JOB_BHR, [])


def test_bamboohr_scopes_the_id_by_company():
    """BambooHR numbers postings per tenant, and they're small integers: "35"
    would collide across companies instantly."""
    assert bamboohr._job_url("gorillalogic", "186") == \
        "https://gorillalogic.bamboohr.com/careers/186"
    assert bamboohr._list_url("gorillalogic") == \
        "https://gorillalogic.bamboohr.com/careers/list"


# --- Greenhouse / Lever / Ashby -------------------------------------------

def test_ats_filters_the_country_locally():
    """None of the three filters by location on the server, so this is the only
    thing standing between the orchestrator and the whole board — 141 postings
    at West Monroe, of which 6 are Costa Rica's."""
    assert ats._in_countries("Costa Rica", ["Costa Rica"])
    assert not ats._in_countries("Chicago", ["Costa Rica"])


def test_ats_keeps_multi_site_postings():
    """Greenhouse writes several sites into one string."""
    assert ats._in_countries("Boston; Chicago; San Jose, Costa Rica",
                             ["Costa Rica"])


def test_ats_is_case_insensitive_and_tolerates_no_location():
    assert ats._in_countries("COSTA RICA", ["costa rica"])
    assert not ats._in_countries("", ["Costa Rica"])
    assert not ats._in_countries(None, ["Costa Rica"])


def test_ats_without_countries_keeps_the_whole_board():
    """`countries: []` is a valid choice, same as `location_hints: []`."""
    assert ats._in_countries("Chicago", [])
    assert ats._in_countries("Chicago", None)


# --- IBM ------------------------------------------------------------------

def test_ibm_uses_the_jobid_and_not_the_hash_as_id():
    """`_id` is a 64-char hash: stable, but useless in a notification. The
    stable code humans can look up is the URL's jobId."""
    source = {"url": "https://careers.ibm.com/careers/JobDetail?jobId=120944",
              "_id": "f5fc3dfee0da55f5"}
    assert ibm._job_id(source) == "120944"


def test_ibm_falls_back_to_the_hash_without_a_jobid():
    assert ibm._job_id({"url": "https://careers.ibm.com/x", "_id": "a" * 64}) == "a" * 16


def test_ibm_replaces_the_iso2_with_the_country_name():
    """The city field carries "Heredia, CR" — `location_hints` has nothing to
    match "costa rica" against unless the name is put back."""
    assert ibm._location({"field_keyword_19": "Heredia, CR",
                          "field_keyword_05": "Costa Rica"}) == "Heredia, Costa Rica"


def test_ibm_does_not_repeat_a_country_already_in_the_city():
    assert ibm._location({"field_keyword_19": "Heredia, Costa Rica",
                          "field_keyword_05": "Costa Rica"}) == "Heredia, Costa Rica"


def test_ibm_tolerates_a_missing_city():
    assert ibm._location({"field_keyword_05": "Costa Rica"}) == "Costa Rica"


def test_ibm_filters_one_country_with_a_term_and_several_with_a_should():
    assert ibm._country_filter(["Costa Rica"]) == {
        "term": {"field_keyword_05": "Costa Rica"}}
    assert ibm._country_filter(["Costa Rica", "Mexico"]) == {"bool": {"should": [
        {"term": {"field_keyword_05": "Costa Rica"}},
        {"term": {"field_keyword_05": "Mexico"}}]}}


def test_ibm_reads_the_country_catalog_out_of_the_aggregation():
    """That catalog is what turns a typo into an error instead of a silent
    zero: an unknown country returns total 0, not a failure."""
    payload = {"aggregations": {"all_countries": {"field_keyword_05": {
        "buckets": [{"key": "Costa Rica"}, {"key": "Mexico"}]}}}}
    assert ibm._known_countries(payload) == {"Costa Rica", "Mexico"}
    assert ibm._known_countries({}) == set()


# --- Jibe / iCIMS ---------------------------------------------------------

def test_jibe_links_to_the_public_page_not_the_icims_login():
    """`apply_url` points at careers-teknowledge.icims.com/jobs/<id>/login,
    which is the login screen — same trap as Amazon's `urlNextStep`."""
    job = jibe._map_job({"req_id": "11870", "title": "FinTech Analyst",
                         "apply_url": "https://careers-teknowledge.icims.com/jobs/11870/login"},
                        "https://careers.teknowledge.com", "tek", "TeKnowledge")
    assert job["url"] == "https://careers.teknowledge.com/jobs/11870"
    assert "icims" not in job["url"]


def test_jibe_collapses_a_location_repeated_with_semicolons():
    """Some postings repeat the same site: "San Pedro, CR; San Pedro, CR"."""
    assert jibe._location({"full_location": "San Pedro, Costa Rica; San Pedro, Costa Rica"}) \
        == "San Pedro, Costa Rica"


def test_jibe_keeps_genuinely_distinct_locations():
    assert jibe._location({"full_location": "San Pedro, Costa Rica; Heredia, Costa Rica"}) \
        == "San Pedro, Costa Rica · Heredia, Costa Rica"


def test_jibe_builds_the_location_from_parts_without_full_location():
    assert jibe._location({"city": "San Pedro", "state": "San José",
                           "country": "Costa Rica"}) == "San Pedro, San José, Costa Rica"


def test_jibe_reads_the_category_out_of_the_list_of_dicts():
    assert jibe._category({"categories": [{"name": "Customer Support"}]}) == "Customer Support"
    assert jibe._category({"categories": []}) == ""
    assert jibe._category({}) == ""


def test_jibe_raises_on_the_silent_error_response():
    """An unknown country answers HTTP 200 with `{"error": ...}` and no `jobs`.
    Unchecked, that reads exactly like "no openings here", forever."""
    with pytest.raises(RuntimeError, match="rejected the query"):
        jibe._check_error({"error": "invalid location"}, "TeKnowledge", ["Wakanda"])


def test_jibe_accepts_a_normal_response():
    jibe._check_error({"jobs": [], "totalCount": 0}, "TeKnowledge", ["Costa Rica"])


# --- Phenom ---------------------------------------------------------------

def fake_jwt(payload):
    """PLAY_SESSION is shaped like a JWT: header.payload.signature, and the
    payload is base64url with no padding."""
    raw = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode()
    return f"header.{raw.rstrip('=')}.signature"


def test_phenom_pulls_the_csrf_from_inside_the_cookie():
    """The token doesn't travel in a header: it's inside the PLAY_SESSION."""
    cookie = fake_jwt({"data": {"csrfToken": "abc123"}})
    assert phenom._csrf_from_play_session(cookie) == "abc123"


def test_phenom_returns_none_if_the_cookie_is_no_good():
    assert phenom._csrf_from_play_session("anything at all") is None
    assert phenom._csrf_from_play_session(fake_jwt({"data": {}})) is None


def test_phenom_annotates_multi_location_postings():
    """HPE publishes roles based in Texas that can also be taken from Heredia.
    Without the annotation, `location_hints` would silently discard them."""
    job = {"cityStateCountry": "Austin, Texas, United States",
           "country": "United States",
           "multi_location": ["Austin", "Heredia"]}
    location = phenom._location(job, ["Costa Rica"])
    assert "Costa Rica" in location
    assert "+1 location" in location


def test_phenom_does_not_annotate_if_the_primary_site_is_in_the_country():
    job = {"cityStateCountry": "Heredia, Costa Rica",
           "country": "Costa Rica",
           "multi_location": ["Heredia", "San Jose"]}
    assert phenom._location(job, ["Costa Rica"]) == "Heredia, Costa Rica"


def test_phenom_finds_the_postings_even_if_the_structure_changes():
    """The response changes shape between Phenom versions."""
    assert phenom._find_jobs_list({"a": {"b": {"jobs": [{"id": 1}]}}}) == [{"id": 1}]
    assert phenom._find_jobs_list({"nothing": "here"}) == []


def test_phenom_uses_the_multi_category_when_there_is_no_simple_one():
    assert phenom._category({"category": "Engineering"}) == "Engineering"
    assert phenom._category({"multi_category": ["IT", "Data"]}) == "IT"
    assert phenom._category({}) == ""


# --- Radancy --------------------------------------------------------------

def test_radancy_knows_the_geographic_node_of_costa_rica():
    geo = radancy._geo("Costa Rica")
    assert geo["path"] and geo["lat"] and geo["lon"]


def test_radancy_fails_clearly_on_a_country_it_does_not_have():
    """Better an explicit error than sending the request with no location,
    because the API would return the global catalog without warning."""
    with pytest.raises(ValueError, match="COUNTRY_GEO"):
        radancy._geo("Wakanda")


def test_radancy_parses_the_older_moodys_skin():
    from bs4 import BeautifulSoup
    html = ('<li class="search-results-list__item">'
            '<a class="search-results-list__job-link" data-job-id="97934207472" '
            'href="/en/job/heredia/software-engineer/49841/97934207472">'
            'Software Engineer</a>'
            '<span class="job-location">Heredia, Costa Rica</span></li>')
    jobs = radancy._parse_items(BeautifulSoup(html, "html.parser"),
                                "https://careers.moodys.com", "Moody's", "49841")
    assert len(jobs) == 1
    assert jobs[0]["id"] == "rdc-49841-97934207472"
    assert jobs[0]["location"] == "Heredia, Costa Rica"


def test_radancy_parses_the_newer_citi_skin():
    """Same platform and same data, different class names. Guessing one skin is
    what made this template return zero postings for Citi."""
    from bs4 import BeautifulSoup
    html = ('<li class="sr-job-item">'
            '<h3 class="sr-job-item__title">'
            '<a class="sr-job-item__link" data-job-id="98481831680" '
            'href="/job/escazu/credit-risk-2lod-sr-analyst-c12/287/98481831680">'
            'Credit Risk 2LOD Sr Analyst - C12</a></h3>'
            '<span class="sr-job-item__facet sr-job-location">'
            'Escazú, Provincia de San José, Costa Rica</span></li>')
    jobs = radancy._parse_items(BeautifulSoup(html, "html.parser"),
                               "https://jobs.citi.com", "Citi", "287")
    assert len(jobs) == 1
    assert jobs[0]["id"] == "rdc-287-98481831680"
    assert "Costa Rica" in jobs[0]["location"]
    assert jobs[0]["url"].startswith("https://jobs.citi.com/job/")


def test_radancy_builds_the_server_rendered_url_with_the_filters_in_the_path():
    url = radancy._ssr_url("https://jobs.citi.com", "287", 2, "Costa Rica",
                           radancy._geo("Costa Rica"), 1)
    assert url == ("https://jobs.citi.com/search-jobs/Costa%20Rica/287/2/"
                   "3624060/10.00000/-84.00000/50/1")


def test_radancy_sends_the_five_location_fields_together():
    """With a partial combination the API doesn't fail: it returns the global
    catalog. Either all five go or none of them do."""
    params = radancy._params("49841", "Costa Rica", radancy._geo("Costa Rica"),
                             1, 50, "")
    for field in ("Location", "LocationPath", "Latitude", "Longitude", "LocationType"):
        assert params.get(field) not in (None, "")


# --- Workday --------------------------------------------------------------

def test_workday_resolves_the_nested_country_facet():
    """P&G's shape: the countries hang off a `locationMainGroup` group. The IDs
    are opaque GUIDs, resolved against the catalog in the response itself."""
    payload = {"facets": [{"values": [{
        "facetParameter": "locationCountry",
        "values": [{"descriptor": "Costa Rica", "id": "99abe7e6"},
                   {"descriptor": "Mexico", "id": "other"}],
    }]}]}
    assert workday._resolve_country_facets(payload, ["Costa Rica"]) == \
        ("locationCountry", ["99abe7e6"])


def test_workday_resolves_the_flat_country_facet():
    """Workday's own tenant exposes `Location_Country` as a top-level facet.
    Guessing a single name is what made this template silently fall back to
    fetching the global catalog."""
    payload = {"facets": [
        {"facetParameter": "remoteType", "values": [{"descriptor": "Remote"}]},
        {"facetParameter": "Location_Country",
         "values": [{"descriptor": "Costa Rica", "id": "99abe7e6"},
                    {"descriptor": "Ireland", "id": "other"}]},
    ]}
    assert workday._resolve_country_facets(payload, ["Costa Rica"]) == \
        ("Location_Country", ["99abe7e6"])


def test_workday_returns_the_parameter_name_it_matched():
    """`appliedFacets` has to be keyed by that same name, so returning the ids
    alone isn't enough."""
    payload = {"facets": [{"facetParameter": "Location_Country",
                           "values": [{"descriptor": "Mexico", "id": "mx"}]}]}
    param, ids = workday._resolve_country_facets(payload, ["Mexico"])
    assert param == "Location_Country" and ids == ["mx"]


def test_workday_finds_no_facet_for_an_absent_country():
    payload = {"facets": [{"values": [{
        "facetParameter": "locationCountry",
        "values": [{"descriptor": "Mexico", "id": "x"}],
    }]}]}
    assert workday._resolve_country_facets(payload, ["Costa Rica"]) == (None, [])


def test_workday_pulls_the_job_code_from_bulletfields():
    assert workday._req_id({"bulletFields": ["R000154991"]}) == "R000154991"


def test_workday_falls_back_to_externalpath_without_bulletfields():
    """The fallback also has to give a stable ID."""
    posting = {"bulletFields": [], "externalPath": "/job/Heredia/Analyst_R000154991"}
    assert workday._req_id(posting) == "Analyst_R000154991"
