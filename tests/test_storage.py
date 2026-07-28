"""
Persistent state: dedupe (`seen`) and source health (`source_health`).

Each test builds its own database in a temporary file, so they never touch
`data/seen_jobs.db`.
"""

import sqlite3

import pytest

from jobbot.storage import (already_seen, init_db, is_empty, mark_seen,
                            record_failure, record_success)


@pytest.fixture
def con(tmp_path):
    connection = init_db(tmp_path / "test.db")
    yield connection
    connection.close()


# --- dedupe ---------------------------------------------------------------

def test_a_new_database_is_empty(con):
    """An empty database is what the orchestrator reads as 'first run'."""
    assert is_empty(con)


def test_marking_a_posting_leaves_it_seen(con):
    assert not already_seen(con, "efx-J001")
    mark_seen(con, ["efx-J001"])
    assert already_seen(con, "efx-J001")
    assert not is_empty(con)


def test_marking_twice_does_not_break(con):
    """`mark_seen` runs with IDs that may already be there: it must not blow up
    on the PRIMARY KEY."""
    mark_seen(con, ["efx-J001", "efx-J002"])
    mark_seen(con, ["efx-J001", "efx-J003"])
    assert con.execute("SELECT COUNT(*) FROM seen").fetchone()[0] == 3


def test_marking_an_empty_list_does_nothing(con):
    mark_seen(con, [])
    assert is_empty(con)


def test_ids_do_not_get_confused_between_sources(con):
    """The source prefix is what keeps two boards from colliding."""
    mark_seen(con, ["pg-R000151170"])
    assert not already_seen(con, "wd-pg-R000151170")


def test_init_db_is_idempotent(tmp_path):
    """It's called on every run against the same database."""
    path = tmp_path / "test.db"
    first = init_db(path)
    mark_seen(first, ["efx-J001"])
    first.close()

    second = init_db(path)
    assert already_seen(second, "efx-J001")
    second.close()


def test_init_db_adds_source_health_to_an_old_database(tmp_path):
    """Migration: the Actions cache holds databases created before
    `source_health` existed. The table has to appear on its own."""
    path = tmp_path / "old.db"
    old = sqlite3.connect(path)
    old.execute("CREATE TABLE seen (id TEXT PRIMARY KEY, ts INTEGER)")
    old.execute("INSERT INTO seen VALUES ('efx-J001', 0)")
    old.commit()
    old.close()

    con = init_db(path)
    assert already_seen(con, "efx-J001")          # nothing was lost
    assert record_failure(con, "equifax", 1) == (True, 1)   # the table exists
    con.close()


# --- source health --------------------------------------------------------

def test_the_first_failure_does_not_alert(con):
    """A one-off timeout must not fire an alert."""
    should_alert, fails = record_failure(con, "moodys", 2)
    assert not should_alert
    assert fails == 1


def test_it_alerts_when_it_reaches_the_threshold(con):
    record_failure(con, "moodys", 2)
    should_alert, fails = record_failure(con, "moodys", 2)
    assert should_alert
    assert fails == 2


def test_it_does_not_repeat_the_alert_while_still_down(con):
    """What prevents a message every 30 minutes for days."""
    record_failure(con, "moodys", 2)
    record_failure(con, "moodys", 2)          # it alerted here
    for _ in range(5):
        should_alert, _ = record_failure(con, "moodys", 2)
        assert not should_alert


def test_a_threshold_of_one_alerts_on_the_first_failure(con):
    assert record_failure(con, "moodys", 1) == (True, 1)


def test_sources_are_counted_separately(con):
    record_failure(con, "moodys", 2)
    should_alert, fails = record_failure(con, "hpe", 2)
    assert not should_alert and fails == 1


def test_a_healthy_source_does_not_alert_a_recovery(con):
    """The normal case on every run: it was never down."""
    assert record_success(con, "moodys") is None


def test_it_alerts_the_recovery_only_if_it_alerted_the_outage(con):
    record_failure(con, "moodys", 2)
    record_failure(con, "moodys", 2)          # it alerted here
    downtime = record_success(con, "moodys")
    assert downtime is not None and downtime >= 0


def test_a_short_outage_recovers_silently(con):
    """It failed once, never reached the threshold and came back: nobody found
    out, and it's right that nobody found out."""
    record_failure(con, "moodys", 2)
    assert record_success(con, "moodys") is None


def test_recovering_clears_the_state(con):
    """Otherwise the next outage would start with the old counter."""
    record_failure(con, "moodys", 2)
    record_failure(con, "moodys", 2)
    record_success(con, "moodys")

    should_alert, fails = record_failure(con, "moodys", 2)
    assert not should_alert and fails == 1


def test_health_does_not_pollute_the_dedupe(con):
    """`is_empty` looks only at `seen`: a source being down must not make the
    bot think it has already seeded."""
    record_failure(con, "moodys", 2)
    assert is_empty(con)
