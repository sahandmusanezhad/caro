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


# The four outcomes, kept apart on purpose. Collapsing any two of them is how
# "we collected 30 rows" turns into "we have evidence for a valuation model".
INVALID = "INVALID_ACQUISITION"        # the run did not test what it claims to
TOO_FEW = "INSUFFICIENT_OBSERVATIONS"  # not enough eligible listings
TOO_FLAT = "INSUFFICIENT_VARIATION"    # enough listings, too alike
READY = "APPRAISAL_READY"              # both gates cleared

OUTCOME_MEANING = {
    INVALID: "the acquisition did not do what it claims — NOT a statement "
             "about the market",
    TOO_FEW: "not enough appraisal-eligible observations",
    TOO_FLAT: "enough observations, but they are too alike to fit",
    READY: "count and variation both cleared",
}


class ArmResult:
    """One model under one sampling strategy, at every stage of the ladder.

    `fetched → unique → usable → appraisal-eligible → variation → ready`.
    Every stage is reported because every stage is a different reason to
    stop, and the gaps say which one applies.
    """

    def __init__(self, model: str, arm: str, listings: list,
                 fetched: int, acquisition_ok: bool = True,
                 acquisition_note: str = ""):
        self.model, self.arm = model, arm
        self.fetched = fetched
        self.acquisition_ok = acquisition_ok
        self.acquisition_note = acquisition_note
        by_id = {x.listing_id: x for x in listings}
        self.unique = len(by_id)
        rows = list(by_id.values())
        self.usable = sum(1 for x in rows if x.model and x.year_jalali
                          and x.mileage_status == "plausible")
        self.eligible_rows = [x for x in rows if eligibility(x)[0]]
        self.eligible = len(self.eligible_rows)
        self.cov = cov_mod.assess_model(model, self.eligible_rows)

    @property
    def outcome(self) -> str:
        # Order matters. An invalid acquisition is decided first, because a
        # run that fetched the wrong pages says nothing about variation, and
        # reporting it as TOO_FLAT would be evidence laundering.
        if not self.acquisition_ok:
            return INVALID
        if self.eligible < cov_mod.MIN_ELIGIBLE:
            return TOO_FEW
        if self.cov.degenerate:
            return TOO_FLAT
        return READY

    def line(self) -> str:
        return (f"  {self.model:<8}{self.arm:<11}"
                f"{self.fetched:>5}{self.unique:>8}{self.usable:>8}"
                f"{self.eligible:>10}"
                f"{'pass' if not self.cov.degenerate else 'FAIL':>11}"
                f"   {self.outcome}")


def compare(arms: dict[str, list], fetched: dict[str, int] | None = None,
            acquisition: dict[str, tuple[bool, str]] | None = None) -> str:
    """The full ladder, per model per arm, with the outcomes kept distinct."""
    fetched = fetched or {}
    acquisition = acquisition or {}

    results: list[ArmResult] = []
    for arm, listings in arms.items():
        ok, note = acquisition.get(arm, (True, ""))
        by_model: dict[str, list] = {}
        for x in listings:
            if x.model:
                by_model.setdefault(f"{x.make} {x.model}", []).append(x)
        for model, rows in by_model.items():
            results.append(ArmResult(model, arm, rows,
                                     fetched.get(arm, len(listings)), ok, note))

    L = ["RUN 3 RESULT — the ladder, per model per arm", "=" * 78, "",
         f"  {'model':<8}{'arm':<11}{'fetch':>5}{'unique':>8}{'usable':>8}"
         f"{'eligible':>10}{'variation':>11}   outcome",
         "  " + "-" * 74]
    for r in sorted(results, key=lambda r: (r.model, r.arm)):
        L.append(r.line())
        for f in r.cov.findings:
            L.append(f"        ⚠ {f}")
        if not r.acquisition_ok:
            L.append(f"        ⚠ {r.acquisition_note}")

    L += ["", "  outcome key", "  " + "-" * 74]
    for k, v in OUTCOME_MEANING.items():
        L.append(f"    {k:<26}{v}")

    # Did the two arms actually reach different cars? If not, the comparison
    # answers nothing regardless of what the counts say.
    ids = {a: {x.listing_id for x in ls} for a, ls in arms.items()}
    if len(ids) > 1:
        overlap = set.intersection(*ids.values())
        union = set.union(*ids.values())
        share = len(overlap) / len(union) if union else 0.0
        L += ["", "ARM INDEPENDENCE", "-" * 62,
              f"  {len(overlap)} of {len(union)} distinct listings appear in "
              f"more than one arm ({share:.0%} overlap)."]
        if share > 0.8:
            L.append("  ⚠ the arms are largely the SAME QUERY wearing two "
                     "names. Whatever they agree on is not a comparison.")

    merged = {x.listing_id: x for ls in arms.values() for x in ls}
    covs = cov_mod.assess(list(merged.values()))
    ready = sorted(k for k, c in covs.items() if c.sufficient)
    invalid = [r for r in results if not r.acquisition_ok]

    L += ["", "VERDICT (pooled across arms, deduplicated)", "-" * 62]
    if invalid:
        L.append(f"  {INVALID} — {len(invalid)} arm/model cell(s) did not "
                 "acquire what they claim to. Fix acquisition and re-run; "
                 "this run is not evidence about the market either way.")
    elif ready:
        L.append(f"  {READY}: {', '.join(ready)} — count AND variation. "
                 "W1 may be unlocked for those models only.")
    else:
        pooled_big = [k for k, c in covs.items()
                      if c.n_eligible >= cov_mod.MIN_ELIGIBLE]
        if pooled_big:
            L.append(f"  {TOO_FLAT} — {', '.join(sorted(pooled_big))} reached "
                     f"{cov_mod.MIN_ELIGIBLE}+ eligible listings but stayed "
                     "too alike. Volume was not the binding constraint.")
        else:
            best = max(covs.values(), key=lambda c: c.n_eligible, default=None)
            L.append(f"  {TOO_FEW} — best model has "
                     f"{best.n_eligible if best else 0} eligible listings of "
                     f"{cov_mod.MIN_ELIGIBLE} needed.")
        L.append("  A failed run is a result. Record which arm got closer and "
                 "try a third sampling strategy — do not move the thresholds.")
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
