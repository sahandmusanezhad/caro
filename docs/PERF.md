# Performance — what the search answers under load, and the target

The plan's phase 4 asks for a k6 baseline on `/api/search` with a p95
target written down; its phase 7 asks for k6 at ten times the target. This
is where both are kept, each run with what it ran on.

The script is [`perf/search.js`](../perf/search.js): a number of users at
once, each asking the search one of eight questions the site's own checks
ask, in turn, with no pause between two — one API process kept busy. It
fails when its thresholds are not met: the 95th percentile of a search
under the target, and no more than one answer in a hundred failed.

## The target

**The 95th percentile of a search under 300 ms, with ten users at once, on
the server, through one API process** (`CARO_P95_MS=300`, the script's
default). Ten users with no pause between their questions is far more than
CARO has asked of it so far; 300 ms is ten times what this sandbox measured
for it, the margin for a server's two shared cores against four here, and
still well under the second a person waits for a search.

## Runs

| when | where | users | for | answers/s | p50 | p95 | p99 | max | failed |
|---|---|---|---|---|---|---|---|---|---|
| 2026-11-04 | the session's sandbox, 4 cores, the API's image, run17 (492 rows) | 10 | 60 s | 477 | 19.9 ms | 28.2 ms | 43.0 ms | 80.7 ms | 0 of 28,657 |
| 2026-11-04 | the same | 100 | 60 s | 436 | 224.8 ms | 278.2 ms | 299.8 ms | 847.4 ms | 0 of 26,188 |

Read from the two: one process answers about 450 searches a second here,
and adding users past that adds waiting, not answers -- a hundred users wait
on average 229 ms, which is a hundred over 436 a second, as a queue would.
Its memory stayed at 63 MB. The server's own runs, on staging, are the
owner's ([PHASE4_SETUP](PHASE4_SETUP.md), step 4); phase 7 runs the same
script at ten times the target there, and says whether one server still
holds it.

Each run: k6 v2.3.0 (`grafana/k6`), the API's image on the host's network,
`CARO_INBOX=off`, nothing else on the machine but the run.
