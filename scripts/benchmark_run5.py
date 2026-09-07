#!/usr/bin/env python3
"""Run 5 v2 — the frozen estimator and the frozen gate, on the new corpus.

    python3 scripts/benchmark_run5.py

Nothing here is new except the data. The estimator, the gate, MIN_SLICE_N,
MIN_PER_TRIM_FLOOR, THIN_TRIM_MAX, the hold-out fraction and the seed are all
the ones D34 ran with, and RUN5_SPEC.md §4 says changing any of them ends the
run rather than amending it. This script imports them; it does not restate
them, so it cannot drift from what W1 actually uses.

Every slice count is printed with the POPULATION it was computed on, per
§5 and §11. "thin = 60" on its own is a different number with the same name:
thin is measured inside the TRAINING set after the trim-level split, while
conditional coverage is measured over the whole eligible corpus. They are
complements over different populations by design (D37), and a report that
lets them be read as the same thing is not reporting the experiment.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.appraisal import Row                                     # noqa: E402
from caro.hierarchical import (                                    # noqa: E402
    GateVerdict, HierarchicalGate, MIN_SLICE_N, PartialPoolingQuantiles,
    four_slices, held_out_trim_split, thin_trim_rows,
)
from caro.ingest.quality import MIN_PER_TRIM_FLOOR, eligibility    # noqa: E402
from caro.ingest.stratification import conditional_scope           # noqa: E402

HOLDOUT_FRACTION = 0.25      # frozen, D34
SPLIT_SEED = 0               # frozen, D34
SNAP = ROOT / "data" / "snapshots" / "run5"


def load():
    from scripts.replay_run3 import rebuild                        # noqa: E402
    from caro.ingest.bama import ParseTrace, parse_detail_page     # noqa: E402
    recs = json.loads((SNAP / "listings.json").read_text(encoding="utf-8"))
    arms = (SNAP / "arms.txt").read_text(encoding="utf-8").strip()
    listings, rows, kept_arms = [], [], []
    for rec, arm in zip(recs, arms):
        url, page = rebuild(rec)
        got = parse_detail_page(url, page, trace=ParseTrace())
        if got is None:
            continue
        listings.append(got)
        if not eligibility(got)[0]:
            continue
        rows.append(Row(
            listing_id=got.listing_id, cluster_id=got.listing_id,
            first_seen_ordinal=0,
            model_key=f"{got.make}|{got.model}|{got.trim or ''}",
            year_jalali=int(got.year_jalali),
            mileage_km=float(got.mileage_km),
            asking_price_toman=float(got.asking_price_toman)))
        kept_arms.append(arm)
    return recs, listings, rows, kept_arms


def baseline_mae(train, test) -> float:
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
    recs, listings, rows, arms = load()
    print("RUN 5 v2 BENCHMARK — frozen estimator, frozen gate, new corpus")
    print("=" * 78)
    print(f"  listings collected     {len(recs)}")
    print(f"  parsed                 {len(listings)}")
    print(f"  appraisal-eligible     {len(rows)}"
          f"   ({len(rows) / len(recs):.1%} of collected)")
    print(f"  distinct trims         {len({r.model_key for r in rows})}")
    print(f"  thin-arm / thick-arm   {arms.count('t')} / {arms.count('k')}"
          f"   (eligible only)")

    # conditional_scope reads CarListings, not appraisal Rows — it asks a
    # question about the corpus, not about the design matrix.
    scope = conditional_scope(listings)
    print(f"\n  conditional coverage   {scope.covered_share:.0%}"
          f"   population: WHOLE eligible corpus, trims with "
          f"{MIN_PER_TRIM_FLOOR}+ (D30 wants 70%)")

    train, test = held_out_trim_split(rows, fraction=HOLDOUT_FRACTION,
                                      seed=SPLIT_SEED)
    counts = Counter(r.model_key for r in train)
    thin = thin_trim_rows(train, counts)
    print(f"  thin slice             {len(thin)}"
          f"   population: TRAINING trims only, at or below THIN_TRIM_MAX")
    print(f"  held-out slice         {len(test)}"
          f"   population: the held-out trims")
    print(f"  both need              {MIN_SLICE_N}"
          f"   to support a calibration verdict at 2.5 SE")

    model = PartialPoolingQuantiles().fit(train)
    slices = four_slices(model, train, dict(model._n), held_out=test)

    print(f"\n  {'slice':<22}{'n':>5}{'MAE':>13}{'medAE':>13}"
          f"{'cover':>10}{'err':>9}{'shrink':>8}{'extrap':>8}")
    print("  " + "-" * 88)
    for s in slices:
        print(s.line())

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

    # The registered wording, §12. Not composed after seeing the result.
    print("\nREGISTERED WORDING (RUN5_SPEC.md §12)", "\n" + "-" * 78)
    if verdict is GateVerdict.ACCEPTED:
        print("  On the frozen Bama benchmark, the estimator passed the")
        print("  pre-registered acceptance gate for the tested conditional")
        print("  scope.")
    elif verdict is GateVerdict.REJECTED:
        print("  The frozen benchmark rejected the estimator for the tested")
        print("  conditional scope.")
    else:
        print("  The available corpus could not judge the required")
        print("  calibration slices.")
        for u in unanswered:
            print(f"    · {u}")
    print("\n  None of these is a claim about Iranian used-car prices. One")
    print("  snapshot, one source, one frozen scope. PASS would not license")
    print("  serving either — D30's preconditions sit above this gate.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
