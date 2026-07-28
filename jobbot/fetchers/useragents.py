"""
The bot's two User-Agents, and why there are two.

`BOT_UA` identifies itself as what it is and points at the repo, which is the
right way to show up: if the traffic bothers someone, they know who it is and
where to complain. It's used where the source serves the content without
fighting — a public feed (Equifax), the open APIs of Greenhouse/Lever/Ashby, or
plain HTML.

`BROWSER_UA` is a Chrome string. It's used only on the four platforms that
**reject or degrade** a request that doesn't look like a browser: Workday
responds 200 with an HTML page instead of the JSON, and Phenom, Radancy and
Amazon serve the same API their own front-end consumes, which always sends this
header. In those cases the User-Agent doesn't bypass any access control: the API
is public and asks for no credentials; it only avoids a heuristic rejection.

Neither of them touches robots.txt or rate limits: each fetcher handles that
with its own pauses between pages. LinkedIn and Indeed are deliberately left out
of the bot, because there scraping really does go against their terms.
"""

REPO = "https://github.com/Esteban-PG/Job-alert-bot"

BOT_UA = f"job-alert-bot/1.0 (personal use; +{REPO})"

BROWSER_UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
              "AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/149.0.0.0 Safari/537.36")
