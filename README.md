# Job alert bot

[![Tests](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/tests.yml)
[![Job alerts](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/job-alerts.yml/badge.svg)](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/job-alerts.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Monitors several job boards and pings you on Telegram **as soon as a new opening
shows up** that matches the profile you're after (junior software engineering,
data analysis or QA roles, in Costa Rica or remote).

The idea is to replace a pile of noisy email alerts — each with its own format,
its own cadence and its own noise — with **a single filtered feed**.

```
23:15:48 INFO    equifax             11 jobs ·   3 new ·   2 notified
23:15:51 INFO    pg                   2 jobs ·   0 new ·   0 notified
23:15:53 INFO    cisco                4 jobs ·   1 new ·   1 notified
23:15:56 INFO    hpe                 20 jobs ·   2 new ·   1 notified
23:15:58 INFO    moodys              22 jobs ·   3 new ·   2 notified
23:16:00 INFO    amazon               8 jobs ·   1 new ·   1 notified
23:16:00 INFO    total: 67 jobs · 9 new · 6 notified · 6/6 sources ok
```

```
🟢 New job posting
Billing Analyst - Junior
Heredia, Costa Rica · Accounting · Equifax
https://careers.equifax.com/es/trabajos/j00178026/billing-analyst-junior/
```

## The core idea

**N job boards are not N problems.** Almost no company builds its own job
board: they outsource it to a well-known ATS. Once you classify the sources by
platform, they all collapse into 4-5 reusable templates, and adding one more
company becomes a single YAML entry.

| Platform             | How to recognize it               | How it's solved              | Status                                |
| -------------------- | --------------------------------- | ---------------------------- | ------------------------------------- |
| Greenhouse           | `boards.greenhouse.io/<company>`  | Public JSON API              | template ready                        |
| Lever                | `jobs.lever.co/<company>`         | Public JSON API              | template ready                        |
| Ashby                | `jobs.ashbyhq.com/<company>`      | Public JSON API              | template ready                        |
| Workday              | `<tenant>.<dc>.myworkdayjobs.com` | JSON POST to `/wday/cxs/`    | ✅ verified live                      |
| Phenom               | `/widgets` endpoint               | POST + CSRF token            | ✅ verified live (P&G, Cisco, HPE)    |
| Equifax              | its own XML feed                  | 1 GET to the feed            | ✅ verified live                      |
| Radancy / TalentBrew | assets on `tbcdn.talentbrew.com`  | GET with HTML inside the JSON | ✅ verified live (Moody's)            |
| Amazon               | `amazon.jobs/api/jobs/search`     | 1 POST, no token             | ✅ verified live                      |
| Heavy JS with no API | nothing in the Network tab        | Playwright                   | last resort, no cases yet             |

**LinkedIn and Indeed are deliberately left out.** They actively block scraping
and it goes against their terms of service. For those two, the sane way out is
their native email alerts + a Gmail rule.

## Architecture

Four decoupled pieces, so that adding a source doesn't touch anything else:

```
config/sources.yaml ──> fetchers ──> dedupe (SQLite) ──> filters ──> Telegram
                           │
                           └── one per platform; they all return the same schema
```

1. **Fetchers** (`jobbot/fetchers/`) — one per platform. They know nothing about
   filters or notifications: they just return normalized job postings.
2. **Dedupe** — SQLite holding the IDs already seen. Without this the bot
   repeats everything on every run.
3. **Filters** — include/exclude by title and location hint.
4. **Notification** — Telegram over HTTP.

Every fetcher returns lists of dicts with this shape. It's the contract that
lets the orchestrator not care where each posting came from:

```python
{
    "id":       "efx-J00178026",   # unique and STABLE, prefixed by source
    "title":    "Billing Analyst - Junior",
    "location": "Heredia, Costa Rica",
    "url":      "https://...",
    "source":   "Equifax",
    "category": "Accounting",      # optional
    "posted":   "2026-07-20",      # optional
}
```

The `id` is the dedupe key: it comes from the source's own job code, never from
the position in the list nor from a hash of the title. If the site reorders its
results or fixes a word in the title, the bot doesn't notify again.

### Down-source alerting

A source that breaks doesn't take down the run: the orchestrator logs it and
carries on with the rest. The problem is that, on its own, that's invisible — if
Moody's changes its API tomorrow, you stop getting Moody's postings and **the
silence reads exactly like "nothing came up this week"**. With a single source
it's tolerable; with fifteen, something breaking every now and then is the
expected case.

That's why the bot pings you on Telegram when a source goes down, and again when
it comes back. The state lives in the `source_health` table of the same
database:

- It only alerts on the **second consecutive failed run** (`FAIL_ALERT_AFTER` in
  `jobbot/config.py`). A one-off timeout triggers nothing; at `*/30`, two
  failures in a row already means thirty minutes down.
- It alerts **once per outage**, not on every run.
- If several go down at once — which is what you'd expect if the one that lost
  network was the runner — it sends **a single message** with all of them.

This is the counterpart to the point above: it's what makes the bot's silence
always mean "no new postings" and never "I've been broken for three weeks".

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# See what it would find, without notifying or touching the database:
python run.py --dry-run

# For real (needs the Telegram credentials, see below):
cp .env.example .env    # and fill in the two values
python run.py
```

Without `TELEGRAM_TOKEN`/`TELEGRAM_CHAT_ID` the bot doesn't fail: it prints the
postings to the console. Handy for tuning filters.

Useful flags:

| Flag                 | What it's for                                             |
| -------------------- | --------------------------------------------------------- |
| `--dry-run`          | Prints instead of notifying and doesn't write the database |
| `--source equifax`   | Runs a single source (by type or by name)                  |
| `--config other.yaml`| Uses a different sources file                              |
| `--no-seed`          | With an empty database, notifies instead of seeding silently |
| `-v`                 | DEBUG logging                                              |

`--no-seed` exists for the initial start: with an empty database, the normal run
swallows the postings that were **already published** (see _Design decisions_).
If you want to receive them once before the database marks them as seen, that
first run goes with `--no-seed`. Once the database is populated the flag changes
nothing.

Each fetcher also runs standalone, which is the quick way to check whether a
source is still alive:

```bash
python -m jobbot.fetchers.equifax
python -m jobbot.fetchers.phenom     # P&G, Cisco and HPE
python -m jobbot.fetchers.workday
python -m jobbot.fetchers.radancy    # Moody's
python -m jobbot.fetchers.amazon
```

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

73 tests, ~0.15 s, and **none of them touch the network or Telegram**: they run
without credentials and offline. They cover the filters, the SQLite database
(dedupe, alert threshold and the `source_health` migration), the message
formatting and the pure functions of the fetchers — date parsing, location
assembly and decoding Phenom's JWT.

The fetchers themselves are deliberately left out: they talk to six sites that
change whenever they feel like it, and a test that depends on that fails for
reasons unrelated to the code. That gap is covered by the down-source alerting
in production. See [tests/README.md](tests/README.md).

They run on their own on every push (`.github/workflows/tests.yml`) against
**Python 3.12 and 3.14**: the first is what the bot uses in production and the
second is the development environment, so a change that works in one and not the
other shows up right away instead of at 3 a.m. in the cron.

### Setting up Telegram

1. Talk to [@BotFather](https://t.me/BotFather), send `/newbot`, pick a name and
   a username (it has to end in `bot`). It gives you back the **token**.
2. Search for your new bot by its username and **send it anything**. Without
   that first message from you, Telegram won't let it message you.
3. Open `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` in the browser and
   copy the number in `result[0].message.chat.id` — that's the **chat id**.
4. Put both values in `.env` (local) and as Secrets in GitHub Actions.

The bot reads the credentials from two places, in this order:

| Where                 | What for                    | Committed to the repo      |
| --------------------- | --------------------------- | -------------------------- |
| Environment variables | Production / GitHub Actions | no                         |
| `.env` file           | Local convenience           | no, it's in `.gitignore`   |

Real environment variables take precedence over `.env`, so in Actions the
Secrets win even if the file existed.

## Adding a source

You edit `config/sources.yaml`, not the code. Look at the board's URL and pick
the type:

```yaml
sources:
  - type: greenhouse
    company: name-in-the-url # boards.greenhouse.io/name-in-the-url

  - type: workday
    tenant: pg # https://pg.wd5.myworkdayjobs.com/1000
    dc: wd5
    site: "1000"
    countries: ["Costa Rica"]
    name: "P&G"

  - type: equifax
    countries: ["Costa Rica"]

  - type: cisco # Phenom preset, same as `pg` and `hpe`
    countries: ["Costa Rica"]

  - type: moodys # Radancy preset
    countries: ["Costa Rica"]

  - type: amazon # amazon.jobs; accepts a name or ISO-2 ("CR")
    countries: ["Costa Rica"]
    categories: # optional; omit = the technical ones by default
      - "Software Development" # `categories: []` = all of them
      - "Operations, IT, & Support Engineering"
```

The Phenom boards that already have a preset (`pg`, `cisco`, `hpe`) are one
line. For a new Phenom one you use `type: phenom` with the values you can see in
the POST to `/widgets` (`site`, `page_id`, `ref_num`, `id_prefix`); the full
example is commented out in `config/sources.yaml`.

On Workday, `countries` takes the country **name** exactly as the site's filter
shows it. Internally Workday doesn't filter by name but by an opaque ID (Costa
Rica = `99abe7e6bb3f4c108aebebf01a369ec5` on P&G's tenant), so the fetcher reads
the facet catalog that comes in the first response and translates the name on its
own. That saves you from hunting down GUIDs by hand for every tenant.

If the board doesn't belong to any known platform, it falls back to `type: html`
with a CSS selector — and if there's nothing in the HTML either, then it's
Playwright time.

The filters also live in `config/sources.yaml`, so they can be tuned without
touching Python:

```yaml
filters:
  include: ['\bjunior\b', '\bdata\b', '\bqa\b', ...]
  exclude: ['\bsenior\b', '\bmanager\b', ...]
  location_hints: ["remote", "costa rica", "heredia", ...]
```

A title that matches `exclude` is dropped even if it matches `include`. To skip
filtering by location, use `location_hints: []`.

## Deploy

### GitHub Actions (included)

`.github/workflows/job-alerts.yml` runs every 30 minutes on GitHub's servers —
no need to leave your computer on. You only have to load `TELEGRAM_TOKEN` and
`TELEGRAM_CHAT_ID` into _Settings → Secrets and variables → Actions_.

**The detail that matters:** the runner starts clean on every run. If
`data/seen_jobs.db` isn't persisted, the database comes up empty and the bot
believes it's its first run, **every time**: it seeds silently and never
notifies anything. The failure is silent — from the chat it reads exactly like
"nothing came up this week". The workflow solves it with `actions/cache`: since
Actions caches are immutable, the key carries the `run_id` (always different) and
`restore-keys` recovers the most recent one by prefix.

It's worth verifying this by hand once, because it's the point that breaks most
easily and the quietest one: run the workflow **twice in a row** and confirm the
second one says `0 new`. If it says `seeding (no notifications)`, or if the
*Restore seen-jobs database* step says `Cache not found`, the database isn't
persisting.

Three GitHub Actions caveats worth knowing:

- **Minutes are billed on private repos.** The Free plan gives 2000 min/month
  and GitHub rounds each run up to the minute. At `*/30` that's ~1440 runs/month:
  it fits. At `*/15` it'd be ~2880 and you'd go over. On **public repos minutes
  are free and unlimited**, so if the repo is public (which is a good idea as a
  portfolio piece) frequency stops being a problem.
- Cron schedules **aren't punctual, and on top of that they drop runs**. It's not
  "it's a bit late": under load GitHub discards the slot instead of queueing it.
  Measured over this bot's first 34 runs with `*/30`, across 58 hours: **it ran
  29% of what was scheduled**, with a median of 83 min between runs, a minimum of
  59 min (it never actually ran every 30) and peaks of almost 4 hours. That's why
  the cron is `7,37 * * * *` and not `*/30`: `:00` and `:30` are the minutes
  everybody schedules on and where the queue is deepest. For job postings the
  delay is irrelevant — nobody fills a role in an hour — and the dedupe prevents
  duplicates no matter when it runs.
- Scheduled workflows **disable themselves** after 60 days without activity in
  the repo. A commit every once in a while is enough, or use the alternative
  below.

To change the frequency you edit one line of the workflow:

```yaml
- cron: "*/30 * * * *" # every 30 min · "0 * * * *" = hourly
```

### VPS with cron

```cron
*/30 * * * * cd /path/to/the/bot && /path/to/.venv/bin/python run.py >> bot.log 2>&1
```

Here `data/seen_jobs.db` persists on its own, which is the main advantage.

## Design decisions

- **The first run doesn't notify.** If the database is empty, it gets filled with
  everything that's there but nothing is announced; otherwise the bot starts with
  an avalanche of old postings. From the second run on it only announces what's
  new. The cost is that already-published postings never arrive, so the
  `--no-seed` flag lets you do the startup the other way around: notify that
  initial batch and seed with it.
- **Fetch everything and filter locally.** The fetchers don't filter by keyword
  at the source (empty `subsearch` in Phenom, empty `searchText` in Workday).
  Every site indexes differently and a search for "junior" eats postings that
  were actually a good fit. It fetches everything for the location and the bot
  does the filtering.
- **Amazon is the exception, and filters by category at the source.** It posts so
  much outside of engineering that fetching everything means 73 Costa Rica
  postings to end up keeping 8. The difference from filtering by keyword is that
  the **category is a structured field of the ATS itself**, not a text search: it
  doesn't eat titles based on how they happen to be worded. Even so it pays to be
  generous with the list — "Software Development" alone brings 1 posting, because
  Amazon classifies nearly all of engineering under "Operations, IT, & Support
  Engineering".
- **A down source doesn't take down the run.** Each source goes in its own
  try/except; the error is logged and it moves on to the rest. The process only
  exits with an error if _all_ of them failed.
- **If Telegram fails, the posting isn't marked as seen.** That way it's retried
  on the next run instead of getting lost silently.
- **Messages in HTML, not Markdown.** Real titles carry `&`, parentheses and
  dashes (`FP&A Analyst`, `Support (French, English)`) that break Telegram's
  Markdown parser and make the send fail with HTTP 400.
- **Respectful scraping.** Cron every 30 minutes, an identifiable `User-Agent`
  and pauses between pages and between sources. Nobody fills a posting in under
  an hour; raising the frequency only increases the risk of getting blocked.
- **Secrets via environment variables.** Never in the repo.

## Reverse engineering notes

What came up while verifying the sources against the real sites:

- **Equifax**: the public `/es/trabajos/` page accepts `?location=`, `?country=`
  and `?page=`… and ignores all of them. Filtering and pagination are
  client-side: the server always returns the same 20 postings, regardless of the
  parameters (verified: page 1 and page 2 bring exactly the same set). A scraper
  over that HTML returned 3 Costa Rica postings and looked correct. The site also
  publishes an XML feed (`/es/trabajos/xml/`) with the full catalog: **12 Costa
  Rica postings in a single GET**, with location and category already structured,
  and the same job code the public URL uses. The fetcher uses the feed.
- **Workday**: `limit` caps at 20 — asking for 100 returns HTTP 400. Pagination
  goes through `offset`. The CXS endpoint responded the same on three different
  tenants (`pg`, `intel`, `3m`), which is what makes it a template and not a
  one-off case.
- **P&G / Phenom**: the `x-csrf-token` doesn't come in a `<meta>` or a header,
  but **inside** the `PLAY_SESSION` cookie, which is a JWT — you have to decode
  the payload and pull out `data.csrfToken`. If the POST comes back empty or with
  a 403, that's the first suspect. On Cisco the same token also shows up **in
  plain text in the HTML**; the fetcher tries the JWT first and falls back to the
  HTML if it isn't there.
- **Phenom is the same API for everyone**: P&G, Cisco and HPE share the endpoint,
  the token flow and the response shape; what changes is four payload fields
  (`pageId`, `pageName`, `pageType`, `refNum`), the site's language/market (HPE
  runs on `en_us`/`us`, the others on `en_global`/`global` — this does not limit
  postings to the US, the country is still filtered by `selected_fields`) and the
  odd quirk here and there (P&G sends a `locationData` slider block the others
  don't have). That's why the fetcher is parameterized and each company is a
  preset of the same function.
- **Radancy / Moody's: the location filter is all-or-nothing.** It's only applied
  if **all five** parameters go together (`Location`, `LocationPath`, `Latitude`,
  `Longitude`, `LocationType=2`). With any partial combination the API **doesn't
  fail**: it returns the global catalog — 251 postings instead of 22. I tried all
  five combinations to confirm it. Since `location_hints` includes "remote", that
  silent failure would have let in remote postings from any country, so the
  fetcher **revalidates locally** that each posting mentions the country and logs
  a warning if it had to discard anything. Verified by breaking the filter on
  purpose: it returns the correct 22 and logs the warning.
- **Radancy filters by geographic node**, not by name: Costa Rica is
  `LocationPath=3624060` (GeoNames) plus its coordinates. An invalid ID also
  falls back to the global catalog silently, so the ones in `COUNTRY_GEO` are
  verified one by one against Moody's.
- **Amazon** doesn't use a third-party ATS, it has its own (`sourceSystem:
JobCreator`), but the API is the simplest of them all: a POST with no token and
  no cookies, and `size: 100` brings all 73 Costa Rica postings in one shot. Two
  traps: in `searchHits[].fields` **each value comes wrapped in a single-element
  list** (`"title": ["Designer, …"]`), and the `urlNextStep` field is **useless
  as a link** — it points to `account.amazon.jobs/…/apply`, which redirects to
  the login screen. The public page is
  `www.amazon.jobs/en/jobs/<icimsJobId>`.
- **Amazon's categories are misleading.** "Software Development" has **1**
  posting in Costa Rica; the _Incident Management Engineer_ and the _AV
  Deployment Engineer_ live under "Operations, IT, & Support Engineering", and
  the data ones under "Business Intelligence". A misspelled name doesn't error
  out: it returns zero silently. To see the exact names with their counts:
  `python -m jobbot.fetchers.amazon --categories`.
- **Amazon filters by ISO-2 code** (`CR`), not by name. The fetcher translates
  `countries: ["Costa Rica"]` so it doesn't break the contract with the rest of
  the sources, and if the country isn't in its table it says so with a clear
  error instead of fetching the entire world. On top of that
  `normalizedLocation` ends in the ISO-3 (`"Heredia, Heredia, CRI"`), so the
  location is rebuilt with the country name to give `location_hints` something to
  match against.
- **Multi-location postings (HPE)**: 8 of the 20 in Costa Rica have their primary
  site in Texas, India or Mexico and Heredia as an additional site. The API's
  country filter **does** return them correctly, but `cityStateCountry` only
  shows the primary one, so the bot's `location_hints` would discard them. Worse:
  the `multi_location` array lists the cities **without the country**
  (`"Heredia, Heredia, 400803"`), meaning there's nowhere to read "Costa Rica"
  from. Since the API already applied the filter, the fetcher records the
  location as `Spring, Texas, … (+2 locations, includes Costa Rica)`.
- **Cisco**: `pageName`/`pageType` describe which page the UI is searching from
  and **don't change the results** (verified: searching from the "Product and
  Engineering" category or from the global search box returns the same thing);
  the real filter is `selected_fields`. `size` accepts 100 without complaining,
  unlike Workday. The `x-csrf-token` turned out to be **optional**: the endpoint
  responds 200 without it, but it's sent anyway to mirror the browser.
- **P&G shows up on two platforms**: the board is Phenom but the "Apply" button
  redirects to Workday (`pg.wd5.myworkdayjobs.com`). Both fetchers return the
  same 2 Costa Rica postings with different IDs (`pg-R000151170` vs
  `wd-pg-R000151170`), so you have to enable **only one**: the dedupe can't cross
  them. Cisco (`cisco.wd5/Cisco_Careers`) and HPE (`hpe.wd5/Jobsathpe`) are the
  same case: if they're ever added as `type: workday`, the corresponding Phenom
  preset has to be removed.

### Verification status

| Source                     | Verified live                                                    |
| -------------------------- | ---------------------------------------------------------------- |
| Equifax (XML feed)         | ✅ 11 postings in Costa Rica                                     |
| P&G (Phenom)               | ✅ 2 postings in Costa Rica                                      |
| Cisco (Phenom)             | ✅ 4 postings in Costa Rica (out of 1023 globally)               |
| HPE (Phenom)               | ✅ 20 postings in Costa Rica (out of 1061 globally), 8 multi-site |
| Moody's (Radancy)          | ✅ 22 postings in Costa Rica (out of 251 globally)               |
| Amazon (own ATS)           | ✅ 8 technical postings in Costa Rica (73 unfiltered by category) |
| Workday (tenant `pg`)      | ✅ 2 postings, the same ones as Phenom                           |
| Greenhouse / Lever / Ashby | ⚠️ code ready, no real company configured yet                    |

## Stack

Python 3, `requests` + `beautifulsoup4` + `PyYAML`. No frameworks. SQLite from
the standard library. `pytest` only for the tests, in `requirements-dev.txt`: the
app doesn't need it. Playwright is kept in reserve in case some source turns out
to be heavy-JS-with-no-API.

## Structure

```
run.py                    entry point
config/
  sources.yaml            sources and filters (the only thing edited day to day)
data/
  seen_jobs.db            seen postings + source health (not versioned)
jobbot/
  cli.py                  orchestrator: wires the four pieces together
  config.py               .env, paths and sources.yaml
  filters.py              include / exclude / location
  storage.py              dedupe and source health, in SQLite
  notify.py               Telegram (postings and down-source alerts)
  fetchers/
    __init__.py           registry: type -> function
    useragents.py         the bot's two User-Agents, and why there are two
    ats.py                Greenhouse, Lever and Ashby (public JSON API)
    amazon.py             amazon.jobs (POST with no token)
    equifax.py            XML feed
    phenom.py             Phenom (POST + CSRF in a JWT) + P&G/Cisco/HPE presets
    radancy.py            Radancy/TalentBrew (HTML inside the JSON) + Moody's
    workday.py            Workday (CXS POST + facets)
    generic_html.py       last resort: CSS selector
tests/                    73 tests, no network (see tests/README.md)
.github/workflows/
  job-alerts.yml          the bot, every 30 min
  tests.yml               pytest on every push (Python 3.12 and 3.14)
pytest.ini                pytest config
requirements-dev.txt      test-only dependencies
LICENSE                   MIT
```

The folders follow the four architecture pieces: each file in `jobbot/` is one
of them, and `fetchers/` grows as platforms are added. Adding a board on an
already-supported platform **doesn't touch a single `.py` file** — only
`config/sources.yaml`.

## License

MIT — see [LICENSE](LICENSE).
