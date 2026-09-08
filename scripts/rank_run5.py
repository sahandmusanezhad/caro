#!/usr/bin/env python3
"""The decision path, on real Bama listings. An audit, not an experiment.

    python3 scripts/rank_run5.py

Five live runs, two pre-registered benchmarks and a confidence interval have
all been spent on the *estimator*. The thesis says the product is a decision
engine and the estimate is one input to it. So the obvious question has never
been asked: what does the retrieval → relaxation → ranking → refusal path
actually do when it is pointed at the 403 listings Run 5 collected?

**This produces no verdict.** `winrate_vs_price_sort` needs a `utility_fn`
giving what the buyer really gains, and on real data that function does not
exist — the honest substitute is a blind human panel, which is a person, not
a script. Nothing here may be quoted as "CARO's ranking beats price-sort on
real data". What it can establish is narrower and still worth having: which
parts of the decision path are *alive* on real data, and which are computing
a constant.

Nothing is fitted, tuned, or gated here. No frozen constant is touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.appraisal import (                                       # noqa: E402
    ComparableQuantiles, GlobalQuantiles, MarketEstimator, NotBenchmarked,
    Split, run_benchmark,
)
from caro.hierarchical import held_out_trim_split                  # noqa: E402
from caro.ranking import (                                         # noqa: E402
    RankingPipeline, Ranker, RuleIntentParser, retrieve,
)

HOLDOUT_FRACTION = 0.25
SPLIT_SEED = 0

# The six terms `Ranker.score` combines, and where each reads its input.
TERMS = [
    ("value",        "estimate − asking − priced damage"),
    ("risk",         'features["risk"]'),
    ("running_cost", 'features["ownership_risk"]'),
    ("liquidity",    'features["liquidity"]'),
    ("mileage",      "Row.mileage_km"),
    ("recency",      "Row.first_seen_ordinal"),
]

QUERIES = [
    "یه ۲۰۶ تا ۲ میلیارد میخوام",
    "ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۵ میلیارد",
    "پراید کم‌کارکرد تا ۸۰۰ میلیون",
    "پژو ۴۰۵ مدل ۹۶ به بالا تا ۱.۲ میلیارد",
    "یه ماشین خوب حدود ۱.۲ میلیارد",
    "کوییک تا ۱.۱ میلیارد، تصادفی نباشه",
]


def term_liveness(rows) -> list[tuple[str, str, int, str]]:
    """Which ranking terms vary across this corpus, and which are constant.

    A term whose input is identical on every row contributes an identical
    amount to every score. It is not weak, it is absent: no weight the user
    moves can make it matter.
    """
    out = []
    for name, source in TERMS:
        if name == "value":
            vals = np.array([r.asking_price_toman for r in rows], float)
        elif name == "mileage":
            vals = np.array([r.mileage_km for r in rows], float)
        elif name == "recency":
            vals = np.array([float(r.first_seen_ordinal) for r in rows])
        else:
            key = {"risk": "risk", "running_cost": "ownership_risk",
                   "liquidity": "liquidity"}[name]
            vals = np.array([r.features.get(key, np.nan) for r in rows], float)
        present = int(np.count_nonzero(~np.isnan(vals)))
        distinct = len(np.unique(vals[~np.isnan(vals)]))
        state = "LIVE" if distinct > 1 else "CONSTANT"
        out.append((name, source, present, f"{state} ({distinct} distinct)"))
    return out


def main() -> int:
    from scripts.benchmark_run5 import load                        # noqa: E402
    _, listings, rows, _ = load()

    print("THE DECISION PATH ON REAL DATA — audit, no verdict")
    print("=" * 78)
    print(f"  corpus                 Run 5, {len(listings)} parsed listings, "
          f"{len(rows)} appraisal-eligible")

    print("\n1. WHICH RANKING TERMS ARE ALIVE HERE")
    print("-" * 78)
    live = term_liveness(rows)
    for name, source, present, state in live:
        print(f"  {name:<14} {source:<38} {present:>4}/{len(rows)}  {state}")
    dead = [n for n, _, _, s in live if s.startswith("CONSTANT")]
    print(f"\n  {len(live) - len(dead)} of {len(live)} terms vary on this "
          f"corpus. Constant: {', '.join(dead) if dead else 'none'}.")
    if dead:
        print("  A constant term cannot change an ordering, and the weight")
        print("  slider over it does nothing. This is an INGEST gap, not a")
        print("  ranking one: W4 never populates these fields from Bama.")

    print("\n2. CAN THE RANKER EVEN RUN? (it needs a gated estimator)")
    print("-" * 78)
    train, test = held_out_trim_split(rows, fraction=HOLDOUT_FRACTION,
                                      seed=SPLIT_SEED)
    split = Split(train=train, test=test, dropped_straddling=0,
                  cutoff_ordinal=0)
    base = {"global-quantiles": run_benchmark(GlobalQuantiles(), split,
                                              name="global-quantiles")}
    est = MarketEstimator(ComparableQuantiles())
    ok, why = est.benchmark(split, base, name="comparable-quantiles")
    print(f"  candidate              comparable-quantiles (the baseline "
          f"class D12 ships if the model loses)")
    print(f"  gate                   {'APPROVED' if ok else 'REFUSED'}")
    for w in why:
        print(f"    · {w}")

    print("\n3. RETRIEVAL AND THE RELAXATION LADDER")
    print("-" * 78)
    parser = RuleIntentParser()
    pipe = RankingPipeline(parser, Ranker(est))
    for q in QUERIES:
        spec = parser.parse(q)
        cands, _, rep = retrieve(rows, spec)
        budget = (f"{spec.budget_max_toman:,}" if spec.budget_max_toman
                  else "—")
        print(f"\n  «{q}»")
        print(f"    parsed → budget≤{budget}  "
              f"models={'/'.join(spec.model_hints) or '—'}  "
              f"unparsed={len(spec.unparsed)}")
        print(f"    candidates {len(cands):>3}   relaxed={rep.relaxed}"
              f"   {rep.text_fa() or '(no relaxation needed)'}")
        if not ok:
            print("    shortlist  — refused: estimator is not gated")
            continue
        try:
            sl = pipe.run(q, rows, k=3)
        except NotBenchmarked as exc:
            print(f"    shortlist  — refused: {str(exc)[:60]}")
            continue
        if not sl.items:
            print("    shortlist  — empty (no candidate survived)")
            continue
        for s in sl.items:
            r = s.row
            print(f"      {r.model_key:<34} {r.year_jalali}  "
                  f"{r.mileage_km:>9,.0f}km  {r.asking_price_toman:>15,.0f}")

    print("\n4. WHAT THIS DOES NOT SETTLE")
    print("-" * 78)
    print("  No win-rate is printed. `winrate_vs_price_sort` needs ground")
    print("  truth about what the buyer gains, which exists on the synthetic")
    print("  corpus (the generating process) and nowhere in Bama's HTML. The")
    print("  only honest substitute is a blind panel over shuffled unlabelled")
    print("  shortlists, and it has not been run. Until it is, 'CARO's")
    print("  ranking beats sorting by price' is a claim measured on data the")
    print("  project generated for itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
