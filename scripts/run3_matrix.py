#!/usr/bin/env python3
"""
Run 3 — an experiment, not a bigger scrape.

    python3 scripts/run3_matrix.py --plan
    python3 scripts/run3_matrix.py --replay data/snapshots/run3/

Run 2 ended with a specific open question, and it is worth stating precisely
because the sloppy version of it is what makes a methodology attackable.

    Established:  the 2026-09-07 sample is not evidence of a varied market.
                  Saina's eligible listings are 100% `intact` with an
                  asking-price IQR of 3% of the median.

    NOT established: that deeper pagination cannot fix it. Page 4 could
                  perfectly well hold different sellers, conditions and
                  prices. Nobody has fetched it.

So Run 3 varies the *sampling strategy* and holds the *gate* fixed:

                        one target model
                               │
              ┌────────────────┴────────────────┐
        pagination depth                 query variation
      pages 1..N of one query        year bands, condition
              │                      filters, region splits
              └────────────────┬────────────────┘
                               ▼
                  eligibility + degeneracy   (UNCHANGED)
                               ▼
                     ≥30 eligible per model?
                               ▼
                          W1 unlock

The direction of that dependency is the whole design. Thresholds are inputs
to the experiment, never outputs of it — a gate tuned to whatever the run
happened to produce is measuring the run, not the market. If Run 3 fails,
the honest outcome is a failed run, not a lowered bar.

**Do not edit `caro/ingest/coverage.py` or `quality.py` while running this.**
The contract is frozen (docs/DATA_CONTRACT.md). If the new corpus exposes a
genuinely new semantic failure — as Run 2 did with the currency label — that
is a reason to change it *and record why*, which is a different act from
relaxing a threshold to pass.

What each arm answers
---------------------
`depth`      Does more of the same query add variation, or only volume? If
             eligible count rises while the degeneracy findings stay
             identical, that is a clean, publishable negative result: the
             homogeneity is a property of the query.

`variation`  Does a differently-shaped retrieval reach a different part of
             the market? Year bands are the sharpest probe, because year is
             the predictor most obviously collapsed in Run 2's slices.

Both arms are run for every target model. Comparing them is the point;
either alone answers nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest import coverage as cov_mod                        # noqa: E402
from caro.ingest.quality import eligibility                        # noqa: E402

# Chosen from Run 2, on evidence rather than convenience:
#   Tiba   — the healthiest slice (8 eligible, 6 distinct years, no findings)
#   Saina  — the sickest (3% price IQR, 100% one condition)
#   Quik   — mid, and a different manufacturer line
# A matrix run only on the healthy slice would prove nothing about the sick
# one, and the sick one is where the question actually lives.
TARGETS = ("pride", "tiba", "saina", "quick")

ARMS = {
    "depth": {
        "what": "pages 1..4 of the plain model query",
        "tests": "whether volume alone brings variation",
        "urls": lambda slug, n=4: [f"https://bama.ir/car/{slug}"
                                   + ("" if p == 1 else f"?page={p}")
                                   for p in range(1, n + 1)],
    },
    "variation": {
        "what": "the same model sliced by year band",
        "tests": "whether a differently-shaped query reaches other cars",
        # Year is the predictor most collapsed in Run 2's slices, so it is
        # the sharpest probe available. The parameter names must be
        # confirmed against the live filter UI before the run — guessing
        # them would silently return the unfiltered feed, which is exactly
        # the mistake the first run made with /car/saipa.
        "urls": lambda slug, *_: [
            f"https://bama.ir/car/{slug}?year={lo}-{hi}"
            for lo, hi in ((1380, 1392), (1393, 1399), (1400, 1405))],
    },
}


def plan() -> str:
    L = ["RUN 3 — EXPERIMENT MATRIX", "=" * 62, "",
         "The gate is frozen. The sampling strategy is the variable.", "",
         f"targets: {', '.join(TARGETS)}", ""]
    for name, arm in ARMS.items():
        L += [f"  arm '{name}' — {arm['what']}",
              f"    tests: {arm['tests']}",
              f"    e.g.   {arm['urls'](TARGETS[1])[0]}",
              f"           {arm['urls'](TARGETS[1])[-1]}", ""]
    L += ["success criteria, fixed in advance:",
          f"  · ≥{cov_mod.MIN_ELIGIBLE} appraisal-eligible listings for at "
          "least one target model, AND",
          f"  · no more than {cov_mod.MAX_LEVEL_SHARE:.0%} sharing one model "
          "year or body condition, AND",
          f"  · mileage IQR ≥ {cov_mod.MIN_RELATIVE_IQR:.0%} of the median.",
          "",
          "Anything short of all three is a failed run, and the response is",
          "another sampling strategy — never a lowered threshold.",
          "",
          "PRE-FLIGHT (both are ways the last two runs actually went wrong):",
          "  · confirm the year-filter parameter against the live UI; a",
          "    guessed name returns the unfiltered feed while looking fine,",
          "    exactly as /car/saipa silently did.",
          "  · confirm ?page=N paginates rather than redirecting to page 1.",
          "  · dedupe by listing id ACROSS arms before counting anything —",
          "    the same car reached two ways is one observation, and",
          "    counting it twice would manufacture the diversity under test."]
    return "\n".join(L)


def compare(arms: dict[str, list]) -> str:
    """Side-by-side: did either arm change the answer?"""
    L = ["RUN 3 RESULT", "=" * 62, ""]
    seen_ids: dict[str, set] = {}
    for arm, listings in arms.items():
        ids = {x.listing_id for x in listings}
        seen_ids[arm] = ids
        elig = [x for x in listings if eligibility(x)[0]]
        L += [f"arm '{arm}': {len(listings)} parsed, {len(ids)} distinct, "
              f"{len(elig)} eligible"]
        L += cov_mod.report(cov_mod.assess(listings))
        L.append("")

    if len(seen_ids) > 1:
        arms_list = list(seen_ids)
        overlap = set.intersection(*seen_ids.values())
        union = set.union(*seen_ids.values())
        L += ["OVERLAP BETWEEN ARMS", "-" * 62,
              f"  {len(overlap)} listings appear in both of "
              f"{', '.join(arms_list)}; {len(union)} distinct in total.",
              "  High overlap means the arms are the same query wearing two",
              "  names, and the comparison answers nothing."]

    merged = [x for ls in arms.values() for x in ls]
    dedup = {x.listing_id: x for x in merged}.values()
    covs = cov_mod.assess(list(dedup))
    ready = [k for k, c in covs.items() if c.sufficient]
    L += ["", "VERDICT (pooled, deduplicated)", "-" * 62]
    if ready:
        L.append(f"  {', '.join(sorted(ready))} meet BOTH the count and the "
                 "spread. W1 may be unlocked for those models only.")
    else:
        L.append("  No model meets both gates. This is a failed run, which is "
                 "a result: record which arm got closer and try a third "
                 "sampling strategy. Do not move the thresholds.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true",
                    help="print the matrix and the pre-agreed criteria")
    ap.add_argument("--replay", type=Path,
                    help="directory of per-arm snapshots to compare")
    args = ap.parse_args()

    if args.replay:
        from scripts.replay_bama import rebuild                    # noqa: E402
        from caro.ingest.bama import ParseTrace, parse_detail_page  # noqa: E402
        arms: dict[str, list] = {}
        for p in sorted(args.replay.glob("*.json")):
            recs = json.loads(p.read_text(encoding="utf-8"))
            got = []
            for rec in recs:
                url, page = rebuild(rec)
                x = parse_detail_page(url, page, trace=ParseTrace())
                if x is not None:
                    got.append(x)
            arms[p.stem] = got
        print(compare(arms))
        return 0

    print(plan())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
