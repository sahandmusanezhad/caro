#!/usr/bin/env python3
"""Benchmark the estimator WITHIN ONE COLLECTION. A different question.

    python3 scripts/benchmark_within.py --run-id run17

`benchmark_corpus.py` asks whether the estimator holds up on listings
separated IN TIME, and one snapshot cannot answer that: it has no first-seen
history, so it is refused as `missing_temporal_axis` (D55). D55 also said
what one snapshot CAN be asked, and how: whether the estimator holds up on
other listings of the same collection — "a second protocol arrives as a
second runner with its own name, its own contract, and its own entry". This
is that runner, and its name travels with every result it prints:

    protocol   within_collection

What a verdict here is about: one published artifact — one source, one day,
the asking prices that source showed. Not across time (the temporal
protocol), not another source, and nothing about the market (D36). An
ACCEPTED here would not be the temporal gate's acceptance and serves nothing.

Everything after the split is the temporal runner's, not a copy of it: the
hold-out fraction, the seed and the baseline are imported from it, and the
estimator, the slices and the gate are caro.hierarchical's, called the way it
calls them (D35). Only the split differs, and it is a function here so the
suite can hold it to what it says.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np                                                # noqa: E402

from caro.appraisal import (                                      # noqa: E402
    Comparability, MIN_COMPARABLE_N, Row, Split, distribution_shift,
)
from caro.corpus_reader import (                                  # noqa: E402
    CorpusUnavailable, corpus_identity, load_corpus, rows_from_corpus,
)
from caro.hierarchical import (                                   # noqa: E402
    GateVerdict, HierarchicalGate, MIN_SLICE_N, PartialPoolingQuantiles,
    four_slices,
)
from scripts.benchmark_corpus import (                            # noqa: E402
    HOLDOUT_FRACTION, SEED, _baseline_mae,
)

# The question, as a constant a reader can find and no flag can switch.
PROTOCOL = "within_collection"

# Closed, as the temporal runner's is. `missing_temporal_axis` is not here:
# this protocol never asks for time, so it can never be refused for lacking it.
REASONS = {
    "prerequisite_missing":  "no published artifact for this run id",
    "corpus_unusable":       "the artifact fails a guard; it is not a corpus",
    "no_eligible_rows":      "valid artifact, nothing appraisable in it",
    "split_leaked":          "a car appears on both sides of the split",
    "severe_shift":          "train and test are not alike; test error is "
                             "not evidence about the within-collection "
                             "question",
    "shift_unknown":         "too few rows a side to establish whether they "
                             "are comparable at all",
    "insufficient_slices":   "the gate's own verdict: the collection cannot "
                             "answer",
    "measured_failure":      "the estimator was assessed and fell short",
    "accepted":              "every condition of the frozen gate held, "
                             "within this one collection",
}

SCOPE = ("one collection of one source -- not across time, not another "
         "source, not the market (D36)")


def report(status: str, reason: str, ident=None, artifact=None) -> None:
    """The block every exit prints: the question, and what it is about."""
    assert reason in REASONS, f"undeclared reason {reason!r}"
    print()
    print("EVALUATION")
    print("-" * 62)
    print(f"  protocol   {PROTOCOL}")
    print(f"  status     {status}")
    print(f"  reason     {reason}   ({REASONS[reason]})")
    if ident is not None:
        print(f"  run_id     {ident.run_id}")
        print(f"  sha256     {ident.sha256}")
    if artifact is not None:
        print(f"  source     {artifact.get('source')}   "
              f"collected {artifact.get('collected_on')}")
        print(f"  scope      {SCOPE}")
    print()


def _car(r: Row) -> tuple:
    """What one car looks like inside one collection."""
    return (r.model_key, r.year_jalali, r.mileage_km, r.asking_price_toman)


def within_split(rows: list[Row], *, test_fraction: float, seed: int) -> Split:
    """A random split of one collection, by car.

    A published corpus names no car across listings: each row is its own
    cluster. Two listings alike in model key, year, odometer and asking price
    are taken here as one car -- a repost the corpus could not tell apart --
    and kept on one side, so the model is never tested on a car it was
    trained on. Each car carries its smallest listing id as its cluster, which
    is what `Split.leakage()` reads.

    The cars are ordered by that id before the seeded permutation, so the
    split depends on the collection and the seed, never on the file's order.
    """
    cars: dict[tuple, list[Row]] = {}
    for r in rows:
        cars.setdefault(_car(r), []).append(r)
    named = sorted((min(r.listing_id for r in rs), rs) for rs in cars.values())
    order = np.random.default_rng(seed).permutation(len(named))
    n_test = max(1, int(round(len(named) * test_fraction)))
    to_test = set(int(i) for i in order[:n_test])
    train: list[Row] = []
    test: list[Row] = []
    for i, (cid, rs) in enumerate(named):
        (test if i in to_test else train).extend(
            replace(r, cluster_id=cid) for r in rs)
    return Split(train, test, dropped_straddling=0, cutoff_ordinal=0)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run-id", required=True)
    a = ap.parse_args()

    print("QUESTION")
    print("-" * 62)
    print(f"  protocol   {PROTOCOL}")
    print("  asks       does the frozen estimator hold up on other listings")
    print("             of the same collection?")
    print(f"  scope      {SCOPE}")
    print()

    # ---- the artifact, or nothing ---------------------------------------
    try:
        artifact = load_corpus(a.run_id)
    except CorpusUnavailable as e:
        print(f"PREREQUISITE_MISSING\n\n{e}\n")
        print("The benchmark did not run. There is no fallback to a snapshot "
              "or a scrape.")
        report("refused", "prerequisite_missing")
        return 2
    except ValueError as e:
        print(f"CORPUS_UNUSABLE\n\n{e}\n")
        print("A file that fails the schema or content guard is not a corpus "
              "(D49), and the\nbenchmark does not run on one.")
        report("refused", "corpus_unusable")
        return 2

    ident = corpus_identity(a.run_id)
    print("CORPUS")
    print("-" * 62)
    print(f"  run_id     {ident.run_id}")
    print(f"  path       {ident.path}")
    print(f"  sha256     {ident.sha256}")
    print(f"  bytes      {ident.bytes:,}")
    print(f"  source     {artifact.get('source')}")
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
        report("unjudgeable", "no_eligible_rows", ident, artifact)
        return 1

    split = within_split(rows, test_fraction=HOLDOUT_FRACTION, seed=SEED)
    train, test = split.train, split.test
    leak = split.leakage()
    n_cars = len({r.cluster_id for r in train + test})
    print(f"  cars                 {n_cars:>5}   (listings alike in model, "
          "year, odometer and price are one)")
    print(f"  train / test         {len(train):>5} / {len(test)}")
    print(f"  leakage              {len(leak):>5}   (must be 0)")
    print()
    if leak:
        print("REFUSING: the split leaked. Nothing below this line would "
              "mean anything.")
        report("refused", "split_leaked", ident, artifact)
        return 1
    if not test or not train:
        print("UNJUDGEABLE\n")
        print(f"  {len(train)} train / {len(test)} test rows. A hold-out of "
              "this size cannot\n  answer anything about calibration.")
        report("unjudgeable", "insufficient_slices", ident, artifact)
        return 1

    # ---- is the test half evidence about anything? ----------------------
    shift = distribution_shift(split)
    print("COMPARABILITY")
    print("-" * 62)
    print(f"  state                {shift.comparability.value}")
    print(f"  {shift}")
    print()

    if shift.comparability is Comparability.INSUFFICIENT:
        print("UNJUDGEABLE\n")
        print(f"  {shift.n_train} train / {shift.n_test} test rows, against a "
              f"floor of {MIN_COMPARABLE_N} a side.\n  Below it the comparison "
              "has no power. This is an answer about the\n  COLLECTION: the "
              "estimator was not run and has not failed anything.")
        report("unjudgeable", "shift_unknown", ident, artifact)
        return 1

    if shift.comparability is Comparability.SHIFTED:
        print("UNJUDGEABLE\n")
        print("  Train and test are measurably unalike, so the test error is "
              "no longer\n  evidence. NOT a rejection: REJECTED is spent only "
              "on an estimator measured\n  on a valid evaluation population.")
        report("unjudgeable", "severe_shift", ident, artifact)
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
    print(f"  {verdict.value}   (protocol {PROTOCOL})")
    print()
    if failures:
        print("  demonstrated failures — the model was measured and fell short")
        for f in failures:
            print(f"    · {f}")
        print()
    if unanswered:
        print("  unanswered questions — the collection cannot say")
        for u in unanswered:
            print(f"    · {u}")
        print()
    print(f"  These are {artifact.get('source')}'s asking prices, collected "
          f"{artifact.get('collected_on')}: one collection.")
    if verdict is GateVerdict.ACCEPTED:
        print("  Every condition held, within this collection. That is not "
              "the temporal\n  gate's acceptance, and nothing is served on it "
              "(D30, D31, D32, D55).")
    report({GateVerdict.ACCEPTED: "accepted",
            GateVerdict.REJECTED: "rejected"}.get(verdict, "unjudgeable"),
           {GateVerdict.ACCEPTED: "accepted",
            GateVerdict.REJECTED: "measured_failure"}.get(
               verdict, "insufficient_slices"),
           ident, artifact)
    return 0 if verdict is GateVerdict.ACCEPTED else 1


if __name__ == "__main__":
    raise SystemExit(main())
