"""Enables `python -m jobbot`. The convenient entry point is `python run.py`."""

from .cli import main

raise SystemExit(main())
