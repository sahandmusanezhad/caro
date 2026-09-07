"""
D32 — partial pooling that SHOWS its work.

Run 4 proved the acquisition ceiling: with complete collection of everything
Bama publishes for Pride, at most 63% of listings sit in trims with five or
more observations, against the 70% the conditional estimand needs (D31). The
shortfall is the market's long tail, not our route, so no further crawling
fixes it.

That leaves one honest option: keep trim-level conditioning and make the
borrowing across trims **explicit, measured and visible**, rather than
implicit and unmeasurable as pooling currently is.

The trap this module is built to avoid
--------------------------------------
A hierarchical model trained only on this corpus can very easily learn

    thin trim → parent mean

and then dress the same extrapolation the pooled estimator was already doing
in Bayesian clothing. The output would look more principled and contain no
more information. Three defences, all structural:

1. **Shrinkage is computed, not chosen.** `λ_t = τ² / (τ² + σ²/n_t)` is
   empirical Bayes: the data decides how much a trim speaks for itself, from
   the ratio of between-trim to within-trim variance. Nothing is hand-tuned
   toward a nicer answer.
2. **Every prediction carries a `PoolingTrace`** saying how many observations
   its trim actually had, how much of the estimate came from the trim versus
   the parent, and whether that counts as material extrapolation. A number
   built almost entirely from the parent says so, in the trace, on that
   prediction.
3. **The gate stresses thin trims and held-out trims separately.** Mean error
   over a corpus dominated by well-observed trims cannot see a model that is
   useless on the tail — and the tail is 45% of this corpus.

Borrowing strength is not a sampling weight. Using Pride to inform
`Pride 131 EX` never claims to know 131 EX's share of the market; it claims
that Prides are informative about Prides. That distinction is exactly what
`1/P(inclusion)` weighting would have violated (D29) and what this does not.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np

from caro.appraisal import QUANTILES, Row, _ridge_fit, rearrange_monotone

# Below this share of the estimate coming from the trim's own observations,
# the number is mostly the parent's and is reported as extrapolation. Policy,
# in the same sense as DAMAGE_COST_FACTOR — it encodes what a buyer is owed a
# warning about, not a quantity estimable from data.
MATERIAL_EXTRAPOLATION_BELOW = 0.50

# A second, independent trigger, and the tests are what forced it. Empirical
# Bayes will happily hand λ = 0.58 to a trim with ONE listing when the
# between-trim variance is large: statistically defensible — if trims really
# differ, one observation is informative — and yet the resulting estimate
# swings on a single seller's asking price. λ measures how much the model
# should weight the trim. It does not measure whether a buyer should be told
# the number rests on one advert.
#
# So the flag fires on either condition, and this floor is deliberately the
# same MIN_PER_TRIM the data contract uses (D30). Two thresholds meaning "too
# few to speak for itself" would eventually disagree, and the disagreement
# would surface as a confident estimate the contract says is out of scope.
from caro.ingest.quality import MIN_PER_TRIM_FLOOR  # noqa: E402


@dataclass(frozen=True)
class PoolingTrace:
    """Where one estimate's information actually came from.

    The point of the trace is that a thin-trim estimate and a well-observed
    one must not be indistinguishable in the output. They are different
    claims and the difference is not visible in the number.
    """
    trim: str
    parent: str
    n_trim: int
    shrinkage: float            # 0 = entirely parent, 1 = entirely trim
    trim_offset_raw: float      # the trim's own deviation, before shrinking
    trim_offset_applied: float  # what was actually used
    material_extrapolation: bool
    reason: str = ""            # which trigger fired, for the trace

    def explain(self) -> str:
        src = (f"{self.shrinkage:.0%} from this trim's own "
               f"{self.n_trim} listing(s), "
               f"{1 - self.shrinkage:.0%} borrowed from {self.parent}")
        if self.material_extrapolation:
            return f"{src}\n  ⚠ MATERIAL EXTRAPOLATION — {self.reason}"
        return src


def _parent_of(row: Row) -> str:
    """model_key is 'make|model|trim'; the parent pools across trims."""
    return "|".join(row.model_key.split("|")[:2])


@dataclass
class PartialPoolingQuantiles:
    """Ridge on year and mileage, plus an empirical-Bayes trim offset.

    Structure, deliberately simple enough to inspect:

        log(price) ≈ base(parent, year, mileage) + λ_t · offset_t

    `base` pools at the PARENT level, where there is always enough data.
    `offset_t` is the trim's own mean deviation from that, shrunk toward zero
    by λ_t. A trim with many listings keeps its offset; a trim with one gets
    almost none of it, and the trace says so rather than the output hiding it.

    Why not simply add trim dummies to the ridge: a dummy for a trim with one
    observation is fitted to that observation, and ridge's penalty shrinks it
    by an amount chosen for numerical convenience rather than estimated from
    the between-trim variance. The shrinkage would exist but would not be
    reportable, which is precisely the failure mode this module exists to
    avoid.
    """
    quantiles: Sequence[float] = QUANTILES
    alpha: float = 1.0
    _cols: list[str] = None                     # parent keys, one-hot
    _coef: np.ndarray | None = None
    _intercept: float = 0.0
    _offsets: dict[str, float] = None           # trim -> shrunk offset
    _n: dict[str, int] = None
    _lam: dict[str, float] = None
    _raw: dict[str, float] = None
    _parent_of_trim: dict[str, str] = None
    _resid_q: np.ndarray | None = None

    # -- design ----------------------------------------------------------
    def _design(self, rows: Sequence[Row], fit: bool = False) -> np.ndarray:
        if fit:
            self._cols = sorted({_parent_of(r) for r in rows})
        X = np.zeros((len(rows), len(self._cols) + 2))
        for i, r in enumerate(rows):
            p = _parent_of(r)
            if p in self._cols:
                X[i, self._cols.index(p)] = 1.0
            X[i, -2] = r.year_jalali
            X[i, -1] = r.mileage_km / 1e5
        return X

    # -- fit -------------------------------------------------------------
    def fit(self, rows: Sequence[Row]) -> "PartialPoolingQuantiles":
        X = self._design(rows, fit=True)
        y = np.log(np.array([r.asking_price_toman for r in rows], dtype=float))
        self._coef, self._intercept = _ridge_fit(X, y, self.alpha)
        resid = y - (X @ self._coef + self._intercept)

        by_trim: dict[str, list[float]] = {}
        self._parent_of_trim = {}
        for r, e in zip(rows, resid):
            by_trim.setdefault(r.model_key, []).append(float(e))
            self._parent_of_trim[r.model_key] = _parent_of(r)

        means = {t: float(np.mean(v)) for t, v in by_trim.items()}
        self._n = {t: len(v) for t, v in by_trim.items()}

        # Within-trim noise, pooled across trims that can supply an estimate.
        within = [float(np.var(v, ddof=1)) for v in by_trim.values() if len(v) > 1]
        sigma2 = float(np.mean(within)) if within else float(np.var(resid))

        # Between-trim variance, with the within-trim sampling noise removed.
        # Negative after subtraction means the trims are indistinguishable, so
        # nothing should be attributed to trim at all — λ = 0 everywhere.
        spread = float(np.var(list(means.values()))) if len(means) > 1 else 0.0
        tau2 = max(0.0, spread - sigma2 / max(1, int(np.mean(list(self._n.values())))))

        self._lam, self._offsets, self._raw = {}, {}, {}
        for t, m in means.items():
            n = self._n[t]
            lam = tau2 / (tau2 + sigma2 / n) if (tau2 + sigma2 / n) > 0 else 0.0
            self._lam[t] = float(lam)
            self._raw[t] = m
            self._offsets[t] = float(lam * m)

        fitted = self._raw_predict(rows)
        self._resid_q = np.quantile(y - fitted, self.quantiles)
        return self

    def _raw_predict(self, rows: Sequence[Row]) -> np.ndarray:
        X = self._design(rows)
        base = X @ self._coef + self._intercept
        off = np.array([self._offsets.get(r.model_key, 0.0) for r in rows])
        return base + off

    def predict(self, rows: Sequence[Row]) -> np.ndarray:
        mu = self._raw_predict(rows)
        out = np.exp(mu[:, None] + self._resid_q[None, :])
        return rearrange_monotone(out)

    # -- the part that must not be optional -------------------------------
    def trace(self, row: Row) -> PoolingTrace:
        t = row.model_key
        n = self._n.get(t, 0)
        lam = self._lam.get(t, 0.0)
        parent = self._parent_of_trim.get(t, _parent_of(row))
        reason = ""
        if n < MIN_PER_TRIM_FLOOR:
            reason = (f"this trim has {n} listing(s), below the {MIN_PER_TRIM_FLOOR} "
                      f"the contract requires for a stratum to speak for "
                      f"itself. The estimate rests on too few adverts "
                      f"regardless of how the model weights them.")
        elif lam < MATERIAL_EXTRAPOLATION_BELOW:
            reason = (f"most of this estimate is {parent}, not {t} — the "
                      f"trim's own signal was shrunk to {lam:.0%}.")
        return PoolingTrace(
            trim=t, parent=parent, n_trim=n, shrinkage=lam,
            trim_offset_raw=self._raw.get(t, 0.0),
            trim_offset_applied=self._offsets.get(t, 0.0),
            material_extrapolation=bool(reason), reason=reason)

    def extrapolation_rate(self, rows: Sequence[Row]) -> float:
        """Share of rows whose estimate is mostly borrowed.

        Reported next to any aggregate metric, because a model can post a
        fine average error while most of its answers are the parent's.
        """
        if not rows:
            return 0.0
        return sum(1 for r in rows
                   if self.trace(r).material_extrapolation) / len(rows)


# ---------------------------------------------------------------------------
# The gate, stressed where the corpus is weakest
# ---------------------------------------------------------------------------

THIN_TRIM_MAX = 4          # a trim below the conditional-scope floor (D30)


def thin_trim_rows(rows: Sequence[Row], counts: dict[str, int]) -> list[Row]:
    return [r for r in rows if counts.get(r.model_key, 0) <= THIN_TRIM_MAX]


def held_out_trim_split(rows: Sequence[Row], fraction: float = 0.2,
                        seed: int = 0) -> tuple[list[Row], list[Row]]:
    """Hold out ENTIRE trims, not rows.

    The harshest honest test of partial pooling: a trim the model has never
    seen must be priced from its parent alone, and the trace must admit it.
    A row-level split cannot ask this question, because every trim appears on
    both sides.
    """
    trims = sorted({r.model_key for r in rows})
    rng = np.random.default_rng(seed)
    rng.shuffle(trims)
    n_out = max(1, int(len(trims) * fraction))
    out = set(trims[:n_out])
    return ([r for r in rows if r.model_key not in out],
            [r for r in rows if r.model_key in out])
