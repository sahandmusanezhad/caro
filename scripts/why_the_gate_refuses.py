#!/usr/bin/env python3
"""Why does the gate refuse even the BASELINE on Run 5's corpus?

    python3 scripts/why_the_gate_refuses.py

D41 recorded that `comparable-quantiles` fails the acceptance gate on Run 5
at a coverage error of 0.206 against a 0.07 limit, and read that as a fact
about the baseline: "the thing D12 promised to ship does not clear the gate
either." That reading is wrong, and this script is how it was found out.

Nothing is fitted, tuned or gated here. It re-runs the frozen split on the
frozen corpus and prints the arithmetic underneath one number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.appraisal import (                                       # noqa: E402
    ComparableQuantiles, GlobalQuantiles, Split, run_benchmark,
)
from caro.hierarchical import held_out_trim_split                  # noqa: E402


def main() -> int:
    from scripts.benchmark_run5 import (                           # noqa: E402
        HOLDOUT_FRACTION, SPLIT_SEED, load,
    )
    _, _, rows, _ = load()
    train, test = held_out_trim_split(rows, fraction=HOLDOUT_FRACTION,
                                      seed=SPLIT_SEED)
    split = Split(train=train, test=test, dropped_straddling=0,
                  cutoff_ordinal=0)

    print("WHY THE GATE REFUSES — the arithmetic under 0.206")
    print("=" * 78)

    print("\n1. THE TWO ESTIMATORS ARE THE SAME ESTIMATOR HERE")
    print("-" * 78)
    pc = ComparableQuantiles().fit(train).predict(test)
    pg = GlobalQuantiles().fit(train).predict(test)
    same = bool(np.allclose(pc, pg))
    print(f"  comparable vs global predictions identical   {same}"
          f"   (max |diff| {float(np.max(np.abs(pc - pg))):,.0f})")

    tt = {r.model_key for r in train}
    et = {r.model_key for r in test}
    ptr = {"|".join(k.split("|")[:2]) for k in tt}
    pte = {"|".join(k.split("|")[:2]) for k in et}
    print(f"  trims    train {len(tt):>3}   test {len(et):>3}   "
          f"overlap {len(tt & et)}")
    print(f"  parents  train {len(ptr):>3}   test {len(pte):>3}   "
          f"overlap {len(ptr & pte)}")
    print("\n  The split holds out whole TRIMS, so no test row has a comparable")
    print("  in training. The ladder falls through to `global` on every row,")
    print("  and a comparables estimator with no comparables IS the global")
    print("  estimator. Under this split the gate cannot tell them apart —")
    print("  and it did not: both reported the same 0.206.")

    print("\n2. THE HELD-OUT TRIMS ARE A DIFFERENT PRICE POPULATION")
    print("-" * 78)
    a = np.array([r.asking_price_toman for r in train], float)
    b = np.array([r.asking_price_toman for r in test], float)
    for nm, v in (("train", a), ("test", b)):
        print(f"  {nm:<6} n={len(v):>4}  median {np.median(v):>16,.0f}  "
              f"p15 {np.percentile(v, 15):>15,.0f}  "
              f"p85 {np.percentile(v, 85):>15,.0f}  spread "
              f"{v.max() / v.min():>4.0f}x")

    below15 = float((b < np.percentile(a, 15)).mean())
    below50 = float((b < np.median(a)).mean())
    print(f"\n  share of TEST rows below TRAIN p15      {below15:.3f}")
    print(f"  share of TEST rows below TRAIN median   {below50:.3f}")

    print("\n3. THOSE TWO NUMBERS *ARE* THE COVERAGE FAILURE")
    print("-" * 78)
    r = run_benchmark(ComparableQuantiles(), split, name="comparable-quantiles")
    o = r.overall
    for tau, emp in sorted(o.coverage_by_tau.items()):
        lo, hi = o.coverage_ci(tau)
        flag = "" if o.nominal_inside_ci(tau) else "   nominal OUTSIDE 95% CI"
        print(f"  tau {tau:.2f}   empirical {emp:.3f}   err {emp - tau:+.3f}"
              f"   CI [{lo:.2f}, {hi:.2f}]{flag}")
    print(f"\n  worst error {o.max_abs_coverage_error:.3f}, and past 2.5 SE it "
          f"is still {o.significant_coverage_error():.3f}")
    print("\n  Read them together: 0.000 coverage at tau=0.15 is the same fact")
    print("  as 'no test row is cheaper than the train p15', and 0.294 at the")
    print("  median is the same fact as 'only 29% of test rows are below the")
    print("  train median'. The coverage failure is not a property of the")
    print("  estimator. It is what happens when a distribution fitted on one")
    print("  price population is asked to be calibrated on another.")

    print("\nWHAT THIS CHANGES, AND WHAT IT DOES NOT")
    print("-" * 78)
    print("  Corrects D41. 'The baseline class does not clear the gate either'")
    print("  reads as a fact about the baseline, and it is not: under this")
    print("  split EVERY estimator is the same estimator, and it is being")
    print("  scored against trims it has never seen at prices it has never")
    print("  seen. The refusal is real and correct — CARO still may not serve")
    print("  an estimate here — but the reason is the corpus and the split,")
    print("  not the model.")
    print("\n  Does NOT rescue the estimator. Run 5's REJECT stands as")
    print("  registered, with D39's interval attached, and nothing here is")
    print("  evidence that partial pooling would have passed under a kinder")
    print("  split. Choosing a kinder split now, after seeing this, is exactly")
    print("  the D35 move — so the split is untouched and this is a finding.")
    print("\n  It is the third appearance of D38's blind spot: a registration")
    print("  that constrained trim COUNTS and said nothing about price")
    print("  heterogeneity. First it decided the benchmark; then it explained")
    print("  the thin-slice tension; now it turns out to have decided whether")
    print("  a market estimate can be served at all.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
