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
    3  a missing corpus             → SYNTHETIC, and no fault
    4  a broken corpus              → UNUSABLE, a fault, and never SYNTHETIC
    5  an ungated corpus            → evidence may exist, no estimate is
                                      fabricated for it
    6  a refusal                    → HTTP 200, a product state, schema-valid
    7  the client's TypeScript      → the same fields as the Python models

Seven is the one that cannot be written any other way. `lib/api.ts` is a
second hand-written description of `webapp/api/schemas.py`, and TypeScript
validates the client against ITS OWN belief about the server. That belief is
exactly what goes stale. So this reads the file.
"""

from __future__ import annotations

import contextlib
import io
import json
import re
import sys
import tempfile
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


@contextlib.contextmanager
def corpus_dir(body: str | None):
    """Point the reader at a temp directory, optionally holding an artifact.

    Nothing is written under `data/corpora/`. A fabricated file there is
    indistinguishable from a collected one, and that confusion is what the
    corpus label exists to prevent.
    """
    was = corpus_reader.CORPORA
    with tempfile.TemporaryDirectory() as d:
        if body is not None:
            (Path(d) / "run3.json").write_text(body, encoding="utf-8")
        corpus_reader.CORPORA = Path(d)
        corpus_mod.active.cache_clear()
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                yield
        finally:
            corpus_reader.CORPORA = was
            corpus_mod.active.cache_clear()


def valid_artifact(n: int = 9) -> str:
    obj = {
        "schema": SCHEMA, "run_id": "run3", "source": "bama.ir",
        "collected_on": "2026-09-09",
        "listings": [
            {"listing_id": f"b{i}",
             "asking_price_toman": 500_000_000 + i * 40_000_000,
             "year_jalali": 1392 + (i % 4), "mileage_km": 90_000 + i * 9000,
             "make": "peugeot", "model": "206", "trim": "TU5",
             "province": "tehran"}
            for i in range(n)],
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
    check("  run_id names the run", r.corpus.identity.run_id == "run3")

    lst = api.listing(r.evidence[0].id)
    ok, why = validates(schemas.ListingResponse, lst)
    check("ListingResponse validates on a real corpus", ok, why)

    cmp_ = api.compare(schemas.CompareRequest(
        ids=[e.id for e in r.evidence[:2]], q="۲۰۶"))
    ok, why = validates(schemas.CompareResponse, cmp_)
    check("CompareResponse validates on a real corpus", ok, why)
    check("  and it returns evidence, not rows",
          cmp_.rows == [] and len(cmp_.evidence) == 2)


# ---------------------------------------------------------------------------
print("\n3 — a missing corpus falls back, silently and correctly")
with corpus_dir(None):
    r = api.which_corpus()
    check("kind is SYNTHETIC", r.status.kind == "SYNTHETIC", r.status.kind)
    check("  and there is NO fault — absence is not a failure",
          r.fault is None, str(r.fault))
    check("  and no identity is invented for it",
          r.corpus.identity is None)


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
with corpus_dir(valid_artifact()):
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
    check("  which is what makes this structural rather than a check",
          "estimate_toman" in schemas.ScoredItem.model_fields)


# ---------------------------------------------------------------------------
print("\n6 — a refusal is a product state, not an error")
with corpus_dir(valid_artifact()):
    r = api.search(q="۲۰۶", k=5)
    ok, why = validates(schemas.SearchResponse, r)
    check("the refusal is schema-valid", ok, why)
    check("  served is false and a fault says why",
          r.status.served is False and r.fault is not None)
    check("  the fault is the gate, not a corpus fault",
          r.fault.code == "ESTIMATOR_NOT_GATED", r.fault.code)
    check("  the parsed intent survives", r.intent.query != "")
    check("  and `still_available` is not a promise — evidence is present",
          "evidence" in r.fault.still_available and len(r.evidence) > 0)
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
    ("ScoredItem", schemas.ScoredItem),
    ("WeightSet", schemas.Weights),
    ("Intent", schemas.Intent),
    ("SearchResponse", schemas.SearchResponse),
    ("ListingResponse", schemas.ListingResponse),
    ("CompareResponse", schemas.CompareResponse),
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


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
