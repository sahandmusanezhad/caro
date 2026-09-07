#!/usr/bin/env python3
"""What Run 5 has to collect, computed from Run 3 rather than estimated.

    python3 scripts/run5_target.py

D34 returned UNJUDGEABLE_SLICE: the estimator was measured and the corpus
could not judge two of the three slices. This script answers the only
question that follows — how much more of the same corpus makes those slices
judgeable — and it answers it by arithmetic on the frozen Run 3 snapshot, so
the number in RUN5_SPEC.md is reproducible and moves only if the corpus or
the frozen split moves.

The point of computing it rather than picking it: a target chosen by feel
can be quietly revised downward when collection gets tedious, and nobody
will notice, because there is nothing to check it against. A target derived
from a stated model has to be argued with.

THE FINDING THIS SCRIPT EXISTS TO HAVE PRODUCED ON PAPER
--------------------------------------------------------
The obvious plan — "collect more of what Run 3 collected" — cannot work, and
the reason is structural rather than a matter of degree.

    thin slice     rows in trims with FEWER than 5 listings
    coverage       share of rows in trims with 5 OR MORE (D30 wants ≥70%)

They are complements. Deepening the trims we already have, which is exactly
what D31 chose in order to raise coverage, moves trims out of the thin slice
— push it far enough and the thin slice is EMPTY and permanently
unjudgeable. Broadening into new trims fills the thin slice and drives
coverage down, which is the precondition D30 already failed on at 55%.

So the two frozen gates pull in opposite directions on acquisition strategy,
and neither pure strategy satisfies both. A mixed corpus does, and it has a
minimum size that can be computed:

    thin ≥ 58 with coverage ≥ 70%   ⇒   at least 58 / 0.30 ≈ 194 eligible

That number is the whole reason for pre-registering. Discovered halfway
through collection, it would arrive as pressure to relax 5, or 70%, or 58 —
each of which makes the shortfall disappear without answering anything, and
each of which D30/D32/D34 refused for reasons that have not changed.

The three strategies are all reported below so the tension is visible rather
than asserted.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.hierarchical import (                                    # noqa: E402
    MIN_SLICE_N, held_out_trim_split, thin_trim_rows,
)
from caro.ingest.quality import MIN_PER_TRIM_FLOOR                 # noqa: E402

HOLDOUT_FRACTION = 0.25      # frozen: the value D34 ran at
SPLIT_SEED = 0               # frozen: the seed D34 ran at

# The registered hard cap, from RUN5_SPEC.md §1. It is a REGISTERED NUMBER,
# not a computed one, and the difference matters: a cap the script produces
# moves whenever the script does, and a budget that quietly grows with its
# own derivation is not a budget. The derivation below is checked against
# this constant, never used to replace it. If the check fails, the spec needs
# an explicit amendment — which under §4 ends the run rather than adjusting
# it.
REGISTERED_BUDGET = 576

# Run 3, measured. Detail pages fetched -> rows that parsed -> rows W1 can
# use. Every conversion below comes from these two numbers, not from a guess
# about what a good crawler achieves.
RUN3_DETAIL_FETCHED = 221


def load_run3():
    from scripts.replay_run3 import rebuild                        # noqa: E402
    from caro.ingest.bama import ParseTrace, parse_detail_page     # noqa: E402
    from caro.appraisal import Row                                 # noqa: E402
    from caro.ingest.quality import eligibility                    # noqa: E402

    snap = ROOT / "data" / "snapshots" / "run3" / "listings.json"
    rows, parsed = [], 0
    for rec in json.loads(snap.read_text(encoding="utf-8")):
        url, page = rebuild(rec)
        got = parse_detail_page(url, page, trace=ParseTrace())
        if got is None:
            continue
        parsed += 1
        if not eligibility(got)[0]:
            continue
        rows.append(Row(
            listing_id=got.listing_id, cluster_id=got.listing_id,
            first_seen_ordinal=0,
            model_key=f"{got.make}|{got.model}|{got.trim or ''}",
            year_jalali=int(got.year_jalali),
            mileage_km=float(got.mileage_km),
            asking_price_toman=float(got.asking_price_toman)))
    return rows, parsed


def measure(counts: list[int]) -> dict:
    """Every number the two gates care about, for a trim-size profile.

    Works on counts alone, so a hypothetical corpus can be measured without
    inventing listings to fill it. All three follow the frozen definitions:
    thin is trims at or below THIN_TRIM_MAX, held-out is 25% of trims under
    the frozen seed, coverage is D30's share in trims of MIN_PER_TRIM_FLOOR
    or more.
    """
    rng = np.random.default_rng(SPLIT_SEED)
    idx = np.arange(len(counts))
    rng.shuffle(idx)
    n_out = max(1, int(len(counts) * HOLDOUT_FRACTION))
    held = set(idx[:n_out].tolist())
    train = [c for i, c in enumerate(counts) if i not in held]
    total = sum(counts)
    return dict(
        eligible=total,
        trims=len(counts),
        thin=sum(c for c in train if c < MIN_PER_TRIM_FLOOR),
        held_out=sum(counts[i] for i in held),
        coverage=(sum(c for c in counts if c >= MIN_PER_TRIM_FLOOR) / total
                  if total else 0.0),
    )


def judgeable(m: dict) -> bool:
    return m["thin"] >= MIN_SLICE_N and m["held_out"] >= MIN_SLICE_N


def search(counts: list[int], mode: str) -> dict | None:
    """Smallest corpus of this shape where both slices become judgeable.

    Searched, not solved. The held-out slice is a step function of which
    trims the frozen shuffle picks, so a closed form would only look more
    authoritative than it is.
    """
    base = sorted(counts)
    for step in range(1, 6001):
        k = 1 + step * 0.01
        if mode == "deepen":
            prof = [max(1, int(round(c * k))) for c in base]
        elif mode == "broaden":
            reps = int(round(len(base) * k))
            prof = [base[i % len(base)] for i in range(reps)]
        else:                                     # mixed
            # Deepen every trim to just clear the floor, then add thin trims
            # until the thin slice is large enough. This is the only shape
            # that can satisfy both gates, and it is what the spec asks the
            # collector to build.
            thick = [max(MIN_PER_TRIM_FLOOR, c) for c in base]
            extra = int(round(len(base) * (k - 1)))
            prof = thick + [MIN_PER_TRIM_FLOOR - 1] * extra
        m = measure(prof)
        if judgeable(m) and (mode != "mixed" or m["coverage"] >= 0.70):
            m["k"] = k
            return m
    return None


def main() -> int:
    rows, parsed = load_run3()
    counts = list(Counter(r.model_key for r in rows).values())

    train, test = held_out_trim_split(rows, fraction=HOLDOUT_FRACTION,
                                      seed=SPLIT_SEED)
    n_thin = len(thin_trim_rows(train, Counter(r.model_key for r in train)))

    print("RUN 5 TARGET — derived from the Run 3 snapshot")
    print("=" * 74)
    print(f"  detail pages fetched      {RUN3_DETAIL_FETCHED}")
    print(f"  parsed                    {parsed}"
          f"   ({parsed / RUN3_DETAIL_FETCHED:.0%} of fetched)")
    print(f"  appraisal-eligible        {len(rows)}"
          f"   ({len(rows) / RUN3_DETAIL_FETCHED:.0%} of fetched)")
    print(f"  distinct trims            {len(counts)}")
    print(f"  median listings per trim  {int(np.median(counts))}")
    print()
    print(f"  {'slice':<22}{'now':>6}{'needed':>9}{'short by':>10}")
    print("  " + "-" * 47)
    print(f"  {'thin trim':<22}{n_thin:>6}{MIN_SLICE_N:>9}"
          f"{max(0, MIN_SLICE_N - n_thin):>10}")
    print(f"  {'held-out trim':<22}{len(test):>6}{MIN_SLICE_N:>9}"
          f"{max(0, MIN_SLICE_N - len(test)):>10}")
    print("\n  Read as two shortfalls this says 'collect ~2x more'. That is")
    print("  the wrong reading, and the table below is why: the two slices")
    print("  respond to opposite things, so no single multiplier reaches "
          "both.")

    now = measure(counts)
    print(f"  conditional coverage      {now['coverage']:.0%}"
          f"   (D30 wants 70%)")

    print("\nWHAT EACH ACQUISITION STRATEGY WOULD PRODUCE", "\n" + "-" * 74)
    print(f"  {'strategy':<10}{'eligible':>9}{'trims':>7}{'thin':>7}"
          f"{'held':>7}{'cover':>8}   verdict")
    print("  " + "-" * 72)
    results = {}
    for mode, blurb in (
            ("deepen", "more listings in the trims we already have (D31)"),
            ("broaden", "new trims, same size distribution as now"),
            ("mixed", "every trim over the floor, PLUS enough thin trims")):
        m = search(counts, mode)
        results[mode] = m
        if m is None:
            print(f"  {mode:<10}{'—':>9}{'—':>7}{'—':>7}{'—':>7}{'—':>8}"
                  f"   UNREACHABLE")
        else:
            print(f"  {mode:<10}{m['eligible']:>9}{m['trims']:>7}"
                  f"{m['thin']:>7}{m['held_out']:>7}{m['coverage']:>7.0%}"
                  f"   {'ok' if m['coverage'] >= 0.70 else 'fails D30'}")
        print(f"             {blurb}")

    if results["deepen"] is None:
        print("\n  'deepen' is UNREACHABLE and that is the finding, not a bug.")
        print("  The thin slice is trims with FEWER than 5 listings. Deepening")
        print("  moves trims out of it, so past a point the slice is empty and")
        print("  can never reach 58. D31's strategy raises coverage and")
        print("  destroys the thin-slice benchmark at the same time.")

    plan = results["mixed"]
    if plan is None:
        print("\n  No strategy satisfies both gates. Report and stop.")
        return 1

    target = plan["eligible"]
    print(f"\n  TARGET  {target} eligible listings, shaped: "
          f"{plan['trims']} trims, at least {MIN_PER_TRIM_FLOOR} listings in")
    print(f"          each of the well-observed ones, and enough trims left")
    print(f"          under the floor to put {plan['thin']} listings in the "
          f"thin slice.")
    print("\n  The SHAPE is the requirement. A corpus of this size collected")
    print("  the obvious way — deepest models first — satisfies neither gate,")
    print("  and the count on its own would look like success.")

    rate = len(rows) / RUN3_DETAIL_FETCHED
    fetches = int(np.ceil(target / rate))
    cat = int(fetches / 8) + 1
    print("\nREQUEST ENVELOPE", "\n" + "-" * 74)
    print(f"  eligible per detail page fetched   {rate:.3f}"
          f"   (measured in Run 3, not assumed)")
    print(f"  detail fetches for {target} eligible      {fetches}")
    print(f"  + trim pages to find them           ~{cat}"
          f"   (Run 3 saw ~8-10 listings per trim page)")
    print("  + 15% for duplicates and dead slugs")
    derived = int((fetches + cat) * 1.15)
    print(f"  derivation lands at                 {derived}")
    print(f"\n  BUDGET  {REGISTERED_BUDGET} requests, hard cap — REGISTERED "
          f"in RUN5_SPEC.md §1,\n          not recomputed here. Run 3 spent "
          f"~314.")

    ok = derived <= REGISTERED_BUDGET
    print(f"\n  {'✓' if ok else '✗'} the derivation still fits the registered "
          f"cap ({derived} ≤ {REGISTERED_BUDGET})")
    if not ok:
        print("\n  It does not. That is not a licence to raise the cap: under")
        print("  §4 a changed constant ENDS Run 5 rather than amending it, so")
        print("  this needs an explicit new registration, argued on its own.")
        print("  A budget that grows with its own derivation is not a budget.")

    print("\n  The cap is a ceiling, not a plan to spend it. The stopping rule")
    print("  is on the corpus (§3), not the budget; the budget only bounds")
    print("  what a bug can cost.")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
