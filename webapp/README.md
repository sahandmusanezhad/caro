# The platform

Two processes. The Python package is the product; these serve it.

    webapp/api/     FastAPI. Imports `caro` directly — no service boundary,
                    no serialisation round-trip, no second place for a
                    number to change on the way past.
    webapp/web/     Next.js 15 + TypeScript + Tailwind, RTL Persian.

## Running it

Two terminals, from the repository root.

```sh
# 1 — the API
pip install -r webapp/requirements.txt
uvicorn webapp.api.main:app --reload            # 127.0.0.1:8000

# 2 — the client
cd webapp/web && npm install && npm run dev     # 127.0.0.1:3000
```

`next.config.mjs` rewrites `/api/*` to `http://127.0.0.1:8000` unless
`CARO_API` says otherwise, so client code writes `/api/...` in development
and behind one origin in production alike.

For production, both are images (`Dockerfile`, `webapp/web/Dockerfile`)
behind one nginx, so the browser sees a single origin: `docker compose up
--build` runs them on a laptop, and the server runs `compose.vps.yml` per
environment behind `compose.edge.yml` ([PHASE1_SETUP](../docs/PHASE1_SETUP.md)).

### Environment

| variable | effect |
| --- | --- |
| `CARO_API` | where the client's `/api/*` rewrite points. Read at **build** time, so a change needs a rebuild, not a restart. |
| `CARO_ADMIN_TOKEN` | opens `/admin`. **Unset means the inbox opens for nobody** — that is the safe state, not a misconfiguration to route around. |
| `CARO_INBOX` | `off` switches the contact inbox off: no form is drawn, and `POST /api/contact` answers 503 and names GitHub Issues. **Set it wherever the disk does not keep what is written** — a serverless function, a container without a volume. Unset, messages are appended to `data/inbox/messages.jsonl`, and a write that fails anyway is the same 503: never a reference for a message that was not kept. |
| `CARO_RUN` | which corpus the API serves, by run id. Unset means `webapp.api.corpus.DEFAULT_RUN`. **Set it and get it wrong and the site serves nothing** — see below; that is the point of setting it. |
| `CARO_CORPORA` | where corpora are read from. For pointing the reader at a directory a test controls, and for nothing else. |
| `CARO_CATALOG_URL` | serve the published runs from the catalog, `sqlite:///<path>` or `postgresql://...`, loaded by `scripts/catalog_load.py` (docs/SERVICES.md). Unset, the files are read. **Set and unable to serve the run, the site serves nothing** (`CATALOG_UNAVAILABLE`), asked again every 30 s. |
| `CARO_SMS_PROVIDER` | who sends a seller's login code: `kavenegar`, or `fake` on a laptop's SQLite store only (`webapp/api/sms.py`). Unset, the login is off. |
| `CARO_SMS_KAVENEGAR_KEY`, `_TEMPLATE`, `_SENDER` | Kavenegar's API key, the one-time-code template the code goes by (its `%token` is the six digits), and the line an ordinary message goes from when no template is set. The key is typed into the server's env file and nowhere else (docs/PHASE2_SETUP.md). |
| `CARO_WORKER_TOKEN` | what the server knows the collection worker by: `POST /api/worker/runs` takes a run's record with it (`webapp/api/collection.py`, docs/PHASE3_SETUP.md). Unset, the records are off, 503 `RUNS_OFF`. |
| `CARO_OPS_URL` | where the records are kept, and the alerts read them (`caro/runs.py`): `sqlite:///...` or `postgresql://...`; on the server, the environment's Postgres. |
| `CARO_ALERT_EXPECT`, `CARO_ALERT_TELEGRAM_TOKEN`, `_CHAT` | the alerts' role (`webapp/alerts.py`): the runs expected each day, `source@HH:MM` in Tehran, and the Telegram bot and chat they are said to. Without the bot, they go to the log. |
| `CARO_EDGE_TTL` | how long, in seconds, a shared cache may keep `/api/models`, `/api/model` and `/api/corpus` (`webapp/api/edge.py`); 300 when unset or not a number. |
| `CARO_TURNSTILE_SECRET` | Turnstile's secret: with it, the seller's code request and the contact form ask for the widget's token and Cloudflare is asked whether it is good (`webapp/api/turnstile.py`). Unset, nothing is asked. The site draws the widget where `NEXT_PUBLIC_TURNSTILE_SITE_KEY` was set at build. |
| `CARO_CF_API_TOKEN`, `CARO_CF_ZONE_ID`, `CARO_SITE_HOST` | the edge purge's (`scripts/edge_purge.py`, run by the server's pull): a Cloudflare token with Zone → Cache Purge, the zone, and the host purged. |
| `CARO_BUILD` | the commit the process was built from, which `/api/health` names; the API's image sets it at build time, and a deploy waits until it names the new commit (`scripts/deploy_wait.py`). Unset, health says `null`. |
| `CARO_API_PORT` | the port the image's `api` role listens on inside its container, 8000 by default (`webapp/role.py`). |
| `CARO_FORWARDED_ALLOW_IPS` | the addresses whose `X-Forwarded-*` headers uvicorn believes, for the image's `api` role. Unset, none: on the server the edge sets `X-Forwarded-For` and the API reads it under `CARO_TRUST_PROXY=1`. |
| `SENTRY_DSN` | error reports to Sentry (`webapp/api/observability.py`). Unset, the SDK is not even imported. Set, an event carries an exception's type, message and frames, and no cookie, body, query, address, user, variable, source line or mobile number. `SENTRY_ENVIRONMENT` (default `production`), `SENTRY_RELEASE` and `SENTRY_TRACES_SAMPLE_RATE` (default 0) beside it. `POST /api/admin/report-test`, with the operator's token and code, sends one test message and gives back its id, or says `off`. |
| `NEXT_PUBLIC_SENTRY_DSN` | the site's error reports, read at **build** time. Unset, the site loads no Sentry script at all. Set, a browser sends its reports to `/api/report`, where the API cleans each with its own rule and forwards it to the project `SENTRY_DSN` names; nothing goes from a browser to Sentry directly (the site's `connect-src 'self'`). |

### Python version

`webapp/requirements.txt` carries a floor and a ceiling rather than exact
pins, because exact ones stopped being installable: `pydantic-core` is
compiled and ships a wheel per Python version, and the pinned 2.10.4 has none
for Python 3.14 — so on a machine whose `python3` is 3.14, pip tries to build
it from source, wants Rust, and fails. The file says the rest.

A virtualenv is the shortest path on Debian and Ubuntu, where the system
Python refuses installs (PEP 668):

```sh
python3 -m venv .venv                      # apt install python3.X-venv if this fails
.venv/bin/pip install -r webapp/requirements.txt
.venv/bin/python -m uvicorn webapp.api.main:app --reload --port 8000
```

`.venv/` is already in `.gitignore`.

## Deploying

The site and the API run on the server as two images, behind its one nginx
and Cloudflare. [PHASE1_SETUP](../docs/PHASE1_SETUP.md) sets the server up;
the images workflow builds both images, runs the API's suites inside its
own, walks both in a browser and pushes them; the server pulls them every
minute (`deploy/pull.sh`). Nothing reaches the server to deploy.

Until phase 6 the site and the API were one Vercel project of two services,
built from a `vercel.json` on each push to `main` of `Tecso-Dev/caro`. It was
retired once the server had served the site for a week
([PHASE6_SETUP](../docs/PHASE6_SETUP.md)). What that deployment showed, page
by page, and the region its function ran in are in D64 (docs/DECISIONS.md);
how it was set up, and its cold start, measured once on 2026-09-27, are in
this file's history.

## Why the requirements file is separate

`webapp/requirements.txt` holds fastapi, uvicorn and pydantic. None of them
belong in the core: the README's claim that numpy is `caro`'s only hard
dependency has to stay true, and it stops being true the moment a web
framework can be imported from inside the package.

## Which corpus is being served

`webapp/api/corpus.py` decides. **Which run** comes from `CARO_RUN`, or from
`DEFAULT_RUN` when that is unset; **which state** follows from what is at
`data/corpora/<run>.json`:

| | |
| --- | --- |
| **REAL** | the artifact loaded. `caro.corpus_reader` fails closed on missing provenance, so how much of it reaches W1 is a property of the artifact — a listing whose price or mileage arrives without provenance is counted and not appraised. Either way no estimator has cleared the gate on a real corpus (D43), so the site refuses to rank and shows evidence. |
| **SYNTHETIC** | no artifact, and no run was named. The corpus `caro/synthetic.py` generates, the one `tests/test_ranking.py` measures ranking on: real code, real ranking, known true prices, which is why the gate passes on it and a shortlist can actually be served. The note says which artifact was looked for. |
| **UNUSABLE** | nothing may be served. Two causes, kept apart by `fault.code`: `CORPUS_INVALID` — a file that exists and will not load; `RUN_NOT_FOUND` — `CARO_RUN` named a run with no artifact. |

The third row is the rule that took two goes to get right. D49 says absence is
a fallback and failure is not, and `CORPUS_INVALID` is that rule for a file
that breaks. `RUN_NOT_FOUND` is the same rule one level up: the default used
to name `run3`, that artifact has not existed since D46, and so every
deployment fell through to SYNTHETIC on every request — correctly labelled,
never noticed, and with a real corpus sitting on disk beside it. Somebody who
names a run gets that run or gets nothing.

The label travels with every API response and sits in the site header on
every screen. That is deliberate and it is not a debug affordance: a listing
card looks identical whichever corpus produced it.

## Verifying a change

```sh
python3 tests/run_all.py          # the whole suite, including W3 ranking
cd webapp/web && npm run build    # types and the nine routes
```

The API has two suites of its own. `tests/test_api_contract.py` calls every
endpoint, in every corpus state, against the client's types in `lib/api.ts`.
`tests/test_screens.py` draws the site's own components with what those
endpoints return, the car page in each state its two requests can leave it
in among them. Both run under `tests/run_all.py`, and both need what the API
needs; the second also needs node and `webapp/web/node_modules`. Without
them a suite is skipped by name, and never counted as passed.

`.github/workflows/ci.yml` runs every suite and the site's type check, lint and
build on each push to `main` and each pull request. It fails when a suite is
skipped, since skipped is not passed.
