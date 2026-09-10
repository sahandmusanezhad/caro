#!/usr/bin/env python3
"""Benchmark the estimator against a PUBLISHED CORPUS ARTIFACT. Nothing else.

    python3 scripts/benchmark_corpus.py --run-id run11

Every benchmark this project has produced read rebuilt pages and re-parsed
them: `benchmark_run5.py` calls `replay_run3.rebuild`, which reconstructs a
detail page from a positional record and hands it back to
`parse_detail_page`. That measured the estimator against the PARSER's output,
and it is why nobody noticed that every published artifact held zero
appraisal-eligible rows — the artifact was never the input to anything.

So the rule this file exists to enforce, and the reason it is a separate file
rather than a flag on the old one:

    Benchmark evidence comes exclusively from the published corpus artifact,
    identified by its run id and its SHA-256.

There is no fetch here, no `parse_detail_page`, no rebuild, and no fallback
to any of them. `tests/test_benchmark_contract.py` asserts that by reading
this module's own imports, because a rule enforced by intention is a rule
that lasts until someone is in a hurry.

FOUR OUTCOMES, AND THREE OF THEM ARE NOT A NUMBER
-------------------------------------------------
    artifact missing    PREREQUISITE_MISSING. The benchmark does not run.
                        Not synthetic data, not a warning banner, not a zero.
    artifact unusable   CORPUS_UNUSABLE. A file that fails the schema or
                        content guard is not a corpus with problems; it is
                        not a corpus (D49).
    evidence too thin   UNJUDGEABLE. The gate's own verdict, unchanged.
    evidence sufficient the estimator runs and the frozen gate answers.

The corpus identity is printed with the verdict and belongs in whatever
records it, so nobody can later say a number was "run 11" when it was run on
a snapshot, a scrape, or a different promotion of the same day.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                                                # noqa: E402

from caro.appraisal import cluster_temporal_split                 # noqa: E402
from caro.corpus_reader import (                                  # noqa: E402
    CorpusUnavailable, corpus_identity, load_corpus, rows_from_corpus,
)
from caro.hierarchical import (                                   # noqa: E402
    GateVerdict, HierarchicalGate, MIN_SLICE_N, PartialPoolingQuantiles,
    four_slices,
)

HOLDOUT_FRACTION = 0.25          # frozen, D34
SEED = 0                         # frozen


def _baseline_mae(train, test) -> float:
    """Median asking price per make|model, which is what D12 ships if it wins.

    Deliberately the dumbest thing that could work. A baseline that is itself
    a model makes the comparison flattering, and D12's rule — if the baseline
    wins, ship the baseline — only means anything if the baseline is the
    thing a person would otherwise do.
    """
    by: dict[str, list[float]] = {}
    for r in train:
        key = "|".join(r.model_key.split("|")[:2])
        by.setdefault(key, []).append(float(r.asking_price_toman))
    med = {k: float(np.median(v)) for k, v in by.items()}
    overall = float(np.median([float(r.asking_price_toman) for r in train]))
    err = [abs(med.get("|".join(r.model_key.split("|")[:2]), overall)
               - float(r.asking_price_toman)) for r in test]
    return float(np.mean(err)) if err else float("nan")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    a = ap.parse_args()

    # ---- the artifact, or nothing ---------------------------------------
    try:
        artifact = load_corpus(a.run_id)
    except CorpusUnavailable as e:
        print(f"PREREQUISITE_MISSING\n\n{e}\n")
        print("The benchmark did not run. There is no fallback to a snapshot "
              "or a scrape:\nan estimate produced from anything but the "
              "published artifact would be a\nnumber about a different "
              "corpus wearing this one's run id.")
        return 2
    except ValueError as e:
        print(f"CORPUS_UNUSABLE\n\n{e}\n")
        print("A file that fails the schema or content guard is not a corpus "
              "with problems.\nIt is not a corpus (D49), and the benchmark "
              "does not run on one.")
        return 2

    ident = corpus_identity(a.run_id)
    print("CORPUS")
    print("-" * 62)
    print(f"  run_id     {ident.run_id}")
    print(f"  path       {ident.path}")
    print(f"  sha256     {ident.sha256}")
    print(f"  bytes      {ident.bytes:,}")
    print(f"  collected  {artifact.get('collected_on')}   "
          f"promoted {artifact.get('promoted_on')}")
    print()

    listings, rows = rows_from_corpus(artifact)
    print("EVIDENCE")
    print("-" * 62)
    print(f"  published            {len(listings):>5}")
    print(f"  appraisal-eligible   {len(rows):>5}")
    if not rows:
        print()
        print("UNJUDGEABLE\n")
        print("  The artifact is valid and holds no appraisal-eligible row. "
              "That is not a\n  model result and not a corpus fault — it is "
              "an answer about the evidence.")
        return 1

    split = cluster_temporal_split(rows, test_fraction=HOLDOUT_FRACTION)
    train, test = split.train, split.test
    leak = split.leakage()
    print(f"  train / test         {len(train):>5} / {len(test)}")
    print(f"  leakage              {len(leak):>5}   (must be 0)")
    print(f"  dropped straddling   {split.dropped_straddling:>5}")
    print()
    if leak:
        print("REFUSING: the split leaked. Nothing below this line would "
              "mean anything.")
        return 1
    if not test or not train:
        print("UNJUDGEABLE\n")
        print(f"  {len(train)} train / {len(test)} test rows. A hold-out of "
              "this size cannot\n  answer anything about calibration.")
        return 1

    model = PartialPoolingQuantiles().fit(train)
    counts: dict[str, int] = {}
    for r in train:
        counts[r.model_key] = counts.get(r.model_key, 0) + 1
    slices = four_slices(model, test, counts)

    preds = model.predict(test)
    med = preds[:, preds.shape[1] // 2]
    truth = np.array([float(r.asking_price_toman) for r in test])
    model_mae = float(np.mean(np.abs(med - truth)))
    base_mae = _baseline_mae(train, test)

    print("SLICES")
    print("-" * 62)
    for s in slices:
        flag = "" if s.reliable else f"   <-- below n={MIN_SLICE_N}"
        print(f"  {s.name:<24}n={s.n:<5}coverage {s.coverage:>5.0%}"
              f"  mae {s.mae:>13,.0f}{flag}")
    if not any(s.reliable for s in slices):
        print(f"  no slice reaches n={MIN_SLICE_N}, the size a calibration "
              "verdict needs")
    print()

    print("ERROR")
    print("-" * 62)
    print(f"  model MAE            {model_mae:>15,.0f}")
    print(f"  baseline MAE         {base_mae:>15,.0f}   "
          f"(median asking price per make|model)")
    if base_mae == base_mae and base_mae:      # not NaN
        print(f"  difference           {(model_mae / base_mae - 1):>14.1%}")
    print()

    verdict, failures, unanswered = HierarchicalGate().verdict(
        slices, baseline_mae=base_mae, model_mae=model_mae)

    print("VERDICT")
    print("-" * 62)
    print(f"  {verdict.value}")
    print()
    if failures:
        print("  demonstrated failures — the model was measured and fell short")
        for f in failures:
            print(f"    · {f}")
        print()
    if unanswered:
        print("  unanswered questions — the corpus cannot say")
        for u in unanswered:
            print(f"    · {u}")
        print()
    if verdict is GateVerdict.UNJUDGEABLE:
        print("  NOT a model failure and emphatically not a pass. Nothing "
              "here may be\n  served as a conditional appraisal (D30, D31, "
              "D32).")
    elif verdict is GateVerdict.ACCEPTED:
        print("  Every condition held. The identity above is what this "
              "verdict is about;\n  quote them together or not at all.")
    print()
    print(f"  corpus  run_id={ident.run_id}  sha256={ident.sha256}")
    return 0 if verdict is GateVerdict.ACCEPTED else 1


if __name__ == "__main__":
    raise SystemExit(main())
