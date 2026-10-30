"""The benchmark reads a published artifact, and cannot reach anything else.

    Run: PYTHONPATH=. python3 tests/test_benchmark_contract.py

Every benchmark this project produced before now read rebuilt pages and
re-parsed them. `benchmark_run5.py` calls `replay_run3.rebuild`, which
reconstructs a detail page from a positional record and hands it to
`parse_detail_page`, so what was measured was the PARSER's output. That is
why nobody noticed that every published corpus artifact held zero
appraisal-eligible rows: the artifact was never the input to anything.

The rule:

    Benchmark evidence comes exclusively from the published corpus artifact,
    identified by its run id and its SHA-256.

A rule enforced by intention is a rule that lasts until someone is in a
hurry, so half of this suite reads `benchmark_corpus.py`'s own source and
asserts that the fallback is not reachable — not that it is not taken.

The other half is behavioural, and the three refusals matter more than the
one success: a missing artifact, an unusable one, and a valid one with no
evidence are three different answers, and none of them is a number.
"""

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("CARO_SELLER_SALT", "test-salt")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FAILS: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


BENCH = ROOT / "scripts" / "benchmark_corpus.py"
SRC = BENCH.read_text(encoding="utf-8")
TREE = ast.parse(SRC)


def imported_names() -> set[str]:
    """Every module and symbol this file imports, at any depth."""
    out: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            out.add(node.module or "")
            out.update(a.name for a in node.names)
    return out


# ---------------------------------------------------------------------------
print("\nthe fallback is not reachable, not merely not taken")
# ---------------------------------------------------------------------------

NAMES = imported_names()

# The specific things that made every earlier benchmark measure the parser.
FORBIDDEN = {
    "parse_detail_page": "re-parses a page instead of reading the artifact",
    "rebuild": "reconstructs a detail page from a positional record",
    "http_fetcher": "fetches",
    "playwright_fetcher": "fetches",
    "BamaAdapter": "collects",
    "DivarCarAdapter": "collects",
    "urllib": "fetches",
    "requests": "fetches",
    "scripts.replay_run3": "the rebuild path",
    "replay_run3": "the rebuild path",
}
for bad, why in FORBIDDEN.items():
    check(f"does not import {bad} — it {why}",
          bad not in NAMES, str(sorted(NAMES)))

# Identifiers the CODE uses, not words the prose mentions. The first version
# of this check searched the raw source and failed on the docstring, which
# explains at length what this file must not do — a rule cannot be stated
# and then violated by stating it.
def identifiers() -> set[str]:
    out: set[str] = set()
    for node in ast.walk(TREE):
        if isinstance(node, ast.Name):
            out.add(node.id)
        elif isinstance(node, ast.Attribute):
            out.add(node.attr)
    return out


CODE_NAMES = identifiers() | NAMES
check("nor calls any of them anywhere in the code",
      not ({"parse_detail_page", "rebuild", "http_fetcher",
            "playwright_fetcher"} & CODE_NAMES),
      str(sorted({"parse_detail_page", "rebuild", "http_fetcher",
                  "playwright_fetcher"} & CODE_NAMES)))

check("it DOES read the corpus reader",
      {"load_corpus", "rows_from_corpus", "corpus_identity"} <= NAMES,
      str(sorted(NAMES)))
check("  and the frozen gate, not a local copy of one",
      {"HierarchicalGate", "PartialPoolingQuantiles"} <= NAMES)

# The knobs must come from the frozen constants, not be re-declared here with
# values that happen to suit the corpus in front of us.
consts = {n.targets[0].id: n.value for n in TREE.body
          if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
check("the hold-out fraction is stated in the file, so a reader sees it",
      "HOLDOUT_FRACTION" in consts)
check("  and it is D34's 0.25, not something chosen after the fact",
      getattr(consts.get("HOLDOUT_FRACTION"), "value", None) == 0.25,
      str(consts.get("HOLDOUT_FRACTION")))
check("  the seed likewise",
      getattr(consts.get("SEED"), "value", None) == 0)
check("MIN_SLICE_N is imported, never redefined",
      "MIN_SLICE_N" in NAMES and "MIN_SLICE_N" not in consts,
      "a gate whose threshold the caller can restate is not a frozen gate")


# ---------------------------------------------------------------------------
print("\nthree refusals, and none of them is a number")
# ---------------------------------------------------------------------------

def run(run_id: str, corpora: Path) -> tuple[int, str]:
    """The script, in a sandbox whose corpora directory we control."""
    env = {**os.environ, "PYTHONPATH": str(ROOT), "NO_COLOR": "1",
           "CARO_CORPORA": str(corpora)}
    p = subprocess.run([sys.executable, str(BENCH), "--run-id", run_id],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=180)
    return p.returncode, p.stdout + p.stderr


with tempfile.TemporaryDirectory() as d:
    corpora = Path(d)

    code, out = run("nothing-here", corpora)
    check("a MISSING artifact refuses, and says it is a prerequisite",
          code != 0 and "PREREQUISITE_MISSING" in out, out[:300])
    check("  and states there is no fallback, rather than quietly having none",
          "no fallback" in out, out[:300])
    check("  it does not print an MAE",
          "model MAE" not in out, out[:300])

    (corpora / "broken.json").write_text('{"schema": "wrong", "listings": []}',
                                         encoding="utf-8")
    code, out = run("broken", corpora)
    check("an UNUSABLE artifact is not a corpus with problems (D49)",
          code != 0 and "CORPUS_UNUSABLE" in out, out[:300])
    check("  and it does not fall back to synthetic anything",
          "SYNTHETIC" not in out.upper(), out[:300])

    # Valid, guards clean, rows PRESENT — and not one of them appraisable.
    # This is the third refusal and the one most likely to be mistaken for a
    # model result, because the file is fine and the pipeline ran.
    #
    # Rows, not an empty array: an artifact with `listings: []` is refused by
    # the schema guard as an empty corpus, which is a different refusal from
    # this one and would have tested the wrong thing.
    empty = {"schema": "caro.corpus/1", "run_id": "empty", "source": "bama",
             "collected_on": "2026-09-10", "promoted_on": "2026-09-10",
             "provenance": {"input_name": "x", "input_sha256": "0" * 64,
                            "records_in": 1, "records_published": 1,
                            "records_refused": 0},
             "listings": [{"listing_id": "x1", "source": "bama",
                           "year_jalali": 1395, "make": "Saipa",
                           "model": "Pride", "condition": "intact",
                           "condition_source": "field"}]}
    (corpora / "empty.json").write_text(json.dumps(empty), encoding="utf-8")
    code, out = run("empty", corpora)
    check("a VALID artifact with no eligible row is UNJUDGEABLE",
          code != 0 and "UNJUDGEABLE" in out, out[:400])
    # Whitespace-normalised: the message is wrapped for a terminal, and a
    # substring check against wrapped output tests the line width.
    flat = " ".join(out.split())
    check("  and says so as a fact about the evidence, not the model",
          "not a model result" in flat, out[-400:])
    check("  and no MAE is printed for a corpus that answered nothing",
          "model MAE" not in out, out[-400:])

    # A corpus that IS eligible, and still cannot be evaluated: every row
    # carries first_seen_ordinal=0 because a published artifact has no
    # per-listing first-seen date. The temporal split then returns 0 train /
    # N test and reports a clean, meaningless zero.
    rows = []
    for i in range(40):
        rows.append({"listing_id": f"e{i}", "source": "bama",
                     "year_jalali": 1391 + i % 12,
                     "mileage_km": 90_000 + i * 900,
                     "asking_price_toman": 500_000_000 + i * 7_000_000,
                     "make": "Saipa", "model": "Pride", "trim": "131",
                     "condition": "intact", "condition_source": "field",
                     "product_class": "vehicle",
                     "product_class_source": "canonical_name",
                     "price_kind": "cash",
                     "price_kind_source": "no_contrary_evidence",
                     "price_status": "display_confirmed",
                     "mileage_status": "plausible"})
    flat_time = dict(empty, run_id="flat", listings=rows,
                     provenance=dict(empty["provenance"], records_in=40,
                                     records_published=40))
    (corpora / "flat.json").write_text(json.dumps(flat_time), encoding="utf-8")
    code, out = run("flat", corpora)
    flat = " ".join(out.split())
    check("a corpus with no TIME AXIS is UNJUDGEABLE, not a 0/N split",
          code != 0 and "UNJUDGEABLE" in out, out[-500:])
    check("  and it names the cause rather than reporting an empty train set",
          "first_seen_ordinal" in flat, out[-500:])
    check("  and says a random split would be a different claim, not a repair",
          "not a" in flat and "repair" in flat, out[-500:])
    check("  no MAE, and no verdict from the gate",
          "model MAE" not in out and "demonstrated failures" not in out,
          out[-500:])

# ---------------------------------------------------------------------------
print("\nno result leaves this file without the question it answers")
# ---------------------------------------------------------------------------
#
# A bare `MAE = 63,900,000` in a transcript is a number with no question
# attached, and six months later it is quoted as "CARO's accuracy". The
# protocol is what makes it mean anything, so it travels with every result —
# including the good one, which is the case where nobody thinks to ask.
#
# The second protocol worth having, a cluster-aware split inside ONE
# snapshot, answers a DIFFERENT question: generalisation to other listings in
# the same collection, not across time. It must arrive as its own runner with
# its own name. A flag here would let one number be produced under either
# meaning and quoted under whichever suits.

check("the protocol is declared in the file, as a constant a reader can find",
      "PROTOCOL" in consts
      and getattr(consts.get("PROTOCOL"), "value", None) == "temporal",
      str(consts.get("PROTOCOL")))
check("  and there is no flag that would switch it",
      "--protocol" not in SRC and "--split" not in SRC,
      "one runner, one question; a second protocol is a second file")

_reasons = {n.targets[0].id for n in TREE.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
check("the reason vocabulary is closed, not free text",
      "REASONS" in _reasons,
      "a status line nobody can grep is a status line nobody reads")

with tempfile.TemporaryDirectory() as d2:
    corpora2 = Path(d2)
    for rid, want in (("nothing-here", "prerequisite_missing"),):
        _, out = run(rid, corpora2)
        flat = " ".join(out.split())
        check(f"a refusal for {want} still declares its protocol",
              "protocol temporal" in flat, out[-300:])
        check(f"  and names {want} from the closed vocabulary",
              f"reason {want}" in flat, out[-300:])

    (corpora2 / "flat.json").write_text(json.dumps(flat_time), encoding="utf-8")
    _, out = run("flat", corpora2)
    flat = " ".join(out.split())
    check("the no-time-axis refusal carries protocol and reason",
          "protocol temporal" in flat
          and "reason missing_temporal_axis" in flat, out[-400:])
    check("  and the corpus identity, so the refusal is about a known file",
          "sha256" in flat and "run_id flat" in flat, out[-400:])

# The structural invariant: one report() per exit from main(), counted from
# the AST rather than by looking at nearby lines. Line proximity would pass a
# file where two exits shared one report and a third had none.
_main = next(n for n in TREE.body
             if isinstance(n, ast.FunctionDef) and n.name == "main")
_exits = [n for n in ast.walk(_main) if isinstance(n, ast.Return)]
_reports = [n for n in ast.walk(_main)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "report"]
check("main() has as many report() calls as it has exits",
      len(_exits) == len(_reports) and _exits,
      f"{len(_exits)} returns, {len(_reports)} reports — an exit without one "
      f"is a number with no question attached")

# ---------------------------------------------------------------------------
print("\nthe second protocol: within one collection, under its own name")
# ---------------------------------------------------------------------------
#
# Predictions WITHIN, WC1-WC10 (2026-10-30, evening, locked before the code).
# D55 kept the temporal runner to its one question and said how the other may
# be asked: as its own runner, with its own name. These rows hold that runner
# to the same refusals, to the one thing it adds -- a split by car inside one
# collection -- and every exit of it to its own protocol and scope.

WITHIN = ROOT / "scripts" / "benchmark_within.py"


def run_within(run_id: str, corpora: Path) -> tuple[int, str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "NO_COLOR": "1",
           "CARO_CORPORA": str(corpora)}
    p = subprocess.run([sys.executable, str(WITHIN), "--run-id", run_id],
                       cwd=ROOT, env=env, capture_output=True, text=True,
                       timeout=180)
    return p.returncode, p.stdout + p.stderr


with tempfile.TemporaryDirectory() as d3:
    c3 = Path(d3)
    code, out = run_within("nothing-here", c3)
    flat = " ".join(out.split())
    check("WC1: a missing artifact refuses as PREREQUISITE_MISSING, under protocol within_collection "
          "and reason prerequisite_missing, with no MAE",
          code != 0 and "PREREQUISITE_MISSING" in out and "protocol within_collection" in flat
          and "reason prerequisite_missing" in flat and "model MAE" not in out, out[-400:])

    (c3 / "broken.json").write_text('{"schema": "wrong", "listings": []}', encoding="utf-8")
    code, out = run_within("broken", c3)
    flat = " ".join(out.split())
    check("WC2: an unusable artifact refuses as CORPUS_UNUSABLE, reason corpus_unusable",
          code != 0 and "CORPUS_UNUSABLE" in out and "protocol within_collection" in flat
          and "reason corpus_unusable" in flat, out[-400:])

    (c3 / "empty.json").write_text(json.dumps(empty), encoding="utf-8")
    code, out = run_within("empty", c3)
    flat = " ".join(out.split())
    check("WC3: a valid artifact with no eligible row is UNJUDGEABLE, reason no_eligible_rows, no MAE",
          code != 0 and "UNJUDGEABLE" in out and "protocol within_collection" in flat
          and "reason no_eligible_rows" in flat and "model MAE" not in out, out[-400:])

    (c3 / "flat.json").write_text(json.dumps(flat_time), encoding="utf-8")
    code, out = run_within("flat", c3)
    flat = " ".join(out.split())
    check("WC4: the 40 rows the temporal runner refuses for their time axis are split 30 / 10 with "
          "none leaked, then UNJUDGEABLE shift_unknown -- below 93 a side -- with no MAE, and the "
          "collection's source, date and scope in the report",
          code != 0 and "train / test 30 / 10" in flat and "leakage 0" in flat
          and "reason shift_unknown" in flat and "model MAE" not in out
          and "source bama collected 2026-09-10" in flat.rsplit("EVALUATION", 1)[-1]
          and "scope one collection of one source" in flat.rsplit("EVALUATION", 1)[-1], out[-600:])

    # One stationary collection: three trims, the asking price falling with
    # age and odometer, and a spread of ten per cent either way.
    _trims = {"111": 450_000_000, "131": 520_000_000, "132": 560_000_000}
    _big = []
    for i in range(480):
        _t = ("111", "131", "132")[i % 3]
        _year = 1388 + (i * 7) % 15
        _km = 20_000 + (i * 7919) % 260_000
        _noise = 1 + (((i * 2654435761) % 1000) / 1000 - 0.5) * 0.2
        _price = int(_trims[_t] * (1 - 0.025 * (1402 - _year)) * (1 - _km / 1_500_000)
                     * _noise) // 100_000 * 100_000
        _big.append(dict(rows[0], listing_id=f"w{i}", trim=_t, year_jalali=_year,
                         mileage_km=_km, asking_price_toman=_price))
    big = dict(empty, run_id="big", listings=_big,
               provenance=dict(empty["provenance"], records_in=480, records_published=480))
    (c3 / "big.json").write_text(json.dumps(big), encoding="utf-8")
    code, out = run_within("big", c3)
    flat = " ".join(out.split())
    check("WC5: 480 listings of one stationary collection are split 360 / 120 and found comparable; "
          "the estimator runs, both MAEs are printed, and the frozen gate does not accept -- its own "
          "reason, with the scope and whose asking prices these are",
          "train / test 360 / 120" in flat and "state comparable" in flat
          and "model MAE" in out and "baseline MAE" in out
          and ("reason insufficient_slices" in flat or "reason measured_failure" in flat)
          and "status accepted" not in flat
          and "scope one collection of one source" in flat.rsplit("EVALUATION", 1)[-1]
          and "These are bama's asking prices, collected 2026-09-10" in flat, out[-900:])
    code2, out2 = run_within("big", c3)
    _keep = lambda o: [ln.strip() for ln in o.splitlines()                         # noqa: E731
                       if ln.strip().startswith(("cars", "train / test", "model MAE", "baseline MAE"))]
    check("WC6: the same artifact twice gives the same split and the same two MAEs: the seed is fixed",
          _keep(out) == _keep(out2) and len(_keep(out)) == 4, f"{_keep(out)} | {_keep(out2)}")

from caro.appraisal import Row                                    # noqa: E402
import scripts.benchmark_corpus as BC                             # noqa: E402

try:                       # a runner that does not import fails its rows by name
    import scripts.benchmark_within as BW                         # noqa: E402
    _bw_why = ""
except Exception as e:     # noqa: BLE001
    BW, _bw_why = None, f"{type(e).__name__}: {e}"


def _row(lid: str, km: float, price: float) -> Row:
    return Row(listing_id=lid, cluster_id=lid, first_seen_ordinal=0,
               model_key="Saipa|Pride|131", year_jalali=1395, mileage_km=km,
               asking_price_toman=price)


_WC7 = ("WC7: five listings alike in model, year, odometer and price are one car, on one side; nothing "
        "leaks; 9 of the 36 cars are the test side; the rows' order changes nothing; another seed gives "
        "another split")
if BW is None:
    check(_WC7, False, _bw_why)
else:
    _twins = [_row(f"t{k}", 55_000.0, 777_000_000.0) for k in range(5)]
    _pool = [_row(f"r{i:02d}", 100_000.0 + i, 500_000_000.0 + i) for i in range(35)] + _twins
    _s = BW.within_split(_pool, test_fraction=0.25, seed=0)
    _s_rev = BW.within_split(list(reversed(_pool)), test_fraction=0.25, seed=0)
    _s_other = BW.within_split(_pool, test_fraction=0.25, seed=1)
    _tested = lambda s: sorted(r.listing_id for r in s.test)                      # noqa: E731
    _twin_sides = {"test" if t.listing_id in _tested(_s) else "train" for t in _twins}
    _cars_tested = len({r.cluster_id for r in _s.test})
    check(_WC7,
          len(_twin_sides) == 1 and not _s.leakage() and _cars_tested == 9
          and len(_s.train) + len(_s.test) == len(_pool)
          and _tested(_s) == _tested(_s_rev) and _tested(_s) != _tested(_s_other),
          f"twins on {_twin_sides}, leaked {_s.leakage()}, {_cars_tested} cars tested, order-free "
          f"{_tested(_s) == _tested(_s_rev)}, seed used {_tested(_s) != _tested(_s_other)}")

# WC11 (predictions WITHIN2, locked before the code): one listing read twice,
# its price changed between the two pages, and a third row the first
# reading's twin. A listing is one car whatever changed between its readings.
_WC11 = ("WC11: a listing read twice with two prices, and a twin of its first reading, are one car on "
         "one side whatever the seed (0 to 19); no error, no row lost, and the same split with the rows "
         "reversed")
if BW is None:
    check(_WC11, False, _bw_why)
else:
    _again = [_row("k1", 60_000.0, 800_000_000.0), _row("k1", 60_000.0, 790_000_000.0),
              _row("k9", 60_000.0, 800_000_000.0)]
    _many = [_row(f"m{i:02d}", 120_000.0 + i, 450_000_000.0 + i) for i in range(20)] + _again
    _bad11 = []
    try:
        for _seed in range(20):
            _sa = BW.within_split(_many, test_fraction=0.25, seed=_seed)
            _sb = BW.within_split(list(reversed(_many)), test_fraction=0.25, seed=_seed)
            _in = {(x.listing_id, x.asking_price_toman) for x in _sa.test}
            if (len({(r.listing_id, r.asking_price_toman) in _in for r in _again}) != 1
                    or _sa.leakage() or len(_sa.train) + len(_sa.test) != len(_many)
                    or sorted(r.listing_id for r in _sa.test) != sorted(r.listing_id for r in _sb.test)):
                _bad11.append(_seed)
        _why11 = ""
    except Exception as e:                                         # noqa: BLE001
        _bad11, _why11 = ["raised"], f"{type(e).__name__}: {e}"
    check(_WC11, not _bad11, _why11 or f"not one car, or not order-free, for seeds {_bad11}")

WSRC = WITHIN.read_text(encoding="utf-8") if WITHIN.exists() else ""
WTREE = ast.parse(WSRC)
_wnames: set[str] = set()
for _node in ast.walk(WTREE):
    if isinstance(_node, ast.Import):
        _wnames.update(a.name for a in _node.names)
    elif isinstance(_node, ast.ImportFrom):
        _wnames.add(_node.module or "")
        _wnames.update(a.name for a in _node.names)
_wconsts = {n.targets[0].id: n.value for n in WTREE.body
            if isinstance(n, ast.Assign) and isinstance(n.targets[0], ast.Name)}
_wdefs = {n.name for n in WTREE.body if isinstance(n, ast.FunctionDef)}
_wmain = next((n for n in WTREE.body if isinstance(n, ast.FunctionDef) and n.name == "main"), None)
_wexits = [n for n in ast.walk(_wmain) if isinstance(n, ast.Return)] if _wmain else []
_wreports = [n for n in ast.walk(_wmain) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id == "report"] if _wmain else []
_wc8 = {
    "PROTOCOL is within_collection": getattr(_wconsts.get("PROTOCOL"), "value", None) == "within_collection",
    "no flag switches it": "--protocol" not in WSRC and "--split" not in WSRC,
    "reasons closed, no missing_temporal_axis": BW is not None and "REASONS" in _wconsts
                                                and "missing_temporal_axis" not in BW.REASONS,
    "one report per exit": bool(_wexits) and len(_wexits) == len(_wreports),
    "hold-out, seed and baseline the temporal runner's": BW is not None
        and BW.HOLDOUT_FRACTION == 0.25 and BW.SEED == 0
        and BW._baseline_mae is BC._baseline_mae and not ({"HOLDOUT_FRACTION", "SEED"} & set(_wconsts))
        and "_baseline_mae" not in _wdefs,
    "gate and estimator caro.hierarchical's": {"caro.hierarchical", "HierarchicalGate",
                                               "PartialPoolingQuantiles", "four_slices"} <= _wnames,
    "nothing that fetches or parses": not (set(FORBIDDEN) & _wnames),
}
check("WC8: the file declares PROTOCOL «within_collection» and no flag to switch it; its reasons are "
      "closed and never missing_temporal_axis; every exit of main() reports; the hold-out, the seed and "
      "the baseline are the temporal runner's own objects, the gate and the estimator caro.hierarchical's; "
      "nothing that fetches or parses is imported",
      all(_wc8.values()), str([k for k, v in _wc8.items() if not v]))

with tempfile.TemporaryDirectory() as d4:
    (Path(d4) / "flat.json").write_text(json.dumps(flat_time), encoding="utf-8")
    _, out = run("flat", Path(d4))
    flat = " ".join(out.split())
    check("WC9: the temporal runner's no-time-axis refusal names scripts/benchmark_within.py and "
          "within_collection, and still reports missing_temporal_axis under protocol temporal",
          "scripts/benchmark_within.py" in flat and "within_collection" in flat
          and "protocol temporal" in flat and "reason missing_temporal_axis" in flat, out[-600:])

_wsev = re.search(r'report\(\s*"(\w+)"\s*,\s*"severe_shift"', WSRC)
check("WC10: REJECTED is spent only on the gate's measured failure, and a severe shift reports "
      "unjudgeable -- as the shift suite holds the temporal runner",
      'GateVerdict.REJECTED: "measured_failure"' in WSRC
      and not re.search(r'report\(\s*"rejected"', WSRC)
      and _wsev is not None and _wsev.group(1) == "unjudgeable",
      f"severe shift reports {_wsev.group(1) if _wsev else '<no such call>'}")

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("benchmark contract: the artifact is the only input, and the three "
      "refusals hold")
