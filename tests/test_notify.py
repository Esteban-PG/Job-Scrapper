"""
Formatting of the Telegram messages.

Sending isn't tested: `send()` goes out to the network and these tests run
without credentials. What is tested is what gets handed to Telegram, which is
where the real bugs were — a title with `&` broke the parser and the send failed
with HTTP 400.
"""

from jobbot.notify import (as_plain_text, format_health_message,
                           format_message, humanize)

TELEGRAM_LIMIT = 4096


# --- postings -------------------------------------------------------------

def test_the_message_carries_title_location_and_link():
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


def test_it_escapes_the_titles_that_broke_the_parser():
    """`FP&A Analyst` is a real title: unescaped, Telegram returns a 400."""
    msg = format_message({"title": "FP&A Analyst", "url": "", "source": ""})
    assert "FP&amp;A" in msg
    assert "FP&A " not in msg


def test_it_escapes_html_embedded_in_the_title():
    msg = format_message({"title": "Dev <script>alert(1)</script>",
                          "url": "", "source": ""})
    assert "<script>" not in msg
    assert "&lt;script&gt;" in msg


def test_it_tolerates_a_posting_without_optional_fields():
    msg = format_message({})
    assert "Untitled" in msg


def test_as_plain_text_keeps_the_message_readable_in_a_console():
    """It's what gets printed with --dry-run and without credentials."""
    plain = as_plain_text(format_message({
        "title": "FP&A Analyst", "location": "Heredia", "source": "Moody's",
        "url": "https://x.com/1",
    }))
    assert "FP&A Analyst" in plain
    assert "<b>" not in plain and "&amp;" not in plain


# --- durations ------------------------------------------------------------

def test_humanize_rounds_to_readable_units():
    assert humanize(30) == "1 min"        # never "0 min"
    assert humanize(2700) == "45 min"
    assert humanize(7200) == "2 h"
    assert humanize(86400) == "1 day"     # singular
    assert humanize(172800) == "2 days"


# --- down-source alerts ---------------------------------------------------

def test_alert_for_a_single_down_source():
    msg = format_health_message([("moodys", "HTTPError: 503", 2)], [])
    assert "Source down" in as_plain_text(msg)
    assert "moodys" in msg
    assert "503" in msg
    assert "2 failed runs" in msg


def test_plural_title_with_several_sources():
    msg = as_plain_text(format_health_message(
        [("moodys", "err", 2), ("hpe", "err", 2)], []))
    assert "2 sources down" in msg


def test_recovery_alert_includes_how_long_it_was_down():
    msg = as_plain_text(format_health_message([], [("equifax", 7200)]))
    assert "Source recovered" in msg
    assert "equifax" in msg
    assert "2 h" in msg


def test_outages_and_recoveries_go_in_the_same_message():
    msg = as_plain_text(format_health_message(
        [("moodys", "err", 2)], [("equifax", 3600)]))
    assert "moodys" in msg and "equifax" in msg


def test_the_error_gets_trimmed():
    """An error response may carry a whole HTML page."""
    msg = format_health_message([("moodys", "X" * 5000, 2)], [])
    assert len(msg) < 500


def test_the_error_gets_escaped_as_html():
    """An error with HTML inside would break the whole message."""
    msg = format_health_message(
        [("moodys", "<html><body>500</body></html>", 2)], [])
    assert "<html>" not in msg
    assert "&lt;html&gt;" in msg


def test_many_down_sources_do_not_pass_the_telegram_limit():
    """If the runner's network goes down they all fail at once, and that's
    exactly when you don't want to lose the alert to a 400."""
    broken = [(f"source-{i}", "HTTPError: 503 " + "x" * 200, 2) for i in range(15)]
    msg = format_health_message(broken, [])
    assert len(msg) < TELEGRAM_LIMIT
    assert "and 7 more" in as_plain_text(msg)
    assert "source-14" in msg          # the ones not detailed are still named
