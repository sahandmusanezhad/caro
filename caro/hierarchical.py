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
from enum import Enum
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
    _tau2: float = 0.0
    _resid_var: float = 1.0

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

        self._tau2 = float(tau2)
        fitted = self._raw_predict(rows)
        resid_after = y - fitted
        self._resid_q = np.quantile(resid_after, self.quantiles)
        self._resid_var = float(np.var(resid_after)) or 1e-12
        return self

    def _raw_predict(self, rows: Sequence[Row]) -> np.ndarray:
        X = self._design(rows)
        base = X @ self._coef + self._intercept
        off = np.array([self._offsets.get(r.model_key, 0.0) for r in rows])
        return base + off

    def _interval_scale(self, rows: Sequence[Row]) -> np.ndarray:
        """Widen the band by the trim offset we did NOT get to observe.

        The tests caught this, and it is the second real flaw they have found
        here. Training residuals are computed AFTER each trim's offset has
        been applied, so they describe within-trim scatter for trims we have
        seen. For a trim we have not seen — or have shrunk heavily — the
        offset itself is unknown, and its variance belongs in the predictive
        interval.

            predictive variance ≈ σ²_within + (1 − λ_t)² · τ²

        Held-out-trim coverage was 12% against a nominal 70% before this: the
        point estimate fell back to the parent, correctly, while the band
        stayed as tight as if the trim were fully observed. That is precisely
        "more confident and less right", and the gate rejected it.

        Widening rather than refusing is right here because the uncertainty
        is real and quantified: an unseen trim genuinely can be priced from
        its parent, as long as the interval admits how much it might differ.
        """
        lam = np.array([self._lam.get(r.model_key, 0.0) for r in rows])
        extra = ((1.0 - lam) ** 2) * self._tau2
        return np.sqrt(1.0 + extra / self._resid_var)

    def predict(self, rows: Sequence[Row]) -> np.ndarray:
        """Bare quantiles. For BENCHMARKING only — see `predict_traced`."""
        mu = self._raw_predict(rows)
        scale = self._interval_scale(rows)
        out = np.exp(mu[:, None] + self._resid_q[None, :] * scale[:, None])
        return rearrange_monotone(out)

    def predict_traced(self, rows: Sequence[Row]) -> list["TracedEstimate"]:
        """The serving path: every number arrives attached to its provenance."""
        preds = self.predict(rows)
        return [TracedEstimate(preds[i], self.trace(r))
                for i, r in enumerate(rows)]

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


# ---------------------------------------------------------------------------
# The trace is part of the OUTPUT, not a log line
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TracedEstimate:
    """A prediction that cannot be separated from how it was made.

    `predict()` returns bare numbers and is kept only for benchmarking, where
    the caller is a metric function that has no user to mislead. Anything
    that serves a person goes through `predict_traced()`, because a
    downstream that CAN drop the trace eventually will — not maliciously, but
    because an array is easier to pass around than a pair, and the version
    that drops it looks like it works.
    """
    quantiles: np.ndarray       # the prices
    trace: PoolingTrace

    @property
    def median(self) -> float:
        return float(self.quantiles[len(self.quantiles) // 2])

    def __str__(self) -> str:
        return f"{self.median:,.0f} toman\n  {self.trace.explain()}"


# ---------------------------------------------------------------------------
# Slice metrics — an average over a corpus dominated by fat trims sees nothing
# ---------------------------------------------------------------------------

# Derived, not chosen. To detect a 15-point coverage deviation at 2.5 binomial
# standard errors you need 2.5·sqrt(0.7·0.3/n) < 0.15, i.e. n > 58. Below that
# a slice cannot support a calibration verdict at all — and the honest
# response is to say so, not to lower z until a small slice starts producing
# opinions. W1 reached the same conclusion at MIN_SLICE_N = 150 for its own
# error metric; this is the same arithmetic at a looser tolerance.
MIN_SLICE_N = 58
NOMINAL_COVERAGE = 0.70  # the [q15, q85] band


@dataclass(frozen=True)
class SliceMetrics:
    name: str
    n: int
    mae: float
    median_ae: float
    coverage: float          # share of truths inside [q15, q85]
    coverage_error: float    # |coverage - nominal|
    mean_shrinkage: float
    extrapolation_rate: float

    @property
    def reliable(self) -> bool:
        return self.n >= MIN_SLICE_N

    @property
    def coverage_se(self) -> float:
        """Binomial standard error of the coverage estimate itself."""
        import math
        if self.n <= 0:
            return 1.0
        t = NOMINAL_COVERAGE
        return math.sqrt(max(t * (1 - t), 1e-9) / self.n)

    def significant_coverage_error(self, z: float = 2.5) -> float:
        """Coverage error beyond what sampling noise explains.

        The same correction W1 needed and for the same reason — and this
        module repeated the mistake before the tests caught it. On an
        18-listing slice the coverage estimate carries a standard error of
        about 11 points, so a 19-point deviation is under two SE and is not
        evidence of anything. Judging several slices on raw deviation picks
        the noisiest one every time (winner's curse), which on a corpus with
        a long thin tail means the gate would reject every model, including
        correct ones.

        A gate that always fails is exactly as useless as one that always
        passes.
        """
        excess = self.coverage_error - z * self.coverage_se
        return max(0.0, excess)

    def line(self) -> str:
        flag = "" if self.reliable else "   (thin — metrics are noise)"
        return (f"  {self.name:<22}{self.n:>5}{self.mae:>13,.0f}"
                f"{self.median_ae:>13,.0f}{self.coverage:>10.0%}"
                f"{self.coverage_error:>9.0%}{self.mean_shrinkage:>8.2f}"
                f"{self.extrapolation_rate:>8.0%}{flag}")


def slice_metrics(model, rows: Sequence[Row], name: str) -> SliceMetrics | None:
    if not rows:
        return None
    preds = model.predict(rows)
    truth = np.array([r.asking_price_toman for r in rows], dtype=float)
    med = preds[:, len(model.quantiles) // 2]
    lo, hi = preds[:, 0], preds[:, -1]
    cov = float(np.mean((truth >= lo) & (truth <= hi)))
    traces = [model.trace(r) for r in rows]
    return SliceMetrics(
        name=name, n=len(rows),
        mae=float(np.mean(np.abs(med - truth))),
        median_ae=float(np.median(np.abs(med - truth))),
        coverage=cov, coverage_error=abs(cov - NOMINAL_COVERAGE),
        mean_shrinkage=float(np.mean([t.shrinkage for t in traces])),
        extrapolation_rate=float(np.mean(
            [t.material_extrapolation for t in traces])))


def four_slices(model, test: Sequence[Row], train_counts: dict[str, int],
                held_out: Sequence[Row] = ()) -> list[SliceMetrics]:
    """The four questions, each of which the aggregate cannot answer.

        well-observed   does pooling BREAK anything that already worked?
        thin            does shrinkage help without hiding the data's weakness?
        held-out trim   does the parent actually generalise?
        worst model×trim where is the worst slice we can still trust?
    """
    out = []
    fat = [r for r in test if train_counts.get(r.model_key, 0) > THIN_TRIM_MAX]
    thin = [r for r in test if 0 < train_counts.get(r.model_key, 0) <= THIN_TRIM_MAX]
    for rows, nm in ((fat, "well-observed trim"), (thin, "thin trim"),
                     (list(held_out), "held-out trim")):
        m = slice_metrics(model, rows, nm)
        if m:
            out.append(m)

    by_key: dict[str, list[Row]] = {}
    for r in test:
        by_key.setdefault(r.model_key, []).append(r)
    per = [m for m in (slice_metrics(model, v, k.split("|")[-1] or k)
                       for k, v in by_key.items()) if m and m.reliable]
    if per:
        worst = max(per, key=lambda m: m.coverage_error)
        out.append(SliceMetrics(f"worst reliable: {worst.name}"[:22], worst.n,
                                worst.mae, worst.median_ae, worst.coverage,
                                worst.coverage_error, worst.mean_shrinkage,
                                worst.extrapolation_rate))
    return out


# ---------------------------------------------------------------------------
# Acceptance — conjunctive, and with NO silent fallback
# ---------------------------------------------------------------------------

class ReasonKind(str, Enum):
    """Why the gate is refusing — as a value, not as a turn of phrase.

    `verdict` used to sort reasons by asking whether the words "cannot judge"
    appeared in them. Two branches of one idea were worded differently and
    one of them routed wrong: a slice that was ENTIRELY ABSENT said "the gate
    cannot pass on evidence it does not have", which contains no such phrase,
    so a corpus that measured nothing came back REJECTED — "the model was
    measured and found wanting". That is the exact conflation the verdict
    enum exists to prevent, sitting inside the code that enforces it.

    Measured on a 71-row corpus: two required slices missing, nothing
    assessed, verdict REJECTED.

    The message is for a person. This is the contract.
    """
    EVIDENCE_MISSING = "evidence_missing"    # the corpus cannot answer
    MEASURED_FAILURE = "measured_failure"    # the model was assessed and failed


class GateReason(str):
    """A refusal message that also carries WHY it is a refusal.

    A `str` subclass rather than a dataclass, on purpose: every existing
    caller — the benchmark scripts, `serve_or_refuse`, the suites — treats a
    reason as text and prints it or searches it. Changing that shape would
    have meant editing all of them to gain nothing, and a migration that
    touches ten files to fix one classification is a migration that
    introduces its own defect.
    """

    kind: ReasonKind
    subject: str

    def __new__(cls, message: str, kind: ReasonKind, subject: str = ""):
        self = super().__new__(cls, message)
        self.kind = kind
        self.subject = subject
        return self


@dataclass
class HierarchicalGate:
    """Every condition must hold. Failing any of them means NOT ACCEPTED.

    Deliberately not `hierarchical_mae < baseline_mae`. A model that improves
    the average while breaking interval coverage has become more confident
    and less right, which for an appraisal product is a worse failure than
    being a little further off with honest bands.

    The last clause is the one that matters most in practice: when this gate
    rejects, the answer is NOT_ACCEPTED — never a quiet re-run of the pooled
    estimator whose output is then served as a conditional appraisal. That
    substitution would undo D30, D31 and D32 in one line of orchestration
    code, and it is the kind of line that gets written to make a demo work.
    """
    max_coverage_error: float = 0.15
    max_worst_slice_coverage_error: float = 0.25
    z: float = 2.5               # SEs a deviation must clear to count
    mae_tolerance: float = 1.10          # may be up to 10% worse than baseline
    require_trace_observable: bool = True

    def verdict(self, slices: Sequence[SliceMetrics], *,
                baseline_mae: float, model_mae: float,
                population_weighted: bool = False
                ) -> tuple["GateVerdict", list[str], list[str]]:
        """(verdict, demonstrated failures, unanswered questions).

        Ordering is deliberate: a demonstrated failure on a slice we COULD
        judge outranks an unjudgeable one. Being measurably wrong is worse
        news than being unmeasured, and reporting UNJUDGEABLE when a real
        failure is already visible would understate what is known.
        """
        ok, all_reasons = self.check(
            slices, baseline_mae=baseline_mae, model_mae=model_mae,
            population_weighted=population_weighted)
        # On the KIND, never on the wording. A reason that has to announce
        # its own category in prose is a reason whose category depends on
        # whoever wrote the sentence.
        # `r not in unjudged` would have compared by VALUE, since a reason is
        # a str — two reasons with identical text and different kinds would
        # collapse into one. Both lists are built from the kind directly.
        unjudged = [r for r in all_reasons
                    if getattr(r, "kind", None) is ReasonKind.EVIDENCE_MISSING]
        failed = [r for r in all_reasons
                  if getattr(r, "kind", None) is not ReasonKind.EVIDENCE_MISSING]
        if failed:
            return GateVerdict.REJECTED, failed, unjudged
        if unjudged:
            return GateVerdict.UNJUDGEABLE, [], unjudged
        return GateVerdict.ACCEPTED, [], []

    def check(self, slices: Sequence[SliceMetrics], *,
              baseline_mae: float, model_mae: float,
              population_weighted: bool = False
              ) -> tuple[bool, list[GateReason]]:
        fails: list[GateReason] = []

        if model_mae > baseline_mae * self.mae_tolerance:
            fails.append(GateReason(
                f"MAE {model_mae:,.0f} is worse than the baseline "
                f"{baseline_mae:,.0f} by more than "
                f"{(self.mae_tolerance - 1):.0%}",
                ReasonKind.MEASURED_FAILURE, "mae"))

        reliable = [s for s in slices if s.reliable]
        for s in reliable:
            if s.significant_coverage_error(self.z) > self.max_coverage_error:
                fails.append(GateReason(
                    f"'{s.name}' interval coverage is {s.coverage:.0%} "
                    f"against a nominal {NOMINAL_COVERAGE:.0%} "
                    f"(±{s.coverage_se:.0%} noise on n={s.n}) — a better "
                    "average with broken bands is more confident and less "
                    "right",
                    ReasonKind.MEASURED_FAILURE, s.name))
        worst = max((s.significant_coverage_error(self.z) for s in reliable),
                    default=0.0)
        if worst > self.max_worst_slice_coverage_error:
            fails.append(GateReason(
                f"worst reliable slice is off by {worst:.0%}",
                ReasonKind.MEASURED_FAILURE, "worst reliable slice"))

        by_name = {s.name: s for s in slices}
        if self.require_trace_observable:
            for needed in ("thin trim", "held-out trim"):
                s = by_name.get(needed)
                if s is None:
                    # Nothing was measured here. That is the corpus failing
                    # to answer, not the model failing — and it used to be
                    # classified the other way because this sentence happens
                    # not to contain the words the sorter looked for.
                    fails.append(GateReason(
                        f"'{needed}' behaviour was not measured — the gate "
                        "cannot pass on evidence it does not have",
                        ReasonKind.EVIDENCE_MISSING, needed))
                elif not s.reliable:
                    # The distinction that matters: this is not "the model
                    # failed", it is "the corpus cannot answer". Passing here
                    # would let a model be accepted precisely where it was
                    # never tested.
                    fails.append(GateReason(
                        f"'{needed}' has n={s.n}, below the {MIN_SLICE_N} a "
                        "calibration verdict needs. NOT a model failure — "
                        "the corpus cannot judge this slice, and the gate "
                        "does not pass on an unanswered question",
                        ReasonKind.EVIDENCE_MISSING, needed))

        if population_weighted:
            # A thing the estimator DID, observed. Not a gap in the corpus.
            fails.append(GateReason(
                "the estimator introduced population weighting; "
                "P(inclusion) is unknown (D29) and no weight may be derived "
                "from the sample's own shape",
                ReasonKind.MEASURED_FAILURE, "population weighting"))

        return (not fails), fails


class GateVerdict(str, Enum):
    """Three outcomes, and the third is not a shade of the other two.

    REJECTED   the model was measured and found wanting.
    UNJUDGEABLE the corpus cannot answer the question. NOT a model failure —
               and emphatically not a pass. Folding it into either would let
               a model be accepted where it was never tested, or condemned
               for evidence nobody has.

    CARO already reports uncertainty about prices. This reports uncertainty
    about its own ability to assess uncertainty, which is the layer that
    normally goes unstated and is exactly where an unearned claim hides.
    """
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    UNJUDGEABLE = "UNJUDGEABLE_SLICE"


class NotAccepted(RuntimeError):
    """The hierarchical estimator failed its gate.

    Raised INSTEAD of returning a pooled estimate. There is no fallback path
    on purpose: a conditional appraisal that quietly becomes a pooled one is
    the exact claim D30 refused, and it would be indistinguishable in the
    output.
    """


def serve_or_refuse(model, rows: Sequence[Row], accepted: bool
                    ) -> list[TracedEstimate]:
    if not accepted:
        raise NotAccepted(
            "the partial-pooling estimator did not pass its gate. No "
            "conditional appraisal is available, and the pooled estimator is "
            "NOT substituted — it answers a different question (D30/D32).")
    preds = model.predict(rows)
    return [TracedEstimate(preds[i], model.trace(r))
            for i, r in enumerate(rows)]
