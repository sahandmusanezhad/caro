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
| `CARO_RUN` | which corpus the API serves, by run id. Unset means `webapp.api.corpus.DEFAULT_RUN`. **Set it and get it wrong and the site serves nothing** — see below; that is the point of setting it. |
| `CARO_CORPORA` | where corpora are read from. For pointing the reader at a directory a test controls, and for nothing else. |

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
| **SYNTHETIC** | no artifact, and no run was named. The corpus `tests/test_ranking.py` generates: real code, real ranking, known true prices, which is why the gate passes on it and a shortlist can actually be served. The note says which artifact was looked for. |
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

The API has no test suite of its own yet. It is thin enough that the
interesting behaviour lives in `caro/` and is covered there — but "thin
enough" is a judgement, not a guarantee, and this line should be deleted the
day a decision starts being made in `webapp/api/`.
