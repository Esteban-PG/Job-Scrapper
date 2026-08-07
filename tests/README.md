# Tests

```bash
pip install -r requirements-dev.txt
pytest
```

**None of them touch the network or Telegram.** They can be run without
credentials, offline and without fear of sending yourself a message: what's
tested are the pure functions and the SQLite database (always against a
temporary file, never against `data/seen_jobs.db`).

That deliberately leaves the fetchers out of the tests: what they do is talk to
twenty-one sites that change whenever they feel like it, and a test that depends
on that fails for reasons that aren't the code's fault. To find out whether a
source is still alive there's the manual smoke test most modules carry:

```bash
python -m jobbot.fetchers.radancy      # or equifax, phenom, workday, amazon
```

and, in production, the down-source alert (`source_health`), which is exactly
what covers that gap without needing a fragile test.

What is tested about the fetchers is their **pure functions**: date parsing,
location assembly, country translation and decoding Phenom's JWT. That's where
the subtle bugs live, and they need no network.
