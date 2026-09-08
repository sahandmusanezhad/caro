#!/usr/bin/env python3
"""Export the DECISION half of the demo: shortlist, weights, relaxation, ledger.

    python3 demo/export_ranking.py        # writes demo/ranking_data.json

`export_demo.py` covers W2 — one listing, appraised, with its evidence. This
covers W3, which is what the product thesis actually claims to be: a Persian
sentence in, a defensible ranked decision out.

Two panels, and the split is the honest part.

    SYNTHETIC   the full path — shortlist, per-term breakdown, a weight moved
                and the order changing, the relaxation ladder. It runs here
                because the estimator clears the gate on a corpus this project
                generated, where the true prices are known.

    REAL        Run 3's 221 Bama listings. No shortlist: no estimator clears
                the gate on any real corpus (D43), so `Ranker.score` raises.
                What IS real is the decision ledger — which inputs each
                candidate actually had, observed / imputed / absent.

Nothing is hand-written. Every number is whatever the pipeline produced.
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ranking import (                                         # noqa: E402
    LEDGER_INPUTS, CONDITION_RISK, RankingPipeline, Ranker, RuleIntentParser,
    Weights, decision_ledger, retrieve,
)

QUERIES = [
    "ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۵ میلیارد",
    "ماشین برای اسنپ، کم‌مصرف، قطعاتش ارزون باشه، زیر ۸۰۰ میلیون",
]
TIGHT = "پراید بدون رنگ، مدل ۱۴۰۱ به بالا، کارکرد زیر ۲۰ هزار، تا ۵۰۰ میلیون"


def card(s, rank: int) -> dict:
    r = s.row
    return {
        "rank": rank,
        "id": r.listing_id,
        "model": r.model_key,
        "year": r.year_jalali,
        "km": r.mileage_km,
        "asking": r.asking_price_toman,
        "role": s.breakdown.get("_role", ""),
        "estimate": s.conservative_estimate_toman,
        "opportunity": s.adjusted_opportunity_toman,
        "damage": s.expected_damage_toman,
        "score": s.score,
        "terms": {k: v for k, v in s.breakdown.items() if not k.startswith("_")},
    }


def shortlist_for(pipe, pool, query: str, weights: Weights | None = None,
                  k: int = 3) -> dict:
    spec = pipe.parser.parse(query)
    if weights is not None:
        spec = spec.with_weights(weights)
    cands, used, rep = retrieve(pool, spec)
    scored = pipe.ranker.score(cands, used)
    from caro.ranking import diversify
    items = diversify(scored, k=k)
    return {
        "query": query,
        "intent": {
            "budget_max": spec.budget_max_toman,
            "budget_hard": spec.budget_hard,
            "models": list(spec.model_hints),
            "year_min": spec.year_min,
            "max_km": spec.max_mileage_km,
            "use_case": spec.use_case,
            "deal_breakers": list(spec.deal_breakers),
            "risk_profile": spec.risk_profile,
            "assumptions": list(spec.assumptions),
            "unparsed": list(spec.unparsed),
            "weights": {
                "value": spec.weights.normalized().value,
                "risk": spec.weights.normalized().risk,
                "running_cost": spec.weights.normalized().running_cost,
                "liquidity": spec.weights.normalized().liquidity,
                "mileage": spec.weights.normalized().mileage,
                "recency": spec.weights.normalized().recency,
            },
        },
        "considered": len(pool),
        "candidates": len(cands),
        "relaxed": rep.relaxed,
        "relaxation_fa": rep.text_fa(),
        "items": [card(s, i + 1) for i, s in enumerate(items)],
    }


def synthetic_panel() -> dict:
    # Importing the test module builds the corpus and gates the estimator —
    # and prints its own check lines, which must not land in the JSON.
    import contextlib
    import io
    with contextlib.redirect_stdout(io.StringIO()):
        import tests.test_ranking as T
    pipe, pool = T.PIPE, T.POOL

    base = shortlist_for(pipe, pool, QUERIES[0])
    # The same query with reliability turned up. Nothing else changes.
    heavy = shortlist_for(pipe, pool, QUERIES[0],
                          weights=Weights(value=0.10, risk=0.65,
                                          running_cost=0.05, liquidity=0.05,
                                          mileage=0.10, recency=0.05))
    return {
        "corpus": {"rows": len(T.ROWS), "pool": len(pool),
                   "estimator": "log-linear-ridge", "gated": bool(T.OK)},
        "shortlist": base,
        "reweighted": heavy,
        "second": shortlist_for(pipe, pool, QUERIES[1]),
        "refusal": shortlist_for(pipe, pool, TIGHT),
    }


def real_panel() -> dict:
    from scripts.rank_run3 import load, QUERY                      # noqa: E402
    listings, rows = load()
    parser = RuleIntentParser()
    spec = parser.parse(QUERY)
    cands, _, rep = retrieve(rows, spec)
    no_db, _, _ = retrieve(rows, replace(spec, deal_breakers=()))
    ledger = decision_ledger(cands, spec, estimator=None)

    present = Counter()
    for lr in ledger:
        for key in lr.values:
            present[key] += 1
    n = len(ledger) or 1
    return {
        "corpus": {"parsed": len(listings), "eligible": len(rows),
                   "source": "Bama, Run 3, collected 2026-09-07"},
        "condition": dict(Counter(l.body_condition for l in listings)),
        "condition_risk": CONDITION_RISK,
        "query": QUERY,
        "candidates": len(cands),
        "excluded_by_deal_breaker": len(no_db) - len(cands),
        "shortlist_refused": "no estimator clears the acceptance gate on any "
                             "real corpus, so Ranker.score raises NotBenchmarked",
        "inputs": [
            {"name": name, "what": what, "present": present.get(name, 0),
             "of": n}
            for name, what in LEDGER_INPUTS if name != "data_completeness"
        ],
        "completeness": sum(l.completeness for l in ledger) / n,
        "observed_completeness": sum(l.observed_completeness for l in ledger) / n,
        "imputed_rows": sum(1 for l in ledger if l.imputed),
        "missing": ledger[0].missing if ledger else {},
        "imputed_reason": (next((l for l in ledger if l.imputed), None)
                           or ledger[0]).imputed if ledger else {},
    }


def main() -> int:
    out = {"synthetic": synthetic_panel(), "real": real_panel()}
    dest = ROOT / "demo" / "ranking_data.json"
    dest.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(f"wrote {dest} ({dest.stat().st_size:,} bytes)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
