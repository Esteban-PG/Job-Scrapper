"""
Filters on title and location.

The patterns come from `config/sources.yaml` and are regexes. The rule: if
something matches `exclude`, it's discarded even if it also matches `include`.

The last gate uses the ATS's own `category`, which is a structured field and so
a much better signal than guessing from the title. It is deliberately NOT a hard
block: companies file roles under the business unit they serve, so a real BI
Developer shows up under "Finance & Audit". What it does instead is raise the
bar — in a non-technical category a weak word like `analyst` or `data` is no
longer enough, the title has to carry a strong signal of its own.

The category is never concatenated into the matched text. If it were, every HPE
posting would match `\bengineer\b` through its "Engineering & QA" category and
the include list would stop meaning anything.
"""

import re

KEYS = ("include", "exclude", "location_hints",
        "strong_include", "nontech_categories")


def compile_filters(filters):
    return {
        key: [re.compile(p, re.IGNORECASE) for p in filters.get(key) or []]
        for key in KEYS
    }


def matches(job, rx):
    text = f"{job.get('title', '')} {job.get('location', '')}".lower()
    if any(p.search(text) for p in rx["exclude"]):
        return False
    if rx["include"] and not any(p.search(text) for p in rx["include"]):
        return False
    if rx["location_hints"] and not any(p.search(text) for p in rx["location_hints"]):
        return False
    return _passes_category(job, rx)


def _passes_category(job, rx):
    """Sources that carry no category (Radancy's listing doesn't) skip this gate
    entirely: an absent category is not evidence of anything."""
    category = (job.get("category") or "").lower()
    if not category or not rx["nontech_categories"]:
        return True
    if not any(p.search(category) for p in rx["nontech_categories"]):
        return True
    # Strong signal is looked for in the title alone — the location has no say
    # in whether a role is technical.
    title = (job.get("title") or "").lower()
    return any(p.search(title) for p in rx["strong_include"])
