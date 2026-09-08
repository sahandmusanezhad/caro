#!/usr/bin/env python3
"""The decision path on Run 3's corpus — the one that kept body condition.

    python3 scripts/rank_run3.py

`scripts/rank_run5.py` reported 38% mean ledger completeness and named the
cause: four of six scoring terms have no input on Run 5's rows. D45 found that
the cause is narrower than "Bama does not publish it" — Run 3 recorded body
condition on 214 of 221 listings and Run 5's extractor lost it.

So this runs the same audit against the corpus that still has it, and the
comparison is the point: the difference between the two numbers is what one
lost field costs the decision layer.

Same rules as `rank_run5.py`. No verdict, no win-rate, no ground truth. The
risk input comes from `CONDITION_RISK`, a published band table calibrated by
judgement and not fitted to anything — see the note above it in `caro/ranking`.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.appraisal import Row                                     # noqa: E402
from caro.ingest.bama import ParseTrace, parse_detail_page         # noqa: E402
from caro.ingest.quality import eligibility                        # noqa: E402
from caro.ranking import (                                         # noqa: E402
    LEDGER_INPUTS, IntentSpec, RuleIntentParser, decision_ledger,
    features_from_listing, retrieve,
)

SNAP = ROOT / "data" / "snapshots" / "run3"
QUERY = "ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۵ میلیارد"


def load():
    from scripts.replay_run3 import rebuild                        # noqa: E402
    recs = json.loads((SNAP / "listings.json").read_text(encoding="utf-8"))
    listings, rows = [], []
    for rec in recs:
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
            asking_price_toman=float(got.asking_price_toman),
            features=features_from_listing(got)))
    return listings, rows


def main() -> int:
    listings, rows = load()
    print("THE DECISION PATH ON RUN 3 — the corpus that kept condition")
    print("=" * 78)
    print(f"  corpus                 {len(listings)} parsed, "
          f"{len(rows)} appraisal-eligible")

    cond = Counter(l.body_condition for l in listings)
    print(f"\n  body condition, as Bama printed it:")
    for k, v in cond.most_common():
        print(f"    {k:<16} {v:>4}")

    print("\nTHE RISK INPUT, NOW THAT IT EXISTS")
    print("-" * 78)
    with_risk = sum(1 for r in rows if "risk" in r.features)
    vals = sorted({r.features["risk"] for r in rows if "risk" in r.features})
    print(f"  rows carrying a risk value   {with_risk}/{len(rows)}")
    print(f"  distinct values              {len(vals)}   {vals}")
    print("  A term with six distinct values can change an ordering. On Run 5")
    print("  this column had none, so the slider over it moved nothing.")

    parser = RuleIntentParser()
    spec = parser.parse(QUERY)
    cands, _, rep = retrieve(rows, spec)
    from dataclasses import replace as _replace
    no_db, _, _ = retrieve(rows, _replace(spec, deal_breakers=()))
    n_acc = sum(1 for r in rows if r.features.get("has_accident", 0) > 0.5)
    n_over = sum(1 for r in rows
                 if spec.budget_max_toman
                 and r.asking_price_toman > spec.budget_max_toman)
    print(f"\n  «{QUERY}»")
    print(f"    eligible rows      {len(rows)}")
    print(f"    over budget        {n_over}")
    print(f"    has_accident       {n_acc}")
    print(f"    candidates         {len(cands)}   relaxed={rep.relaxed}")
    print(f"    same, no deal-breaker  {len(no_db)}")
    print(f"    → the deal-breaker excluded {len(no_db) - len(cands)} car(s). "
          f"On Run 5 it excluded 0, because has_accident was never set —")
    print(f"      a deal-breaker with no input does not fail loudly, it just "
          f"never fires.")

    print("\nTHE DECISION LEDGER")
    print("-" * 78)
    ledger = decision_ledger(cands, spec, estimator=None)
    present = Counter()
    for lr in ledger:
        for k in lr.values:
            present[k] += 1
    n = len(ledger) or 1
    for name, what in LEDGER_INPUTS:
        if name == "data_completeness":
            continue
        c = present.get(name, 0)
        mark = "present" if c == n else ("absent " if c == 0 else "partial")
        print(f"    {name:<26} {mark}  {c:>3}/{n}   {what}")
    comp = sum(l.completeness for l in ledger) / n
    print(f"\n  mean completeness  {comp:.0%}   (Run 5, same query: 38%)")
    print("\n  The gap between those two numbers is what one lost field costs")
    print("  the decision layer — D45. It is not a claim that the ranking is")
    print("  better here; a fed term is not a correct term.")

    print("\nSTILL MISSING, AND WHY")
    print("-" * 78)
    if ledger:
        for k, v in ledger[0].missing.items():
            print(f"    {k}\n      → {v}")
    print("\n  ownership_risk and liquidity stay absent on purpose. No")
    print("  observation in this repository supports either, and inventing a")
    print("  plausible constant from make or model would turn a missing input")
    print("  into a fake one — which the ledger could not then report.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
