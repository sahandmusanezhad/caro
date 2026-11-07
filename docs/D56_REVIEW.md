# D56, reviewed: its three conditions, measured

D56 keeps CARO in one language: no Go fetcher, no Go service, no second
place for a number to change on its way past. It is reopened by any one of
three conditions, "demonstrated rather than anticipated". Phase 7 of the
plan asks for the three to be measured, and then for a written decision on
Go for the collector and on any service boundary.

`scripts/d56_measure.py` makes each measurement. This file records:

- what it measured on 2026-11-06, in the session's sandbox, with the network
  off;
- what waits on the owner's data.

The decision is the owner's. By D56's own rule, a condition not
demonstrated reopens nothing.

## The predictions, locked before the code

Written at 08:05 UTC on 2026-11-06, before any line of the script:

- **P1, the hot path.** An in-process search over run17 spends more on
  building and validating the answer (FastAPI, pydantic, JSON) than on any
  one of CARO's stages. Of CARO's stages, the intent parser is the largest.
  A whole search, in process, is under 5 ms.
- **P2, the stages, on run17 grown to 50,000 listings.** Every stage grows
  about linearly: a log-log slope of 0.8 to 1.2 between 5,000 and 50,000
  listings. At 50,000:
  - the free-text parser is the slowest, over 1 s;
  - serialisation and the read back are each under 1 s;
  - the index build is under 2 s;
  - the comparison of two runs is under 0.5 s;
  - one search is under 200 ms.
- **P3.** At 50,000 listings no stage takes more than 10 s, while collecting
  that many at the permitted rate takes hours. So no stage is a bottleneck
  another language would move.

What they got wrong is at the end.

## 1. A multi-source crawl that no longer finishes in its window

**Not measured: no run has been recorded.**

`d56_measure.py window` reads each Tehran day's collected runs from the
runs' database, where the worker reports them (phase 3). For each source it
takes the day's longest run, then adds the sources one after another and
sets them side by side. The parallelism D56 means is between domains, so the
condition is met only on a day of more than one source that, side by side,
did not finish in its window (6 h unless told otherwise).

On 2026-11-06 the worker had not run anywhere: [PHASE3_SETUP](PHASE3_SETUP.md)
is the owner's, and no record had reached a server. Khodro45 runs daily on
the owner's machine, 60 pages a run, and Divar has not run live. One source a
day cannot meet the condition.

At D56's own measured pace, 114 s for 20 requests (5.7 s each, politeness
included), a source would need about 3,800 requests in a day before its own
run alone passed six hours. That is a bound from D56's numbers, not a
measurement. Khodro45's run is 60 pages.

On the server, once records arrive:

```
docker compose -p caro-production --env-file /etc/caro/production.env \
  -f compose.vps.yml exec api python scripts/d56_measure.py window
```

## 2. `duration_stats` genuinely running

**Not measured here: the observations are on the owner's machine.**

`d56_measure.py durations` folds two inputs into tracking state, day by day:

- the snapshots under `data/snapshots/`;
- date_watch's observations, `data/observations/date_watch.jsonl`.

It prints the observed disappearances against D56's thirty, with the
censored and the left-truncated apart, and what folding them cost.

Writing this review found that the snapshots alone cannot meet the
condition. A disappearance is an outcome `absent` in a snapshot to be
trusted, and only date_watch writes one: it fetches a tracked listing's own
page. A run of list pages, like the daily Khodro45 run, never records a
listing leaving its list. The watch's observations are therefore counted
too.

D56 recorded one listing watched from present to gone (`xlyildqb`,
2026-09-14). On the owner's machine, in the checkout:

```
python3 scripts/d56_measure.py durations
```

## 3. A stage that is the bottleneck, and transferable

**Measured: none is.**

`d56_measure.py stages` grows the served corpus, run17's 492 listings, by
copying its own listings under new ids, so that every stage does the work
real listings ask of it. It then times each stage. In the sandbox, 4 cores,
with the network off:

| stage | 500 | 5,000 | 50,000 | slope, 5k to 50k |
|---|---|---|---|---|
| the free-text parser (`parse_listing`) | 0.244 s | 2.289 s | 24.415 s | 1.03 |
| canonicalisation (`extract_make_model`) | 0.031 s | 0.305 s | 3.292 s | 1.03 |
| serialisation (`json.dumps`) | 0.002 s | 0.023 s | 0.233 s | 1.01 |
| the read back (`json.loads`) | 0.002 s | 0.023 s | 0.224 s | 0.98 |
| the index build (`rows_from_corpus`) | 0.008 s | 0.049 s | 0.745 s | 1.18 |
| the comparison of two runs | 0.000 s | 0.004 s | 0.057 s | 1.15 |
| one search (`retrieve`, the eight questions' mean) | 0.001 s | 0.003 s | 0.035 s | 1.01 |

- **The parser is the slowest stage.** It costs 0.49 ms a listing and grows
  linearly.
- **It is not where a run's time goes.** Collecting the same 50,000 at 25
  listings a page is 2,000 pages, or about 3.2 hours at D56's 5.7 s a
  request. The parser's 24 s is 0.2% of that. Moving it to another language
  would move 0.2% of a run, and leave the 99.8% that is politeness, which is
  a product commitment and not a speed.
- **Nothing grows faster than the listings.** The index build's slope of
  1.18 is the steepest. A search over 50,000 listings is still 35 ms, a
  tenth of the 300 ms target.

## The hot path

Phase 7 also asks for the search's hot path profiled and its slowest stage
named. This is not one of D56's conditions. `d56_measure.py profile` times
each stage of a search on its own, over the eight questions perf/search.js
asks, with no profiler in the way. In process, per search:

| part | time |
|---|---|
| the intent parser | 0.13 ms |
| the evidence | 0.21 ms |
| the endpoint, whole | 0.33 ms |
| the answer encoded as JSON | 0.30 ms |

The slowest part is not CARO's code but what a request goes through before
and after it: routing, the response's validation, and four middlewares.
Measured through the test client, best of five runs of 480 searches:

- **The four middlewares together** cost 1.1 ms of a search.
- **The newest of them, this phase's own counter,** was the largest single
  one: 0.34 to 0.42 ms. It was built on Starlette's BaseHTTPMiddleware,
  which runs each request through streams and a task group of its own.
- **Rewritten as plain ASGI,** it costs 0.02 to 0.04 ms. The four together
  cost 0.95 ms.

The next two are the edge's cache and the security headers, both still on
BaseHTTPMiddleware ([PERF](PERF.md)).

## What the predictions got wrong

- **P1.** Half right: encoding the answer (0.30 ms) outweighs either of
  CARO's stages. Two things were wrong:
  - the evidence (0.21 ms) is the larger of CARO's stages, not the intent
    parser (0.13 ms);
  - it did not foresee the largest part at all, the middlewares and the
    routing around the endpoint.

  "Under 5 ms" held.
- **P2.** Right throughout: every slope is between 0.98 and 1.18, and every
  stage is within its bound.
- **P3.** Wrong in its number: the parser takes 24 s at 50,000 listings, not
  under 10. Right in its conclusion: the collection of the same listings
  takes hours.

## What D56's rule says

None of the three conditions is demonstrated:

- the first is not measured: no run has been recorded;
- the second is not measured here: the observations are the owner's;
- the third is measured, and no stage is a bottleneck.

D56's words are: until one of those is on the table, measure first, then add
a boundary. On this record it stands. The written decision on Go for the
collector, and on any service boundary inside the decision core, is the
owner's to make, and its D-entry records it, whichever way it goes.

Phase 7's other question is Kubernetes: whether one server still holds ten
times the search's target. [PERF](PERF.md) has the sandbox's answer, a
hundred users at p95 278 ms in one process. The server's own run is
[PHASE7_SETUP](PHASE7_SETUP.md)'s.
