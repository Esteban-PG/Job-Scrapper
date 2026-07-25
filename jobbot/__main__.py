"""Permite `python -m jobbot`. El entrypoint cómodo es `python run.py`."""

from .cli import main

raise SystemExit(main())
