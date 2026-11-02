# CARO as services — the design, measured before the code

Written 2026-11-02. The owner decided that CARO becomes a set of services,
because the listings are going to grow to tens of thousands. D56 kept CARO in
one process until a measurement showed where it breaks; this document is that
measurement, and the design it leads to. Nothing in it is built yet: each
step below is a pull request of its own, measured and tested like any other.

**Chosen by the owner, 2026-11-01 and 2026-11-02:**

- services, for tens of thousands of listings;
- **Postgres alone**, for the data and for the work queue — no Redis;
- **Docker now**, a Dockerfile per service and one `docker-compose.yml`;
  **Kubernetes later**, with nginx, when a server exists;
- collectors run **on the owner's machine** for now; a server later;
- the site serves Khodro45's corpus instead of run16, after a measurement of
  what changes.

## Where the shape breaks, measured

Synthetic corpora drawn from run17's 492 rows, each row given its own id and
its price and odometer jittered; they measure load and speed, nothing about
the market, and are not committed. Main `cad4e54`, network off, each size in
a process of its own:

| listings | corpus file | first API request | process memory | `/api/models` | `/api/model` | search | one listing |
|---|---|---|---|---|---|---|---|
| 10,000 | 7.6 MB | 2.5 s | 205 MB | 56 ms | 42 ms | 14 ms | 7 ms |
| 50,000 | 38 MB | 11.4 s | 712 MB | 254 ms | 192 ms | 42 ms | 7 ms |
| 100,000 | 76 MB | 22.1 s | 1.36 GB | 549 ms | 368 ms | 67 ms | 7 ms |

- **History breaks first.** A model's page reads the middle asking price of
  every published run (`published_runs()`), and that loads every corpus into
  memory and validates each one. Ten daily runs of 10,000: **20.5 s** and
  508 MB on the first request. A month of daily runs would take about a
  minute and 1.5 GB on a cold process — past what a serverless function may
  use, and every visitor after a deploy would wait for it.
- **Every read re-validates.** `load_corpus` runs both guards over the whole
  text each time a process starts. Promotion already runs them once (10,000
  records: 2.2 s); doing it again on every read is most of the cold start.
- **Git is the wrong store for daily runs.** A run of 10,000 is 7.6 MB of
  JSON; thirty a month add about 230 MB to the repository's history.
- **What does not break:** the parser, the gate, the quality rules and the
  search (67 ms at 100,000). The slowest warm request is `/api/models` —
  half a second at 100,000 — because it groups every row on every call.

So the first boundary is **the data**, not the logic.

## What does not change

- **One language, one library.** Every service imports `caro`. What
  «absent» means, the fault codes, the price statuses, the gate and the
  quality rules exist once, in `caro/` — the reason D56 gave for one
  process holds for every service: two services must never hold two copies
  of a rule. Between services, contract tests, as between the API and the
  site today.
- **Every rule about the sources.** robots.txt read in code and obeyed, one
  pause per request, a stop on a block, no rotation of anything, no phone
  number of a seller stored, `CARO_SELLER_SALT` outside the repository.
  Live requests start on the owner's machine, by his decision, until he
  decides otherwise.
- **The suites run offline.** Postgres in production, SQLite in the suites
  through the same module, as the seller store already does
  (`webapp/api/store.py`); CI runs the same tests once more against a real
  Postgres.
- **`caro.corpus/1` stays the published format.** A run promoted into the
  database is also written as the JSON it is today, so what was published
  can still be read, checked and replayed without a database.
- **Migrations only add.** A table or a column is added, never renamed or
  dropped under a running reader.

## The services

| service | does | owns | runs |
|---|---|---|---|
| **collector** | reads a source as `first_run.py` does — one worker per source, so the parallelism is between domains, never against one (D56) | snapshots, on the owner's machine | the owner's machine, Docker |
| **ingest** | promotes a snapshot: the records, the guards, the far-price rule, then the run's rows and its model summaries into Postgres, and the JSON export | `runs`, `listings`, `model_runs` | a worker, Docker |
| **catalog API** | today's FastAPI: models, a model's page and history, a listing, the search — read from Postgres; from files where no database is set | nothing; reads | the API, Docker or Vercel |
| **decision** | the appraiser, the ranking and the review (W1, W3, W2) | — | inside the catalog API, as a library call, until a measurement says a model's training is heavy enough to need its own worker |
| **accounts** | the listings sellers post, and their login | `accounts`, `listings_posted` — the people's numbers, apart from everything else | inside the API until it is turned on; then its own service, so that personal data sits behind one door |
| **web** | the site | — | Vercel today; the server later |

The decision core is kept in the API on purpose: it is fast (the search at
100,000 is 67 ms), and splitting it would put a network boundary in the
middle of the chain the suites check end to end today.

## The data

```
runs        run_id PK · source · collected_on · promoted_on · listings · provenance (json)
listings    (run_id, listing_id) PK · make · model · trim · year_jalali · mileage_km
            · asking_price_toman · price_status · price_kind · product_class
            · province · province_source · condition · … every corpus field
            index (run_id, make, model) · index (listing_id)
model_runs  (run_id, make, model) PK · listings · priced · price_min · price_median · price_max
jobs        id · kind · payload (json) · state · run_after · attempts · locked_by · locked_at · error
```

- `model_runs` is computed once, when a run is promoted, by the same rule the
  site uses today (`priced()` in `webapp/api/market.py`); a model's history
  becomes one indexed read instead of every corpus in memory. A suite row
  holds the stored middle equal to the one computed in Python, run by run.
- `/api/models` reads the served run's rows of `model_runs` instead of
  grouping every listing on every request.
- **The queue is a table.** A worker takes a job with
  `SELECT … FOR UPDATE SKIP LOCKED`, so two never take the same one; a job
  is idempotent (promoting a run twice writes it once), retried with a
  backoff, and its error kept. One collector per source holds that source's
  lock, so the pause between requests to a domain is never shared out.

## The way there — each step a pull request, the site never down

1. **The catalog store.** The tables above, SQLite and Postgres behind one
   module; a loader that reads `data/corpora/*.json` into it, idempotent;
   the API reads it where `DATABASE_URL` is set, files otherwise. The
   contract suite runs both ways and the answers must be the same.
2. **Ingest.** Promotion writes into the store as well as the JSON, and
   fills `model_runs`.
3. **Serving Khodro45** (the owner's choice, after its measurement): which
   models, counts and examples change on the site when run17 replaces run16,
   then the switch.
4. **The queue and the collector.** The `jobs` table, a worker that runs a
   Khodro45 collection on a schedule on the owner's machine and hands its
   snapshot to ingest.
5. **Docker.** An image for the API and the workers (one image, two
   commands), one for the site, Postgres; `docker-compose.yml` with health
   checks; secrets only in an `.env` that never enters the repository; CI
   builds the images and brings the stack up once.
6. **Kubernetes**, when the server exists: the same images, a Deployment
   each, a CronJob for the daily collection, nginx in front.

What the owner will be asked on the way: where Postgres lives once the site
is served from it (the server, or a managed one), and when collection leaves
his machine — that changes a rule of the working agreement, so it is his.

## What it costs

- Two ways to read data during the move — files and the store — until step 3
  is done; the contract suite runs both, so they cannot drift.
- A database to keep: backups, upgrades, a password outside the repository.
- More moving parts in a deploy. The site is never switched to the store
  before the store has served the same answers as the files in CI.
