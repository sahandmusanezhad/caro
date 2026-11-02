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

For production: `npm run build && npm run start`, with both processes behind
one nginx (or equivalent) so the browser sees a single origin.

### Environment

| variable | effect |
| --- | --- |
| `CARO_API` | where the client's `/api/*` rewrite points. Read at **build** time, so a change needs a rebuild, not a restart. |
| `CARO_ADMIN_TOKEN` | opens `/admin`. **Unset means the inbox opens for nobody** — that is the safe state, not a misconfiguration to route around. |
| `CARO_INBOX` | `off` switches the contact inbox off: no form is drawn, and `POST /api/contact` answers 503 and names GitHub Issues. **Set it wherever the disk does not keep what is written** — a serverless function, a container without a volume. Unset, messages are appended to `data/inbox/messages.jsonl`, and a write that fails anyway is the same 503: never a reference for a message that was not kept. |
| `CARO_RUN` | which corpus the API serves, by run id. Unset means `webapp.api.corpus.DEFAULT_RUN`. **Set it and get it wrong and the site serves nothing** — see below; that is the point of setting it. |
| `CARO_CORPORA` | where corpora are read from. For pointing the reader at a directory a test controls, and for nothing else. |
| `CARO_CATALOG_URL` | serve the published runs from the catalog, `sqlite:///<path>` or `postgresql://...`, loaded by `scripts/catalog_load.py` (docs/SERVICES.md). Unset, the files are read. **Set and unable to serve the run, the site serves nothing** (`CATALOG_UNAVAILABLE`), asked again every 30 s. |
| `SENTRY_DSN` | error reports to Sentry (`webapp/api/observability.py`). Unset, the SDK is not even imported. Set, an event carries an exception's type, message and frames, and no cookie, body, query, address, user, variable, source line or mobile number. `SENTRY_ENVIRONMENT` (default `production`), `SENTRY_RELEASE` and `SENTRY_TRACES_SAMPLE_RATE` (default 0) beside it. |

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

## Deploying on Vercel

`vercel.json` at the repository root makes one Vercel project of two
services on one domain: the site from `webapp/web`, and the API from the
repository root, so that its function carries `caro/` and `data/corpora/`.
It needs nothing under `tests/`: the SYNTHETIC fallback is built by
`caro/synthetic.py`. `/api/*` goes to the API and everything else to the
site. The API sees the original path, so its routes are the ones above, and
the site's own `/api` rewrite is never reached: `CARO_API` is not needed
there.

Services is in beta on Vercel and may need enabling for the account. Then:

1. import the repository as one project, with the root directory left at the
   repository root, where `vercel.json` is;
2. set `CARO_INBOX=off`, so the contact page shows GitHub Issues instead of a
   form. Left unset, the form is drawn and every message is refused with a
   503, because a function's disk does not keep what is written;
3. leave `CARO_RUN` unset to serve run16, and `CARO_ADMIN_TOKEN` unset — with
   the inbox off there is nothing for it to open;
4. deploy a preview, and look at `/`, `/search`, `/car/bama:q571duyy`,
   `/compare` and `/api/listing/bama:q571duyy` before promoting it.

The API installs numpy and `webapp/requirements.txt` through the service's
`installCommand`, which keeps fastapi out of the package's dependencies.
`vercel dev` does not start the API service — it installs from
`pyproject.toml` and ignores that command — so for local work use the two
terminals above.

Measured before this was written, with Vercel CLI 60.1.3 and `vercel build`
on the tree: both services build; the API function is 97 MB of a 500 MB
limit; served from those files alone it answers the listing and contact
endpoints, switches the inbox off with `CARO_INBOX=off`, and refuses a message
with 503 when it cannot write. What the first real deployment showed, page by
page, and the region its function runs in, iad1, are in D64
(docs/DECISIONS.md).

Cold start was measured once, on 2026-09-27, from one machine, straight
after a deploy, each request on a new connection: the API's first answer came
in 1.40 s to its first byte, the five after it in 0.82 to 1.29 s, and a
static page, which never reaches the API, in 1.27 s. Whatever the first
answer paid for starting is not distinguishable from the network at that
resolution: it was 0.40 s slower than the median of the five that followed,
and those five spread over 0.46 s.

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
