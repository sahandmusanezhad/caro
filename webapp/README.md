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

## Why the requirements file is separate

`webapp/requirements.txt` holds fastapi, uvicorn and pydantic. None of them
belong in the core: the README's claim that numpy is `caro`'s only hard
dependency has to stay true, and it stops being true the moment a web
framework can be imported from inside the package.

## Which corpus is being served

`webapp/api/corpus.py` decides, in this order:

1. **REAL** — `data/corpora/<run>.json`, if a published artifact exists.
   Loaded through `caro.corpus_reader`, which fails closed on missing
   provenance. On today's artifacts that yields a corpus that can be listed
   but not appraised, so the site refuses to rank and shows evidence instead.
2. **SYNTHETIC** — the corpus `tests/test_ranking.py` generates. Real code,
   real ranking, known true prices, which is why the gate passes on it and a
   shortlist can actually be served.

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
