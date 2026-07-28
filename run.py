"""
Entry point of the job alert bot.

    python run.py                    # check everything and notify what's new
    python run.py --dry-run          # show what it would notify, without sending
    python run.py --source equifax   # run a single source
    python run.py --no-seed          # with an empty database, notify instead of seeding
    python run.py -v                 # DEBUG logging

Sources and filters live in `config/sources.yaml`.
Telegram credentials live in `.env` (local) or as environment variables.
"""

from jobbot.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
