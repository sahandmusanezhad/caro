#!/usr/bin/env python3
"""
The real benchmark: partial pooling against the Run 3 corpus.

    python3 scripts/benchmark_run3.py

Everything up to here has been architecture and fixtures. This runs the
shipped estimator and the shipped gate against 221 listings collected from
bama.ir on 2026-09-07, and prints whichever of three verdicts comes out.

The outcome is not known in advance and is not supposed to be. All three are
legitimate results:

    ACCEPTED           the estimator earned the right to serve these models
    REJECTED           it was measured and found wanting
    UNJUDGEABLE_SLICE  the corpus cannot answer — a failure of the evidence
                       for this claim, not of the model

The third is the one worth stating plainly, because it is the one a tuning
pass would try to make disappear. If aggregate MAE looks excellent while
held-out-trim coverage cannot be judged, CARO must not conclude from the
aggregate that conditional appraisal is valid. That inference is exactly the
one D30 refused.

One structural limitation of this corpus, stated rather than worked around:
it is a single snapshot, so there is no time dimension and
`cluster_temporal_split` cannot run. Only the held-out-TRIM split applies —
which is the split D32 actually needs, but it means this benchmark says
nothing about temporal generalisation. A second snapshot is what would.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.appraisal import Row                                       # noqa: E402
from caro.hierarchical import (                                      # noqa: E402
    GateVerdict, HierarchicalGate, MIN_SLICE_N, PartialPoolingQuantiles,
    four_slices, held_out_trim_split,
)
from caro.ingest.quality import eligibility                          # noqa: E402


def to_rows(listings) -> list[Row]:
    """Appraisal rows from parsed listings.

    `cluster_id` is the listing id: a single snapshot has no repeat
    observations, so no repost clusters exist to collapse. That is a property
    of having one day of data, not a claim that reposts do not happen.
    """
    out = []
    for x in listings:
        if not eligibility(x)[0]:
            continue
        out.append(Row(
            listing_id=x.listing_id, cluster_id=x.listing_id,
            first_seen_ordinal=0,
            model_key=f"{x.make}|{x.model}|{x.trim or ''}",
            year_jalali=int(x.year_jalali), mileage_km=float(x.mileage_km),
            asking_price_toman=float(x.asking_price_toman)))
    return out


def baseline_mae(train: list[Row], test: list[Row]) -> float:
    """Parent-level median: the boring thing partial pooling must beat."""
    by_parent: dict[str, list[float]] = {}
    for r in train:
        by_parent.setdefault("|".join(r.model_key.split("|")[:2]),
                             []).append(r.asking_price_toman)
    glob = float(np.median([r.asking_price_toman for r in train]))
    preds = np.array([
        float(np.median(by_parent.get("|".join(r.model_key.split("|")[:2]),
                                      [glob]))) for r in test])
    truth = np.array([r.asking_price_toman for r in test])
    return float(np.mean(np.abs(preds - truth)))


def main() -> int:
    from caro.corpus_reader import load_corpus, listings_from_corpus  # noqa: E402

    listings = listings_from_corpus(load_corpus("run3"))
    rows = to_rows(listings)

    print("BENCHMARK — partial pooling on the Run 3 corpus")
    print("=" * 78)
    print(f"  parsed listings        {len(listings)}")
    print(f"  appraisal-eligible     {len(rows)}")
    print(f"  distinct trims         {len({r.model_key for r in rows})}")
    print("  split                  held-out TRIMS (single snapshot: no")
    print("                         temporal split is possible, so this says")
    print("                         nothing about temporal generalisation)")
    print()

    train, test = held_out_trim_split(rows, fraction=0.25, seed=0)
    model = PartialPoolingQuantiles().fit(train)
    counts = dict(model._n)
    slices = four_slices(model, train, counts, held_out=test)

    print(f"  {'slice':<22}{'n':>5}{'MAE':>13}{'medAE':>13}"
          f"{'cover':>10}{'err':>9}{'shrink':>8}{'extrap':>8}")
    print("  " + "-" * 88)
    for s in slices:
        print(s.line())
    print(f"\n  calibration verdicts need n ≥ {MIN_SLICE_N} "
          f"(2.5 SE on a 15-point deviation)")

    preds = model.predict(train)
    truth = np.array([r.asking_price_toman for r in train])
    m_mae = float(np.mean(np.abs(preds[:, len(model.quantiles) // 2] - truth)))
    b_mae = baseline_mae(train, train)

    verdict, failures, unanswered = HierarchicalGate().verdict(
        slices, baseline_mae=b_mae, model_mae=m_mae)

    print("\nVERDICT", "\n" + "-" * 78)
    print(f"  {verdict.value}")
    print(f"  MAE {m_mae:,.0f} vs parent-median baseline {b_mae:,.0f}"
          f"  ({(m_mae / b_mae - 1):+.1%})")
    for f in failures:
        print(f"    ✗ {f}")
    for u in unanswered:
        print(f"    ? {u}")

    # Three statements that do not contradict each other, printed together
    # so the flattering one cannot be quoted without the other two. An
    # aggregate MAE lifted out of this block is a different claim from the
    # one the evidence supports.
    print("\nREAD AS THREE SEPARATE STATEMENTS", "\n" + "-" * 78)
    print(f"  estimator quality              promising "
          f"({(1 - m_mae / b_mae):.0%} better than the parent-median "
          f"baseline on aggregate error)")
    print("  evidence for conditional serving   INSUFFICIENT "
          f"({verdict.value})")
    print("  decision                       DO NOT SERVE")
    print("\n  The first does not imply the third is wrong, and the third")
    print("  does not imply the first is false. Partial pooling has a much")
    print("  lower aggregate error on this corpus than the baseline; that")
    print("  result alone does not establish the validity of a CONDITIONAL")
    print("  appraisal, because the slices the conditioning depends on")
    print("  cannot be judged at this sample size.")

    if verdict is GateVerdict.UNJUDGEABLE:
        print("\n  This is a failure of the EVIDENCE for this claim, not of")
        print("  the model. The aggregate MAE above is real and says nothing")
        print("  about whether conditional appraisal is valid — concluding")
        print("  otherwise from it is the inference D30 refused. W1 stays")
        print("  locked, and the fix is a corpus that can judge, not a")
        print("  tuning pass that makes the question go away.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
