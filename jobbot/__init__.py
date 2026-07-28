"""
Job alert bot.

Monitors several job boards and pings you on Telegram as soon as a new posting
shows up that passes the filters.

Four decoupled pieces:
    fetchers/  one per platform; they return already-normalized postings
    storage    dedupe in SQLite (what has already been seen)
    filters    include / exclude / location
    notify     Telegram
    cli        the orchestrator that wires them together
"""
