# SLOs, and every alert CARO raises

The plan's phase 7 asks for SLOs on availability, the search's 95th
percentile and the daily run, and for the full alert catalogue. Each SLO
here is read from what the API counts (`webapp/api/metrics.py`), which the
`observe` service writes to Grafana Cloud (`deploy/alloy/config.alloy`); each
alert is in `deploy/grafana/alerts.yml` and is tested by
`deploy/grafana/alerts_test.yml`, or is named below where it lives.

## The SLOs

Each is per environment, over 30 days, and the target is for production;
staging is read the same way and promises nothing.

| SLO | target | read from |
|---|---|---|
| **Availability** | 99.5% of the public reads answered without a fault of ours | `caro_requests_total`, the public reads, 5xx against all |
| **The search's speed** | 95% of searches answered within 300 ms, at the API | `caro_request_seconds_bucket{route="/api/search", le="0.3"}` against `_count` |
| **The daily run** | a collected run of each expected source every Tehran day, by its time | `caro_collection_last_run_timestamp_seconds`, and the server's alerts |

**The public reads** are `/api/search`, `/api/search/reweight`,
`/api/models`, `/api/model`, `/api/corpus`, `/api/compare`, `/api/health`
and `/api/listing/{listing_id}`: the routes whose 5xx is always a fault. A
503 elsewhere is a state the site was built to show: the seller listings
switched off, the worker's records switched off.

**99.5%** is 3 hours 36 minutes of failing reads in 30 days. That is about
what one server, deployed by pull every minute and restarted for updates,
can promise before it has a month of its own numbers. It is revised when it
has them.

**300 ms** is the target [PERF](PERF.md) set, with ten users. It is
measured at the API, so it leaves out the network and Cloudflare, which no
change to CARO's code can move. The histogram has a bucket at 0.3 s, so the
share within it is counted, not interpolated between two buckets.

**The daily run** is the alerts role's: `CARO_ALERT_EXPECT` names each
source and the time of day its run must have arrived by
([PHASE3_SETUP](PHASE3_SETUP.md)).

## The alerts

| alert | when | goes to | defined in |
|---|---|---|---|
| CaroApiDown | the API has not answered its collector for 5 minutes | page | `deploy/grafana/alerts.yml` |
| CaroErrorBudgetFastBurn | public reads failing 14.4 times as fast as the budget lasts, over 1 h and 5 min | page | `deploy/grafana/alerts.yml` |
| CaroErrorBudgetSlowBurn | 6 times as fast, over 6 h and 30 min | ticket | `deploy/grafana/alerts.yml` |
| CaroSearchSlow | under 95% of the last hour's searches within 300 ms, with at least 100 of them | ticket | `deploy/grafana/alerts.yml` |
| CaroCorpusNotReal | production's API answers and names no REAL corpus | page | `deploy/grafana/alerts.yml` |
| CaroCollectionUnread | the API cannot read the runs' database for 30 minutes | ticket | `deploy/grafana/alerts.yml` |
| CaroCollectionStale | a source has collected no run for more than 26 hours | ticket | `deploy/grafana/alerts.yml` |
| missing | an expected run did not arrive by its time | Telegram | `webapp/alerts.py`, on the server |
| stopped | a run stopped on robots.txt, a block, a source that could not be read, or an error of ours | Telegram | `webapp/alerts.py` |
| robots | robots.txt is not the file the run before read | Telegram | `webapp/alerts.py` |
| count | a run collected far fewer or far more listings than the runs before it | Telegram | `webapp/alerts.py` |
| the site down | `caro.noxioai.com` does not answer from outside | Telegram | UptimeRobot ([PHASE0_SETUP](PHASE0_SETUP.md)) |
| an error report | an error of ours in the API or a browser, with nothing personal | Sentry's mail | `webapp/api/observability.py` ([PHASE0_SETUP](PHASE0_SETUP.md)) |
| a published number is stale | `/about` or the README counts other than the suites run | the pull request | `tests/run_all.py`, CI's `suites` job |
| a page broken in a browser | a key route not right to left, two headings, wider than the screen, asking another origin, or erring | the pull request | `webapp/web/e2e/routes.mjs`, CI's `e2e` job and the images workflow |
| a deploy that did not arrive | an environment not running the commit, or not served through Cloudflare alone | the workflow's run | `scripts/deploy_wait.py`, `scripts/site_check.py --cloudflare` |

**Page** and **ticket** are the alerts' `severity`, for Grafana's
notification policy to route: a page to the Telegram contact point at
once, a ticket to the same chat by day ([PHASE7_SETUP](PHASE7_SETUP.md)).
The burn-rate pair is the usual one for a 30-day budget: 2% of it spent in
an hour pages, 10% in six hours is a ticket, and both windows must agree so
that one slow minute does not page and a fault that has ended stops
paging.

**Two alerts say the same thing twice, on purpose.** A missing run is said
by the server's alerts role, and CaroCollectionStale says it from outside
the server: should the server stop, its own alerts stop with it.

## What this does not measure

- The site's own pages: Next.js is not counted. The browser check walks
  every key route on each change, and UptimeRobot reads the home page
  from outside.
- Anything between the visitor and Cloudflare, or Cloudflare and the
  server.
- The worker's machine: it is the owner's. Its runs are known by the
  records they post, and a worker that stopped is known by the records that
  did not arrive.
