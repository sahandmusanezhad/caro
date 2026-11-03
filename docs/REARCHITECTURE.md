# Re-architecture plan, 2026

**Status: ACCEPTED, as amended by its review.** Written 2026-11-02 by Sobhan,
after the discovery round the two of us ran, for the owner to accept, amend
or refuse. The owner asked the same day for it to be reviewed and for the
best of what it proposes to be chosen; «What the review changed» says what
was changed and why, and the stack, the structure and the phases below are
written as accepted. Each phase names the lines it reopens, because several
of them are lines this record froze on purpose (D47, D56, D64,
WORKING_AGREEMENT), and a frozen line is reopened in the open or not at
all; the decision entry that records them is D97, written after the merge,
as the working agreement requires.

The order of work in [ROADMAP](ROADMAP.md) — the first live Divar run, a
larger corpus over time, an estimator that clears the gate on real data — is
the owner's track and stays as it is. This plan runs beside it and touches
nothing on the decision path: not the estimator, not the gate, not the
parser, not what the site may claim.

## The rule this plan keeps

CARO's differentiator is that a claim may not outrun its evidence. Every
phase below changes what is *under* the decision core — where it runs, how a
collection is scheduled, how an answer is served and watched, what the site
is built with — and none of them moves a number to a second place where it
could change on the way past (D50, D56). `caro/` stays one package, imported
by the API, in one language.

## What the review changed

Most of the plan is taken as it was written: the phase order, Cloudflare in
front, the environments and the deploys, the read model in D47's direction,
the edge cache keyed by the corpus digest, the alerts, the load tests, and
D56's measurements before any talk of Go. Five things changed:

| Proposed | Chosen | Why |
|---|---|---|
| Arq and Redis for the run queue | **A table in Postgres**, `jobs`, taken with `SELECT … FOR UPDATE SKIP LOCKED`, as [SERVICES](SERVICES.md) designs it | The owner chose Postgres alone, for the data and for the queue, on 2026-11-02. A handful of runs a day needs no second stateful service; a job and what it writes commit in one transaction; there is one database to back up. |
| Nuxt 4: the panels first (phase 5), then the public site, Next.js retired (phase 6) | **Next.js stays.** The design system and the panels are done in it (phase 5); phase 6 becomes the site in its own image on the server, and Vercel is retired | Seven to ten of the plan's sixteen weeks would go to a second front end that gives a buyer nothing the site lacks, and every refusal state the site's suites hold today would have to be earned again — 261 rows of the screens suite, the section-7 contract between the TypeScript and the Python, the palette's contrast; the plan names that risk itself. D47's Next.js line stays closed. |
| Kubernetes out of scope | **Later, not out**: the same images, when a server and its traffic warrant it | The owner's choice of 2026-11-02: Docker now, Kubernetes later. Nothing in phases 1 to 7 depends on it, and phase 7's load tests are where the need would show. |
| Caddy at the origin | **nginx** | The owner's choice, and the ingress Kubernetes would use later. |
| One API process and one worker | **One image, a container per role**: the API, the collection worker, and the ingest worker that promotes a snapshot into the catalog | The owner asked for services, for tens of thousands of listings. A process per role is deployed and scaled apart, with every rule still in `caro/`, once; SERVICES.md has the design, and D56's measurements still decide anything finer. |

Already built when the plan was accepted: the listings read model of phase
2, as the catalog (`caro/catalog.py`, sahandmusanezhad/caro#10) — loaded from the published
artifacts, read by the API under `CARO_CATALOG_URL`, and answering 740
questions the same as the files on SQLite and on Postgres — and phase 2's
`tests/test_store.py` on a real Postgres, which CI's `postgres` job now runs
on every pull request.

## What is proposed

A public product for buyers in Iran at `caro.noxioai.com`, behind
Cloudflare: a **modular monolith** — the API and a separate collection
worker, both the same package — in Docker Compose, with the API and the
product database in Europe (Hetzner, Neon) and the collection worker on a
VPS in Iran under the owner's control and the same politeness and robots
rules as today; a queue in Postgres for collection runs, each of which
still writes its own transcript; artifacts in git until they outgrow it, then an
object store addressed by digest; error tracking, logs, metrics and uptime
alerts; CI/CD with preview, staging and production environments; the seller
listings switched on with a real SMS provider; and the front end's design
system and panels, in the Next.js the site is built with, then the site in
its own image on the server. Go and any boundary inside the decision core
come last, and only if the measurements D56 names say so; Kubernetes comes
when a server and its traffic warrant it.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Decision core | Python 3.12 + numpy, unchanged | D56; no second place for a number |
| API | FastAPI + pydantic, unchanged; `psycopg[binary]` 3 | the two contract suites already hold it |
| Queue and worker | a `jobs` table in Postgres, taken with `FOR UPDATE SKIP LOCKED`; the worker is the same package, `first_run.collect` as a job | the owner's choice: Postgres alone; every run keeps its transcript |
| Front end | Next.js 15 + TypeScript + Tailwind, RTL, Vazirmatn, as today; its design system and panels refreshed in place | D47's line kept; the suites that hold the site stay as they are |
| Product database | Postgres in Compose on the Hetzner server, beside the API; SQLite locally and in the suites | the owner's choice of 2026-11-02, after the probe from Iran (phase 0): the API is the only reader that has to reach it, and it is next to it |
| Evidence storage | `data/corpora` in git to about 50 MB, then Cloudflare R2 addressed by content with the digest in the repository; snapshots in a private R2 bucket | DATA_CONTRACT allows exactly this |
| Edge | Cloudflare: proxied DNS, managed WAF (free), rate-limiting rules, Turnstile on our own forms, cache rules; the origin answers Cloudflare's addresses only | security and a CDN at no cost |
| Hosting | Hetzner CX for the API, Postgres, the site and nginx in Compose, **reached only through Cloudflare**; the worker in Iran, which writes through Cloudflare and never to Hetzner directly; Vercel until phase 6 moves the site; Kubernetes later, with the same images | the owner's choices of 2026-11-02: Docker now, Kubernetes later; Hetzner behind Cloudflare after the probe from Iran found Hetzner unreachable from there and Cloudflare reachable |
| Observability | Sentry (API and front end); OpenTelemetry to Grafana Cloud; UptimeRobot to Telegram | free tiers |
| CI/CD | GitHub Actions: PR → preview, `main` → staging, tag `vX.Y.Z` → production; images in GHCR; deploy by SSH and `docker compose` | simple, reviewable |
| Tests | the seventeen suites, CI's Postgres job; Playwright end-to-end on the key routes; k6 on `/api/search` | the contract suites carry the architecture |
| Secrets | platform environments and a shared password vault; `CARO_SELLER_SALT` only in the worker's environment | the existing rule |

## Structure (monorepo)

```
caro/                    the decision core, unchanged
webapp/api/              FastAPI, plus the read model and the job definitions
webapp/web/              Next.js: the site, its design system and the panels
scripts/                 unchanged; first_run is also callable as a job
infra/docker/            one image for the API and the workers, one for the site
infra/compose/           compose.yml (local: API, Postgres), compose.vps.yml (nginx, API, site, Postgres or Neon), compose.worker.yml
infra/cloudflare/        WAF, rate-limit and cache rules as code
infra/otel/              collector configuration
.github/workflows/       ci.yml unchanged; build-images, deploy-staging, deploy-prod, e2e
docs/REARCHITECTURE.md   this document
```

## Security, as five measures

1. The origin accepts Cloudflare's addresses only; TLS everywhere; HSTS stays.
2. Edge rate limits on `/api/search`, `/api/account/code`, `/api/contact` and
   `/api/listings/*/reveal`, in front of the limits the store already keeps.
3. Turnstile on the seller login and the contact form — on our own site
   only; nothing here ever challenges or evades a source.
4. No secret in git or in a conversation; the salt lives only where the
   worker runs; the operator's second step stays as O1 built it.
5. Every new client keeps the envelope and the fault vocabulary, held by a
   contract test of the same kind as section 7 of `tests/test_api_contract.py`.
6. An error report carries no personal data: Sentry with its default PII
   off, and a seller's number, a session cookie and an address scrubbed
   before an event leaves the process.

## Deliberately out of scope

gRPC · splitting the decision core into a service · buyer
accounts · payment (P0) · accident damage from photos (the owner's, later) ·
a language model anywhere on the decision path · any change to the politeness
policy (2–5 s) · any change to the estimator, the gate or the parser. Kubernetes is not
out of scope but later: the same images, when a server and its traffic
warrant it.

## Assumptions the owner may veto

- `noxioai.com` is on Cloudflare's nameservers, and `caro.noxioai.com`
  already points at Vercel, unproxied; phase 0 proxies it.
- The owner amends WORKING_AGREEMENT for two people: each commits under his
  own name; the roles are written down; issues live in `Tecso-Dev/caro`,
  where D68 already points the contact page.
- The owner accepts a collection worker he controls on an Iranian VPS as
  "his machine" for the purpose of the live-request rule. If not, the worker
  stays on his laptop and phase 3 builds the queue and the bucket only.
- Budget: one small Hetzner instance, one small Iranian VPS, free tiers.
- The durations are for two people part-time and are re-estimated in each
  issue.

## The phases

Each phase is one issue with its goal, deliverables, what closes it, the
decisions it waits on, and its risks. The phases are sequential; phase 5 may
overlap phases 3 and 4.

### Phase 0 — Foundation and governance (about a week; both)

**Closed** on 2026-11-03 by the owner's choice (D99): everything below is
done but the four steps in the owner's accounts -- branch protection and
the environments, the error reports' DSN, Cloudflare in front, UptimeRobot
to Telegram -- which are carried to an issue of their own, so the site is
not yet behind Cloudflare and no alert has been seen to reach Telegram.

- WORKING_AGREEMENT amended by the owner, in a commit of its own: two
  people, each committing under his own name; the roles; issues in
  `Tecso-Dev/caro`; the pull request still the only way into `main`.
- This document merged, and the owner's D-entry recording what it accepts
  and which lines it reopens: D97.
- `caro.noxioai.com` proxied through Cloudflare to the site as it is;
  managed WAF, bot protection, a first rate-limiting rule on `/api/*`, and a
  cache rule that bypasses `/api/*` until phase 4.
- Sentry on the API and the site; UptimeRobot on `/api/health` and `/`,
  alerting to Telegram.
- Branch protection on `main`, `staging` and `production` environments,
  CODEOWNERS.
- A reachability probe from inside Iran to Hetzner and Neon, recorded,
  because D64 raised that question and nobody measured it. **Run** by the
  owner on 2026-11-02 at 21:30 UTC, from an ordinary connection in Iran
  with no VPN, five rounds (`scripts/reach_probe.py`):

  | target | TLS handshake, median | reached | failed |
  |---|---|---|---|
  | Hetzner, Falkenstein | 1057 ms | 0/5 | no answer after the handshake ×5 |
  | Hetzner, Nuremberg | 494 ms | 0/5 | no answer after the handshake ×5 |
  | Hetzner, Helsinki | 598 ms | 0/5 | no answer ×4, reset in the handshake ×1 |
  | Neon's console | 520 ms | 5/5 | — |
  | Cloudflare | 580 ms | 5/5 | — |
  | the site on Vercel | 636 ms | 5/5 | — |
  | GitHub | 1403 ms | 5/5 | — |
  | GitHub's container registry | 786 ms | 5/5 | — |

  Every Hetzner handshake that finished carried Hetzner's own certificate,
  and every request after it was met by the connection closing without a
  byte: filtering, not a server that does not answer. The TCP connection
  took 14 to 16 ms to every target, Helsinki and Virginia alike, which no
  route from Iran can do: an intercepting proxy on the way answers the
  connection, and the handshake times are the real path.
  **What follows from it,** the owner's choice of the same day: the
  servers are Hetzner's and are reached only through Cloudflare, which
  answers from Iran; Postgres sits beside the API; the collection worker in
  Iran writes through Cloudflare (the bucket, or an ingest address behind
  it), never to Hetzner directly; the owner reaches the server for its
  administration through the owner's own VPN.
- **Closes when** the site answers at `caro.noxioai.com` through
  Cloudflare, a test alert has reached Telegram, and the D-entry exists.
- **Reopens:** WORKING_AGREEMENT (one person → two).

### Phase 1 — Containers and environments (one to two weeks; Sobhan)

- One image for the API and the workers — a role per command — and one for
  the site; `compose.yml` for a laptop (API, a local Postgres) and
  `compose.vps.yml` (nginx, API, Postgres), the origin answering
  Cloudflare's addresses only: Iran does not reach Hetzner (phase 0's
  probe), and nothing but Cloudflare needs to.
- One Hetzner instance holding staging and production as two Compose
  projects; the origin locked to Cloudflare's addresses.
- Workflows: images to GHCR; deploy to staging on every push to `main`;
  deploy to production on a tag; `ci.yml` untouched except the sentence that
  names a host it no longer uses.
- The API moves from the Vercel service to the VPS; Next.js stays on Vercel
  with its `/api/*` rewrite pointed at the new origin.
- **Closes when** staging and production answer from the VPS through
  Cloudflare, `tests/test_api_contract.py` is green against staging, and the
  Vercel API service is gone.
- **Reopens:** D64 (where the API runs).

### Phase 2 — Data layer and seller listings (about two weeks; Sobhan, two owner decisions)

- Neon Postgres and `psycopg[binary]` 3 in `webapp/requirements.txt`;
  `store.py` unchanged; every later migration still only adds.
- The listings read model in Postgres, in D47's direction and no other:
  `promote → artifact → projection job → Postgres`. Search keeps reading the
  artifact until the contract suite shows the read model answers the same,
  then switches. **Built** as the catalog (sahandmusanezhad/caro#10): the projection from the
  published artifacts, the API reading it under `CARO_CATALOG_URL`, and 740
  questions answered the same both ways on SQLite and Postgres. Left:
  promotion writing into it (SERVICES.md, step 2), its per-model summaries,
  and production switched to it.
- The SMS provider the owner chooses (Kavenegar proposed) behind the existing
  `Provider` interface, tried by the owner on his own number first;
  `DATABASE_URL`, `CARO_STORE_SECRET`, `CARO_SITE_ORIGINS` and
  `NEXT_PUBLIC_SELLER_LISTINGS=on` set in production.
- A private R2 bucket for snapshots, ready for phase 3; the 50 MB rule for
  corpora written into DATA_CONTRACT.
- **Closes when** a seller logs in, posts, is approved and has the number
  revealed in production with real SMS, and `tests/test_store.py` is green on
  a real Postgres — which CI's `postgres` job has done since sahandmusanezhad/caro#10.
- **Waits on the owner:** the driver, the provider.
- **Risk:** Neon unreachable from Iran → Postgres in Compose on the VPS.

### Phase 3 — Collection worker and scheduler (about two weeks; both)

- The queue in Postgres — SERVICES.md's `jobs` table, taken with
  `FOR UPDATE SKIP LOCKED`, retried with a backoff, its error kept — and a
  job `collect(source, pin)` that calls `first_run.collect` and writes the
  transcript and the snapshot to the private bucket; one record per run with
  its pin, digest and output. One collector per source holds that source's
  lock, so the pause between two requests to a domain is never shared out.
- The worker on an Iranian VPS (`compose.worker.yml`); `CARO_SELLER_SALT`
  only there; the daily Khodro45 run on the same pin (`--pages 60`). It
  writes through Cloudflare -- the private bucket, or an ingest address
  behind Cloudflare -- since phase 0's probe found Hetzner unreachable
  from Iran.
- Promotion stays a deliberate, reviewed step: a pull request carrying the
  corpus, every line read, as today.
- Alerts: a run that did not arrive, a run that stopped on a block or on a
  robots.txt answering 5xx, a robots.txt that changed, a listing count
  outside its usual range.
- **Closes when** seven consecutive daily runs have come from the VPS with
  their transcripts and no manual step but promotion, and
  `scripts/replicate_check.py` has compared two of them from the bucket.
- **Reopens:** D47 (no queue — in Postgres, the owner's choice, rather than
  the Arq D47 names) and WORKING_AGREEMENT (live requests on the owner's
  machine → on a worker the owner controls). **Waits on the owner** for the
  second: until then the worker runs on the owner's machine.

### Phase 4 — The edge: cache, rate limiting, Turnstile (about a week; Sobhan)

- `ETag` carrying `corpus_sha256` and a `Cache-Control` on
  `GET /api/models`, `/api/model` and `/api/corpus`; a cache rule for those
  three only; a purge on promotion. The key is what D47 requires: the
  corpus digest, the gate state, the ranking version.
- Rate-limiting rules tuned from the traffic phases 0–3 observed; Turnstile
  on the seller login and the contact form, verified on the server.
- A k6 baseline on `/api/search` with a p95 target written down.
- **Closes when** the three GETs are served from the cache more than 80% of
  the time, the p95 target holds, and no cached answer ever carries a digest
  other than the corpus being served.
- **Reopens:** D47 (no cache — at the edge only, keyed as D47 requires).

### Phase 5 — The design system and the panels, in Next.js (one to two weeks; Sobhan)

- A design system for the site as it is, in `webapp/web`: tokens that start
  from the site's palette and evolve, with the contrast checks
  `tests/test_palette.py` makes; RTL, Vazirmatn, dark and light.
- The operator panel (review queue, inbox, corpus state) and the seller
  panel (login, post, my listings), which exist, brought into it.
- Playwright end-to-end on the key routes, in CI.
- **Closes when** the panels and the public pages share the system, the
  suites are green, and the end-to-end run is part of CI.
- **Reopens:** nothing. (Proposed as Nuxt 4 panels; see «What the review
  changed».)

### Phase 6 — The site in its own image, Vercel retired (about a week; Sobhan, reviewed by the owner)

- The site built standalone into an image of its own, served beside the API
  behind nginx on the VPS, through Cloudflare; `/api/*` to the API's
  container.
- Every refusal state kept exactly as it is: the screens suite, the
  section-7 contract and the palette's checks run against the same code, so
  nothing has to be earned again.
- The Vercel project retired.
- **Closes when** the site answers from the VPS through Cloudflare, the
  suites are green against it, and the decision entry records that the site
  left Vercel.
- **Reopens:** D64 (the site as a Vercel service). (Proposed as the public
  site on Nuxt with Next.js retired; see «What the review changed».)

### Phase 7 — Observability, scale, and the D56 review (about two weeks; both)

- OpenTelemetry in the API and the worker to Grafana Cloud; dashboards;
  SLOs for availability, search p95 and the daily run; the full alert
  catalogue, including "a published count disagrees with the suites", raised
  from CI.
- k6 at ten times the target; the hot path profiled and the slowest stage
  named; and whether one VPS still holds that load, which is the question
  Kubernetes answers.
- **The three conditions of D56 measured**, not anticipated: whether a
  multi-source crawl finishes in its window (with Divar live, if the owner
  has run it); whether `duration_stats` is genuinely running; which stage, if
  any, is a transferable bottleneck. Then a written decision on Go for the
  collector and on any service boundary — each its own D-entry, whichever
  way it goes.
- **Closes when** the dashboards and SLOs are live and the D56 decision is
  written.
- **Reopens:** D56 — only if the measurements say so.

## Frozen lines this plan asks to reopen

| Line | Phase | How |
|---|---|---|
| WORKING_AGREEMENT: one person | 0 | two people, each under his own name |
| D64: the API as a Vercel service | 1 | the API in Compose on a VPS |
| D47: no queue | 3 | in Postgres (the owner's choice), every run with its transcript |
| WORKING_AGREEMENT: live requests on the owner's machine | 3 | on a worker the owner controls |
| D47: no cache | 4 | at the edge only, keyed by digest, gate and version |
| D64: the site as a Vercel service | 6 | the site's own image on the server |
| D56: one language | 7 | only if the measurements it names come out that way |

## Timing

Phase 0: a week · 1: one to two · 2: two · 3: two · 4: one · 5: one to two
· 6: one · 7: two — about three months for two people part-time,
re-estimated in each issue. (Proposed: about four; the five to eight weeks
saved are phases 5 and 6 without a second front end.)

## Tracking

One issue per phase in `Tecso-Dev/caro`, under an epic that links them, each
labelled with its phase and with every line it reopens, and each carrying
its goal, deliverables, what closes it, the decisions it waits on and its
risks. A phase starts when the one before it is closed, and never before the
owner has made the decisions its issue names.
