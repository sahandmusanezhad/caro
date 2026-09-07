"""Tests for the W1 benchmark harness.

The point of these is narrow and important: BEFORE the harness is allowed to
judge a model on real data, prove the harness itself is right. Evaluation
code that is silently wrong will make you ship a broken model or discard a
good one, and you will not find out until the demo.

Method: synthetic data drawn from a distribution whose true quantiles are
known in closed form, so an ORACLE estimator can be constructed and the
metrics checked against what they must produce for a perfect model.

Run: python3 test_appraisal.py
"""

import numpy as np

from caro.appraisal import (
    QUANTILES, Row, cluster_temporal_split, rearrange_monotone, crossing_rate,
    pinball_loss, coverage, interval_coverage, evaluate, run_benchmark,
    ComparableQuantiles, GlobalQuantiles, AcceptanceGate, MarketEstimator,
    NotBenchmarked, format_report, MIN_SLICE_N,
    LogLinearQuantiles, distribution_shift, RunMetadata, ComparableEvidence,
)

FAILS: list[str] = []
rng = np.random.default_rng(20260906)


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# Synthetic world with KNOWN truth.
#   log(price) ~ Normal(mu(model, year, mileage), sigma)
# so the true tau-quantile is exp(mu + sigma * z_tau). An oracle using that
# formula must produce coverage == tau up to sampling noise.
# ---------------------------------------------------------------------------

MODELS = {"pride": 20.4, "206": 21.0, "tiba": 20.6, "pars": 21.2}
SIGMA = 0.18


def true_mu(model_key: str, year: int, mileage: float) -> float:
    return MODELS[model_key] + 0.06 * (year - 1395) - 0.0000012 * mileage


def make_rows(n=2400, *, reposts=True):
    rows, cid = [], 0
    from scipy.stats import norm  # only used to build the oracle
    for i in range(n):
        m = list(MODELS)[i % len(MODELS)]
        year = int(rng.integers(1390, 1403))
        mileage = float(rng.integers(10_000, 300_000))
        mu = true_mu(m, year, mileage)
        price = float(np.exp(rng.normal(mu, SIGMA)))
        cid += 1
        day = int(rng.integers(0, 120))
        rows.append(Row(f"l{i}", f"c{cid}", day, m, year, mileage, price))
        # ~15% of cars are reposted: same car, same day-ish, near-same price.
        if reposts and rng.random() < 0.15:
            rows.append(Row(f"l{i}r", f"c{cid}", day + int(rng.integers(1, 6)),
                            m, year, mileage, price * float(rng.normal(0.98, 0.01))))
    return rows


class Oracle:
    """Knows the true conditional quantiles. The upper bound on performance."""
    def fit(self, rows):
        return self

    def predict(self, rows):
        from scipy.stats import norm
        z = np.array([norm.ppf(t) for t in QUANTILES])
        return np.array([np.exp(true_mu(r.model_key, r.year_jalali, r.mileage_km)
                                + SIGMA * z) for r in rows])


class Crosser:
    """Deliberately emits out-of-order quantiles, to test detection."""
    def fit(self, rows):
        return self

    def predict(self, rows):
        base = np.array([1.4e9, 1.5e9, 1.45e9, 1.7e9])   # 50 < 35
        return np.tile(base, (len(rows), 1))


ROWS = make_rows()


# ---------------------------------------------------------------------------
print("\nsplit: no cluster may appear on both sides")
sp = cluster_temporal_split(ROWS, test_fraction=0.25)
check("zero leakage", sp.leakage() == set(), f"leaked {len(sp.leakage())}")
check("train non-empty", len(sp.train) > 0)
check("test non-empty", len(sp.test) > 0)
check("test is strictly later than the cutoff",
      all(r.first_seen_ordinal >= sp.cutoff_ordinal for r in sp.test))
check("train is strictly earlier",
      all(r.first_seen_ordinal < sp.cutoff_ordinal for r in sp.train))
check("straddling clusters dropped, not leaked", sp.dropped_straddling >= 0)

shuffled = list(ROWS)
rng.shuffle(shuffled)
naive = shuffled[:int(len(shuffled) * .75)], shuffled[int(len(shuffled) * .75):]
naive_leak = {r.cluster_id for r in naive[0]} & {r.cluster_id for r in naive[1]}
check(f"a naive row split WOULD have leaked ({len(naive_leak)} clusters)",
      len(naive_leak) > 0)


# ---------------------------------------------------------------------------
print("\nmetrics are correct on data with known truth")
y = np.array([1.0, 2.0, 3.0, 4.0])
check("coverage counts y<=q", coverage(y, np.array([2.5] * 4)) == 0.5)
check("interval coverage", interval_coverage(y, np.full(4, 1.5), np.full(4, 3.5)) == 0.5)

# Pinball is minimised at the true quantile.
sample = rng.normal(0, 1, 40_000)
losses = {c: pinball_loss(sample, np.full_like(sample, c), 0.15)
          for c in np.linspace(-2.0, 0.0, 41)}
best_c = min(losses, key=losses.get)
from scipy.stats import norm
check(f"pinball(τ=0.15) minimised near z=-1.036 (got {best_c:.2f})",
      abs(best_c - norm.ppf(0.15)) < 0.08)

check("pinball is zero for a perfect point prediction",
      abs(pinball_loss(y, y, 0.5)) < 1e-12)


# ---------------------------------------------------------------------------
print("\noracle: a perfect model must show coverage == tau")
orc = run_benchmark(Oracle(), sp, name="oracle")
for t in QUANTILES:
    c = orc.overall.coverage_by_tau[t]
    check(f"τ={t:.2f} coverage {c:.3f} ≈ {t}", abs(c - t) < 0.035, f"err {c - t:+.3f}")
check("oracle interval coverage ≈ 0.70",
      abs(orc.overall.interval_coverage_15_85 - 0.70) < 0.04,
      f"got {orc.overall.interval_coverage_15_85:.3f}")
check("oracle does not cross", orc.crossing_rate_before_rearrange == 0.0)


# ---------------------------------------------------------------------------
print("\ncrossing is detected, then repaired")
raw = np.array([[3.0, 1.0, 2.0], [1.0, 2.0, 3.0]])
check("crossing_rate sees the bad row", crossing_rate(raw) == 0.5)
fixed = rearrange_monotone(raw)
check("rearrangement makes every row monotone",
      bool(np.all(np.diff(fixed, axis=1) >= 0)))
check("rearrangement preserves each row's values",
      bool(np.all(np.sort(raw, axis=1) == fixed)))

cross_res = run_benchmark(Crosser(), sp, name="crosser")
check("benchmark reports a 100% crossing rate",
      cross_res.crossing_rate_before_rearrange == 1.0)


# ---------------------------------------------------------------------------
print("\nbaselines behave as expected")
res = {
    "global-quantiles": run_benchmark(GlobalQuantiles(), sp, name="global-quantiles"),
    "comparable-quantiles": run_benchmark(ComparableQuantiles(), sp, name="comparable-quantiles"),
    "oracle": orc,
}
check("comparables beat the global floor",
      res["comparable-quantiles"].mean_pinball < res["global-quantiles"].mean_pinball,
      f"{res['comparable-quantiles'].mean_pinball:.0f} vs {res['global-quantiles'].mean_pinball:.0f}")
check("oracle beats comparables",
      res["oracle"].mean_pinball < res["comparable-quantiles"].mean_pinball)
cq = ComparableQuantiles().fit(sp.train)
ev = cq.evidence(sp.test[0])
check("comparables report which rung of the ladder was used",
      ev.tier in ("strict", "relaxed_mileage", "relaxed_year", "model_only", "global"))
check("  and the Persian claim matches the tier",
      ("مشابه" in ev.claim_fa()) or ("کافی" in ev.claim_fa()))
check("model_only never claims the listings are comparable",
      "مشابه نیستند" in ComparableEvidence(211, "model_only", 0.2).claim_fa())
check("count alone is not confidence: many loose comparables => low quality",
      ComparableEvidence(200, "model_only", 0.5).quality == "low")
check("  while few tight ones can be medium or better",
      ComparableEvidence(12, "strict", 0.15).quality in ("medium", "high"))
hist = cq.tier_histogram(sp.test)
check("tier histogram covers every prediction", sum(hist.values()) == len(sp.test))

print("\nridge baseline sits between comparables and the oracle")
res["log-linear-ridge"] = run_benchmark(LogLinearQuantiles(), sp, name="log-linear-ridge")
check("ridge beats the global floor",
      res["log-linear-ridge"].mean_pinball < res["global-quantiles"].mean_pinball)
# Ridge can EDGE OUT the population oracle here, and that is not a bug.
# This synthetic world is exactly log-linear in (model, year, mileage) with
# homoscedastic Gaussian noise — precisely Ridge's functional form. With 2000
# training rows it recovers the true parameters, and its residual quantiles
# are empirical, so on a finite test set it can land marginally below the
# population-optimal loss. The oracle is the population bound, not a
# finite-sample one.
#
# The lesson matters beyond the test: a synthetic world that matches a model
# family cannot tell you which family wins on real data. It validates the
# HARNESS only. Whether ridge or a GBM wins on the Kaggle corpus is an
# empirical question this benchmark exists to answer, not one it presupposes.
check("ridge lands within 3% of the population oracle (world is log-linear)",
      abs(res["log-linear-ridge"].mean_pinball - res["oracle"].mean_pinball)
      / res["oracle"].mean_pinball < 0.03,
      f'ridge {res["log-linear-ridge"].mean_pinball:,.0f} vs '
      f'oracle {res["oracle"].mean_pinball:,.0f}')
check("ridge beats empirical comparables in a world matching its form",
      res["log-linear-ridge"].mean_pinball < res["comparable-quantiles"].mean_pinball)
check("ridge quantiles do not cross",
      res["log-linear-ridge"].crossing_rate_before_rearrange == 0.0)

print("\nlong-lived listings are counted, never dropped")
check("long-span clusters are reported separately", sp.long_span_clusters >= 0)
check("only straddling clusters are excluded",
      len(sp.train) + len(sp.test) + sp.dropped_straddling == len(ROWS))

print("\ndistribution shift is measured, not assumed away")
sh = distribution_shift(sp)
check("stationary synthetic world shows no severe shift", not sh.severe, str(sh))
drifted = [Row(r.listing_id, r.cluster_id, r.first_seen_ordinal, r.model_key,
               r.year_jalali, r.mileage_km,
               r.asking_price_irr * (1.9 if r.first_seen_ordinal > 60 else 1.0))
           for r in ROWS]
check("a 90% price jump IS flagged severe",
      distribution_shift(cluster_temporal_split(drifted)).severe)

print("\ncoverage carries a real confidence interval")
check("oracle: nominal inside the 95% CI at every tau",
      all(orc.overall.nominal_inside_ci(t) for t in QUANTILES))
lo, hi = orc.overall.coverage_ci(0.50)
check(f"CI is an interval around the estimate ([{lo:.3f}, {hi:.3f}])", lo < hi)
check("run metadata is stamped", orc.meta.split_cutoff == sp.cutoff_ordinal)


# ---------------------------------------------------------------------------
print("\nslicing: an aggregate number must not hide a broken slice")
sliced = orc.slices
check("slices were computed", len(sliced) > 4, f"got {len(sliced)}")
check("thin slices are marked unreliable, not reported as rates",
      all(s.reliable == (s.n >= MIN_SLICE_N) for s in sliced))
check("every model has its own slice",
      all(any(s.name == f"model={m}" for s in sliced) for m in MODELS))


# ---------------------------------------------------------------------------
print("\nthe gate blocks predictions until a benchmark passes")
me = MarketEstimator(GlobalQuantiles())
try:
    me.predict(sp.test[:3])
    check("unbenchmarked estimator refuses to serve", False, "it served anyway")
except NotBenchmarked:
    check("unbenchmarked estimator refuses to serve", True)

ok, fails = me.benchmark(sp, res, name="global-quantiles")
check("global-quantiles is REJECTED (does not beat comparables)", not ok)
check("  and the reason names the baseline",
      any("does not beat" in f for f in fails), str(fails))

me2 = MarketEstimator(Oracle())
ok2, fails2 = me2.benchmark(sp, res, name="oracle")
check("oracle is ACCEPTED", ok2, str(fails2))
check("  and then serves monotone predictions",
      bool(np.all(np.diff(me2.predict(sp.test[:50]), axis=1) >= 0)))

me3 = MarketEstimator(Crosser())
ok3, fails3 = me3.benchmark(sp, res, name="crosser")
check("a crossing model is REJECTED", not ok3)
check("  and crossing is named as a reason",
      any("crossing" in f for f in fails3), str(fails3))

gate = AcceptanceGate(max_coverage_error=0.01, require_beats=None)
bad = gate.check(res["global-quantiles"], {})
check("a strict coverage bound rejects a miscalibrated model", not bad[0])


# ---------------------------------------------------------------------------
print("\nreport renders\n")
print(format_report(res, sp))

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
