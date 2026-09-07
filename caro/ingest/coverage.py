"""
Is a comparable set *varied*, or just *large*?

Thirty eligible listings unlock the estimator mechanically. Thirty listings
that are the same car thirty times unlock nothing, and the failure is worse
than having no data — it is quiet, and it points the wrong way.

The statistical reason, which is the whole justification for this module. The
appraiser fits price on year, mileage and condition. A coefficient is only
identified if its predictor *varies* in the sample. If every Tiba in the set
is a 1399 with 85–90k km and no paint, then:

  * the mileage coefficient is estimated from almost no spread, so it is
    noise wearing a number;
  * the model returns something very close to the slice mean and presents it
    as a conditional estimate; and — the dangerous part —
  * residuals within a homogeneous slice are *small*, so the prediction
    interval comes out **narrower**, and the acceptance gate in W1 sees a
    well-calibrated model.

Degeneracy therefore manufactures confidence rather than destroying it. No
metric computed on the same slice can see it, because the held-out half is
degenerate in exactly the same way. It has to be checked structurally, on the
inputs, before anything is fitted.

What this cannot check
----------------------
Seller diversity, mostly. CARO never reads a phone number, so there is no
seller identity to count distinct values of. `seller_type` below is inferred
from a dealership block the page publishes about itself — a real signal, and
a coarse one. Thirty listings from thirty different dealers would still pass
as diverse here. That limit is stated rather than papered over.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

# Policy, not fitted constants — the same status as DAMAGE_COST_FACTOR. They
# encode "how homogeneous is too homogeneous to price against", which is a
# judgement about what a buyer is owed, not a quantity estimable from data.

# One value holding more than this share of a categorical predictor means the
# other levels are represented by a handful of rows at best, and any contrast
# against them is noise.
MAX_LEVEL_SHARE = 0.80

# Interquartile range over median. Below this a continuous predictor has no
# usable spread: the fit is interpolating inside a band it never leaves.
MIN_RELATIVE_IQR = 0.15

# A model needs this many appraisal-eligible listings before variation is even
# worth measuring. Kept equal to the readiness gate on purpose: two thresholds
# that could drift apart would eventually disagree.
MIN_ELIGIBLE = 30


def _quantile(xs: list[float], q: float) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    return s[min(len(s) - 1, max(0, int(q * (len(s) - 1))))]


def relative_iqr(values: list) -> float | None:
    """Spread as a fraction of the middle, so it compares across scales.

    A 200k-toman IQR means something entirely different on a 300M Pride than
    on a 3B Tara, which is why this is not an absolute range check.
    """
    xs = [float(v) for v in values if v is not None]
    if len(xs) < 4:
        return None
    med = _quantile(xs, 0.5)
    if med <= 0:
        return None
    return (_quantile(xs, 0.75) - _quantile(xs, 0.25)) / med


def top_share(values: list) -> tuple[float, object] | None:
    """(share of the most common value, that value)."""
    vs = [v for v in values if v is not None]
    if not vs:
        return None
    value, count = Counter(vs).most_common(1)[0]
    return count / len(vs), value


@dataclass
class ModelCoverage:
    """One target model's comparable set, judged on variation."""
    key: str
    n_eligible: int
    findings: list[str] = field(default_factory=list)
    detail: dict = field(default_factory=dict)

    @property
    def degenerate(self) -> bool:
        return bool(self.findings)

    @property
    def sufficient(self) -> bool:
        """Enough rows AND enough spread. Both, or neither counts."""
        return self.n_eligible >= MIN_ELIGIBLE and not self.degenerate


def assess_model(key: str, rows: list) -> ModelCoverage:
    cov = ModelCoverage(key=key, n_eligible=len(rows))
    if not rows:
        return cov

    years = [r.year_jalali for r in rows]
    kms = [r.mileage_km for r in rows]
    prices = [r.asking_price_toman for r in rows]
    conds = [r.body_condition for r in rows]
    sellers = [getattr(r, "seller_type", "unknown") for r in rows]

    cov.detail = {
        "distinct_years": len({y for y in years if y}),
        "year_top": top_share(years),
        "condition_top": top_share(conds),
        "mileage_riqr": relative_iqr(kms),
        "price_riqr": relative_iqr(prices),
        "seller_types": dict(Counter(sellers)),
    }

    yt = cov.detail["year_top"]
    if yt and yt[0] > MAX_LEVEL_SHARE:
        cov.findings.append(
            f"{yt[0]:.0%} of listings are model year {yt[1]} — the year "
            "coefficient would be fitted on almost no contrast")

    ct = cov.detail["condition_top"]
    if ct and ct[0] > MAX_LEVEL_SHARE:
        cov.findings.append(
            f"{ct[0]:.0%} share one body condition ({ct[1]}) — the risk "
            "layer has nothing to discriminate on")

    mi = cov.detail["mileage_riqr"]
    if mi is not None and mi < MIN_RELATIVE_IQR:
        cov.findings.append(
            f"mileage IQR is {mi:.0%} of the median — the fit never leaves "
            "that band, so its mileage term is noise")

    pi = cov.detail["price_riqr"]
    if pi is not None and pi < MIN_RELATIVE_IQR / 2:
        cov.findings.append(
            f"asking prices are near-uniform (IQR {pi:.0%} of median) — "
            "check this is a market and not one seller's inventory")

    return cov


def assess(listings: list, eligible_only: bool = True) -> dict:
    """Every model in the corpus, keyed as the inventory keys them."""
    from caro.ingest.quality import eligibility

    groups: dict[str, list] = {}
    for x in listings:
        if not x.model:
            continue
        if eligible_only and not eligibility(x)[0]:
            continue
        groups.setdefault(f"{x.make} {x.model}", []).append(x)
    return {k: assess_model(k, v) for k, v in groups.items()}


def report(covs: dict) -> list[str]:
    """The section the run prints. Ordered by size, because the biggest
    model is the one most likely to be mistaken for readiness."""
    if not covs:
        return []
    L = ["", "COMPARABLE-SET VARIATION  (size is not coverage)", "-" * 62]
    ranked = sorted(covs.values(), key=lambda c: -c.n_eligible)
    for c in ranked[:8]:
        d = c.detail
        mi = d.get("mileage_riqr")
        pi = d.get("price_riqr")
        L.append(f"  {c.key:<20}{c.n_eligible:>3} eligible   "
                 f"years:{d.get('distinct_years', 0):<3} "
                 f"km-iqr:{f'{mi:.0%}' if mi is not None else '  -':<6} "
                 f"price-iqr:{f'{pi:.0%}' if pi is not None else '  -':<6}")
        for f in c.findings:
            L.append(f"      ⚠ {f}")

    ready = [c for c in ranked if c.sufficient]
    if ready:
        L.append(f"  {len(ready)} model(s) have both the count and the spread "
                 "to price against.")
    else:
        big = [c for c in ranked if c.n_eligible >= MIN_ELIGIBLE]
        if big:
            L.append(f"  ⚠ {len(big)} model(s) reach {MIN_ELIGIBLE}+ eligible "
                     "listings but are too homogeneous to fit — MORE OF THE "
                     "SAME PAGE WILL NOT FIX THIS. Vary the query instead.")
        else:
            flagged = sum(1 for c in ranked if c.degenerate)
            L.append(f"  No model reaches {MIN_ELIGIBLE} eligible listings, "
                     "so none is ready regardless of spread.")
            if flagged:
                # Worth reading now rather than after the deeper run: a slice
                # that is already homogeneous at n=8 will usually still be
                # homogeneous at n=40, because more pages of one query return
                # more of one kind of car.
                L.append(f"  {flagged} of them ALREADY show the homogeneity "
                         "above at this size. Deeper pagination on the same "
                         "query will not fix that — it is a property of the "
                         "query, not of the sample size.")
    return L
