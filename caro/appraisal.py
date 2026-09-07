"""
CARO W1 — market-estimate benchmark harness.

The question this answers is NOT "can we build a model?" It is:

    does any model beat a boring comparable-median baseline,
    on a split that does not leak,
    with quantiles that do not cross,
    and coverage that holds inside every slice we will actually serve?

Nothing here claims a market estimate. A model is only allowed to serve
predictions after it passes `AcceptanceGate` — that gate is enforced in code
(see `MarketEstimator.predict`) rather than promised in a README.

Dependencies: numpy only. Any estimator is pluggable, so LightGBM /
scikit-learn quantile models drop in without touching the harness.

Vocabulary, deliberately: `y` is an ASKING price. Everything downstream is
an estimate of the distribution of asking prices — never a transaction
price, never a "fair price", never a "true value".
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable, Protocol, Sequence

import numpy as np

QUANTILES = (0.15, 0.35, 0.50, 0.85)


# ---------------------------------------------------------------------------
# Rows
# ---------------------------------------------------------------------------

@dataclass
class Row:
    """One listing, as the appraiser sees it."""
    listing_id: str
    cluster_id: str          # physical car — reposts of one car share this
    first_seen_ordinal: int  # day number; the temporal split key
    model_key: str           # canonical make|model|trim
    year_jalali: int
    mileage_km: float
    asking_asking_price_toman: float  # the target. AN ASKING PRICE.
    features: dict[str, float] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Splitting — the leakage that would silently inflate every number
# ---------------------------------------------------------------------------

@dataclass
class Split:
    train: list[Row]
    test: list[Row]
    dropped_straddling: int      # genuine leakage risk — correctly excluded
    cutoff_ordinal: int
    long_span_clusters: int = 0  # KEPT, merely counted — see below
    long_span_rows: int = 0

    def leakage(self) -> set[str]:
        """Clusters appearing on both sides. Must always be empty."""
        return {r.cluster_id for r in self.train} & {r.cluster_id for r in self.test}


def cluster_temporal_split(rows: Sequence[Row], *, test_fraction: float = 0.25,
                           long_span_days: int = 60) -> Split:
    """Split by TIME, at the granularity of a physical car.

    Two failure modes this exists to prevent:

    1. Row-level or listing-level splitting puts one car's repost in train
       and another in test. The model has then already seen that exact
       vehicle at nearly that exact price, and every metric is inflated.
       Reposts make this far more likely than ordinary duplication does.

    2. A cluster whose listings straddle the cutoff cannot be assigned to
       either side without leaking. Those are dropped and counted — a small,
       reported loss beats a silent contamination.

    A cluster is placed by its EARLIEST sighting, so "train on the past,
    test on the future" holds at the vehicle level.

    What this does NOT do is drop a cluster merely for being long-lived.
    An earlier version did, and it was a bad bug: a long observation span is
    not a leakage condition, and the cars that sit on the market longest are
    precisely the overpriced and hard-to-shift ones. Excluding them would
    bias the corpus toward fast-moving, well-priced cars — flattering every
    metric while making the model systematically worst on the listings a
    buyer most needs help with. Long-span clusters are counted and reported
    so drift can be judged, never silently removed.
    """
    if not rows:
        return Split([], [], 0, 0)

    by_cluster: dict[str, list[Row]] = {}
    for r in rows:
        by_cluster.setdefault(r.cluster_id, []).append(r)

    firsts = {c: min(r.first_seen_ordinal for r in rs) for c, rs in by_cluster.items()}
    ordered = sorted(firsts, key=lambda c: firsts[c])
    n_test = max(1, int(round(len(ordered) * test_fraction)))
    cutoff = firsts[ordered[len(ordered) - n_test]]

    train: list[Row] = []
    test: list[Row] = []
    dropped = 0
    long_clusters = long_rows = 0
    for c, rs in by_cluster.items():
        lo = min(r.first_seen_ordinal for r in rs)
        hi = max(r.first_seen_ordinal for r in rs)
        if (hi - lo) > long_span_days:
            long_clusters += 1
            long_rows += len(rs)        # counted, NOT dropped
        if lo < cutoff <= hi:
            dropped += len(rs)          # straddles the boundary — unusable
            continue
        (test if lo >= cutoff else train).extend(rs)

    return Split(train, test, dropped, cutoff, long_clusters, long_rows)


@dataclass
class ShiftReport:
    train_median: float
    test_median: float
    ratio: float
    ks_statistic: float
    severe: bool

    def __str__(self) -> str:
        flag = "  ⚠ SEVERE — interpret model metrics with caution" if self.severe else ""
        return (f"train median {self.train_median:,.0f} · test median "
                f"{self.test_median:,.0f} · ratio {self.ratio:.3f} · "
                f"KS {self.ks_statistic:.3f}{flag}")


def distribution_shift(split: Split, *, ratio_tol: float = 0.10,
                       ks_tol: float = 0.20) -> ShiftReport:
    """Did the price distribution move between train and test?

    A temporal split is only meaningful if you then ASK this. Iranian car
    prices move fast; if the test period sits at a different level, a model
    can look broken while being fine, or look fine while being stale. The
    stationary synthetic world used in the tests cannot surface this, so it
    is measured explicitly on real data.
    """
    a = np.sort(np.array([r.asking_asking_price_toman for r in split.train], dtype=float))
    b = np.sort(np.array([r.asking_asking_price_toman for r in split.test], dtype=float))
    if a.size == 0 or b.size == 0:
        return ShiftReport(0.0, 0.0, 1.0, 0.0, False)
    ma, mb = float(np.median(a)), float(np.median(b))
    grid = np.concatenate([a, b])
    ks = float(np.max(np.abs(np.searchsorted(a, grid, "right") / a.size
                             - np.searchsorted(b, grid, "right") / b.size)))
    ratio = mb / ma if ma else 1.0
    return ShiftReport(ma, mb, ratio, ks,
                       severe=(abs(ratio - 1) > ratio_tol or ks > ks_tol))


# ---------------------------------------------------------------------------
# Quantile crossing — a hard acceptance criterion, not a warning
# ---------------------------------------------------------------------------

def rearrange_monotone(preds: np.ndarray) -> np.ndarray:
    """Sort each row's quantile predictions ascending.

    Independently fitted quantile models are not guaranteed monotone, and a
    UI that prints «محدوده بازار: ۱.۲ تا ۱.۰ میلیارد» is unshippable.

    Sorting is not a hack: rearranging a non-monotone quantile curve is
    provably no worse than the original in estimation error (Chernozhukov,
    Fernández-Val & Galichon, "Quantile and Probability Curves Without
    Crossing"). So it is a legitimate post-process — but the crossing RATE
    is still reported, because a model that crosses often is telling you
    something is wrong upstream.
    """
    return np.sort(preds, axis=1)


def crossing_rate(preds: np.ndarray) -> float:
    """Fraction of rows where quantiles are out of order before rearranging."""
    if preds.size == 0:
        return 0.0
    return float(np.mean(np.any(np.diff(preds, axis=1) < 0, axis=1)))


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def pinball_loss(y: np.ndarray, q: np.ndarray, tau: float) -> float:
    """Mean pinball (quantile) loss. Minimised by the true tau-quantile."""
    d = y - q
    return float(np.mean(np.maximum(tau * d, (tau - 1) * d)))


def coverage(y: np.ndarray, q: np.ndarray) -> float:
    """P(y <= q). For a well-calibrated tau-quantile this should be ~tau."""
    return float(np.mean(y <= q)) if y.size else float("nan")


def interval_coverage(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> float:
    return float(np.mean((y >= lo) & (y <= hi))) if y.size else float("nan")


@dataclass
class SliceResult:
    name: str
    n: int
    coverage_by_tau: dict[float, float]
    pinball_by_tau: dict[float, float]
    interval_coverage_15_85: float
    reliable: bool          # False when n is too small to read a rate from
    max_abs_coverage_error: float

    def coverage_ci(self, tau: float, z: float = 1.96) -> tuple[float, float]:
        """Wilson score interval for the observed coverage proportion.

        The gate's tolerance is a PRODUCT POLICY, not a statistical test.
        This is the actual statistics, reported alongside it so the two are
        never confused.
        """
        if self.n == 0:
            return (float("nan"), float("nan"))
        p, n = self.coverage_by_tau[tau], self.n
        d = 1 + z * z / n
        c = (p + z * z / (2 * n)) / d
        h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
        return (max(0.0, c - h), min(1.0, c + h))

    def nominal_inside_ci(self, tau: float) -> bool:
        lo, hi = self.coverage_ci(tau)
        return lo <= tau <= hi

    def significant_coverage_error(self, z: float = 2.5) -> float:
        """Largest coverage error that is bigger than sampling noise explains.

        Taking a plain max over ~12 slices x 4 quantiles is a biased
        statistic: with 48 noisy estimates the largest one looks alarming
        even for a perfect model (winner's curse / multiple comparisons).
        A slice only counts against a model when its deviation exceeds z
        binomial standard errors, sd = sqrt(t(1-t)/n).
        """
        if self.n == 0:
            return 0.0
        worst = 0.0
        for t, c in self.coverage_by_tau.items():
            se = math.sqrt(max(t * (1 - t), 1e-9) / self.n)
            err = abs(c - t)
            if err > z * se:
                worst = max(worst, err)
        return worst


# A coverage RATE needs enough rows to mean anything. At n=30 the standard
# error on a 0.15 quantile is ~0.065, so a +/-0.12 tolerance is inside noise
# and the slice tells you nothing. 150 puts the standard error near 0.03.
MIN_SLICE_N = 150


def evaluate(y: np.ndarray, preds: np.ndarray, *, name: str,
             quantiles: Sequence[float] = QUANTILES) -> SliceResult:
    cov = {t: coverage(y, preds[:, i]) for i, t in enumerate(quantiles)}
    pin = {t: pinball_loss(y, preds[:, i], t) for i, t in enumerate(quantiles)}
    lo_i, hi_i = 0, len(quantiles) - 1
    err = max(abs(cov[t] - t) for t in quantiles) if y.size else float("nan")
    return SliceResult(
        name=name, n=int(y.size), coverage_by_tau=cov, pinball_by_tau=pin,
        interval_coverage_15_85=interval_coverage(y, preds[:, lo_i], preds[:, hi_i]),
        reliable=y.size >= MIN_SLICE_N,
        max_abs_coverage_error=err,
    )


def slice_rows(rows: Sequence[Row], preds: np.ndarray,
               quantiles: Sequence[float] = QUANTILES) -> dict[str, list[int]]:
    """The slices a coverage number must hold inside, not merely on average.

    Aggregate coverage of 15% can hide 206 at 28% and Pride at 9% — the
    product would then be systematically wrong for half its inventory while
    the headline metric looked perfect.

    CRITICAL: every slice must be defined by FEATURES or by the model's own
    PREDICTION — never by the target. Slicing on `asking_asking_price_toman` selects
    on the dependent variable: inside a "price >= 2B" bucket you have kept
    only rows whose y landed high, so even a perfectly calibrated estimator
    shows badly skewed coverage there. That artefact would reject every good
    model. The price band therefore uses the predicted median, which is a
    function of features alone.
    """
    med_i = min(range(len(quantiles)), key=lambda i: abs(quantiles[i] - 0.50))
    out: dict[str, list[int]] = {}
    for i, r in enumerate(rows):
        out.setdefault(f"model={r.model_key}", []).append(i)
        p = float(preds[i, med_i])          # predicted, NOT actual
        band = ("pred<500M" if p < 5e8 else "pred 500M-1B" if p < 1e9
                else "pred 1-2B" if p < 2e9 else "pred>=2B")
        out.setdefault(band, []).append(i)
        m = r.mileage_km
        mband = ("km<50k" if m < 5e4 else "km 50-150k" if m < 1.5e5
                 else "km 150-250k" if m < 2.5e5 else "km>=250k")
        out.setdefault(mband, []).append(i)
    return out


# ---------------------------------------------------------------------------
# Baseline A — comparable quantiles. No ML. The bar to beat.
# ---------------------------------------------------------------------------

class Estimator(Protocol):
    def fit(self, rows: Sequence[Row]) -> "Estimator": ...
    def predict(self, rows: Sequence[Row]) -> np.ndarray: ...


MatchTier = str  # strict | relaxed_mileage | relaxed_year | model_only | global

TIER_RANK = {"strict": 0, "relaxed_mileage": 1, "relaxed_year": 2,
             "model_only": 3, "global": 4}


@dataclass
class ComparableEvidence:
    """What the estimate actually rests on.

    `count` alone is NOT a confidence signal, and treating it as one was a
    mistake: 200 Prides of assorted years and mileages are weaker evidence
    than 12 Prides of the right year at the right mileage. Confidence needs
    the TIER the comparables came from and how DISPERSED their prices are,
    not just how many there were.

    The tier also constrains what the UI may say. If the estimate came from
    `model_only`, the product must not print «۲۱۱ آگهی مشابه» — those
    listings are the same model, not comparable cars.
    """
    count: int
    tier: MatchTier
    dispersion: float          # IQR / median of the comparable prices

    @property
    def quality(self) -> str:
        if self.tier in ("model_only", "global") or self.count < 8:
            return "low"
        if self.tier == "strict" and self.count >= 25 and self.dispersion < 0.35:
            return "high"
        return "medium"

    def claim_fa(self) -> str:
        """Persian phrasing the tier actually licenses."""
        if self.tier == "strict":
            return f"{self.count} آگهی مشابه (مدل، سال و کارکرد نزدیک)"
        if self.tier == "relaxed_mileage":
            return f"{self.count} آگهی با همین مدل و سال (کارکرد متفاوت)"
        if self.tier == "relaxed_year":
            return f"{self.count} آگهی با همین مدل (سال متفاوت)"
        if self.tier == "model_only":
            return f"{self.count} آگهی از همین مدل — مشابه نیستند"
        return "داده‌ی کافی برای این مدل نداریم"


@dataclass
class ComparableQuantiles:
    """Empirical quantiles over comparable listings.

    Deliberately dull. It is explainable to a user in one sentence
    («۸۷ آگهی مشابه با این مدل، سال و کارکرد»), it produces the quantiles the
    ranking rule needs directly, its comparable count IS the confidence
    signal, and on a few thousand rows it is a genuinely hard baseline.

    If a gradient-boosted model cannot beat this, the professional move is
    to ship this and say so.
    """
    quantiles: Sequence[float] = QUANTILES
    year_tolerance: int = 1
    mileage_rel_tolerance: float = 0.30
    min_comparables: int = 5
    _rows: list[Row] = field(default_factory=list)

    def fit(self, rows: Sequence[Row]) -> "ComparableQuantiles":
        self._rows = list(rows)
        return self

    def _comparables(self, r: Row) -> tuple[list[float], MatchTier]:
        """Walk the relaxation ladder, and REPORT which rung was used.

        Silently relaxing and then reporting the resulting count as
        "comparable listings" is how a product ends up making a claim its
        data does not support.
        """
        same_model = [o for o in self._rows if o.model_key == r.model_key]
        same_year = [o for o in same_model
                     if abs(o.year_jalali - r.year_jalali) <= self.year_tolerance]
        strict = [o for o in same_year
                  if r.mileage_km <= 0 or
                  abs(o.mileage_km - r.mileage_km)
                  <= self.mileage_rel_tolerance * max(r.mileage_km, 1)]
        if len(strict) >= self.min_comparables:
            return [o.asking_asking_price_toman for o in strict], "strict"
        if len(same_year) >= self.min_comparables:
            return [o.asking_asking_price_toman for o in same_year], "relaxed_mileage"
        if len(same_model) >= self.min_comparables:
            return [o.asking_asking_price_toman for o in same_model], "relaxed_year"
        if same_model:
            return [o.asking_asking_price_toman for o in same_model], "model_only"
        return [], "global"

    def evidence(self, r: Row) -> ComparableEvidence:
        c, tier = self._comparables(r)
        if not c:
            return ComparableEvidence(0, "global", float("nan"))
        a = np.asarray(c, dtype=float)
        med = float(np.median(a))
        iqr = float(np.quantile(a, 0.75) - np.quantile(a, 0.25))
        return ComparableEvidence(len(c), tier, (iqr / med) if med else float("nan"))

    def tier_histogram(self, rows: Sequence[Row]) -> dict[MatchTier, int]:
        """Which rung each prediction actually came from. Belongs in EVAL.md:
        a model whose estimates mostly come from `model_only` is not doing
        comparable pricing, whatever its pinball loss says."""
        h: dict[MatchTier, int] = {}
        for r in rows:
            h[self._comparables(r)[1]] = h.get(self._comparables(r)[1], 0) + 1
        return dict(sorted(h.items(), key=lambda kv: TIER_RANK[kv[0]]))

    def predict(self, rows: Sequence[Row]) -> np.ndarray:
        allp = np.array([o.asking_asking_price_toman for o in self._rows], dtype=float)
        glob = np.quantile(allp, self.quantiles) if allp.size else np.zeros(len(self.quantiles))
        out = np.empty((len(rows), len(self.quantiles)))
        for i, r in enumerate(rows):
            c, _ = self._comparables(r)
            out[i] = np.quantile(np.asarray(c, dtype=float), self.quantiles) if c else glob
        return rearrange_monotone(out)


@dataclass
class GlobalQuantiles:
    """The floor: ignore every feature, return the corpus quantiles.

    Any estimator that cannot beat THIS is not modelling anything.
    """
    quantiles: Sequence[float] = QUANTILES
    _q: np.ndarray | None = None

    def fit(self, rows: Sequence[Row]) -> "GlobalQuantiles":
        p = np.array([r.asking_asking_price_toman for r in rows], dtype=float)
        self._q = np.quantile(p, self.quantiles) if p.size else np.zeros(len(self.quantiles))
        return self

    def predict(self, rows: Sequence[Row]) -> np.ndarray:
        return np.tile(self._q, (len(rows), 1))


def _ridge_fit(X: np.ndarray, y: np.ndarray,
               alpha: float) -> tuple[np.ndarray, float]:
    """Closed-form ridge: w = (X'X + aI)^-1 X'y, on centred data.

    Written out rather than imported. Ridge regression is four lines of
    linear algebra, and depending on scikit-learn for it costs a heavyweight
    install that lags new Python releases by months — which is exactly the
    kind of friction that stops a reviewer before they see a test pass.
    numpy is the only hard dependency this project has.
    """
    Xm, ym = X.mean(axis=0), float(y.mean())
    Xc, yc = X - Xm, y - ym
    n_features = Xc.shape[1]
    A = Xc.T @ Xc + alpha * np.eye(n_features)
    coef = np.linalg.solve(A, Xc.T @ yc)
    return coef, ym - float(Xm @ coef)


@dataclass
class LogLinearQuantiles:
    """Baseline C: ridge on log-price, quantiles from the residual distribution.

    The missing rung between "empirical comparables" and "gradient boosting".
    It borrows strength across models the way comparables cannot, stays
    fully interpretable, and on a few thousand rows it is frequently the
    thing that wins. Assumes homoscedastic residuals in log space — which is
    exactly the assumption a GBM is supposed to earn its keep by relaxing,
    so this is the right thing to make it beat.
    """
    quantiles: Sequence[float] = QUANTILES
    alpha: float = 1.0
    _coef: np.ndarray | None = None
    _intercept: float = 0.0
    _cols: list[str] = field(default_factory=list)
    _resid_q: np.ndarray | None = None

    def _design(self, rows: Sequence[Row], fit: bool = False) -> np.ndarray:
        if fit:
            self._cols = sorted({r.model_key for r in rows})
        X = np.zeros((len(rows), len(self._cols) + 2))
        for i, r in enumerate(rows):
            if r.model_key in self._cols:
                X[i, self._cols.index(r.model_key)] = 1.0
            X[i, -2] = r.year_jalali
            X[i, -1] = r.mileage_km / 1e5
        return X

    def fit(self, rows: Sequence[Row]) -> "LogLinearQuantiles":
        X = self._design(rows, fit=True)
        y = np.log(np.array([r.asking_asking_price_toman for r in rows], dtype=float))
        self._coef, self._intercept = _ridge_fit(X, y, self.alpha)
        self._resid_q = np.quantile(y - self._raw_predict(X), self.quantiles)
        return self

    def _raw_predict(self, X: np.ndarray) -> np.ndarray:
        return X @ self._coef + self._intercept

    def predict(self, rows: Sequence[Row]) -> np.ndarray:
        mu = self._raw_predict(self._design(rows))
        return rearrange_monotone(np.exp(mu[:, None] + self._resid_q[None, :]))


# ---------------------------------------------------------------------------
# The benchmark
# ---------------------------------------------------------------------------

@dataclass
class RunMetadata:
    """Stamped on every benchmark so a number can be traced to what produced it.

    Without this, "pinball = 113M" six days from now is unattributable.
    """
    dataset: str = "unspecified"
    dataset_version: str = "unspecified"
    split_cutoff: int = -1
    cluster_algorithm_version: str = "unspecified"
    feature_schema_version: str = "unspecified"
    seed: int = -1


@dataclass
class BenchmarkResult:
    name: str
    overall: SliceResult
    slices: list[SliceResult]
    crossing_rate_before_rearrange: float
    mean_pinball: float
    meta: RunMetadata = field(default_factory=RunMetadata)

    def worst_slice(self) -> SliceResult | None:
        """Worst slice by NOISE-ADJUSTED error, among slices big enough to read."""
        rel = [s for s in self.slices if s.reliable]
        return max(rel, key=lambda s: s.significant_coverage_error()) if rel else None


def run_benchmark(est: Estimator, split: Split, *, name: str,
                  quantiles: Sequence[float] = QUANTILES,
                  meta: RunMetadata | None = None) -> BenchmarkResult:
    est.fit(split.train)
    raw = np.asarray(est.predict(split.test), dtype=float)
    cr = crossing_rate(raw)
    preds = rearrange_monotone(raw)
    y = np.array([r.asking_asking_price_toman for r in split.test], dtype=float)

    overall = evaluate(y, preds, name="overall", quantiles=quantiles)
    slices = []
    for sname, idx in slice_rows(split.test, preds, quantiles).items():
        ix = np.array(idx, dtype=int)
        slices.append(evaluate(y[ix], preds[ix], name=sname, quantiles=quantiles))

    return BenchmarkResult(
        name=name, overall=overall, slices=slices,
        crossing_rate_before_rearrange=cr,
        mean_pinball=float(np.mean(list(overall.pinball_by_tau.values()))),
        meta=meta or RunMetadata(split_cutoff=split.cutoff_ordinal),
    )


# ---------------------------------------------------------------------------
# The gate — no market-estimate claim before the benchmark passes
# ---------------------------------------------------------------------------

@dataclass
class AcceptanceGate:
    max_coverage_error: float = 0.07      # |empirical - nominal| per quantile
    max_worst_slice_error: float = 0.12   # same, inside any reliable slice
    max_crossing_rate: float = 0.0        # crossing must be fixed, not tolerated
    require_beats: str | None = "comparable-quantiles"

    def check(self, result: BenchmarkResult,
              baselines: dict[str, BenchmarkResult]) -> tuple[bool, list[str]]:
        fails: list[str] = []
        if result.overall.n == 0:
            return False, ["empty test set"]
        if result.overall.max_abs_coverage_error > self.max_coverage_error:
            fails.append(
                f"overall coverage error {result.overall.max_abs_coverage_error:.3f} "
                f"> {self.max_coverage_error}")
        ws = result.worst_slice()
        if ws and ws.significant_coverage_error() > self.max_worst_slice_error:
            fails.append(
                f"worst slice '{ws.name}' (n={ws.n}) coverage error "
                f"{ws.significant_coverage_error():.3f} > {self.max_worst_slice_error} "
                "(beyond sampling noise)")
        if result.crossing_rate_before_rearrange > self.max_crossing_rate:
            fails.append(
                f"quantile crossing on {result.crossing_rate_before_rearrange:.1%} "
                "of rows — rearranged for safety, but fix the cause")
        if self.require_beats and self.require_beats in baselines:
            b = baselines[self.require_beats]
            if result.mean_pinball >= b.mean_pinball:
                fails.append(
                    f"does not beat {self.require_beats}: pinball "
                    f"{result.mean_pinball:.0f} >= {b.mean_pinball:.0f} — "
                    "ship the baseline instead")
        return (not fails), fails


class NotBenchmarked(RuntimeError):
    pass


@dataclass
class MarketEstimator:
    """Wraps an estimator and REFUSES to serve until the gate passes.

    The honesty rule is enforced here rather than documented: a model that
    has not been benchmarked cannot physically produce a number the product
    could display.
    """
    estimator: Estimator
    gate: AcceptanceGate = field(default_factory=AcceptanceGate)
    _approved: bool = False
    _report: BenchmarkResult | None = None

    def benchmark(self, split: Split, baselines: dict[str, BenchmarkResult],
                  *, name: str = "candidate") -> tuple[bool, list[str]]:
        self._report = run_benchmark(self.estimator, split, name=name)
        self._approved, fails = self.gate.check(self._report, baselines)
        return self._approved, fails

    def predict(self, rows: Sequence[Row]) -> np.ndarray:
        if not self._approved:
            raise NotBenchmarked(
                "market estimates are not available: this estimator has not "
                "passed AcceptanceGate. Run benchmark() first.")
        return rearrange_monotone(np.asarray(self.estimator.predict(rows), dtype=float))


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def format_report(results: dict[str, BenchmarkResult], split: Split,
                  quantiles: Sequence[float] = QUANTILES) -> str:
    L = ["SPLIT", "─" * 62,
         f"train rows          : {len(split.train)}",
         f"test rows           : {len(split.test)}",
         f"dropped (straddling): {split.dropped_straddling}   ← leakage risk",
         f"long-span clusters  : {split.long_span_clusters} "
         f"({split.long_span_rows} rows)  ← KEPT, not dropped",
         f"cluster leakage     : {len(split.leakage())}  (must be 0)",
         f"distribution shift  : {distribution_shift(split)}",
         "",
         "MODELS  (y = ASKING price; this estimates asking-price quantiles)",
         "─" * 62,
         f"{'model':<26}{'pinball':>12}{'cross':>8}{'max cov err':>14}"]
    for name, r in sorted(results.items(), key=lambda kv: kv[1].mean_pinball):
        L.append(f"{name:<26}{r.mean_pinball:>12,.0f}"
                 f"{r.crossing_rate_before_rearrange:>7.1%}"
                 f"{r.overall.max_abs_coverage_error:>14.3f}")
    best = min(results.values(), key=lambda r: r.mean_pinball)
    L += ["", f"COVERAGE — {best.name}", "─" * 62,
          "  τ      nominal   empirical   error   95% CI (Wilson)"]
    for t in quantiles:
        c = best.overall.coverage_by_tau[t]
        lo, hi = best.overall.coverage_ci(t)
        mark = "" if best.overall.nominal_inside_ci(t) else "   ← nominal outside 95% CI"
        L.append(f"  {t:<6.2f} {t:>7.2f}   {c:>9.3f}   {c - t:>+7.3f}"
                 f"   [{lo:.3f}, {hi:.3f}]{mark}")
    L.append(f"  interval [{quantiles[0]}, {quantiles[-1]}] coverage: "
             f"{best.overall.interval_coverage_15_85:.3f} "
             f"(nominal {quantiles[-1] - quantiles[0]:.2f})")
    ws = best.worst_slice()
    if ws:
        L += ["", "WORST RELIABLE SLICE — report this, do not hide it", "─" * 62,
              f"  {ws.name}  (n={ws.n})  raw max error "
              f"{ws.max_abs_coverage_error:.3f}  ·  beyond-noise "
              f"{ws.significant_coverage_error():.3f}"]
        for t in quantiles:
            L.append(f"    τ={t:.2f}  empirical {ws.coverage_by_tau[t]:.3f}")
    thin = [s for s in best.slices if not s.reliable]
    if thin:
        L.append(f"\n  {len(thin)} slices below n={MIN_SLICE_N} — rates not "
                 "reported for these; they are ignorance, not performance")
    return "\n".join(L)
