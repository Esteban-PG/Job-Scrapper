"""
Telegram notification.

Without `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` the bot doesn't fail: it prints to
the console. Handy for tuning filters without receiving messages.
"""

import html
import logging

import requests

from .config import TG_CHAT, TG_TOKEN

log = logging.getLogger("jobbot")

MAX_DETAILED = 8    # down sources listed with their error, see format_health_message


def format_message(job):
    """HTML instead of Markdown on purpose: real titles carry parentheses,
    dashes and `&` ("FP&A Analyst", "Support (French, English)") that break
    Telegram's Markdown parser and make the send fail with a 400."""
    esc = html.escape
    extra = " · ".join(x for x in (job.get("location"), job.get("category")) if x)
    return (
        f"🟢 <b>New job posting</b>\n"
        f"<b>{esc(job.get('title', 'Untitled'))}</b>\n"
        f"{esc(extra or '—')} · {esc(job.get('source', ''))}\n"
        f"{esc(job.get('url', ''))}"
    )


def as_plain_text(message):
    """The same message but readable in a console (no tags, no HTML entities)."""
    for tag in ("<b>", "</b>", "<code>", "</code>"):
        message = message.replace(tag, "")
    return html.unescape(message)


def humanize(seconds):
    """Approximate duration for the alerts ('40 min', '3 h', '2 days')."""
    if seconds < 3600:
        return f"{max(1, seconds // 60)} min"
    if seconds < 86400:
        return f"{seconds // 3600} h"
    days = seconds // 86400
    return f"{days} day" if days == 1 else f"{days} days"


def format_health_message(broken, recovered):
    """Alert about sources that went down and came back.

    `broken` are (source, error, failing_runs) tuples and `recovered` are
    (source, seconds_down). It all goes in a single message: if the runner loses
    network, all 6 sources fail at once and sending 6 alerts makes no sense.
    """
    esc = html.escape
    parts = []

    if broken:
        title = "Source down" if len(broken) == 1 else f"{len(broken)} sources down"
        lines = [f"🔴 <b>{title}</b>"]
        # Telegram cuts off at 4096 characters and rejects the whole message if
        # you go over. With many sources broken at once, knowing which ones
        # matters more than reading each error, so the first few are listed and
        # the rest are counted: the full detail is always in the run's log.
        for source, error, fails in broken[:MAX_DETAILED]:
            # The error may carry a whole HTML response: it gets trimmed.
            detail = " ".join(str(error).split())[:180]
            lines.append(f"\n<b>{esc(source)}</b> · {fails} failed runs\n"
                         f"<code>{esc(detail)}</code>")
        remaining = len(broken) - MAX_DETAILED
        if remaining > 0:
            rest = ", ".join(esc(s) for s, _, _ in broken[MAX_DETAILED:])
            lines.append(f"\n\n…and {remaining} more: {rest}")
        parts.append("".join(lines))

    if recovered:
        lines = ["🟩 <b>Source recovered</b>" if len(recovered) == 1
                 else f"🟩 <b>{len(recovered)} sources recovered</b>"]
        for source, downtime in recovered:
            lines.append(f"\n<b>{esc(source)}</b> · back after {humanize(downtime)}")
        parts.append("".join(lines))

    return "\n\n".join(parts)


def send(text, what=""):
    """Sends an already-formatted message. Returns True if it was delivered (or
    if we're running without Telegram configured, where 'delivering' means
    printing it)."""
    if not (TG_TOKEN and TG_CHAT):
        print(as_plain_text(text))
        return True

    try:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": False},
            timeout=20,
        )
        r.raise_for_status()
        return True
    except Exception as exc:
        log.error("Telegram failed%s: %s", f" for {what}" if what else "", exc)
        return False


def notify(job):
    """Sends the posting. If Telegram fails it returns False and the posting is
    NOT marked as seen: it's retried on the next run."""
    return send(format_message(job), job.get("id"))
