#!/usr/bin/env python3
"""Is Run 5's REJECT distinguishable from sampling noise?

    python3 scripts/run5_significance.py

`HierarchicalGate` rejects when model MAE exceeds baseline MAE by more than
10%. Run 5 tripped it at +15.3%. That comparison has **no uncertainty
control** — it is a raw threshold on a point estimate.

This is the third time this project has met that error. D33 records the first
two: a max over 48 noisy slice estimates rejecting a perfect Oracle, and
`MIN_SLICE_N` rising to 58 so a coverage deviation counts only past 2.5
binomial SE. Both fixes applied significance testing to the *calibration*
criterion. **Neither was applied to the MAE criterion**, which sat one field
away in the same gate and got a bare `>` comparison.

Nothing here changes the estimator, the gate, or any frozen constant. It
measures how much confidence the already-produced verdict deserves, and it
can only ever weaken a claim, never strengthen one — which is the direction a
post-hoc test is allowed to run.

**Clustered by trim, not by row.** Rows inside one trim share a price level,
a parent, and whatever the trim page's own composition bias is; treating 228
of them as independent draws would shrink the interval by pretending we have
more information than we do. Resampling trims keeps the dependence.
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.hierarchical import (                                    # noqa: E402
    HierarchicalGate, PartialPoolingQuantiles, held_out_trim_split,
)

BOOTSTRAP = 10_000
SEED = 0


def main() -> int:
    from scripts.benchmark_run5 import load, baseline_mae           # noqa: E402
    _, _, rows, _ = load()
    train, _ = held_out_trim_split(rows, fraction=0.25, seed=SEED)

    model = PartialPoolingQuantiles().fit(train)
    mid = len(model.quantiles) // 2
    pred_m = model.predict(train)[:, mid]
    truth = np.array([r.asking_price_toman for r in train])

    by_parent: dict[str, list[float]] = defaultdict(list)
    for r in train:
        by_parent["|".join(r.model_key.split("|")[:2])].append(
            r.asking_price_toman)
    glob = float(np.median(truth))
    pred_b = np.array([
        float(np.median(by_parent.get("|".join(r.model_key.split("|")[:2]),
                                      [glob]))) for r in train])

    err_m = np.abs(pred_m - truth)
    err_b = np.abs(pred_b - truth)
    d_obs = err_m.mean() - err_b.mean()

    trims = sorted({r.model_key for r in train})
    idx = {t: np.array([i for i, r in enumerate(train) if r.model_key == t])
           for t in trims}

    rng = np.random.default_rng(SEED)
    deltas = np.empty(BOOTSTRAP)
    ratios = np.empty(BOOTSTRAP)
    for b in range(BOOTSTRAP):
        pick = rng.integers(0, len(trims), len(trims))
        sel = np.concatenate([idx[trims[k]] for k in pick])
        deltas[b] = err_m[sel].mean() - err_b[sel].mean()
        ratios[b] = err_m[sel].mean() / err_b[sel].mean()
    lo, hi = np.percentile(deltas, [2.5, 97.5])
    rlo, rhi = np.percentile(ratios, [2.5, 97.5])

    print("RUN 5 — how much confidence does the REJECT deserve?")
    print("=" * 76)
    print(f"  rows                    {len(train)}   in {len(trims)} trims")
    print(f"  model MAE               {err_m.mean():,.0f}")
    print(f"  baseline MAE            {err_b.mean():,.0f}")
    print(f"  observed difference     {d_obs:+,.0f}"
          f"   ({err_m.mean() / err_b.mean() - 1:+.1%})")
    print(f"\n  paired cluster bootstrap, {BOOTSTRAP:,} resamples of TRIMS")
    print(f"  95% CI on the difference   [{lo:+,.0f}, {hi:+,.0f}]")
    print(f"  95% CI on the ratio        [{rlo:.2f}x, {rhi:.2f}x]")
    print(f"  P(model worse than baseline)      {(deltas > 0).mean():.1%}")
    print(f"  P(worse by more than the gate's 10%)  "
          f"{(ratios > 1.10).mean():.1%}")

    excludes_zero = lo > 0
    excludes_gate = rlo > 1.10
    print("\nWHAT THIS DOES AND DOES NOT SETTLE", "\n" + "-" * 76)
    print(f"  {'✓' if excludes_zero else '✗'} the interval excludes zero — "
          f"the model being WORSE is {'' if excludes_zero else 'not '}"
          f"distinguishable from noise")
    print(f"  {'✓' if excludes_gate else '✗'} the interval excludes the "
          f"gate's 1.10 threshold — 'worse by more than 10%' is "
          f"{'' if excludes_gate else 'NOT '}established")

    if excludes_zero and not excludes_gate:
        print("\n  These two disagree, and the disagreement is the finding.")
        print("  The estimator is worse than its baseline — that much survives")
        print("  resampling. Whether it is worse by more than the 10% the gate")
        print("  rejects on does not. The verdict stands on a point estimate")
        print("  sitting inside its own confidence interval.")
    elif not excludes_zero:
        print("\n  The REJECT does not survive its own uncertainty. On the")
        print("  registered criterion the gate rejected; on the evidence the")
        print("  difference is not distinguishable from sampling noise, and")
        print("  UNJUDGEABLE would be the more honest verdict.")
    else:
        print("\n  The REJECT survives resampling at both thresholds. The")
        print("  verdict is not an artefact of a point estimate.")

    print("\n  Either way this is a finding about the GATE, not about Run 5's")
    print("  execution. `HierarchicalGate.mae_tolerance` is a bare comparison")
    print("  on a point estimate, while the calibration criterion beside it")
    print("  requires 2.5 SE — D33 fixed winner's curse on one field and left")
    print("  the other one raw. Changing it now would be tuning after a loss,")
    print("  so it is recorded and left alone; the next registration decides.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
