# Re-architecture plan, 2026 — a proposal for the owner

**Status: PROPOSAL.** Written 2026-11-02 by Sobhan, after the discovery round
the two of us ran, for the owner to accept, amend or refuse. Nothing in it is
built, and nothing in it is a decision until the owner's D-entry says so.
Each phase names the lines it reopens, because several of them are lines
this record froze on purpose (D47, D56, D64, WORKING_AGREEMENT), and a frozen
line is reopened in the open or not at all.

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

## What is proposed

A public product for buyers in Iran at `caro.noxioai.com`, behind
Cloudflare: a **modular monolith** — the API and a separate collection
worker, both the same package — in Docker Compose, with the API and the
product database in Europe (Hetzner, Neon) and the collection worker on a
VPS in Iran under the owner's control and the same politeness and robots
rules as today; a queue (Arq) for collection runs, each of which still
writes its own transcript; artifacts in git until they outgrow it, then an
object store addressed by digest; error tracking, logs, metrics and uptime
alerts; CI/CD with preview, staging and production environments; the seller
listings switched on with a real SMS provider; and a new front end — a design
system and the operator and seller panels in Nuxt 4 first, then the public
site migrated to the same stack and Next.js retired. Go and any service
boundary come last, and only if the measurements D56 names say so.

## Stack

| Layer | Choice | Why |
|---|---|---|
| Decision core | Python 3.12 + numpy, unchanged | D56; no second place for a number |
| API | FastAPI + pydantic, unchanged; `psycopg[binary]` 3 | the two contract suites already hold it |
| Queue and worker | Arq + Redis; the worker is the same package, `first_run.collect` as a job | D47 names Arq for the day a queue is warranted; every run keeps its transcript |
| Front end | Nuxt 4 + Vue 3 + TypeScript + Tailwind 4, RTL, Vazirmatn; Next.js stays until parity | one stack at the end; the team's strength; reopens the Next.js line of D47 |
| Product database | Neon Postgres (production, staging by branch); SQLite locally and in the suites | D47: Postgres for product state and the read model only |
| Evidence storage | `data/corpora` in git to about 50 MB, then Cloudflare R2 addressed by content with the digest in the repository; snapshots in a private R2 bucket | DATA_CONTRACT allows exactly this |
| Edge | Cloudflare: proxied DNS, managed WAF (free), rate-limiting rules, Turnstile on our own forms, cache rules; the origin answers Cloudflare's addresses only | security and a CDN at no cost |
| Hosting | Hetzner CX for API + Redis + Caddy in Compose; an Iranian VPS for the worker; Cloudflare Pages for Nuxt; Vercel until Next.js is retired | D47: Compose, no Kubernetes |
| Observability | Sentry (API and front end); OpenTelemetry to Grafana Cloud; UptimeRobot to Telegram | free tiers |
| CI/CD | GitHub Actions: PR → preview, `main` → staging, tag `vX.Y.Z` → production; images in GHCR; deploy by SSH and `docker compose` | simple, reviewable |
| Tests | the sixteen suites unchanged; a screens suite for Vue; Playwright end-to-end on the key routes; k6 on `/api/search` | the contract suites carry the architecture |
| Secrets | platform environments and a shared password vault; `CARO_SELLER_SALT` only in the worker's environment | the existing rule |

## Structure (monorepo)

```
caro/                    the decision core, unchanged
webapp/api/              FastAPI, plus the read model and the job definitions
webapp/web/              Next.js, alive until phase 6, then removed
webapp/nuxt/             Nuxt 4: the design system, the panels, then the public site
scripts/                 unchanged; first_run is also callable as a job
infra/docker/            Dockerfile.api, Dockerfile.worker
infra/compose/           compose.yml (local), compose.vps.yml, compose.worker.yml
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

## Deliberately out of scope

Kubernetes · gRPC · splitting the decision core into a service · buyer
accounts · payment (P0) · accident damage from photos (the owner's, later) ·
a language model anywhere on the decision path · any change to the politeness
policy (2–5 s) · any change to the estimator, the gate or the parser.

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

- WORKING_AGREEMENT amended by the owner, in a commit of its own: two
  people, each committing under his own name; the roles; issues in
  `Tecso-Dev/caro`; the pull request still the only way into `main`.
- This document merged, and the owner's D-entry recording what it accepts
  and which lines it reopens.
- `caro.noxioai.com` proxied through Cloudflare to the site as it is;
  managed WAF, bot protection, a first rate-limiting rule on `/api/*`, and a
  cache rule that bypasses `/api/*` until phase 4.
- Sentry on the API and the site; UptimeRobot on `/api/health` and `/`,
  alerting to Telegram.
- Branch protection on `main`, `staging` and `production` environments,
  CODEOWNERS.
- A reachability probe from inside Iran to Hetzner and Neon, recorded,
  because D64 raised that question and nobody measured it.
- **Closes when** the site answers at `caro.noxioai.com` through
  Cloudflare, a test alert has reached Telegram, and the D-entry exists.
- **Reopens:** WORKING_AGREEMENT (one person → two).

### Phase 1 — Containers and environments (one to two weeks; Sobhan)

- `Dockerfile.api`, `Dockerfile.worker`; `compose.yml` for a laptop (API,
  Redis, a local Postgres) and `compose.vps.yml` (Caddy, API, Redis).
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
  then switches.
- The SMS provider the owner chooses (Kavenegar proposed) behind the existing
  `Provider` interface, tried by the owner on his own number first;
  `DATABASE_URL`, `CARO_STORE_SECRET`, `CARO_SITE_ORIGINS` and
  `NEXT_PUBLIC_SELLER_LISTINGS=on` set in production.
- A private R2 bucket for snapshots, ready for phase 3; the 50 MB rule for
  corpora written into DATA_CONTRACT.
- **Closes when** a seller logs in, posts, is approved and has the number
  revealed in production with real SMS, and `tests/test_store.py` is green on
  a real Postgres.
- **Waits on the owner:** the driver, the provider.
- **Risk:** Neon unreachable from Iran → Postgres in Compose on the VPS.

### Phase 3 — Collection worker and scheduler (about two weeks; both)

- Arq and Redis; a job `collect(source, pin)` that calls `first_run.collect`
  and writes the transcript and the snapshot to the private bucket; one
  record per run with its pin, digest and output.
- The worker on an Iranian VPS (`compose.worker.yml`); `CARO_SELLER_SALT`
  only there; the daily Khodro45 run on the same pin (`--pages 60`).
- Promotion stays a deliberate, reviewed step: a pull request carrying the
  corpus, every line read, as today.
- Alerts: a run that did not arrive, a run that stopped on a block or on a
  robots.txt answering 5xx, a robots.txt that changed, a listing count
  outside its usual range.
- **Closes when** seven consecutive daily runs have come from the VPS with
  their transcripts and no manual step but promotion, and
  `scripts/replicate_check.py` has compared two of them from the bucket.
- **Reopens:** D47 (no queue — with Arq, as D47 itself says) and
  WORKING_AGREEMENT (live requests on the owner's machine → on a worker the
  owner controls). **Waits on the owner** for both.

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

### Phase 5 — The design system and the Nuxt 4 panels (three to four weeks; Sobhan)

- `webapp/nuxt/`: Nuxt 4, Tailwind 4, RTL from the first commit, Vazirmatn,
  dark and light; a design system whose tokens start from the site's palette
  and evolve, with the contrast checks `tests/test_palette.py` makes.
- The operator panel (review queue, inbox, corpus state) and the seller
  panel (login, post, my listings), on the endpoints that exist.
- A typed client with a contract test of the section-7 kind; a screens suite
  for Vue (server-rendered) over these pages.
- Served from Cloudflare Pages under the same domain.
- **Closes when** the operator and seller flows run on Nuxt in production
  and `/admin`, `/login`, `/sell` and `/my-listings` are removed from Next.js.
- **Reopens:** nothing yet; Next.js keeps the public site.

### Phase 6 — The public site on Nuxt (four to six weeks; Sobhan, reviewed by the owner)

- The thirteen remaining routes in the new design, against a **parity
  checklist**: the corpus badge on every screen; the NOT SERVED panel and the
  two evidence tables that never mix; the intent panel with what was read,
  assumed and left unread; the card rules for price, odometer and province
  with how each was read; one history line per source; the non-vehicle page;
  what a visitor keeps, kept in the browser.
- `tests/test_screens.py` rewritten for Vue, `tests/test_palette.py` pointed
  at the new tokens, `tests/test_claims.py` scanning `webapp/nuxt`, the
  README and `/about` counts moved in the same commit.
- Next.js and `webapp/web` removed; the Vercel project retired; the site
  served from Pages.
- **Closes when** the checklist is green, all sixteen suites are green, and
  the D-entry records that Next.js is retired.
- **Reopens:** D47 (Next.js + TypeScript + Tailwind). **Waits on the owner**
  before the phase starts.

### Phase 7 — Observability, scale, and the D56 review (about two weeks; both)

- OpenTelemetry in the API and the worker to Grafana Cloud; dashboards;
  SLOs for availability, search p95 and the daily run; the full alert
  catalogue, including "a published count disagrees with the suites", raised
  from CI.
- k6 at ten times the target; the hot path profiled and the slowest stage
  named.
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
| D47: no queue | 3 | Arq, every run with its transcript |
| WORKING_AGREEMENT: live requests on the owner's machine | 3 | on a worker the owner controls |
| D47: no cache | 4 | at the edge only, keyed by digest, gate and version |
| D47: Next.js + TypeScript + Tailwind | 6 | Nuxt 4, after parity |
| D56: one language | 7 | only if the measurements it names come out that way |

## Timing

Phase 0: a week · 1: one to two · 2: two · 3: two · 4: one · 5: three to
four · 6: four to six · 7: two — about four months for two people part-time,
re-estimated in each issue.

## Tracking

One issue per phase in `Tecso-Dev/caro`, under an epic that links them, each
labelled with its phase and with every line it reopens, and each carrying
its goal, deliverables, what closes it, the decisions it waits on and its
risks. A phase starts when the one before it is closed, and never before the
owner has made the decisions its issue names.
