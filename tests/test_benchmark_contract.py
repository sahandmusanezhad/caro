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

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("benchmark contract: the artifact is the only input, and the three "
      "refusals hold")
