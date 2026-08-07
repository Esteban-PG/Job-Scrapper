# Job alert bot

[![Tests](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/tests.yml/badge.svg)](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/tests.yml)
[![Job alerts](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/job-alerts.yml/badge.svg)](https://github.com/Esteban-PG/Job-alert-bot/actions/workflows/job-alerts.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

Monitors several job boards and pings you on Telegram **as soon as a new opening
shows up** that matches the profile you're after (junior software engineering,
data analysis or QA roles, in Costa Rica or remote).

The idea is to replace a pile of noisy email alerts — each with its own format,
its own cadence and its own noise — with **a single filtered feed**.

A first run (`--no-seed`, empty database, so everything counts as new) across the
twenty-one configured sources:

```
14:41:43 INFO    equifax              9 jobs ·   9 new ·   1 notified
14:41:46 INFO    pg                   3 jobs ·   3 new ·   0 notified
14:41:49 INFO    cisco                1 jobs ·   1 new ·   0 notified
14:41:53 INFO    hpe                 17 jobs ·  17 new ·   7 notified
14:41:55 INFO    West Monroe          6 jobs ·   6 new ·   1 notified
14:41:58 INFO    Konrad              23 jobs ·  23 new ·  12 notified
14:42:00 INFO    Datasite             0 jobs ·   0 new ·   0 notified
14:42:07 INFO    experian            18 jobs ·  18 new ·   4 notified
14:42:10 INFO    akamai               9 jobs ·   9 new ·   8 notified
14:42:13 INFO    oracle               2 jobs ·   2 new ·   1 notified
14:42:16 INFO    microsoft            8 jobs ·   8 new ·   1 notified
14:42:18 INFO    gorillalogic         9 jobs ·   9 new ·   1 notified
14:42:22 INFO    bcg                 15 jobs ·  15 new ·   1 notified
14:42:28 INFO    mastercard           3 jobs ·   3 new ·   0 notified
14:42:31 INFO    roche               16 jobs ·  16 new ·   9 notified
14:42:33 INFO    moodys              28 jobs ·  28 new ·  17 notified
14:42:36 INFO    Citi                14 jobs ·  14 new ·   5 notified
14:42:43 INFO    Workday              6 jobs ·   6 new ·   1 notified
14:42:45 INFO    ibm                  4 jobs ·   4 new ·   3 notified
14:42:48 INFO    teknowledge          6 jobs ·   6 new ·   0 notified
14:42:51 INFO    amazon               7 jobs ·   7 new ·   4 notified
14:42:51 INFO    total: 204 jobs · 204 new · 76 notified · 21/21 sources ok
```

From the second run on, `new` is only what actually appeared since the last one —
which is the point: a handful of lines a day instead of twenty inboxes.

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

| Platform             | How to recognize it                | How it's solved               | Status                                        |
| -------------------- | ---------------------------------- | ----------------------------- | --------------------------------------------- |
| Greenhouse           | `boards.greenhouse.io/<company>`   | Public JSON API, filtered locally | ✅ live (West Monroe, Konrad)              |
| Lever                | `jobs.lever.co/<company>`          | Public JSON API               | template ready, no company yet                |
| Ashby                | `jobs.ashbyhq.com/<company>`       | Public JSON API               | template ready, no company yet                |
| Workday              | `<tenant>.<dc>.myworkdayjobs.com`  | JSON POST to `/wday/cxs/`     | ✅ live (P&G, Workday, Datasite)               |
| Phenom               | `/widgets` endpoint                | POST + CSRF token in a JWT    | ✅ live (P&G, Cisco, HPE, Roche, Mastercard, BCG) |
| Radancy / TalentBrew | assets on `tbcdn.talentbrew.com`   | GET, HTML inside JSON or SSR  | ✅ verified live (Moody's, Citi)               |
| Jibe / iCIMS         | `app.jibecdn.com`, `domain=…jibeapply.com` | 1 GET, no token       | ✅ verified live (TeKnowledge)                 |
| Equifax              | its own XML feed                   | 1 GET to the feed             | ✅ verified live                               |
| Amazon               | `amazon.jobs/api/jobs/search`      | 1 POST, no token              | ✅ verified live                               |
| IBM                  | `www-api.ibm.com/search/api/v2`    | 1 POST, Elasticsearch-shaped  | ✅ verified live                               |
| Oracle Recruiting Cloud | `*.fa.*.oraclecloud.com/hcmRestApi` | GET, Oracle "finder" syntax | ✅ live (Oracle, Akamai)                   |
| Eightfold / PCSX     | `/api/pcsx/` endpoints             | 1 GET, no token               | ✅ verified live (Microsoft)                   |
| BambooHR             | `<company>.bamboohr.com/careers`   | `careers/list` returns JSON   | ✅ verified live (Gorilla Logic)               |
| Attrax               | `attrax-*` classes in the markup   | server-rendered HTML          | ✅ verified live (Experian)                    |
| Heavy JS with no API | nothing in the Network tab         | Playwright                    | last resort, no cases yet                     |

Twenty-one companies, twelve platforms. Nine of them — Greenhouse, Workday,
Phenom, Radancy, Jibe, Oracle Recruiting Cloud, Eightfold, BambooHR and Attrax —
are parameterized templates, so the next company on any of those is a YAML entry.
Only Equifax, Amazon and IBM run something of their own and needed a module.

The "how to recognize it" column is a starting point, not a test: a company can
proxy an ATS behind its own domain and leave no trace of it in the Network tab.
Konrad looks like a bespoke backend and is a Greenhouse board — see the
reverse-engineering notes.

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
3. **Filters** — include/exclude by title, a location hint, and a gate on the
   ATS's own category.
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
it's tolerable; with twenty-one, something breaking every now and then is the
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

Most fetchers also run standalone, which is the quick way to check whether a
source is still alive:

```bash
python -m jobbot.fetchers.equifax
python -m jobbot.fetchers.phenom       # P&G, Cisco, HPE and Roche
python -m jobbot.fetchers.workday
python -m jobbot.fetchers.radancy      # Moody's
python -m jobbot.fetchers.jibe         # TeKnowledge
python -m jobbot.fetchers.oraclecloud  # Oracle and Akamai
python -m jobbot.fetchers.eightfold    # Microsoft
python -m jobbot.fetchers.bamboohr     # Gorilla Logic
python -m jobbot.fetchers.attrax       # Experian
python -m jobbot.fetchers.ibm
python -m jobbot.fetchers.amazon
```

`ats.py` (Greenhouse, Lever, Ashby) and `generic_html.py` have no standalone
mode; for those use `python run.py --dry-run --source Konrad`, which works for
any source and is the general answer.

### Tests

```bash
pip install -r requirements-dev.txt
pytest
```

122 tests, ~0.15 s, and **none of them touch the network or Telegram**: they run
without credentials and offline. They cover the filters, the SQLite database
(dedupe, alert threshold and the `source_health` migration), the message
formatting and the pure functions of the fetchers — date parsing, location
assembly and decoding Phenom's JWT.

The fetchers themselves are deliberately left out: they talk to twenty-one sites
that change whenever they feel like it, and a test that depends on that fails for
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

The boards that already have a preset are one line: `pg`, `cisco`, `hpe`,
`roche`, `mastercard` and `bcg` on Phenom; `moodys` on Radancy; `teknowledge` on
Jibe; `oracle` and `akamai` on Oracle Recruiting Cloud; `microsoft` on Eightfold;
`gorillalogic` on BambooHR; `experian` on Attrax; plus `equifax`, `amazon` and
`ibm`. For a new Phenom one you use `type: phenom` with the values you can see in
the POST to `/widgets` (`site`, `page_id`, `ref_num`, `id_prefix`); the full
example is commented out in `config/sources.yaml`.

On Workday, `countries` takes the country **name** exactly as the site's filter
shows it. Internally Workday doesn't filter by name but by an opaque ID (Costa
Rica = `99abe7e6bb3f4c108aebebf01a369ec5`), so the fetcher reads the facet catalog
that comes in the first response and translates the name on its own. That saves
you from hunting down GUIDs by hand — and, more to the point, from guessing the
facet's *name*, which really does change per tenant. See the reverse-engineering
notes.

If the board doesn't belong to any known platform, it falls back to `type: html`
with a CSS selector — and if there's nothing in the HTML either, then it's
Playwright time.

The filters also live in `config/sources.yaml`, so they can be tuned without
touching Python:

```yaml
filters:
  include: ['\bjunior\b', '\bdata\b', '\bqa\b', '\bdeveloper\b', ...]   # 75
  exclude: ['\bsenior\b', '\bmanager\b', ...]                          #  9
  location_hints: ["remote", "costa rica", "heredia", ...]             #  9
  strong_include: ['\bengineer\b', '\barchitect\b', '\bqa\b', ...]     # 42
  nontech_categories: ['accounting', 'finance', 'customer', ...]       # 15
```

Four gates, in this order:

1. **`exclude`** — a title that matches is dropped even if it matches `include`.
2. **`include`** — an OR: one match is enough. It mixes two ideas, seniority and
   domain, so the real rule is "junior OR technical", not "junior AND technical".
   Narrowing seniority is entirely `exclude`'s job.
3. **`location_hints`** — what lets "remote" through. `[]` skips the gate.
4. **The category gate** — the only one that reads structured data instead of
   guessing from the title.

### The category gate

Most of the twenty-one sources carry the ATS's own `category`, which beats any
amount of word matching. It is deliberately **not** a hard block: companies file
roles under the business unit they serve, so a real BI Developer sits under
"Finance & Audit" and an HR internship sits under "Cloud". So a non-technical
category only raises the bar — the title then needs a word from
`strong_include`, and a weak one like `analyst` or `data` no longer suffices.

Measured on one day's real catalog, it removed 10 of 40 postings that passed the
word filter (accounting analysts, an HR enablement role, an administration
analyst) while keeping the two technical ones misfiled under Finance.

The category is never folded into the matched text. If it were, every HPE posting
would match `\bengineer\b` through its "Engineering & QA" category and `include`
would stop meaning anything. Moody's carries no category at all, so it skips this
gate and runs on words alone — an absent category is not evidence of anything.

`nontech_categories: []` turns the gate off.

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

The workflow's *Run workflow* button takes a **Preview only** checkbox that runs
it with `--dry-run`: it prints what it would notify into the Actions log without
sending anything or writing the database. A second manual-only workflow,
`telegram-test.yml`, sends one fixed message to prove the repo Secrets reach
Telegram — useful because a normal run notifies nothing when the dedupe finds
nothing new, so a green run alone doesn't tell you the credentials work.

It's worth verifying the cache by hand once, because it's the point that breaks
most easily and the quietest one: run the workflow **twice in a row** and confirm
the second one says `0 new`. If it says `seeding (no notifications)`, or if the
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
- **The category gate raises the bar instead of blocking.** A non-technical ATS
  category doesn't discard a posting outright, it just demands a stronger word in
  the title. Companies file roles under the business unit they serve, so a hard
  block would throw the BI Developer sitting under "Finance & Audit" out along
  with the accountants. Measured on a real day: 10 of 40 removed, both misfiled
  technical roles kept.
- **Amazon is the exception, and filters by category at the source.** It posts so
  much outside of engineering that fetching everything means 73 Costa Rica
  postings to end up keeping 7. The difference from filtering by keyword is that
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
- **Roche runs a newer Phenom skin (CareerConnect)** that renames half the
  payload: `clientName` instead of `refNum`, `cultureName` instead of `lang`, and
  no `pageId` at all. All of it fits in the template's `extra`. Two traps: the
  request the browser fires when you tick a facet has **no `jobs: True`** and
  comes back with `hits: 0` and no job array — only facet counts, while
  `totalHits` still shows the right number, so it looks like the correct call and
  returns nothing usable. And `keyword` is **ignored**: searching "Costa Rica"
  returns the same 1230 as an empty keyword. The country filter is
  `selected_fields.country`, same as every other Phenom tenant.
- **Workday names the country facet differently per tenant.** P&G hangs it off
  `locationMainGroup` under `locationCountry`; Workday's own tenant exposes
  `Location_Country` as a flat top-level facet. Guessing one name made the
  template fall through to its "fetch everything" fallback: 346 postings, nearly
  all American. That is not a benign failure — `location_hints` includes
  "remote", so a remote role in Virginia would have sailed past the location
  gate. `_resolve_country_facets` now returns the parameter name it matched,
  because `appliedFacets` has to be keyed by that same name. Side finding: the
  Costa Rica GUID is identical on both tenants, so these IDs are Workday-global,
  not per-tenant as first assumed.
- **Radancy has two tenant shapes and two HTML skins.** Moody's answers the
  `/en/search-jobs/results` JSON endpoint; Citi returns that same endpoint with
  `results` empty and instead renders the postings into the search page, whose
  path carries the filters
  (`/search-jobs/{kw}/{orgId}/{subId}/{geoId}/{lat}/{lon}/{radius}/{page}`). So
  the fetcher tries JSON first and falls back to the page. The markup differs
  too: `search-results-list__*` at Moody's, `sr-*` at Citi. A tenant with a third
  skin would parse as zero postings, and the down-source alert would **not** catch
  it — an empty list isn't an error.
- **Jibe / iCIMS (TeKnowledge)**: `apply_url` is useless as a link — it points at
  `careers-teknowledge.icims.com/jobs/<id>/login`, the login screen, exactly like
  Amazon's `urlNextStep`. The public page is `<site>/jobs/<req_id>`. An unknown
  country answers HTTP 200 carrying `{"error": …}` and **no `jobs` key**, which
  unchecked reads like "this company has no openings here", forever. The
  `domain=<tenant>.jibeapply.com` parameter turned out to be optional, and
  `BOT_UA` is enough — no need to pose as a browser. Unlike Radancy, `location`
  alone filters correctly, but dropping it returns the global catalog (43 across
  6 countries), so the country is still revalidated locally.
- **Greenhouse, Lever and Ashby don't filter by location at all.** The board's
  own UI downloads everything and filters in the browser — West Monroe's response
  carries `meta.total: 141` and all 141 postings, with no `page`/`offset` to be
  found. So the country filter has to live in the fetcher. Left as it was, this
  template would have handed the orchestrator the whole board, and since
  `location_hints` includes "remote" a remote Chicago role would have sailed
  through the location gate. That is the fourth source where the same shape of
  bug turned up — after Workday's facet fallback, Radancy's all-or-nothing
  location params and Jibe's missing `location` — which is what makes "remote" in
  `location_hints` the structural soft spot of the design: **any source that
  quietly stops filtering by country becomes a firehose of foreign postings.**
  Here, discarding 135 of 141 is the normal path rather than a failure, so unlike
  `radancy.py` it doesn't warn.
- **BCG filters by country through `keywords`**, URL-encoded inside the JSON
  (`"Costa%20Rica"`). The preset uses `selected_fields.country` instead: after
  Roche, where `keyword` turned out to be ignored outright, the structured facet
  is the one that doesn't depend on the country appearing in the posting's text.
  Its `x-csrf-token` is the usual Phenom one, so `_open_session` handles it.
- **Mastercard is the plain Phenom payload** — `pageId`, `all_fields`,
  `jdsource: facets` — so it needed nothing but its own values. One of its five
  Costa Rica postings is filed in Bogotá with Costa Rica among six sites, and
  arrives annotated rather than dropped, same as HPE.
- **Oracle Recruiting Cloud filters by an opaque geography id, and the ids are
  per tenant.** Unlike Workday's, which turned out to be global — the same Costa
  Rica GUID works on P&G, Workday and Datasite. Verified by crossing them:
  Akamai's Costa Rica id returns 0 on Oracle's tenant and Oracle's returns 0 on
  Akamai's. The response's `locationsFacet` only lists the 18 most common
  locations, so there is nothing to resolve the name against the way `workday.py`
  does, and the ids have to be carried per source. A wrong id returns
  `TotalJobsCount: 0`, indistinguishable from a company that isn't hiring.
- **Eightfold (Microsoft) caps `num` at 10** whatever you ask for, while `count`
  reports the real total — so a fetcher that trusts `num` silently keeps only the
  first page. Its `locations` reads **"Country, State, City"**, country first,
  the opposite of every other source, and unfilled levels come back as the
  literal string "Multiple Locations".
- **BambooHR (Gorilla Logic) returns every structured location field as null** —
  `location`, all four of `atsLocation`, `isRemote`. The country lives only in
  the title text ("… Remote: Colombia - Costa Rica, Full Time …"), so the obvious
  implementation, filtering on `atsLocation.country`, returns zero postings
  forever. The postings are painted server-side into the company's own domain,
  but `<company>.bamboohr.com/careers/list` serves the same list as JSON — it is
  the call the company's own server makes.
- **Attrax (Experian) has no JSON endpoint at all**; the postings are rendered
  into the search page and searching reloads the document. One of the few cases
  where parsing HTML is the right answer rather than a last resort. `q` is a text
  search rather than a country facet, and it does leak: revalidating locally
  discarded a posting that wasn't in Costa Rica.
- **Workday's `locationsText` is whatever the tenant types.** P&G writes
  "Costa Rica", Datasite writes "CRI - San Jose" — the ISO-3, no country name
  anywhere. The second shape only survived the location gate because "san jose"
  happens to be in `location_hints`; a posting in another city would have been
  dropped in silence. Since the country facet already filtered, the country is
  appended when the text omits it, the same treatment `amazon.py` and `ibm.py`
  give their ISO-3 and ISO-2 fields.
- **"I can't read the facet" and "the country isn't in the facet" are not the
  same answer, and conflating them cost Datasite.** The fetcher resolved country
  names against the facet catalog and returned `(None, [])` whenever it came up
  empty — which covered both "this tenant names the facet something I don't
  know" and "this tenant simply has no openings there". The caller answers that
  by fetching the global catalog and letting the orchestrator filter, which is
  right for the first case and a firehose for the second. Datasite closed its
  last Costa Rica role and immediately began returning **all 37 of its worldwide
  postings**.
  What made it dangerous rather than merely noisy is that it disabled its own
  safety net: `_location` appends the country when the text omits it, on the
  premise that "the API already filtered". On the fallback path nothing
  filtered, so it stamped `(Costa Rica)` onto jobs in New York, Milan and Tokyo
  — and since `location_hints` matches on that same string, **the location gate
  was reading text the fetcher had just fabricated**. Seven foreign postings
  passed as Costa Rican. The two fixes are separate and both matter: the
  resolver now returns the facet name even with no matching values, and
  `_location` only appends the country when a filter was actually applied.
  Deciding that an absent country means "no openings" needs one guard, because a
  truncated facet list would look identical: the counts have to account for the
  whole catalog. They sum to **at least** the total rather than exactly it —
  Workday counts a multi-country posting once per country, so P&G reports 692
  across 49 countries for 687 postings. A sum *below* the total is the tell that
  the list is truncated, the way Oracle's `locationsFacet` is, and then the
  fetcher falls back to fetching everything as before.
- **IBM** runs its own unified search endpoint, Elasticsearch-shaped, behind
  opaque field names (`field_keyword_05` is the country, `_08` the business area,
  `_18` the level, `_19` the city). An unknown country returns **`total: 0`, not
  an error**, so there is no way to tell "IBM isn't hiring here" from a typo — the
  country is therefore validated first against the aggregation that lists all 45
  countries in the index, the same trick `workday.py` uses. `field_keyword_19`
  carries the ISO-2 (`"Heredia, CR"`), so the location is rebuilt with the
  country name for `location_hints` to match, exactly like Amazon's ISO-3. The
  four `aggs` blocks the browser sends only paint the sidebar counts; only the
  country one is kept, and only to validate.
- **Konrad looks like a custom backend and is a Greenhouse proxy.** konrad.com is
  a TanStack Start app: the careers page loads through `/_serverFn/<hash>`
  endpoints whose arguments travel as a Seroval-serialized `payload`, and
  replaying one outside the browser gets a 403 or a "Seroval Error". Everything
  about it says "write a new fetcher, and expect to fight a session for it."
  The tell that it isn't is in the data — the posting ids the front-end passes
  around (`6622525003`, `7530792003`) are Greenhouse ids, and `boards.greenhouse.io`
  had never been checked because no `greenhouse.io` request ever appears in the
  Network tab. `boards-api.greenhouse.io/v1/boards/konradgroup/jobs` answers with
  the same 23 Costa Rica postings, no cookies, and even hands back
  `absolute_url` pointing at konrad.com. **Before reverse-engineering a
  proprietary-looking endpoint, take an id from its payload and try the ATS
  boards against it** — a proxied board leaves the upstream's ids in plain sight.
- **Konrad also writes one of its 23 postings as just "San José"**, no country,
  where the other 22 say "Costa Rica" — so `countries: ["Costa Rica"]` alone
  drops it. Same failure Datasite's "CRI - San Jose" caused, but a rung earlier:
  there the country filter had already run server-side and only the location gate
  was at risk, here it's the country filter itself. Greenhouse has no server-side
  location filter to lean on, so the fix is config — the city goes in `countries`,
  in both spellings, since the accented one is what the board writes today and
  nothing stops it from normalizing. It buys the risk that a San Jose, California
  posting would pass; Konrad's US office is New York, and this project's recurring
  lesson is that a silent miss costs more than a stray notification.

### Verification status

Postings in Costa Rica, and how many survive the filters. Counts drift as the
boards change; these are one day's snapshot.

| Source                       | Fetched | Pass | Notes                                        |
| ---------------------------- | ------: | ---: | -------------------------------------------- |
| Moody's (Radancy, JSON)      |      28 |   17 | out of 251 globally                          |
| Konrad (Greenhouse)          |      23 |   12 | best absolute yield; 10 of 23 are Senior     |
| Roche (Phenom CareerConnect) |      16 |    9 | out of 1230 globally                         |
| Akamai (Oracle Recruiting)   |       9 |    8 | best ratio of the lot; mostly level II       |
| HPE (Phenom)                 |      17 |    7 | out of ~1060 globally, several multi-site    |
| Citi (Radancy, SSR)          |      14 |    5 | server-rendered, newer `sr-` markup          |
| Experian (Attrax)            |      18 |    4 | server-rendered; `q` is a text search        |
| Amazon (own ATS)             |       7 |    4 | 73 unfiltered by category                    |
| IBM (own search API)         |       4 |    3 | 3 are the same Cybersecurity Remediation team |
| Equifax (XML feed)           |       9 |    1 | mostly Accounting, cut by the category gate  |
| West Monroe (Greenhouse)     |       6 |    1 | 6 of 141 on the board; 5 are Senior          |
| Microsoft (Eightfold)        |       8 |    1 | out of 1807 globally                         |
| Workday (tenant `workday`)   |       6 |    1 | out of 343 globally                          |
| Gorilla Logic (BambooHR)     |       9 |    1 | all remote CR+CO; 8 of 9 are Senior or Lead  |
| BCG (Phenom)                 |      15 |    1 | out of 879 globally; 10 of 15 are Senior     |
| Oracle (Oracle Recruiting)   |       2 |    1 | out of 2321 globally                         |
| Datasite (Workday)           |       0 |    0 | its 37 are all abroad; had 1 when it was added |
| P&G (Phenom)                 |       3 |    0 | only consumer-relations roles                |
| Mastercard (Phenom)          |       3 |    0 | all Senior or Manager, advisory org          |
| Cisco (Phenom)               |       1 |    0 | out of ~1000 globally                        |
| TeKnowledge (Jibe/iCIMS)     |       6 |    0 | all Customer Support                         |
| **Total**                    | **204** | **76** |                                            |
| Lever / Ashby                |       — |    — | ⚠️ code ready, never run live                |

The split is worth reading: the sources that yield are engineering and IT
delivery centres, and the ones that yield nothing are consultancies and BPO.
That is a property of the companies, not of the filter — see `CANDIDATES.md`.

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
    ats.py                Greenhouse, Lever, Ashby (public API, local country filter)
    amazon.py             amazon.jobs (POST with no token)
    attrax.py             Attrax careers sites (server-rendered) + Experian
    bamboohr.py           BambooHR careers/list + Gorilla Logic
    eightfold.py          Eightfold/PCSX + Microsoft preset
    equifax.py            XML feed
    ibm.py                IBM's own search endpoint (Elasticsearch-shaped)
    jibe.py               Jibe/iCIMS + TeKnowledge preset
    oraclecloud.py        Oracle Recruiting Cloud + Oracle, Akamai presets
    phenom.py             Phenom (JWT CSRF) + 6 presets incl. Roche, BCG
    radancy.py            Radancy/TalentBrew (JSON or SSR) + Moody's, Citi
    workday.py            Workday (CXS POST + facets)
    generic_html.py       last resort: CSS selector
tests/                    122 tests, no network (see tests/README.md)
.github/workflows/
  job-alerts.yml          the bot, every 30 min (+ manual dry-run button)
  telegram-test.yml       manual-only: proves the Secrets reach Telegram
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
