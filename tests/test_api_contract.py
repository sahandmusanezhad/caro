"""The API's contract, checked in every corpus state — and against the client.

Run: PYTHONPATH=. python3 tests/test_api_contract.py

A suite that asserted "the endpoint returned 200" would pass on every bug this
project has actually had. The endpoint returned 200 when it claimed to have
ranked an empty corpus. It returned 200 while serving generated data under a
truthful label because a real artifact had silently failed to load. Status
codes are not the contract.

What is checked instead:

    1  a valid synthetic corpus     → the response model validates
    2  a valid real corpus          → validates, and carries a sha256
    3  a missing DEFAULT corpus     → SYNTHETIC, no fault, and it names
                                      the artifact it looked for
    3b a missing CONFIGURED run     → UNUSABLE / RUN_NOT_FOUND, never a
                                      silent substitution
    3c listing / compare on it      → the envelope, not a 404 claiming the
                                      car is not there
    3d the same, as real HTTP       → 200 when the fault is about the SOURCE,
                                      404 when it is about the RESOURCE, and
                                      an envelope on both
    4  a broken corpus              → UNUSABLE, a fault, and never SYNTHETIC
    5  an ungated corpus            → evidence may exist, no estimate is
                                      fabricated for it
    6  a refusal                    → HTTP 200, a product state, schema-valid
    7  the client's TypeScript      → the same fields AND the same union
                                      members as the Python models

Seven is the one that cannot be written any other way. `lib/api.ts` is a
second hand-written description of `webapp/api/schemas.py`, and TypeScript
validates the client against ITS OWN belief about the server. That belief is
exactly what goes stale. So this reads the file.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import sys
import tempfile
import typing
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.corpus import SCHEMA                              # noqa: E402
import caro.corpus_reader as corpus_reader                         # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import webapp.api.corpus as corpus_mod                         # noqa: E402
    from webapp.api import main as api                             # noqa: E402
from webapp.api import schemas                                     # noqa: E402

FAILS = []

# Loading a corpus prints — `_synthetic()` imports the ranking suite, which
# runs its own checks — and that noise must not land in this suite's output.
# But the suppression is around the corpus load, and `check()` runs INSIDE it.
# Writing to the captured stdout would silently swallow every result line: the
# assertions would still run and still fail the build, while a reader saw
# nothing and the runner counted almost none of them. So `check` holds the
# real stream.
_OUT = sys.stdout


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}", file=_OUT)
    else:
        print(f"  ✗ {name}  {detail}", file=_OUT)
        FAILS.append(name)


RUN = corpus_mod.DEFAULT_RUN     # read, never spelled out — see below
# Sections 9 to 11 follow a listing that is not a car through every path. The
# one real non-vehicle any published corpus holds is run11's assignment, so
# those sections read run11 by name, served as the configured run, whatever
# the default is; a default with no non-vehicle would leave them nothing to
# follow and nothing to catch.
NV_RUN = "run11"


@contextlib.contextmanager
def corpus_dir(body: str | None, *, run_env: str | None = None):
    """Point the reader at a temp directory, optionally holding an artifact.

    Nothing is written under `data/corpora/`. A fabricated file there is
    indistinguishable from a collected one, and that confusion is what the
    corpus label exists to prevent.

    The artifact is named after `corpus_mod.DEFAULT_RUN` rather than a literal.
    Writing `run3.json` was, without meaning to, an assertion that the default
    is whatever this suite happens to write — which is why every check here
    passed for months while the shipped default named an artifact D46 had
    removed, and the site served SYNTHETIC to everybody.

    `run_env` sets CARO_RUN for the block. `None` clears it, so the default
    path is exercised against a known-empty variable rather than the shell's.
    """
    was, was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
    with tempfile.TemporaryDirectory() as d:
        if body is not None:
            (Path(d) / f"{RUN}.json").write_text(body, encoding="utf-8")
        corpus_reader.CORPORA = Path(d)
        if run_env is None:
            os.environ.pop(corpus_mod.RUN_ENV, None)
        else:
            os.environ[corpus_mod.RUN_ENV] = run_env
        corpus_mod.active.cache_clear()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                yield
        finally:
            corpus_reader.CORPORA = was
            if was_run is None:
                os.environ.pop(corpus_mod.RUN_ENV, None)
            else:
                os.environ[corpus_mod.RUN_ENV] = was_run
            corpus_mod.active.cache_clear()


def valid_artifact(n: int = 9, *, product_class: str | None = None) -> str:
    """A small artifact in the published schema.

    By default its rows carry no `product_class`, which the schema allows,
    and the loader records such a row as `unknown` — never as `vehicle`.
    A section whose claim needs cars in the corpus says so by passing
    `product_class="vehicle"`. The default is never assumed to hold any.
    """
    rows = [
        {"listing_id": f"b{i}",
         "asking_price_toman": 500_000_000 + i * 40_000_000,
         "year_jalali": 1392 + (i % 4), "mileage_km": 90_000 + i * 9000,
         "make": "peugeot", "model": "206", "trim": "TU5",
         "province": "tehran"}
        for i in range(n)]
    if product_class is not None:
        for x in rows:
            x["product_class"] = product_class
    obj = {
        "schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
        "collected_on": "2026-09-09",
        "listings": rows,
    }
    return json.dumps(obj, ensure_ascii=False, indent=2)


def validates(model, obj) -> tuple[bool, str]:
    """Round-trip through the model. A response that cannot be re-validated
    from its own serialised form is not a contract, it is a coincidence."""
    try:
        model.model_validate(json.loads(obj.model_dump_json()))
        return True, ""
    except Exception as e:                      # noqa: BLE001
        return False, str(e)[:160]


# ---------------------------------------------------------------------------
print("1 — a valid synthetic corpus", file=_OUT)
with corpus_dir(None):
    r = api.search(q="۲۰۶ زیر ۸۰۰ میلیون", k=3)
    ok, why = validates(schemas.SearchResponse, r)
    check("SearchResponse validates", ok, why)
    check("  status.kind is SYNTHETIC", r.status.kind == "SYNTHETIC",
          r.status.kind)
    check("  and it serves, because the gate passes on it",
          r.status.served and r.status.gated)
    check("  with a shortlist and no evidence table",
          len(r.items) == 3 and r.evidence == [])
    ok, why = validates(schemas.CorpusResponse, api.which_corpus())
    check("CorpusResponse validates", ok, why)


# ---------------------------------------------------------------------------
print("\n2 — a valid real corpus")
with corpus_dir(valid_artifact()):
    r = api.search(q="۲۰۶", k=5)
    ok, why = validates(schemas.SearchResponse, r)
    check("SearchResponse validates", ok, why)
    check("  status.kind is REAL", r.status.kind == "REAL", r.status.kind)
    check("  identity is present", r.corpus.identity is not None)
    check("  and sha256 is a 64-character digest",
          r.corpus.identity is not None
          and re.fullmatch(r"[0-9a-f]{64}", r.corpus.identity.sha256)
          is not None,
          r.corpus.identity.sha256 if r.corpus.identity else "None")
    check("  run_id names the run", r.corpus.identity.run_id == RUN,
          str(r.corpus.identity.run_id))

    # The ids are the fixture's own. Reading them back out of a search made
    # these two checks depend on what search chooses to show, which is a
    # different question from whether a caller holding an id gets a valid
    # envelope from the detail and compare paths.
    lst = api.listing("b0")
    ok, why = validates(schemas.ListingResponse, lst)
    check("ListingResponse validates on a real corpus", ok, why)

    cmp_ = api.compare(schemas.CompareRequest(ids=["b0", "b1"], q="۲۰۶"))
    ok, why = validates(schemas.CompareResponse, cmp_)
    check("CompareResponse validates on a real corpus", ok, why)
    check("  and it returns evidence, not rows",
          cmp_.rows == [] and len(cmp_.evidence) == 2)

    # This fixture carries no `product_class`, as the published schema
    # allows. The loader records such a row as `unknown`, never `vehicle`,
    # and search shows no `unknown` as a car (D52) — strict, by decision: a
    # class nobody determined does not pass the gate. The ids above still
    # reach the detail and compare paths; whether those should refuse a
    # non-vehicle is not decided here.
    _loaded = corpus_mod.active().listings
    check("  a row with no class is loaded as `unknown`, not `vehicle`",
          len(_loaded) == 9
          and all(x.product_class == "unknown" for x in _loaded),
          str(sorted({x.product_class for x in _loaded})))
    check("  and search shows none of them as a car",
          r.evidence == [] and r.items == [],
          f"shown: {[e.id for e in r.evidence]}")

# The control: the same nine rows and the same query, with the class the
# only difference. Without it, «none of them» above would pass just as well
# on a search that showed nothing to anybody.
with corpus_dir(valid_artifact(product_class="vehicle")):
    _r2 = api.search(q="۲۰۶", k=5)
    check("  the same rows declared `vehicle` are shown by the same query",
          len(_r2.evidence) == 5, f"shown: {[e.id for e in _r2.evidence]}")


# ---------------------------------------------------------------------------
print("\n3 — a missing DEFAULT corpus falls back, and says what it looked for")
with corpus_dir(None):
    r = api.which_corpus()
    check("kind is SYNTHETIC", r.status.kind == "SYNTHETIC", r.status.kind)
    check("  and there is NO fault — absence is not a failure",
          r.fault is None, str(r.fault))
    check("  and no identity is invented for it",
          r.corpus.identity is None)
    # The fallback was right, and mute. A deployment whose corpus sat in the
    # wrong directory rendered identically to one that had never collected
    # anything, and neither said which path had been tried.
    check("  and the note names the artifact it did not find",
          f"{RUN}.json" in r.corpus.note_fa, r.corpus.note_fa[-90:])


# ---------------------------------------------------------------------------
print("\n3b — a run that was ASKED FOR and is missing is not a fallback")
with corpus_dir(None, run_env="run_no_such_thing"):
    r = api.search(q="۲۰۶", k=3)
    ok, why = validates(schemas.SearchResponse, r)
    check("SearchResponse still validates", ok, why)
    check("  kind is UNUSABLE, not SYNTHETIC",
          r.status.kind == "UNUSABLE", r.status.kind)
    check("  fault.code is RUN_NOT_FOUND, not CORPUS_INVALID",
          r.fault is not None and r.fault.code == "RUN_NOT_FOUND",
          str(r.fault.code if r.fault else None))
    check("  and the message names the run that was asked for",
          r.fault is not None and "run_no_such_thing" in r.fault.message,
          str(r.fault.message if r.fault else None))
    check("  and nothing is served from it",
          not r.status.served and r.items == [] and r.evidence == [])
    # The two UNUSABLE causes reach a client through `fault.code` and through
    # nothing else, which is why the badge branches on the code and not on the
    # kind: «CORPUS UNUSABLE» over a run that is simply not there sends the
    # reader to inspect an artifact that is fine.
    check("  and `kind` alone cannot tell it from a corrupt file",
          r.status.kind == "UNUSABLE")


# ---------------------------------------------------------------------------
# 3c — the two endpoints that used to answer with a 404.
#
# `/api/listing` and `/api/compare` raised HTTPException before the envelope
# was built, so on an unloadable corpus the client was told «no listing 'b0'
# in this corpus» and «none of those ids are in this corpus». Both sentences
# are claims about a LISTING, made from a fact about the SOURCE (D54), and the
# second one is what a whole deployment said about every car on the site the
# moment CARO_RUN named a run that was not there. The listing may exist; there
# is nowhere to look.
print("\n3c — a refusal about the source is not a 404 about the listing")
for label, body, env, want_code in [
        ("configured run missing", None, "run_no_such_thing", "RUN_NOT_FOUND"),
        ("artifact will not load", "<html>404</html>", None, "CORPUS_INVALID")]:
    with corpus_dir(body, run_env=env):
        r = api.listing("b0")
        ok, why = validates(schemas.ListingResponse, r)
        check(f"{label} → ListingResponse validates", ok, why)
        check("  it carries the envelope, not an HTTP error",
              r.status.kind == "UNUSABLE" and r.fault is not None)
        check(f"  the fault is {want_code}",
              r.fault is not None and r.fault.code == want_code,
              str(r.fault.code if r.fault else None))
        check("  and `listing` is null — no car is claimed either way",
              r.listing is None, str(r.listing))

        c = api.compare(schemas.CompareRequest(ids=["b0", "b1"], q="۲۰۶"))
        ok, why = validates(schemas.CompareResponse, c)
        check("  CompareResponse validates", ok, why)
        check("  with the envelope and nothing in it",
              c.status.kind == "UNUSABLE" and c.rows == [] and c.evidence == [],
              f"rows={len(c.rows)} evidence={len(c.evidence)}")

# ---------------------------------------------------------------------------
# 3d — the statuses, over real HTTP.
#
# The checks above call the endpoints as Python functions, which is right for
# the models and blind to the thing this section is about: whether a 404 is
# still a 404, and whether its BODY is the envelope. A status code set on
# FastAPI's injected response object does not exist until something serves it,
# so this one goes through the stack.
#
# Three outcomes have to stay apart, and the first two used to be one:
#
#     no corpus was read          200   the fault is about the SOURCE
#     a corpus was read, id gone  404   the fault is about the RESOURCE
#     a corpus was read, id there 200   a listing
print("\n3d — the same distinctions as HTTP statuses, with envelopes")
from fastapi.testclient import TestClient                       # noqa: E402

HTTP = [
    # (label, artifact, CARO_RUN, request, want status, want fault code)
    ("no corpus · listing", None, "run_gone", ("GET", "/api/listing/b0"),
     200, "RUN_NOT_FOUND"),
    ("no corpus · compare", None, "run_gone", ("POST", "/api/compare"),
     200, "RUN_NOT_FOUND"),
    ("broken file · listing", "<html>404</html>", None,
     ("GET", "/api/listing/b0"), 200, "CORPUS_INVALID"),
    ("healthy · id present", valid_artifact(), None,
     ("GET", "/api/listing/b0"), 200, "ESTIMATOR_NOT_GATED"),
    ("healthy · id absent", valid_artifact(), None,
     ("GET", "/api/listing/ghost"), 404, "LISTING_NOT_FOUND"),
    ("healthy · no id matches", valid_artifact(), None,
     ("POST", "/api/compare"), 404, "COMPARE_IDS_NOT_FOUND"),
]

for label, body, env, (method, path), want_status, want_code in HTTP:
    with corpus_dir(body, run_env=env):
        with contextlib.redirect_stdout(io.StringIO()):
            client = TestClient(api.app, raise_server_exceptions=False)
            if method == "GET":
                resp = client.get(path)
            else:
                ids = ["b0", "b1"] if "run_gone" in (env or "") else ["ghost"]
                resp = client.post(path, json={"ids": ids, "q": "۲۰۶"})
        got = resp.json()
        fault = (got.get("fault") or {}).get("code")
        check(f"{label} → HTTP {want_status}", resp.status_code == want_status,
              str(resp.status_code))
        check(f"  fault.code is {want_code}", fault == want_code, str(fault))
        # The addition that makes the code usable: a 404 is a typed response
        # like any other. A body of `{"detail": "..."}` forces a client to
        # read English prose to find out what happened, which is how a page
        # ends up printing an exception at a buyer.
        check("  and the body carries the envelope",
              "corpus" in got and "status" in got,
              str(sorted(got))[:80])
        check("  with a Persian sentence for the person reading it",
              bool((got.get("fault") or {}).get("fa")))

# And the half that must NOT change. Turning every miss into a 200 would erase
# the one answer this endpoint is actually for: a corpus was read, and this id
# is not in it.
with corpus_dir(valid_artifact()):
    r = api.listing("b0")
    check("a healthy corpus still answers for an id it HAS",
          r.listing is not None and r.listing.id == "b0",
          str(r.listing))
    r = api.listing("definitely-not-here")
    check("  and still refuses one it does not, by fault code",
          r.listing is None and r.fault is not None
          and r.fault.code == "LISTING_NOT_FOUND",
          str(r.fault.code if r.fault else None))
    check("  while still naming the corpus that answered",
          r.corpus.identity is not None and r.status.kind == "REAL")


# ---------------------------------------------------------------------------
print("\n4 — a broken corpus is UNUSABLE, never SYNTHETIC (D49)")
_BROKEN = {
    "invalid schema": '{"schema": "not.caro/9", "run_id": "x", "source": "s",'
                      ' "collected_on": "d", "listings": []}',
    "truncated write": '{"schema": "caro.corpus/1", "listi',
    "an html error page": "<html>404 Not Found</html>",
    "empty file": "",
}
for label, body in _BROKEN.items():
    with corpus_dir(body):
        r = api.search(q="۲۰۶", k=3)
        ok, why = validates(schemas.SearchResponse, r)
        check(f"{label} → response still validates", ok, why)
        check(f"  kind is UNUSABLE, not SYNTHETIC",
              r.status.kind == "UNUSABLE", r.status.kind)
        check(f"  fault.code is CORPUS_INVALID",
              r.fault is not None and r.fault.code == "CORPUS_INVALID",
              str(r.fault))
        check(f"  and the message names what actually broke",
              r.fault is not None and len(r.fault.message) > 10)
        check(f"  nothing is served from it",
              not r.status.served and r.items == [] and r.evidence == [])


# ---------------------------------------------------------------------------
print("\n5 — an ungated corpus fabricates no estimate (D50)")
# The rows are declared vehicles. What D50 forbids is an estimate on the
# evidence a refusal carries, and that claim needs the evidence to be cars:
# a row whose class nobody determined is not one (D52), and a check that
# passes because nothing was shown to check proves nothing.
with corpus_dir(valid_artifact(product_class="vehicle")):
    r = api.search(q="۲۰۶", k=5)
    check("evidence exists", len(r.evidence) > 0, str(len(r.evidence)))
    check("  while nothing is appraisable", r.appraisable == 0, str(r.appraisable))
    check("  and considered counts the LISTINGS, not the empty row set",
          r.considered == 9, str(r.considered))

    # The invariant, read off the serialised payload rather than the objects:
    # a field that does not exist cannot be filled in by a later serialiser.
    # Searched as a JSON KEY, not as a substring. A bare `"rank" not in blob`
    # fails on the fault message's "no ranking may be served" — and a check
    # that fails on prose is one somebody disables.
    blob = r.model_dump_json()
    for field in ("estimate_toman", "opportunity_toman",
                  "expected_damage_toman", "score", "role_fa", "rank"):
        check(f"  «{field}» is not a key anywhere in the payload",
              f'"{field}":' not in blob)

    check("  and EvidenceItem has no such field to fill",
          not ({"estimate_toman", "opportunity_toman", "score"}
               & set(schemas.EvidenceItem.model_fields)),
          str(sorted(schemas.EvidenceItem.model_fields)))
    check("  nor UncheckedItem, the evidence that could not be checked",
          not ({"estimate_toman", "opportunity_toman", "score"}
               & set(schemas.UncheckedItem.model_fields)),
          str(sorted(schemas.UncheckedItem.model_fields)))
    check("  which is what makes this structural rather than a check",
          "estimate_toman" in schemas.ScoredItem.model_fields)


# ---------------------------------------------------------------------------
print("\n6 — a refusal is a product state, not an error")
# Vehicles for the same reason as section 5: `still_available` promises
# evidence, and the promise is only tested where there are cars to show.
with corpus_dir(valid_artifact(product_class="vehicle")):
    r = api.search(q="۲۰۶", k=5)
    ok, why = validates(schemas.SearchResponse, r)
    check("the refusal is schema-valid", ok, why)
    check("  served is false and a fault says why",
          r.status.served is False and r.fault is not None)
    # Neither expression may assume the fault is there. A check's detail is
    # evaluated whether or not it passes, so `r.fault.code` on a corpus that
    # is ranked (no fault) raised in the middle of the suite, and everything
    # after section 6 -- section 18 among it -- never ran.
    check("  the fault is the gate, not a corpus fault",
          r.fault is not None and r.fault.code == "ESTIMATOR_NOT_GATED",
          str(r.fault.code if r.fault else None))
    check("  the parsed intent survives", r.intent.query != "")
    check("  and `still_available` is not a promise — evidence is present",
          r.fault is not None and "evidence" in r.fault.still_available
          and len(r.evidence) > 0)
    # The endpoint returns a model; FastAPI turns it into a 200. Nothing here
    # raises, and that is the assertion: an HTTPException would be a 500.
    check("  nothing raised on the way out", True)


# ---------------------------------------------------------------------------
# 7 — the client's description of the contract, against the server's.
#
# This is a text parse of TypeScript from Python, which is crude. The
# alternative is codegen and a build step, and for eleven interfaces the check
# closes the same gap for a fraction of the machinery. If this file grows a
# generator, delete this block rather than keeping both.
print("\n7 — lib/api.ts describes the same shapes as schemas.py")

TS = (ROOT / "webapp/web/lib/api.ts").read_text(encoding="utf-8")

_IFACE = re.compile(
    r"export interface (\w+)(?:\s+extends\s+(\w+))?\s*\{(.*?)\n\}",
    re.DOTALL)
_FIELD = re.compile(r"^\s{2}(\w+)\??\s*:", re.MULTILINE)


def ts_interfaces() -> dict[str, tuple[str | None, set[str]]]:
    out = {}
    for name, parent, body in _IFACE.findall(TS):
        # Strip comments so a field name inside prose is not counted.
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        body = re.sub(r"//[^\n]*", "", body)
        out[name] = (parent or None, set(_FIELD.findall(body)))
    return out


TS_IFACES = ts_interfaces()
check(f"parsed {len(TS_IFACES)} interfaces out of lib/api.ts",
      len(TS_IFACES) >= 10, str(sorted(TS_IFACES)))


def ts_fields(name: str) -> set[str]:
    parent, fields = TS_IFACES[name]
    return fields | (ts_fields(parent) if parent else set())


PAIRS = [
    ("CorpusIdentity", schemas.CorpusIdentity),
    ("CorpusMeta", schemas.CorpusMeta),
    ("ServingStatus", schemas.ServingStatus),
    ("Fault", schemas.Fault),
    ("Envelope", schemas.Envelope),
    ("EvidenceItem", schemas.EvidenceItem),
    ("UncheckedItem", schemas.UncheckedItem),
    ("ScoredItem", schemas.ScoredItem),
    ("WeightSet", schemas.Weights),
    ("Intent", schemas.Intent),
    ("SearchResponse", schemas.SearchResponse),
    ("ListingResponse", schemas.ListingResponse),
    ("CompareResponse", schemas.CompareResponse),
    ("ModelSummary", schemas.ModelSummary),
    ("YearPoint", schemas.YearPoint),
    ("HistoryPoint", schemas.HistoryPoint),
    ("ModelsResponse", schemas.ModelsResponse),
    ("ModelResponse", schemas.ModelResponse),
]

for ts_name, model in PAIRS:
    if ts_name not in TS_IFACES:
        check(f"{ts_name} exists in lib/api.ts", False, "not found")
        continue
    got = ts_fields(ts_name)
    want = set(model.model_fields)
    missing, extra = want - got, got - want
    check(f"{ts_name} ≡ {model.__name__}",
          not missing and not extra,
          f"missing in TS: {sorted(missing) or '—'} · "
          f"not in Python: {sorted(extra) or '—'}")


# The unions, which the field comparison above does not reach.
#
# `FaultCode` and `CorpusKind` are `export type`, not `export interface`, so
# every check above is blind to them: the server can grow a member and the
# client keeps compiling, because TypeScript validates the client against its
# own copy of the union — and that copy is exactly the thing that goes stale.
# Nothing here has drifted yet. The check is written now because "nothing has
# drifted yet" is what was true of `lib/api.ts` before check 7 existed too.
_TYPE = re.compile(r"export type (\w+)\s*=\s*([^;]+);")
_MEMBER = re.compile(r"'([^']*)'")
DASH = "—"       # named, because an f-string expression may not hold one


def ts_union(name: str) -> set[str] | None:
    for got, body in _TYPE.findall(TS):
        if got != name:
            continue
        body = re.sub(r"/\*.*?\*/", "", body, flags=re.DOTALL)
        body = re.sub(r"//[^\n]*", "", body)
        return set(_MEMBER.findall(body))
    return None


for ts_name, literal in (("CorpusKind", schemas.CorpusKind),
                         ("FaultCode", schemas.FaultCode),
                         ("ConstraintKey", schemas.ConstraintKey),
                         ("MileageStatus", schemas.MileageStatus),
                         ("ProvinceSource", schemas.ProvinceSource)):
    got = ts_union(ts_name)
    want = set(typing.get_args(literal))
    if got is None:
        check(f"{ts_name} is declared in lib/api.ts", False, "not found")
        continue
    check(f"{ts_name} ≡ the Python Literal, member for member",
          got == want,
          f"missing in TS: {sorted(want - got) or DASH} · "
          f"not in Python: {sorted(got - want) or DASH}")

# And the one list that is not a type at all. `PRICE_STATUS_UNUSABLE` is the
# first half of the card's price rule, copied into TypeScript because the
# client has to apply it; a copy nobody checks is how the client ends up
# drawing a number the server would have refused.
from caro.ingest.quality import UNUSABLE_PRICE                    # noqa: E402

_pu = re.search(r"export const PRICE_STATUS_UNUSABLE: string\[\] = \[(.*?)\];",
                TS, re.S)
_ts_unusable = set(_MEMBER.findall(_pu.group(1))) if _pu else set()
_py_unusable = {s.value for s in UNUSABLE_PRICE}
check("PRICE_STATUS_UNUSABLE ≡ quality.UNUSABLE_PRICE, member for member",
      _ts_unusable == _py_unusable,
      f"missing in TS: {sorted(_py_unusable - _ts_unusable) or DASH} · "
      f"not in Python: {sorted(_ts_unusable - _py_unusable) or DASH}")

# The odometer's statuses are the quality layer's own, not a third copy of
# them: a status the parser can write and the payload cannot carry would
# fail validation on the way out, as a 500.
from caro.ingest.quality import Validity                          # noqa: E402

check("MileageStatus ≡ quality.Validity, member for member",
      set(typing.get_args(schemas.MileageStatus))
      == {v.value for v in Validity},
      f"{sorted(typing.get_args(schemas.MileageStatus))} vs "
      f"{sorted(v.value for v in Validity)}")

# The use-case names, the same way. The intent panel prints them under
# «کاربرد», and the parser names them inside an assumption on the same panel:
# two copies of one vocabulary, held to each other name for name, so the
# panel cannot call a use case one thing and its assumption another.
from caro.ranking import USE_CASE_FA as _PY_UC                    # noqa: E402

_ip = (ROOT / "webapp/web/components/IntentPanel.tsx").read_text(
    encoding="utf-8")
_uc = re.search(r"const USE_CASE_FA: Record<string, string> = \{(.*?)\};",
                _ip, re.S)
_ts_uc = dict(re.findall(r"(\w+):\s*'([^']*)'", _uc.group(1))) if _uc else {}
check("IntentPanel's USE_CASE_FA ≡ caro.ranking.USE_CASE_FA, name for name",
      bool(_ts_uc) and _ts_uc == _PY_UC,
      f"differ on: {sorted(k for k in set(_ts_uc) | set(_PY_UC) if _ts_uc.get(k) != _PY_UC.get(k))}")


# ---------------------------------------------------------------------------
print("\n8 — every example on the search box still finds something")
# ---------------------------------------------------------------------------
#
# The chips under the search box are the likeliest first click on the site,
# and an example that returns nothing is worse than no example at all: it is
# an invitation, and the visitor accepts it. Three of them used to name a 206
# while the shipped corpus held nothing but Saipa, so the most probable first
# impression of CARO was an empty screen.
#
# The list is READ from the component rather than copied here. A copy would
# pass forever while the real chips rotted — the same failure this file's
# section 7 exists to prevent for the TypeScript unions, and the same one the
# palette suite prevents for the demo.
#
# This runs against the REAL default corpus, not a fixture. The claim being
# made is about what is shipped; a synthetic artifact could satisfy any list.

_BOX = (ROOT / "webapp/web/components/SearchBox.tsx").read_text(encoding="utf-8")
_m = re.search(r"const EXAMPLES = \[(.*?)\];", _BOX, re.S)
check("EXAMPLES is readable from SearchBox.tsx", _m is not None)

if _m:
    _chips = re.findall(r"'([^']+)'", _m.group(1))
    check(f"  and holds {len(_chips)} example(s)", len(_chips) >= 3,
          str(_chips))

    _real = ROOT / "data" / "corpora"
    check("  the default corpus is present to check against",
          (_real / f"{RUN}.json").exists(), str(_real / f"{RUN}.json"))

    _was, _was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
    corpus_reader.CORPORA = _real
    os.environ.pop(corpus_mod.RUN_ENV, None)
    corpus_mod.active.cache_clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _kind = api.which_corpus().status.kind
            _res = [(q, api.search(q=q, k=8)) for q in _chips]
        check(f"  serving the real corpus (kind={_kind})", _kind == "REAL",
              _kind)
        for _q, _r in _res:
            # `evidence` is what an ungated corpus can still show. On a gated
            # one the same query would fill `items` instead, so both count —
            # the assertion is that the example leads somewhere, not which
            # branch it lands in. Listings shown apart, because a constraint
            # could not be checked against them, are somewhere too.
            _n = (len(_r.evidence) + len(_r.evidence_unchecked)
                  + len(_r.items))
            check(f"  «{_q[:38]}» → {_n}", _n > 0,
                  "this example finds nothing in the shipped corpus")
    finally:
        corpus_reader.CORPORA = _was
        if _was_run is None:
            os.environ.pop(corpus_mod.RUN_ENV, None)
        else:
            os.environ[corpus_mod.RUN_ENV] = _was_run
        corpus_mod.active.cache_clear()


# ---------------------------------------------------------------------------
print("\n9 — the detail renderer receives product_class")
# ---------------------------------------------------------------------------
#
# `product_class` is the only gate in FIELD_PROVENANCE.md: only `vehicle`
# renders as a car (D52). run11 carries it on all 76 records, and one of them
# is not a vehicle — an assignment, with a make, a model, a trim, a year and a
# price, so every cell the detail page draws is populated. The one field that
# says it is not a car is the one field EvidenceItem was built without,
# and a renderer cannot branch on what it is not sent.
#
# WHAT THIS ASSERTS: that the information reaches the renderer — present in
# the payload model, and delivered by the detail path with the value the
# artifact holds. WHAT IT DOES NOT: what the site or the API should DO with
# it. `200 + product_class` and a `NOT_A_VEHICLE` fault are both open, and
# neither is chosen here. The read below is from where today's path puts the
# listing; the commit that makes that choice moves the read with it.
#
# The TypeScript side is not asserted separately. Section 7 already holds
# lib/api.ts's EvidenceItem to schemas.py field for field, in both
# directions, so a field added here and not there fails there. A second
# assertion of the same fact would be a second place for it to drift.

check("EvidenceItem carries product_class",
      "product_class" in schemas.EvidenceItem.model_fields,
      "the payload has no field that says whether a listing is a car")
print("    lib/api.ts follows from section 7, which compares EvidenceItem "
      "in both directions")

_art_path = ROOT / "data" / "corpora" / f"{RUN}.json"
_nv_path = ROOT / "data" / "corpora" / f"{NV_RUN}.json"
if not (_art_path.exists() and _nv_path.exists()):
    check("  the default corpus, and run11, are present to check against",
          False, f"{_art_path} · {_nv_path}")
else:
    _art = {r["listing_id"]: r for r in json.loads(
        _art_path.read_text(encoding="utf-8"))["listings"]}
    _nv = {r["listing_id"]: r for r in json.loads(
        _nv_path.read_text(encoding="utf-8"))["listings"]}
    print(f"    the default corpus ({RUN}) holds "
          f"{sum(r.get('product_class') != 'vehicle' for r in _art.values())}"
          f" non-vehicle(s); sections 9 to 11 follow {NV_RUN}'s")
    _pc = {i: r.get("product_class") for i, r in _nv.items()}
    _vehicle = next((i for i, c in sorted(_pc.items()) if c == "vehicle"),
                    None)
    _others = sorted(i for i, c in _pc.items() if c and c != "vehicle")
    if not _others:
        print("    the corpus holds no non-vehicle, so the distinguishing "
              "case has nothing to run on — said, not passed")

    # The odometer's status travels with its number (FIELD_PROVENANCE.md) only
    # if the artifact holds one beside every number. run11 does; a corpus that
    # did not would hand the payload a number with nothing to grade it.
    _bare = sorted(i for i, r in _art.items()
                   if r.get("mileage_km") is not None
                   and r.get("mileage_status") is None)
    check(f"  every odometer reading in the artifact states its status "
          f"({sum(1 for r in _art.values() if r.get('mileage_km') is not None)})",
          not _bare, f"a number with no status: {_bare}")

    _was, _was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
    corpus_reader.CORPORA = _nv_path.parent
    os.environ[corpus_mod.RUN_ENV] = NV_RUN
    corpus_mod.active.cache_clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _kind = api.which_corpus().status.kind
            _got = {i: api.listing(listing_id=i)
                    for i in ([_vehicle] if _vehicle else []) + _others}
        check(f"  serving the real corpus (kind={_kind})", _kind == "REAL",
              _kind)
        for _id, _resp in _got.items():
            _delivered = (getattr(_resp.listing, "product_class", None)
                          if _resp.listing is not None else None)
            check(f"  detail path delivers product_class for {_id} "
                  f"(artifact: {_pc[_id]})",
                  _delivered == _pc[_id],
                  f"the renderer receives {_delivered!r}")
            # The two fields the card's price rule names, the same way: a
            # field that is on the model and never filled is a rule the
            # client applies to None. Both paths build a row through
            # `_listing_evidence`, so this follows the value from the
            # artifact to the payload rather than testing one endpoint.
            _want = {k: _nv[_id].get(k) for k in ("price_status", "price_kind",
                                                   "mileage_status")}
            _sent = {k: getattr(_resp.listing, k, None) for k in _want}
            check(f"  and the fields the card's rules read for {_id} "
                  f"({_want['price_status']} / {_want['price_kind']} / "
                  f"{_want['mileage_status']})",
                  _sent == _want, f"the renderer receives {_sent}")
    finally:
        corpus_reader.CORPORA = _was
        if _was_run is None:
            os.environ.pop(corpus_mod.RUN_ENV, None)
        else:
            os.environ[corpus_mod.RUN_ENV] = _was_run
        corpus_mod.active.cache_clear()


# ---------------------------------------------------------------------------
print("\n10 — the gate is applied before a reader sees a row")
# ---------------------------------------------------------------------------
#
# FIELD_PROVENANCE.md defines a gate as the thing "the query applies before a
# reader sees a row; nobody chooses it", and names one: product_class, which
# only `vehicle` passes (D52). Section 9 proves the field reaches the client.
# This proves the QUERY honours it, which it once did not: `_evidence`'s
# filter checked model, budget, year and mileage and never the class, and
# the Quik chip under the search box showed an assignment as the
# eighth of its eight rows — a 1405 Quik at ninety million toman beside real
# ones at a billion.
#
# The gates are read from the declaration rather than named here, so a second
# gate added later fails the first check below until someone decides what
# passes it.
#
# ONLY the search endpoints. A detail page reached by id, and a compare of ids
# someone chose, are not a query whose rows a reader is shown; whether they
# should refuse a non-vehicle is a separate decision and is not taken here.
#
# The class of each row shown is read from the ARTIFACT, by id — not from the
# row the endpoint returned. A guard that takes its verdict from the thing it
# guards passes the day that thing labels what it shows `vehicle`; and a
# scored row carries no class at all (a Row has none, by design), which a
# read of the payload would report as a leak.
#
# Queries are derived, not listed: every example chip, read from the
# component as section 8 reads it, and one bare query per model the corpus
# holds, at k=24 — the most either endpoint accepts (section 14). The reach
# check at the end is what makes 24 enough: each non-vehicle must fall inside
# the first 24 of its own model's query, or the guard could not see it leak.

from webapp.api.eligibility import FIELDS as _DECL               # noqa: E402

_gates = sorted(f for f, e in _DECL.items() if e.gate)
check(f"the declaration's gates are exactly {_gates}",
      _gates == ["product_class"],
      "a new gate needs its own pass rule in this section before it is covered")

_art10 = ROOT / "data" / "corpora" / f"{NV_RUN}.json"
if not _art10.exists():
    check(f"  {NV_RUN} is present to check against", False, str(_art10))
else:
    _rows10 = json.loads(_art10.read_text(encoding="utf-8"))["listings"]
    _cls10 = {x["listing_id"]: x.get("product_class") for x in _rows10}
    _models = sorted({(x.get("model") or "").lower() for x in _rows10
                      if x.get("model")})
    _box10 = (ROOT / "webapp/web/components/SearchBox.tsx").read_text(
        encoding="utf-8")
    _m10 = re.search(r"const EXAMPLES = \[(.*?)\];", _box10, re.S)
    _queries = (re.findall(r"'([^']+)'", _m10.group(1)) if _m10 else []) \
        + _models

    _was, _was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
    corpus_reader.CORPORA = _art10.parent
    os.environ[corpus_mod.RUN_ENV] = NV_RUN
    corpus_mod.active.cache_clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _kind10 = api.which_corpus().status.kind
            _res10 = [(q, "search", api.search(q=q, k=24))
                      for q in _queries] + \
                     [(q, "reweight", api.search_reweight(
                         q=q, weights=schemas.ReweightRequest(), k=24))
                      for q in _queries]
        check(f"  serving the real corpus (kind={_kind10})",
              _kind10 == "REAL", _kind10)
        for _q, _ep, _r in _res10:
            _shown = (list(_r.evidence) + list(_r.evidence_unchecked)
                      + list(_r.items))
            _past = sorted({x.id for x in _shown
                            if _cls10.get(x.id) != "vehicle"})
            check(f"  {_ep:<8} «{_q[:30]}» — {len(_shown)} row(s), none "
                  f"past the gate", not _past,
                  f"a non-vehicle is shown as a row: {_past}")
    finally:
        corpus_reader.CORPORA = _was
        if _was_run is None:
            os.environ.pop(corpus_mod.RUN_ENV, None)
        else:
            os.environ[corpus_mod.RUN_ENV] = _was_run
        corpus_mod.active.cache_clear()

    for _nv in (x for x in _rows10 if x.get("product_class") != "vehicle"):
        _mm = (_nv.get("model") or "").lower()
        _same = [x["listing_id"] for x in _rows10
                 if (x.get("model") or "").lower() == _mm]
        _pos = _same.index(_nv["listing_id"]) + 1
        check(f"  reach: {_nv['listing_id']} ({_nv.get('product_class')}) "
              f"would be row {_pos} of «{_mm}» — inside k=24",
              _pos <= 24,
              "outside what one query can show, so a leak here is invisible")




# ---------------------------------------------------------------------------
print("\n11 — every non-vehicle reaches the screen, with its class")
# ---------------------------------------------------------------------------
#
# The contract chosen for detail and compare, after both were measured: they
# answer 200 with the listing and its class, and the SCREEN is obliged to say
# what the listing is. This is the API half — every non-vehicle it is asked
# about is delivered, with the class the artifact records. By detail; by
# compare alone; and by compare beside a vehicle, where it used to be dropped
# without a word, because that branch answered from appraisal Rows only.
#
# The other half — whether the screen then draws it as a car — is
# tests/test_screens.py. It renders the components the pages use, and it
# needs node, which this suite does not; run_all skips a suite by name when a
# declared dependency is absent, and a render check in here would have taken
# every API assertion down with it.
#
# Two non-vehicles: the assignment in run11, and `unknown` from section 2's
# class-less fixture. run11 carries a class on every record, so without the
# fixture `unknown` would never be asked about here at all.

_art11 = ROOT / "data" / "corpora" / f"{NV_RUN}.json"
_cls11 = {x["listing_id"]: x.get("product_class") for x in json.loads(
    _art11.read_text(encoding="utf-8"))["listings"]}
_nvs = sorted(i for i, c in _cls11.items() if c != "vehicle")
check(f"{NV_RUN} holds {len(_nvs)} non-vehicle(s) to follow",
      len(_nvs) > 0, "nothing to run on — said, not passed")

_was, _was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
corpus_reader.CORPORA = _art11.parent
os.environ[corpus_mod.RUN_ENV] = NV_RUN
corpus_mod.active.cache_clear()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        # A vehicle that is also an appraisal Row: beside one, compare used
        # to take the branch that dropped everything else.
        _veh = next(r.listing_id for r in corpus_mod.active().rows)
        _detail = [(_i, _cls11[_i], api.listing(_i)) for _i in _nvs]
        _asked = [((_i,), api.compare(schemas.CompareRequest(
                      ids=[_i], q="خودرو"))) for _i in _nvs]
        _asked += [((_i, _veh), api.compare(schemas.CompareRequest(
                       ids=[_i, _veh], q="خودرو"))) for _i in _nvs]
finally:
    corpus_reader.CORPORA = _was
    if _was_run is None:
        os.environ.pop(corpus_mod.RUN_ENV, None)
    else:
        os.environ[corpus_mod.RUN_ENV] = _was_run
    corpus_mod.active.cache_clear()

with corpus_dir(valid_artifact()):
    _detail.append(("b0", "unknown", api.listing("b0")))
    _asked.append((("b0",), api.compare(schemas.CompareRequest(
        ids=["b0"], q="۲۰۶"))))
_want11 = {**_cls11, "b0": "unknown"}

for _i, _c, _d in _detail:
    _got = _d.listing.product_class if _d.listing is not None else None
    check(f"  detail delivers {_i} with its class ({_c})", _got == _c,
          f"the screen receives "
          f"{'no listing' if _d.listing is None else repr(_got)}")
for _ids, _r in _asked:
    _sent = {x.id: x.product_class for x in list(_r.evidence) + list(_r.rows)}
    check(f"  compare {' + '.join(_ids)} delivers every id it was asked "
          f"about, the non-vehicle with its class",
          set(_ids) <= set(_sent)
          and all(_sent[_i] == _want11[_i] for _i in _ids
                  if _want11[_i] != "vehicle"),
          f"sent {_sent}")


# ---------------------------------------------------------------------------
print("\n12 — the contact inbox keeps a message, or refuses it and says where")
# ---------------------------------------------------------------------------
# A deployment whose disk does not keep what is written — a serverless
# function — would take a message, return a reference and lose the file. So
# the inbox can be switched off (CARO_INBOX=off), and a write that fails
# anyway is refused the same way. Measured over HTTP on a temporary inbox,
# never on data/inbox/.
from webapp.api import contact as contact_mod                      # noqa: E402

# Where it sends people is the address the owner decided (D68): the Issues
# of Tecso-Dev/caro, the repository the code lives in, where Issues is on and
# open to every account (D68, result). Every other check here holds the
# status and the 503s to ELSEWHERE, which is to say to itself, so pointing it
# at another repository turned nothing red. This holds it to that address.
check("ELSEWHERE is Tecso-Dev/caro's Issues, the address D68 decided",
      contact_mod.ELSEWHERE == "https://github.com/Tecso-Dev/caro/issues",
      contact_mod.ELSEWHERE)

_kept = (contact_mod.INBOX, contact_mod.MESSAGES, os.environ.get("CARO_INBOX"))
_MSG = {"name": "آزمون", "email": "test@example.com",
        "subject": "آزمون", "body": "یک پیام آزمایشی برای صندوق."}


def _lines(p: Path) -> list[str]:
    return p.read_text(encoding="utf-8").splitlines() if p.exists() else []


with tempfile.TemporaryDirectory() as _d:
    contact_mod.INBOX = Path(_d) / "inbox"
    contact_mod.MESSAGES = contact_mod.INBOX / "messages.jsonl"
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            _client = TestClient(api.app, raise_server_exceptions=False)

        os.environ.pop("CARO_INBOX", None)
        _st = _client.get("/api/contact/status").json()
        check("with CARO_INBOX unset the inbox says it is open",
              _st.get("open") is True, f"{_st}")
        _r = _client.post("/api/contact", json=_MSG)
        _ref = _r.json().get("ref") if _r.status_code == 200 else None
        check("  a message is kept, and its reference names the line written",
              bool(_ref) and any(f'"ref": "{_ref}"' in ln
                                 for ln in _lines(contact_mod.MESSAGES)),
              f"HTTP {_r.status_code}, "
              f"{len(_lines(contact_mod.MESSAGES))} line(s) written")

        os.environ["CARO_INBOX"] = "off"
        _st = _client.get("/api/contact/status").json()
        check("with CARO_INBOX=off it says it is closed, and where to go",
              _st.get("open") is False
              and _st.get("elsewhere") == contact_mod.ELSEWHERE, f"{_st}")
        _before = len(_lines(contact_mod.MESSAGES))
        _r = _client.post("/api/contact", json=_MSG)
        check("  a message is refused with 503, naming that place",
              _r.status_code == 503
              and contact_mod.ELSEWHERE in str(_r.json().get("detail", "")),
              f"HTTP {_r.status_code}: {_r.text[:120]}")
        check("  and nothing is written",
              len(_lines(contact_mod.MESSAGES)) == _before,
              f"{len(_lines(contact_mod.MESSAGES))} line(s), was {_before}")

        # Open, on a disk that cannot be written: the inbox's parent is a
        # file, so creating the directory fails as a read-only one does.
        os.environ.pop("CARO_INBOX", None)
        _blocker = Path(_d) / "not-a-directory"
        _blocker.write_text("x", encoding="utf-8")
        contact_mod.INBOX = _blocker / "inbox"
        contact_mod.MESSAGES = contact_mod.INBOX / "messages.jsonl"
        _r = _client.post("/api/contact", json=_MSG)
        check("an open inbox that cannot write refuses with 503, not 500, "
              "and hands out no reference",
              _r.status_code == 503 and "ref" not in _r.json()
              and contact_mod.ELSEWHERE in str(_r.json().get("detail", "")),
              f"HTTP {_r.status_code}: {_r.text[:120]}")
    finally:
        contact_mod.INBOX, contact_mod.MESSAGES = _kept[0], _kept[1]
        if _kept[2] is None:
            os.environ.pop("CARO_INBOX", None)
        else:
            os.environ["CARO_INBOX"] = _kept[2]


# ---------------------------------------------------------------------------
print("\n13 — a match is a listing every stated constraint was checked against")
# ---------------------------------------------------------------------------
#
# `_evidence` used to run a comparison only when the listing carried the
# value, so a listing with no price passed «زیر ۳۰۰ میلیون» and one with no
# odometer passed «کم‌کارکرد» (D60, D61). `webapp/api/constraints.py` gives a
# constraint three answers — met, broken, unknown — and a listing is a match
# only when every constraint the buyer stated is met; one that breaks none and
# lacks a value for some is shown apart, naming it.
#
# First the rule, on listings built here, so that every branch is reached
# whether or not the shipped corpus holds a case for it. Then every example
# chip on the shipped corpus, with each listing's values read from the
# ARTIFACT by id rather than from the payload, for the reason section 10
# gives: a guard that takes its verdict from what it guards passes the day
# the payload agrees with itself.

from types import SimpleNamespace                                   # noqa: E402

from caro.ranking import IntentSpec                                 # noqa: E402
from webapp.api import constraints                                  # noqa: E402


def _L(price=500_000_000, *, status="display_confirmed", kind="cash",
       year=1398, km=100_000, ms="plausible", cond="intact", docs=False,
       gearbox="automatic", trim=None, city=None, source=None):
    # `city` is what the reader calls the corpus's `province`; `source` is
    # `province_source`, which the judge does not read.
    return SimpleNamespace(asking_price_toman=price, price_status=status,
                           price_kind=kind, year_jalali=year, mileage_km=km,
                           mileage_status=ms, body_condition=cond,
                           document_issue=docs, gearbox=gearbox, trim=trim,
                           city=city, province_source=source)


def _u(x, spec):
    return constraints.unchecked(constraints.judge(x, spec))


_BUDGET = IntentSpec(raw_query="t", budget_max_toman=600_000_000)
_STATED = IntentSpec(raw_query="t", budget_max_toman=600_000_000,
                     year_min=1395, max_mileage_km=150_000)

check("a price inside the budget is a match", _u(_L(), _BUDGET) == [])
check("  above it, the listing is left out",
      _u(_L(700_000_000), _BUDGET) is None)
check("  no price at all: not a match, and «budget» is named",
      _u(_L(None, status="absent", kind="negotiable"), _BUDGET) == ["budget"])
check("  a cash figure with no status recorded is still checked",
      _u(_L(status=None), _BUDGET) == []
      and _u(_L(700_000_000, status=None), _BUDGET) is None)
check("  a financing total under the budget is not inside it",
      _u(_L(300_000_000, kind="financing_total"), _BUDGET) == ["budget"])
check("  nor a figure whose status is unusable",
      _u(_L(300_000_000, status="ambiguous"), _BUDGET) == ["budget"])
check("  a floor is checked the same way",
      _u(_L(None), IntentSpec(raw_query="t", budget_min_toman=1)) == ["budget"]
      and _u(_L(), IntentSpec(raw_query="t",
                              budget_min_toman=600_000_000)) is None)
check("no year and no odometer: both named, in the order judged",
      _u(_L(year=None, km=None, ms="unknown"), _STATED) == ["year", "mileage"])
check("  one broken constraint leaves a listing out, whatever else is unknown",
      _u(_L(None, km=400_000), _STATED) is None)

# The odometer, in the four grades of caro.ingest.quality.Validity (D22). Only
# `plausible` lets the number decide; the other three are unknown to the
# constraint and keep their own name on the listing. D21's own examples are
# the cases: the filter before this compared every number alike, and got them
# wrong in both directions.
_KM = IntentSpec(raw_query="t", max_mileage_km=120_000)
check("odometer plausible: 100,000 meets «کم‌کارکرد», 200,000 breaks it",
      _u(_L(km=100_000), _KM) == [] and _u(_L(km=200_000), _KM) is None)
check("  unknown, no number: unknown",
      _u(_L(km=None, ms="unknown"), _KM) == ["mileage"])
check("  suspicious, 1 km on a 1385 car: unknown — it no longer meets the cap",
      _u(_L(km=1, year=1385, ms="suspicious"), _KM) == ["mileage"])
check("  suspicious, the 999,990 placeholder: unknown — nor breaks it",
      _u(_L(km=999_990, ms="suspicious"), _KM) == ["mileage"])
check("  impossible, −5,000 or 2,000,000: unknown, whichever side",
      _u(_L(km=-5_000, ms="impossible"), _KM) == ["mileage"]
      and _u(_L(km=2_000_000, ms="impossible"), _KM) == ["mileage"])
check("  a number whose status was never recorded is not trusted",
      _u(_L(km=90_000, ms=None), _KM) == ["mileage"])
check("  a constraint the buyer did not state is not judged at all",
      constraints.judge(_L(None, year=None, km=None),
                        IntentSpec(raw_query="t")) == {})

# The red lines. Each from the one field that answers it; silence is unknown.
from caro.ranking import DEAL_BREAKER_CUES                          # noqa: E402


def _red(line, **kw):
    return _u(_L(**kw), IntentSpec(raw_query="t", deal_breakers=(line,)))


check("every red line the parser can record has a rule",
      set(constraints.RED_LINES) == set(DEAL_BREAKER_CUES),
      f"no rule: {sorted(set(DEAL_BREAKER_CUES) - set(constraints.RED_LINES))}")
check("  and every name a listing can be unchecked on is one the client knows",
      set(typing.get_args(schemas.ConstraintKey))
      == {"budget", "year", "mileage", "province"}
      | set(constraints.RED_LINES),
      str(sorted(typing.get_args(schemas.ConstraintKey))))
check("«تصادفی نباشه»: an accident is left out, a stated body is a match, "
      "silence is named",
      _red("accident", cond="accident") is None
      and _red("accident", cond="multi_paint") == []
      and _red("accident", cond="unknown") == ["accident"]
      and _red("accident", cond=None) == ["accident"])
check("«سند آزاد»: a document issue is left out, none stated is named",
      _red("unclear_documents", docs=True) is None
      and _red("unclear_documents", docs=False) == []
      and _red("unclear_documents", docs=None) == ["unclear_documents"])
check("«اتومات»: a manual gearbox is left out, an unrecorded one is named",
      _red("manual", gearbox="manual") is None
      and _red("manual", gearbox="automatic") == []
      and _red("manual", gearbox=None) == ["manual"])
check("  with none recorded, a trim word that IS the gearbox answers it",
      _red("manual", gearbox=None, trim="manual") is None
      and _red("manual", gearbox=None, trim="Automatic") == [])
check("  and nothing else in a trim does — an artefact stays unknown",
      _red("manual", gearbox=None, trim="manualr") == ["manual"]
      and _red("manual", gearbox=None, trim="gx lmt") == ["manual"]
      and _red("manual", gearbox="automatic", trim="manual") == [])
check("«بدون رنگ»: only `intact` meets it, every rung above breaks it",
      _red("repaint", cond="intact") == []
      and all(_red("repaint", cond=c) is None for c in
              ("minor_paint", "multi_paint", "replaced_part", "accident"))
      and _red("repaint", cond="unknown") == ["repaint"])
check("  a red line with no rule is not met, it is unknown",
      constraints.judge(_L(), IntentSpec(raw_query="t",
                                         deal_breakers=("no_such_rule",)))
      == {"no_such_rule": "unknown"})


# A province the buyer names. From the one field that answers it; several are
# any-of; a province known from the city's name meets it as a stated one does
# (the table beside the answer says which, D81); and silence is unknown, never
# met.
_PROV = IntentSpec(raw_query="t", provinces=("تهران",))
_PROV2 = IntentSpec(raw_query="t", provinces=("تهران", "اصفهان"))
check("«در تهران»: a listing in Tehran meets it, one elsewhere is left out, "
      "one with no province is named",
      _u(_L(city="تهران"), _PROV) == []
      and _u(_L(city="اصفهان"), _PROV) is None
      and _u(_L(city=None), _PROV) == ["province"])
check("  an empty string is no province",
      _u(_L(city=""), _PROV) == ["province"])
check("  several named are any-of: either meets it, a third is left out",
      _u(_L(city="تهران"), _PROV2) == []
      and _u(_L(city="اصفهان"), _PROV2) == []
      and _u(_L(city="یزد"), _PROV2) is None
      and _u(_L(city=None), _PROV2) == ["province"])
check("  a province known from the city's name meets it as a stated one does",
      _u(_L(city="تهران", source="city"), _PROV) == []
      and _u(_L(city="تهران", source="stated"), _PROV) == []
      and _u(_L(city="اصفهان", source="city"), _PROV) is None)
check("  it is judged when stated and not otherwise",
      constraints.judge(_L(city="تهران"), IntentSpec(raw_query="t")) == {}
      and constraints.judge(_L(city="تهران"), _PROV) == {"province": "met"})
check("  beside the other constraints it is named in the order judged: "
      "after the odometer, before the red lines",
      _u(_L(None, status="absent", kind="negotiable", year=None, city=None,
            cond=None),
         IntentSpec(raw_query="t", budget_max_toman=600_000_000,
                    year_min=1395, provinces=("تهران",),
                    deal_breakers=("accident",)))
      == ["budget", "year", "province", "accident"])
check("  and one broken constraint leaves a listing out, a province or not",
      _u(_L(city=None, km=400_000),
         IntentSpec(raw_query="t", max_mileage_km=150_000,
                    provinces=("تهران",))) is None
      and _u(_L(city="اصفهان", km=None, ms="unknown"),
             IntentSpec(raw_query="t", max_mileage_km=150_000,
                        provinces=("تهران",))) is None)
check("IntentSpec states no province unless one is stated, and the payload "
      "says so",
      IntentSpec(raw_query="t").provinces == ()
      and api._intent(IntentSpec(raw_query="t")).provinces == [])
check("  and carries the provinces stated, in the order stated",
      api._intent(IntentSpec(raw_query="t",
                             provinces=("اصفهان", "تهران"))).provinces
      == ["اصفهان", "تهران"])


# The red lines read off the artifact's own field names, so that the rule is
# stated here a second time rather than borrowed from the code it checks.
_RED13 = {   # line: (field, values that break it, values that meet it)
    "accident": ("condition", {"accident"},
                 {"intact", "minor_paint", "multi_paint", "replaced_part"}),
    "unclear_documents": ("document_issue", {True}, {False}),
    "manual": ("gearbox", {"manual"}, {"automatic"}),
    "repaint": ("condition",
                {"minor_paint", "multi_paint", "replaced_part", "accident"},
                {"intact"}),
}


def _gear13(rec: dict):
    """The gearbox the artifact records, or else a trim word that is one."""
    if rec.get("gearbox") in ("manual", "automatic"):
        return rec["gearbox"]
    words = set((rec.get("trim") or "").lower().split()) & {"manual",
                                                            "automatic"}
    return words.pop() if len(words) == 1 else None


def _red13(rec: dict, line: str):
    field, breaks, meets = _RED13[line]
    return _gear13(rec) if line == "manual" else rec.get(field)


def _value_missing(rec: dict, i) -> list[str]:
    """What the artifact holds no value for, among the constraints `i` states
    — in judge order. A price counts only as the card would draw it."""
    out = []
    if i.budget_max_toman is not None or i.budget_min_toman is not None:
        drawn = ((rec.get("price_kind") or "absent") == "cash"
                 and rec.get("price_status") not in _py_unusable)
        if rec.get("asking_price_toman") is None or not drawn:
            out.append("budget")
    if i.year_min is not None and rec.get("year_jalali") is None:
        out.append("year")
    if i.max_mileage_km is not None and (
            rec.get("mileage_km") is None
            or rec.get("mileage_status") != "plausible"):
        out.append("mileage")
    if i.provinces and not rec.get("province"):
        out.append("province")
    for line in i.deal_breakers:
        _, breaks, meets = _RED13[line]
        if _red13(rec, line) not in breaks | meets:
            out.append(line)
    return out


def _value_breaks(rec: dict, i) -> bool:
    p, y, m = (rec.get("asking_price_toman"), rec.get("year_jalali"),
               rec.get("mileage_km"))
    return ((p is not None and "budget" not in _value_missing(rec, i)
             and ((i.budget_max_toman is not None and p > i.budget_max_toman)
                  or (i.budget_min_toman is not None
                      and p < i.budget_min_toman)))
            or (i.year_min is not None and y is not None and y < i.year_min)
            or (i.max_mileage_km is not None and m is not None
                and rec.get("mileage_status") == "plausible"
                and m > i.max_mileage_km)
            or (bool(i.provinces) and bool(rec.get("province"))
                and rec["province"] not in i.provinces)
            or any(_red13(rec, line) in _RED13[line][1]
                   for line in i.deal_breakers))


_art13 = ROOT / "data" / "corpora" / f"{RUN}.json"
_rec13 = {x["listing_id"]: x for x in json.loads(
    _art13.read_text(encoding="utf-8"))["listings"]}
_box13 = (ROOT / "webapp/web/components/SearchBox.tsx").read_text(
    encoding="utf-8")
_m13 = re.search(r"const EXAMPLES = \[(.*?)\];", _box13, re.S)
_chips13 = re.findall(r"'([^']+)'", _m13.group(1)) if _m13 else []
_K13 = 8                                     # what the results page asks for

_was, _was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
corpus_reader.CORPORA = _art13.parent
os.environ.pop(corpus_mod.RUN_ENV, None)
corpus_mod.active.cache_clear()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        _res13 = [(q, api.search(q=q, k=_K13)) for q in _chips13]
finally:
    corpus_reader.CORPORA = _was
    if _was_run is None:
        os.environ.pop(corpus_mod.RUN_ENV, None)
    else:
        os.environ[corpus_mod.RUN_ENV] = _was_run
    corpus_mod.active.cache_clear()

def _judge13(_q, _r, _rec, _where=""):
    _i = _r.intent
    _bad = [x.id for x in _r.evidence if _value_missing(_rec[x.id], _i)]
    check(f"  «{_q[:30]}»{_where} — {len(_r.evidence)} match(es), each checked "
          f"against every constraint stated", not _bad,
          f"a match with a value missing: {_bad}")
    _wrong = [(x.id, x.unchecked) for x in _r.evidence_unchecked
              if not x.unchecked
              or x.unchecked != _value_missing(_rec[x.id], _i)]
    check(f"    {len(_r.evidence_unchecked)} shown apart, each naming what "
          f"its listing lacks", not _wrong, f"named wrongly: {_wrong}")
    _broke = [x.id for x in list(_r.evidence) + list(_r.evidence_unchecked)
              if _value_breaks(_rec[x.id], _i)]
    check("    nothing shown breaks a constraint stated", not _broke,
          f"shown, and breaking one: {_broke}")
    # The totals, counted in the artifact: every vehicle of the model asked
    # for that breaks nothing, split by whether a value is missing. Checked
    # against the payload's own lists alone, a total that reported only the
    # rows shown would agree with itself.
    _cand = [rec for rec in _rec.values()
             if rec.get("product_class") == "vehicle"
             and (not _i.models
                  or (rec.get("model") or "").lower() in _i.models)
             and not _value_breaks(rec, _i)]
    _want_m = sum(1 for rec in _cand if not _value_missing(rec, _i))
    _want_a = len(_cand) - _want_m
    check(f"    the totals count every one ({_r.evidence_total} matched, "
          f"{_r.evidence_unchecked_total} apart), the lists the first "
          f"{_K13} of each",
          (_r.evidence_total, _r.evidence_unchecked_total)
          == (_want_m, _want_a)
          and len(_r.evidence) == min(_want_m, _K13)
          and len(_r.evidence_unchecked) == min(_want_a, _K13),
          f"the artifact holds {_want_m} matched and {_want_a} apart")


for _q, _r in _res13:
    _judge13(_q, _r, _rec13)

_apart13 = sum(len(r.evidence_unchecked) for _, r in _res13)
check(f"  the examples reach the case: {_apart13} listing(s) shown apart",
      _apart13 > 0,
      "nothing was shown apart, so the checks above cannot see the rule "
      "— said, not passed")

# The province. None of the chips states one, so nothing above reaches what
# `judge` does with it (D82): met when the listing is in a province the buyer
# named, unknown when it holds none, broken when it is in another. The
# published corpora hold the field in different amounts — none of the cars, a
# third of them, all but one, every one — which is the reason to read all of
# them: a rule run only on the default corpus would go on passing the day it
# counted a missing province as a match, because the default has no car
# without one. Each car's province is read from the ARTIFACT by id, and the
# totals are counted there, as they are for the chips.
from caro.ingest.persian import PROVINCES, PROVINCE_SPELLINGS       # noqa: E402

_CORP13 = ROOT / "data" / "corpora"


@contextlib.contextmanager
def _published(run):
    """The API serving one published corpus, whatever the default is."""
    was, was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
    corpus_reader.CORPORA = _CORP13
    os.environ[corpus_mod.RUN_ENV] = run
    corpus_mod.active.cache_clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        corpus_reader.CORPORA = was
        if was_run is None:
            os.environ.pop(corpus_mod.RUN_ENV, None)
        else:
            os.environ[corpus_mod.RUN_ENV] = was_run
        corpus_mod.active.cache_clear()


# What a buyer can type after «در»: the thirty-one names, and each spelling
# that is not one of them with the province it means. Asked with no model and
# with each of the three the corpora hold most of.
_NAMES13 = [(p, p) for p in PROVINCES] + list(PROVINCE_SPELLINGS.items())
_MODELS13 = (("", None), ("پراید ", "pride"), ("تیبا ", "tiba"),
             ("کوییک ", "quik"))
_PROVQ13 = ("پراید در تهران", "در تهران یا اصفهان",
            "پراید زیر ۶۰۰ میلیون در تهران")
_shape13: dict[str, str] = {}
_cells13 = {"met": 0, "unknown": 0, "broken": 0}
_both13: list[str] = []         # a match AND a car apart, on «پراید در تهران»
_two13: list[str] = []          # a car apart on the price AND the province
# «خلیج فارس» holds the name of a province and is not one. Asked of every
# corpus beside «پراید» alone: the same cars, no province stated, the phrase
# in view.
_GULFQ13 = "پراید خلیج فارس"
_gulfn13: list[str] = []        # runs where «پراید» alone finds something
_gulfoff13: list[str] = []      # runs where the Gulf changes the answer
_gulfhid13: list[str] = []      # runs where it is not left in view

for _run13 in sorted(p.stem for p in _CORP13.glob("*.json")):
    _recs13 = {x["listing_id"]: x for x in json.loads(
        (_CORP13 / f"{_run13}.json").read_text(encoding="utf-8"))["listings"]}
    _veh13 = [x for x in _recs13.values() if x.get("product_class") == "vehicle"]
    _held13 = sum(1 for x in _veh13 if x.get("province"))
    _shape13[_run13] = ("none" if not _held13 else
                        "all" if _held13 == len(_veh13) else "some")
    _off13, _n13 = [], 0
    with _published(_run13):
        for _typed13, _canon13 in _NAMES13:
            for _pre13, _model13 in _MODELS13:
                _q13 = f"{_pre13}در {_typed13}"
                _got13 = api.search(q=_q13, k=_K13)
                _pool13 = [x for x in _veh13 if _model13 is None
                           or (x.get("model") or "").lower() == _model13]
                _met13 = sum(1 for x in _pool13
                             if x.get("province") == _canon13)
                _unk13 = sum(1 for x in _pool13 if not x.get("province"))
                _cells13["met"] += _met13
                _cells13["unknown"] += _unk13
                _cells13["broken"] += len(_pool13) - _met13 - _unk13
                _n13 += 1
                if (_got13.evidence_total, _got13.evidence_unchecked_total) \
                        != (_met13, _unk13):
                    _off13.append((_q13, (_got13.evidence_total,
                                          _got13.evidence_unchecked_total),
                                   (_met13, _unk13)))
        _ans13 = {q: api.search(q=q, k=_K13) for q in _PROVQ13}
        _gulf13 = api.search(q=_GULFQ13, k=_K13)
        _plain13 = api.search(q="پراید", k=_K13)
    if _plain13.evidence_total + _plain13.evidence_unchecked_total:
        _gulfn13.append(_run13)
    if (_gulf13.intent.provinces
            or [x.id for x in _gulf13.evidence] != [x.id for x in _plain13.evidence]
            or (_gulf13.evidence_total, _gulf13.evidence_unchecked_total)
            != (_plain13.evidence_total, _plain13.evidence_unchecked_total)):
        _gulfoff13.append(_run13)
    if "خلیج فارس" not in _gulf13.intent.unparsed:
        _gulfhid13.append(_run13)
    check(f"  {_run13} ({_held13} of {len(_veh13)} cars carry a province): "
          f"«در X» for {len(_NAMES13)} names × {len(_MODELS13)} models, "
          f"{_n13} answers, each (matched, apart) the count the artifact gives",
          not _off13, f"differs on {_off13[:3]}")
    for _q13, _r13 in _ans13.items():
        _judge13(_q13, _r13, _recs13, f" · {_run13}")
    _first13, _last13 = _ans13[_PROVQ13[0]], _ans13[_PROVQ13[-1]]
    if _first13.evidence_total and _first13.evidence_unchecked_total:
        _both13.append(_run13)
    if any(tuple(x.unchecked) == ("budget", "province")
           for x in _last13.evidence_unchecked):
        _two13.append(_run13)

check("  the corpora hold the field none, some and all of the way, and each "
      "is read: " + ", ".join(f"{k} {v}" for k, v in _shape13.items()),
      set(_shape13.values()) == {"none", "some", "all"},
      "a way is missing, so a rule's branch is never run on a whole corpus — "
      "said, not passed")
check(f"  and the rule's three answers are all reached ({_cells13['met']} met, "
      f"{_cells13['unknown']} unknown, {_cells13['broken']} broken — a car "
      f"counted once in each answer it is part of)",
      all(_cells13.values()), str(_cells13))
check(f"  «{_PROVQ13[0]}» draws a match and a car shown apart together, on "
      f"{', '.join(_both13) or 'no corpus'}", bool(_both13),
      "no corpus gives both, so the table that tells them apart is never "
      "drawn from a real answer — said, not passed")
check("  a car with neither a price nor a province is shown apart naming "
      f"both, the price first, on {', '.join(_two13) or 'no corpus'}",
      bool(_two13), "the order the constraints are judged in is not reached "
      "on a real car — said, not passed")
check(f"  «{_GULFQ13}» is not the province فارس: on {', '.join(_gulfn13)} it "
      "gives the answer «پراید» gives, and the intent states no province",
      len(_gulfn13) == len(_shape13) and not _gulfoff13,
      f"differs on {_gulfoff13}; «پراید» finds something on {_gulfn13} of "
      f"{list(_shape13)} — a corpus where it finds nothing cannot show it")
check("  and the phrase is left in view under «نفهمیدیم», on each",
      not _gulfhid13, f"not listed on {_gulfhid13}")


# ---------------------------------------------------------------------------
print("\n14 — reweight bounds k as search does")
# ---------------------------------------------------------------------------
# D60 recorded that `/api/search` caps k at 24 and `/api/search/reweight` took
# any k. Measured on run11 with «پراید», 56 matches: reweight answered k=0
# with 200 and an empty table, k=-1 with 200 and every match but the last —
# a Python slice, silently — and k=1000 with all 56. Search answered 422 to
# each. Over HTTP, because the bound is FastAPI's and exists only there.
with corpus_dir(valid_artifact(product_class="vehicle")):
    with contextlib.redirect_stdout(io.StringIO()):
        _c14 = TestClient(api.app, raise_server_exceptions=False)
    for _k, _want in ((0, 422), (-1, 422), (25, 422), (1, 200), (24, 200)):
        _s = _c14.get("/api/search", params={"q": "۲۰۶", "k": _k}).status_code
        _w = _c14.post("/api/search/reweight", params={"q": "۲۰۶", "k": _k},
                       json={}).status_code
        check(f"k={_k}: search {_s}, reweight {_w} — both {_want}",
              _s == _want and _w == _want)


# ---------------------------------------------------------------------------
print("\n15 — an odometer's four grades, through search")
# ---------------------------------------------------------------------------
# Section 13 holds the rule on objects built for it; this sends the same
# cases through the API, from an artifact written to a temporary directory —
# never data/corpora/, for the reason `corpus_dir` gives. run11 holds no
# suspicious or impossible reading, so without this no endpoint would ever be
# seen to carry one. It is a test of the contract, not a measurement: it says
# what the API does with each grade, and nothing about how often a corpus
# holds one.
#
# Each row: id, odometer, grade (None: the record states none), year, and
# where «۲۰۶ کم‌کارکرد» — a cap of 120,000 — must put it, with what the
# filter before this did with it.
_ODO = [
    ("o_ok", 100_000, "plausible", 1398, "match", "match"),
    ("o_hi", 200_000, "plausible", 1398, "out", "out"),
    ("o_none", None, "unknown", 1398, "apart", "apart"),
    ("o_low", 1, "suspicious", 1385, "apart", "match"),
    ("o_ph", 999_990, "suspicious", 1398, "apart", "out"),
    ("o_neg", -5_000, "impossible", 1398, "apart", "match"),
    ("o_huge", 2_000_000, "impossible", 1398, "apart", "out"),
    ("o_bare", 90_000, None, 1398, "apart", "match"),
]


def _odometer_artifact() -> str:
    rows = []
    for i, km, ms, year, *_ in _ODO:
        r = {"listing_id": i, "product_class": "vehicle",
             "asking_price_toman": 500_000_000, "price_kind": "cash",
             "price_status": "display_confirmed", "year_jalali": year,
             "make": "peugeot", "model": "206", "trim": "TU5"}
        if km is not None:
            r["mileage_km"] = km
        if ms is not None:
            r["mileage_status"] = ms
        rows.append(r)
    return json.dumps({"schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
                       "collected_on": "2026-10-05", "listings": rows},
                      ensure_ascii=False)


with corpus_dir(_odometer_artifact()):
    _r15 = api.search(q="۲۰۶ کم‌کارکرد", k=24)
check("the query states the cap it is about",
      _r15.intent.max_mileage_km == 120_000, str(_r15.intent.max_mileage_km))
_where = {x.id: "match" for x in _r15.evidence}
_where.update({x.id: "apart" for x in _r15.evidence_unchecked})
_sent15 = {x.id: x for x in list(_r15.evidence) + list(_r15.evidence_unchecked)}
for _i, _km, _ms, _y, _want, _was in _ODO:
    _got = _where.get(_i, "out")
    check(f"  {_i}: {_km} km, {_ms or 'no grade'} → {_want}"
          + (f" (the filter before: {_was})" if _was != _want else ""),
          _got == _want, f"got {_got}")
    if _got == "apart":
        _x = _sent15[_i]
        check(f"    named «mileage», with its number and grade kept",
              _x.unchecked == ["mileage"] and _x.mileage_km == _km
              and _x.mileage_status == _ms,
              f"{_x.unchecked} {_x.mileage_km} {_x.mileage_status}")


# ---------------------------------------------------------------------------
print("\n16 — every corpus is built without the test suite")
# ---------------------------------------------------------------------------
# The site built SYNTHETIC by importing tests/test_ranking.py, which ran every
# check in it and ended in SystemExit when one was red; under uvicorn every
# request that needed a corpus then answered a bare 500 (measured on
# 2026-10-06). It is built by caro.synthetic now. Two checks keep the suite
# out: read, no module under webapp/ imports from tests/; run, each state is
# built in a fresh process, where nothing else has loaded a test module, and
# that process says what it imported. The artifact the invalid and real states
# are handed is named after DEFAULT_RUN, as everywhere else in this suite:
# spelled «run11.json», the probe could only pass while run11 was the default.
import ast as _ast                                                 # noqa: E402
import subprocess as _sp                                           # noqa: E402

_py16 = sorted(set((ROOT / "webapp").glob("*.py"))
               | set((ROOT / "webapp" / "api").rglob("*.py")))
_from_tests = []
for _p in _py16:
    for _n in _ast.walk(_ast.parse(_p.read_text(encoding="utf-8"))):
        _mods = ([a.name for a in _n.names] if isinstance(_n, _ast.Import)
                 else [_n.module or ""] if isinstance(_n, _ast.ImportFrom)
                 else [])
        if any(m == "tests" or m.startswith("tests.") for m in _mods):
            _from_tests.append(f"{_p.relative_to(ROOT)}:{_n.lineno}")
check(f"none of the {len(_py16)} modules under webapp/ imports from tests/",
      len(_py16) > 0 and not _from_tests,
      str(_from_tests) if _from_tests else "found no module to read")

_PROBE16 = r"""
import json, os, shutil, sys, tempfile
from pathlib import Path
root, mode, run = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
sys.path.insert(0, str(root))
os.environ.pop("CARO_RUN", None)
import caro.corpus_reader as cr
tmp = Path(tempfile.mkdtemp())
if mode == "run99":
    os.environ["CARO_RUN"] = "run99"
elif mode == "invalid":
    (tmp / f"{run}.json").write_text("{ not a corpus", encoding="utf-8")
elif mode == "real":
    shutil.copy(root / "data" / "corpora" / f"{run}.json", tmp / f"{run}.json")
cr.CORPORA = tmp
import webapp.api.corpus as C
c = C.active()
print(json.dumps({"kind": c.kind, "fault": c.fault_code, "source": c.source,
                  "tests": sorted(m for m in sys.modules
                                  if m == "tests" or m.startswith("tests.")),
                  "synthetic": "caro.synthetic" in sys.modules}))
"""
_states16 = {}
for _mode, _want in (("absent", "SYNTHETIC"), ("run99", "UNUSABLE"),
                     ("invalid", "UNUSABLE"), ("real", "REAL")):
    _r = _sp.run([sys.executable, "-c", _PROBE16, str(ROOT), _mode, RUN],
                 capture_output=True, text=True, timeout=300,
                 env={**os.environ, "PYTHONPATH": str(ROOT)})
    try:
        _states16[_mode] = json.loads(_r.stdout.strip().splitlines()[-1])
    except (IndexError, ValueError):
        _states16[_mode] = {"error": (_r.stderr.strip().splitlines()
                                      or ["no output"])[-1][:160]}
    check(f"{_mode}: built as {_want}, with no test module loaded",
          _states16[_mode].get("kind") == _want
          and _states16[_mode].get("tests") == [], str(_states16[_mode]))
_s16 = _states16.get("absent", {})
check("  SYNTHETIC is built by caro.synthetic, and its source says so",
      _s16.get("synthetic") is True
      and _s16.get("source") == "caro/synthetic.py", str(_s16))
# REAL and the two UNUSABLE states rank nothing, and a request on them runs
# the parser alone. They build no synthetic corpus to borrow one from.
for _mode in ("run99", "invalid", "real"):
    check(f"  {_mode}: no synthetic corpus is built for it",
          _states16.get(_mode, {}).get("synthetic") is False,
          str(_states16.get(_mode)))


# ---------------------------------------------------------------------------
print("\n17 — a listing says how its province was read")
# ---------------------------------------------------------------------------
# `province_source` is a closed set in the payload, and nothing upstream of
# the reader closes it: promotion writes three values, and the reader derives
# one of them for a row published before the field existed. A value outside
# the set would fail validation on the way out, as a 500 on the page that
# asked. So every published corpus is read here, as the site would read it.
_PS = set(typing.get_args(schemas.ProvinceSource))
_ps_seen = {}
for _cp in sorted((ROOT / "data" / "corpora").glob("*.json")):
    _ps_seen[_cp.stem] = {x.province_source for x in
                          corpus_reader.listings_from_corpus(
                              json.loads(_cp.read_text(encoding="utf-8")))}
_ps_bad = {k: sorted(v - _PS) for k, v in _ps_seen.items() if v - _PS}
check(f"every published corpus gives a source the payload can carry "
      f"({', '.join(sorted(_ps_seen))})",
      bool(_ps_seen) and not _ps_bad, str(_ps_bad or "found no corpus"))

# And the detail path delivers both, as the reader holds them, for every
# listing the served corpus has — the vehicles and the one that is not.
_was, _was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
corpus_reader.CORPORA = ROOT / "data" / "corpora"
os.environ.pop(corpus_mod.RUN_ENV, None)
corpus_mod.active.cache_clear()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        _held17 = list(corpus_mod.active().listings)
        _sent17 = {x.listing_id: api.listing(listing_id=x.listing_id)
                   for x in _held17}
finally:
    corpus_reader.CORPORA = _was
    if _was_run is None:
        os.environ.pop(corpus_mod.RUN_ENV, None)
    else:
        os.environ[corpus_mod.RUN_ENV] = _was_run
    corpus_mod.active.cache_clear()
_off17 = [x.listing_id for x in _held17
          if _sent17[x.listing_id].listing is None
          or (_sent17[x.listing_id].listing.province,
              _sent17[x.listing_id].listing.province_source)
          != (x.city, x.province_source)]
check(f"the detail path delivers the province and how it was read, for all "
      f"{len(_held17)} listings of {RUN}",
      bool(_held17) and not _off17, f"differs on {_off17[:5]}")
_city17 = sum(1 for x in _held17 if x.province_source == "city")
check(f"  and {RUN} holds provinces read from a city's name ({_city17}), "
      f"so the two are told apart on real rows",
      _city17 > 0, "none to tell apart — said, not passed")


# ---------------------------------------------------------------------------
print("\n18 — the ranked path reads no province, and no published corpus is ranked")
# ---------------------------------------------------------------------------
# D82 left it so. `_passes` in caro/ranking.py compares no province, because an
# appraisal Row carries none (pinned in test_ranking). Where the ranking IS
# served — the SYNTHETIC corpus, which the gate passes — a buyer who writes
# «در تهران» is shown «استان: تهران» as understood and the shortlist the
# sentence without it gives. On the published corpora the ranking is not
# served at all (D43) and the province is judged on the evidence path alone
# (section 13). So the gap is reachable by exactly one change: a published
# corpus that is ranked. The second check turns red the day that happens, and
# says what to decide first.
with corpus_dir(None):
    _q18 = "۲۰۶ زیر ۸۰۰ میلیون"
    _plain18 = api.search(q=_q18, k=6)
    _named18 = api.search(q=f"{_q18} در تهران", k=6)
check("on the corpus the ranking is served on, a province is listed as "
      "understood and does not narrow the shortlist",
      _named18.status.served and _named18.status.gated
      and _named18.intent.provinces == ["تهران"]
      and _plain18.intent.provinces == []
      and len(_named18.items) > 0
      and [i.id for i in _named18.items] == [i.id for i in _plain18.items]
      and (_named18.candidates, _named18.relaxed, _named18.relaxation_fa)
      == (_plain18.candidates, _plain18.relaxed, _plain18.relaxation_fa),
      f"served with {[i.id for i in _named18.items]}, without "
      f"{[i.id for i in _plain18.items]}")

_ranked18, _read18 = [], []
for _run18 in sorted(p.stem for p in _CORP13.glob("*.json")):
    with _published(_run18):
        _got18 = api.search(q="پراید در تهران", k=_K13)
    _read18.append(_run18)
    if _got18.status.gated or _got18.status.served or _got18.items:
        _ranked18.append(_run18)
check(f"no published corpus is ranked ({', '.join(_read18)}), so none of "
      f"their answers goes through `retrieve`",
      bool(_read18) and not _ranked18,
      f"{_ranked18} would be ranked: its shortlist comes from `retrieve`, "
      "which reads no province, while the panel lists «استان» as understood. "
      "Decide that first — docs/ROADMAP.md, «The ranked path's province»")

# ---------------------------------------------------------------------------
print("\n19 — the API's headers, its input bounds, its rate limits and its CORS")
# ---------------------------------------------------------------------------
# Predictions SEC-1..SEC-6 (2026-10-30, locked before the code). Over HTTP, on
# a temporary inbox, with each limiter cleared before and after.
from webapp.api import security as sec_mod                         # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    _c19 = TestClient(api.app, raise_server_exceptions=False)
_h = _c19.get("/api/health").headers
check("SEC-1: every response says nosniff, no framing, no referrer, and a policy that allows nothing",
      _h.get("x-content-type-options") == "nosniff" and _h.get("x-frame-options") == "DENY"
      and _h.get("referrer-policy") == "no-referrer"
      and _h.get("content-security-policy") == "default-src 'none'; frame-ancestors 'none'", str(dict(_h)))
check("  and the admin endpoints are not to be stored",
      _c19.get("/api/admin/status").headers.get("cache-control") == "no-store"
      and "cache-control" not in _c19.get("/api/health").headers)
_long = "پ" * 501
_r1 = _c19.get("/api/search", params={"q": _long})
_r1b = _c19.get("/api/search", params={"q": "پ" * 500})
_r2 = _c19.get("/api/listing/" + "a" * 121)
_r3 = _c19.post("/api/compare", json={"ids": [f"bama:x{i}" for i in range(13)]})
_r4 = _c19.post("/api/compare", json={"ids": ["a" * 121]})
_r5 = _c19.post("/api/search/reweight", params={"q": _long}, json={})
check("SEC-2: a question over 500 characters, an id over 120, thirteen ids to compare, an id of 121 "
      "in a compare and a reweight's question over 500 are refused (422); 500 characters are read",
      [r.status_code for r in (_r1, _r2, _r3, _r4, _r5)] == [422] * 5 and _r1b.status_code == 200,
      str([r.status_code for r in (_r1, _r1b, _r2, _r3, _r4, _r5)]))

_kept19 = (contact_mod.INBOX, contact_mod.MESSAGES, os.environ.get("CARO_INBOX"),
           os.environ.get("CARO_ADMIN_TOKEN"), os.environ.get("CARO_TRUST_PROXY"))
contact_mod.CONTACT_LIMIT.clear()
contact_mod.ADMIN_FAILURES.clear()
with tempfile.TemporaryDirectory() as _d:
    contact_mod.INBOX = Path(_d) / "inbox"
    contact_mod.MESSAGES = contact_mod.INBOX / "messages.jsonl"
    try:
        os.environ.pop("CARO_INBOX", None)
        os.environ.pop("CARO_TRUST_PROXY", None)
        _codes = [_c19.post("/api/contact", json=_MSG).status_code for _ in range(6)]
        _sixth = _c19.post("/api/contact", json=_MSG)
        check("SEC-3: one address posts five messages in ten minutes; the sixth is 429 with Retry-After, "
              "and nothing more is written",
              _codes == [200] * 5 + [429] and _sixth.status_code == 429
              and int(_sixth.headers.get("retry-after", "0")) > 0
              and len(_lines(contact_mod.MESSAGES)) == 5, str((_codes, len(_lines(contact_mod.MESSAGES)))))
        os.environ["CARO_TRUST_PROXY"] = "1"
        _other = _c19.post("/api/contact", json=_MSG, headers={"X-Forwarded-For": "203.0.113.9, 10.0.0.1"})
        os.environ.pop("CARO_TRUST_PROXY", None)
        _spoof = _c19.post("/api/contact", json=_MSG, headers={"X-Forwarded-For": "203.0.113.10"})
        check("  X-Forwarded-For is another address only where CARO_TRUST_PROXY=1 says so",
              _other.status_code == 200 and _spoof.status_code == 429,
              str((_other.status_code, _spoof.status_code)))

        os.environ["CARO_ADMIN_TOKEN"] = "the-right-token-0123456789"
        _fails = [_c19.get("/api/admin/messages", headers={"x-admin-token": f"wrong{i}"}).status_code
                  for i in range(10)]
        _right = _c19.get("/api/admin/messages", headers={"x-admin-token": "the-right-token-0123456789"})
        contact_mod.ADMIN_FAILURES.clear()
        _right2 = _c19.get("/api/admin/messages", headers={"x-admin-token": "the-right-token-0123456789"})
        check("  ten wrong admin tokens are ten 401s; the eleventh try is 429 even with the right token; "
              "once the count is gone the right token opens",
              _fails == [401] * 10 and _right.status_code == 429 and _right2.status_code == 200,
              str((_fails, _right.status_code, _right2.status_code)))

        contact_mod.CONTACT_LIMIT.clear()
        contact_mod.MESSAGES.write_bytes(b"x" * contact_mod.INBOX_MAX_BYTES)
        _full = _c19.post("/api/contact", json=_MSG)
        check("SEC-4: an inbox file of 5 MB takes no more: 503, the «not kept» message, and no growth",
              _full.status_code == 503 and contact_mod.ELSEWHERE in str(_full.json().get("detail", ""))
              and contact_mod.MESSAGES.stat().st_size == contact_mod.INBOX_MAX_BYTES,
              f"HTTP {_full.status_code}")
    finally:
        contact_mod.INBOX, contact_mod.MESSAGES = _kept19[0], _kept19[1]
        for _k, _v in zip(("CARO_INBOX", "CARO_ADMIN_TOKEN", "CARO_TRUST_PROXY"), _kept19[2:]):
            if _v is None:
                os.environ.pop(_k, None)
            else:
                os.environ[_k] = _v
        contact_mod.CONTACT_LIMIT.clear()
        contact_mod.ADMIN_FAILURES.clear()

_pre = _c19.options("/api/search", headers={"Origin": "http://localhost:3000",
                                             "Access-Control-Request-Method": "GET"})
_evil = _c19.options("/api/search", headers={"Origin": "https://evil.example",
                                              "Access-Control-Request-Method": "GET"})
_put = _c19.options("/api/search", headers={"Origin": "http://localhost:3000",
                                            "Access-Control-Request-Method": "PUT"})
check("SEC-5: CORS lets the development origin GET, with no credentials; another origin, or a PUT, is not let",
      _pre.headers.get("access-control-allow-origin") == "http://localhost:3000"
      and "access-control-allow-credentials" not in _pre.headers
      and "access-control-allow-origin" not in _evil.headers and _put.status_code == 400,
      str((dict(_pre.headers), _evil.status_code, _put.status_code)))
_old_cors = os.environ.get("CARO_CORS_ORIGINS")
os.environ["CARO_CORS_ORIGINS"] = "https://a.example, https://b.example"
check("  CARO_CORS_ORIGINS names the origins", sec_mod.cors_origins() == ["https://a.example", "https://b.example"])
if _old_cors is None:
    os.environ.pop("CARO_CORS_ORIGINS", None)
else:
    os.environ["CARO_CORS_ORIGINS"] = _old_cors
_t = [0.0]
_rl = sec_mod.RateLimiter(2, 10, clock=lambda: _t[0], max_keys=3)
_seq = [_rl.hit("a"), _rl.hit("a"), _rl.hit("a")]
_t[0] = 10.0
_after = _rl.hit("a")
for _k in ("b", "c", "d"):
    _rl.hit(_k)
check("  the limiter: two in ten seconds, the third waits 10, the window slides, and a fourth key "
      "pushes the oldest out",
      _seq[:2] == [None, None] and _seq[2] == 10.0 and _after is None and "a" not in _rl._events
      and len(_rl._events) == 3, str((_seq, _after, list(_rl._events))))
_cfg = (ROOT / "webapp" / "web" / "next.config.mjs").read_text(encoding="utf-8")
check("SEC-6: the site's config sends the policy in production, HSTS, no framing, nosniff, a referrer "
      "policy, a permissions policy, and no X-Powered-By",
      all(x in _cfg for x in ("Content-Security-Policy", "frame-ancestors 'none'", "object-src 'none'",
                              "Strict-Transport-Security", "X-Frame-Options", "nosniff",
                              "Referrer-Policy", "Permissions-Policy", "poweredByHeader: false",
                              "process.env.NODE_ENV === 'production'")))

# ---------------------------------------------------------------------------
print("\n20 — a model's page, as Torob gives a product one: its listings, its range, its runs")
# ---------------------------------------------------------------------------
# Predictions MKT-1..MKT-7 (2026-10-30, locked before the code), on the corpus
# the site serves (run16) and the four published runs.
from webapp.api import market as market_mod                        # noqa: E402

_run_was = os.environ.pop("CARO_RUN", None)
corpus_mod.active.cache_clear()
market_mod.published_runs.cache_clear()
try:
    with contextlib.redirect_stdout(io.StringIO()):
        _c20 = TestClient(api.app, raise_server_exceptions=False)
    _ms = _c20.get("/api/models").json()
    _by = {m["model"]: m for m in _ms["models"]}
    check("MKT-1: one summary per model on run16, most listings first: Pride 53 (50 priced, 240 million "
          "to 1.8 billion, the middle 650 million, 1380 to 1405), Quik 10, Tiba 10 (9 priced); the envelope",
          [m["model"] for m in _ms["models"]] == ["Pride", "Quik", "Tiba"]
          and {k: _by["Pride"][k] for k in ("listings", "priced", "price_min", "price_median", "price_max",
                                            "year_min", "year_max")}
          == {"listings": 53, "priced": 50, "price_min": 240000000, "price_median": 650000000,
              "price_max": 1800000000, "year_min": 1380, "year_max": 1405}
          and (_by["Tiba"]["listings"], _by["Tiba"]["priced"]) == (10, 9)
          and _ms["corpus"]["identity"]["run_id"] == "run16", str(_ms["models"])[:400])
    _md = _c20.get("/api/model", params={"make": "Saipa", "model": "Pride"})
    _mj = _md.json()
    _prices = [o["asking_price_toman"] for o in _mj["offers"]]
    _priced_part = [p for p in _prices if p is not None]
    check("MKT-2: Pride's 53 listings, the 50 priced cheapest first and the 3 without a usable price after "
          "them; its summary as on /api/models",
          _md.status_code == 200 and len(_prices) == 53 and _priced_part == sorted(_priced_part)
          and _prices.index(None) == 50 and _mj["summary"] == _by["Pride"]
          and _mj["offers"][0]["url"].startswith("https://bama.ir/"), str(_prices[:5] + _prices[-4:]))
    _years = {y["year_jalali"]: y for y in _mj["by_year"]}
    check("  by year: a year of three priced listings or more has its middle, one of fewer only its count",
          _years[1389] == {"year_jalali": 1389, "priced": 6, "price_median": 582500000}
          and _years[1380] == {"year_jalali": 1380, "priced": 1, "price_median": None}, str(_mj["by_year"][:6]))
    _nf = _c20.get("/api/model", params={"make": "Saipa", "model": "Nope"})
    _long = _c20.get("/api/model", params={"make": "S" * 61, "model": "Pride"})
    check("  a model the corpus does not hold is 404 with the envelope and MODEL_NOT_FOUND; a name over 60 "
          "characters is 422",
          _nf.status_code == 404 and _nf.json()["fault"]["code"] == "MODEL_NOT_FOUND"
          and "corpus" in _nf.json() and _long.status_code == 422, f"{_nf.status_code} {_long.status_code}")
    check("MKT-3: one point per published run, by date, with its priced count and middle: Pride 54, 52, 53 "
          "and 50 priced, 612.5, 600, 635 and 650 million",
          [(h["run_id"], h["collected_on"], h["priced"], h["price_median"]) for h in _mj["history"]]
          == [("run11", "2026-09-10", 54, 612500000), ("run13", "2026-10-06", 52, 600000000),
              ("run14", "2026-10-11", 53, 635000000), ("run16", "2026-10-15", 50, 650000000)],
          str(_mj["history"]))
    _run11 = json.loads((ROOT / "data" / "corpora" / "run11.json").read_text(encoding="utf-8"))
    _quik11 = [x for x in _run11["listings"] if x.get("model") == "Quik"]
    _quik_h = _c20.get("/api/model", params={"make": "Saipa", "model": "Quik"}).json()["history"][0]
    check("  an assignment (run11's one حواله, a Quik) is no listing of the model, in a run as in the corpus",
          any(x.get("product_class") == "assignment" for x in _quik11)
          and _quik_h["priced"] == sum(1 for x in _quik11 if x.get("product_class") == "vehicle"
                                       and x.get("asking_price_toman")
                                       and x.get("price_status") not in ("ambiguous", "negotiable", "absent")
                                       and x.get("price_kind") in (None, "cash")), str(_quik_h))
    _fake = [type("L", (), {"asking_price_toman": p, "price_status": st, "price_kind": k, "year_jalali": 1400})()
             for p, st, k in ((100_000_000, "display_confirmed", "cash"), (90_000_000, "negotiable", "cash"),
                              (80_000_000, "display_confirmed", "financing_total"), (None, "absent", "absent"))]
    _sm = market_mod.summarise("M", "X", _fake)
    check("  «priced» is the gate's reading: a negotiable status, a financing total or no number is not; one "
          "priced listing has a range and no middle",
          (_sm.listings, _sm.priced, _sm.price_min, _sm.price_max, _sm.price_median)
          == (4, 1, 100_000_000, 100_000_000, None), str(_sm))
finally:
    if _run_was is not None:
        os.environ["CARO_RUN"] = _run_was
    corpus_mod.active.cache_clear()
    market_mod.published_runs.cache_clear()

# ---------------------------------------------------------------------------
print("\n21 — the operator's login takes a code from an authenticator app (O1)")
# ---------------------------------------------------------------------------
# Predictions A1..A7 (2026-10-30, locked before the code). The owner chose O1;
# the clock is the test's, the inbox a temporary one, and every limit and every
# spent code is cleared before and after.
from webapp.api import totp as totp_mod                            # noqa: E402

_RFC_KEY = b"12345678901234567890"
_RFC_B32 = "GEZDGNBVGY3TQOJQGEZDGNBVGY3TQOJQ"
check("A1: RFC 6238 appendix B, SHA-1, eight digits, at its six times",
      [totp_mod.code_at(_RFC_KEY, t // 30, 8) for t in (59, 1111111109, 1111111111, 1234567890,
                                                        2000000000, 20000000000)]
      == ["94287082", "07081804", "14050471", "89005924", "69279037", "65353130"]
      and totp_mod.decode_secret(_RFC_B32.lower()) == _RFC_KEY)

_kept21 = (contact_mod.INBOX, contact_mod.MESSAGES, contact_mod.ADMIN_CODES.clock,
           os.environ.get("CARO_ADMIN_TOKEN"), os.environ.get("CARO_ADMIN_TOTP_SECRET"))
_T0 = 1_700_000_000
_now21 = [_T0]
_TOKEN21 = "the-right-token-0123456789"
try:
    with tempfile.TemporaryDirectory() as _tmp21:
        contact_mod.INBOX = Path(_tmp21)
        contact_mod.MESSAGES = Path(_tmp21) / "messages.jsonl"
        contact_mod.ADMIN_CODES.clock = lambda: _now21[0]
        with contextlib.redirect_stdout(io.StringIO()):
            _c21 = TestClient(api.app, raise_server_exceptions=False)

        def _open21(token=_TOKEN21, code=None):
            h = {"x-admin-token": token}
            if code is not None:
                h["x-admin-code"] = code
            return _c21.get("/api/admin/messages", headers=h).status_code

        def _fresh21(at=_T0):
            _now21[0] = at
            contact_mod.ADMIN_CODES.forget()
            contact_mod.ADMIN_FAILURES.clear()

        _code = lambda step: totp_mod.code_at(_RFC_KEY, step)          # noqa: E731
        _s0 = _T0 // 30
        _wrong = next(c for c in ("000000", "111111", "222222") if c != _code(_s0))
        os.environ["CARO_ADMIN_TOKEN"] = _TOKEN21
        os.environ["CARO_ADMIN_TOTP_SECRET"] = _RFC_B32

        _fresh21()
        _a2 = (_open21(), _open21(code=_code(_s0)), _open21(code=_wrong))
        check("A2: with a secret, the token alone is refused, the token and the step's code open, a wrong "
              "code is refused", _a2 == (401, 200, 401), str(_a2))
        _fresh21()
        _a3 = (_open21(token="wrong-token", code=_code(_s0)), _open21(code=_code(_s0)))
        check("A3: a wrong token with the right code is refused, and does not spend the code",
              _a3 == (401, 200), str(_a3))
        _fresh21()
        _a4 = [_open21(code=_code(_s0)), _open21(code=_code(_s0))]
        _fresh21(_T0 + 30)
        _a4.append(_open21(code=_code(_s0)))
        _fresh21(_T0 + 60)
        _a4.append(_open21(code=_code(_s0)))
        check("A4: a code once; the step before's code is taken, a code two steps old is not",
              _a4 == [200, 401, 200, 401], str(_a4))
        # A header carries no Persian digit -- httpx will not encode one and a
        # browser's fetch refuses to send one -- so the page sends the code's
        # digits in ASCII (lib/format.ts asciiDigits, held by the screens
        # suite), and the verifier reads Persian and Arabic-Indic digits for
        # whatever reaches it another way.
        _fresh21()
        _fa = _code(_s0).translate(str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹"))
        _ar = _code(_s0 + 1).translate(str.maketrans("0123456789", "٠١٢٣٤٥٦٧٨٩"))
        _now21[0] = _T0 + 30
        check("A5: a code in Persian digits, and the next in Arabic-Indic ones, are read as their digits",
              contact_mod.ADMIN_CODES.check(_RFC_KEY, _fa) is True
              and contact_mod.ADMIN_CODES.check(_RFC_KEY, _ar) is True, f"{_fa} {_ar}")

        _fresh21()
        os.environ.pop("CARO_ADMIN_TOTP_SECRET", None)
        _off = (_open21(), _c21.get("/api/admin/status").json().get("second_factor"))
        _bad = []
        for _secret in ("not base32 !", "GEZDGNBV"):
            os.environ["CARO_ADMIN_TOTP_SECRET"] = _secret
            _fresh21()
            _bad.append((_open21(code=_code(_s0)), _c21.get("/api/admin/status").json().get("second_factor")))
        check("A6: no secret, the token alone opens and the status says «off»; a secret that is not base32, "
              "or is under 128 bits, opens nothing and the status says «unreadable»",
              _off == (200, "off") and _bad == [(401, "unreadable")] * 2, str((_off, _bad)))

        os.environ["CARO_ADMIN_TOTP_SECRET"] = _RFC_B32
        _fresh21()
        _a7 = [_open21(code=_wrong) for _ in range(10)] + [_open21(code=_code(_s0))]
        check("A7: ten wrong codes with the right token are ten failures; the next try is 429 even with the "
              "right code", _a7 == [401] * 10 + [429], str(_a7))
finally:
    contact_mod.INBOX, contact_mod.MESSAGES, contact_mod.ADMIN_CODES.clock = _kept21[:3]
    for _k, _v in zip(("CARO_ADMIN_TOKEN", "CARO_ADMIN_TOTP_SECRET"), _kept21[3:]):
        if _v is None:
            os.environ.pop(_k, None)
        else:
            os.environ[_k] = _v
    contact_mod.ADMIN_CODES.forget()
    contact_mod.ADMIN_FAILURES.clear()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
