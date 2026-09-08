#!/usr/bin/env python3
"""
Run 4 (D31) — an ACQUISITION experiment, not a modelling one.

    python3 scripts/run4_depth.py --plan
    python4 scripts/run4_depth.py --compare data/snapshots/run3 data/snapshots/run4

Run 3 left one measured failure: 55% of eligible listings sit in trims with
five or more observations, against the 70% the conditional estimand requires
(D30). This run tests whether that can be fixed by acquisition alone.

The primary outcomes are therefore NOT record counts.

    primary    conditional_coverage      55% → ?
    primary    sampling sensitivity      per model, before → after
    secondary  eligible listings         48 → ? (informative, not the goal)

Stating it this way is the point. A run that lifts Pride from 48 to 80
listings while leaving coverage at 55% has bought nothing the estimand needs
— and under the obvious strategy it would actively hurt, which is why the
strategy is constrained:

    existing model
      └── existing, ALREADY-POPULOUS trim facet
            └── deeper valid acquisition
                  └── more independent listings in trims we already have

Adding models, or new trim facets, raises the count and *lowers* coverage,
because each new facet arrives carrying one or two listings of its own. That
would make the primary number worse while looking like progress, and is
excluded by construction rather than by discipline.

Three outcomes, all informative, fixed before the run:

    coverage ≥ 70%   the D30 preconditions are re-evaluated; if they pass,
                     the estimand gate opens for the models that qualify.
    coverage rises
    but < 70%        a measurement of this acquisition design's capacity.
                     Not a failure — it bounds what the route can deliver.
    coverage flat
    or falls         the design cannot support conditional appraisal at this
                     granularity. The answer is then a different estimator
                     (one that shrinks thin trims and benchmarks the
                     extrapolation honestly) or a coarser conditioning level
                     with its own benchmark — never a moved threshold.

Standing rule from D28 carries over: measure the route's own ceiling before
concluding anything from a shortfall. A trim page that saturates at twenty
listings cannot supply thirty, and reporting that as market thinness would
repeat the mistake the pre-flight exists to prevent.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest import coverage as cov_mod                          # noqa: E402
from caro.ingest import stratification as strat                      # noqa: E402
from caro.ingest.quality import eligibility                          # noqa: E402

# A trim worth going deeper into: it already has enough listings that more of
# them raise the covered share instead of diluting it.
POPULOUS_MIN = 3

TARGET_COVERAGE = 0.70          # D30 condition 3. Not moved by this run.


def populous_trims(rows) -> dict[str, list[str]]:
    """Per model, the trims that deeper acquisition should target.

    Deliberately excludes the thin ones. Fetching more of a trim that has one
    listing helps coverage only if it reaches five; fetching more of a trim
    that already has four is nearly certain to. Spending the request budget
    where it moves the primary number is the whole strategy.
    """
    from collections import Counter
    per: dict[str, Counter] = {}
    for r in rows:
        if r.model and eligibility(r)[0]:
            per.setdefault(f"{r.make} {r.model}", Counter())[
                strat.trim_key(r)] += 1
    return {m: sorted(t for t, c in cnt.items() if c >= POPULOUS_MIN)
            for m, cnt in per.items()}


def coverage_line(label: str, rows) -> tuple[str, float]:
    sc = strat.conditional_scope(rows)
    return (f"  {label:<12}{sc.covered_share:>7.0%}   "
            f"({sum(1 for r in rows if r.model and eligibility(r)[0])} "
            f"eligible)"), sc.covered_share


def compare(before, after) -> str:
    """Before/after on the numbers this experiment is actually about."""
    L = ["RUN 4 (D31) — acquisition depth inside existing trims", "=" * 70, "",
         "PRIMARY — conditional coverage", "-" * 70]
    b_line, b_cov = coverage_line("run 3", before)
    a_line, a_cov = coverage_line("run 4", after)
    L += [b_line, a_line,
          f"  {'Δ':<12}{a_cov - b_cov:>+7.0%}   "
          f"target {TARGET_COVERAGE:.0%} (unchanged)"]

    if a_cov >= TARGET_COVERAGE:
        L.append("  → threshold met. Re-evaluate the D30 preconditions; if "
                 "they pass, the estimand gate opens for qualifying models.")
    elif a_cov > b_cov + 0.005:
        L.append("  → coverage rose but fell short. This is a MEASUREMENT of "
                 "the design's capacity, not a failure — it bounds what this "
                 "route can deliver.")
    else:
        L.append("  → coverage did not rise. This acquisition design cannot "
                 "support conditional appraisal at this granularity. Change "
                 "the estimator or the conditioning level — not the "
                 "threshold.")

    L += ["", "PRIMARY — sampling sensitivity, per model", "-" * 70]
    sb = {k: strat.sensitivity([r for r in before
                                if f"{r.make} {r.model}" == k])
          for k in strat.stratify(before)}
    sa = {k: strat.sensitivity([r for r in after
                               if f"{r.make} {r.model}" == k])
          for k in strat.stratify(after)}
    for k in sorted(set(sb) | set(sa)):
        x, y = sb.get(k, {}), sa.get(k, {})
        if not x.get("relative_span") and not y.get("relative_span"):
            continue
        bx = f"{x['relative_span']:.1%}" if x.get("relative_span") else "  –"
        by = f"{y['relative_span']:.1%}" if y.get("relative_span") else "  –"
        arrow = ""
        if x.get("relative_span") and y.get("relative_span"):
            d = y["relative_span"] - x["relative_span"]
            arrow = f"   {d:+.1%}" + ("  ↓ less design-dependent"
                                      if d < -0.01 else "")
        L.append(f"  {k:<18}{bx:>8} → {by:>8}{arrow}")

    L += ["", "SECONDARY — counts (informative, not the objective)", "-" * 70]
    for k in sorted(set(strat.stratify(before)) | set(strat.stratify(after))):
        nb = strat.stratify(before).get(k)
        na = strat.stratify(after).get(k)
        L.append(f"  {k:<18}{(nb.n_eligible if nb else 0):>5} → "
                 f"{(na.n_eligible if na else 0):>5} eligible   "
                 f"{(len(nb.counts) if nb else 0)} → "
                 f"{(len(na.counts) if na else 0)} trims")
    L += ["",
          "  A run that raises counts while leaving coverage flat has bought",
          "  nothing the estimand needs. That is why the count is reported",
          "  last."]
    return "\n".join(L)


def plan(before) -> str:
    L = [__doc__.strip(), "", "TARGETS RESOLVED FROM RUN 3", "-" * 70]
    pops = populous_trims(before)
    for model, trims in sorted(pops.items()):
        if not trims:
            continue
        L.append(f"  {model:<18}{len(trims)} populous trim(s) "
                 f"(≥{POPULOUS_MIN} eligible)")
        for t in trims[:6]:
            L.append(f"      {t}")
    L += ["", "PRE-FLIGHT REQUIRED BEFORE COLLECTING (D28 standing rule)",
          "-" * 70,
          "  · does /car/<model>-<trim>-page-N paginate, or redirect to",
          "    page 1 as ?page=N silently did?",
          "  · what is its saturation ceiling per trim? A trim page that",
          "    tops out at 20 cannot supply 30, and reporting that as market",
          "    thinness would repeat the run-1 mistake.",
          "  · dedupe against the run-3 ids before counting anything."]
    return "\n".join(L)


def _load(run_id: str):
    """Listings from a PUBLISHED corpus, by run id (DATA_CONTRACT)."""
    from caro.corpus_reader import load_corpus, listings_from_corpus  # noqa: E402
    return listings_from_corpus(load_corpus(str(run_id)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--plan", action="store_true")
    ap.add_argument("--compare", nargs=2, type=Path,
                    metavar=("BEFORE_DIR", "AFTER_DIR"))
    args = ap.parse_args()

    if args.compare:
        print(compare(_load(args.compare[0]), _load(args.compare[1])))
        return 0

    before = _load("run3")
    print(plan(before))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
