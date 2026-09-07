# Evaluation

## The harness was validated before it judged anything

Evaluation code that is silently wrong is worse than no evaluation: it makes
you ship a broken model or discard a good one, and you find out at the demo.

So the W1 tests build a synthetic world where
`log(price) ~ Normal(μ(model, year, mileage), σ)` — a distribution whose true
conditional quantiles are known in closed form — and construct an **Oracle**
from that formula. A perfect model must show coverage exactly equal to τ:

```
  τ      nominal   empirical   error    95% CI (Wilson)
  0.15      0.15       0.161    +0.011   [0.139, 0.194]
  0.35      0.35       0.354    +0.004   [0.322, 0.393]
  0.50      0.50       0.511    +0.011   [0.480, 0.554]
  0.85      0.85       0.869    +0.019   [0.842, 0.892]
  interval [0.15, 0.85] coverage: 0.709   (nominal 0.70)
```

**Two real bugs surfaced during that certification**, both of which would have
broken W1 silently:

1. **Slicing on the target selected on the dependent variable.** Coverage was
   sliced by `asking_price_toman`; inside a "price ≥ 2B" bucket only rows whose
   *y* landed high survive, so even a perfectly calibrated estimator shows
   wrecked coverage. The Oracle was rejected with a 0.40 error. Slices are now
   defined by features or by the model's own prediction — never by the target.

2. **A max over many noisy slices rejects perfect models.** With ~12 slices ×
   4 quantiles the gate took a max over 48 noisy estimates; at n=30 the
   binomial standard error on a 0.15 quantile is ~0.065, so the worst of 48
   looks alarming for *any* model. Winner's curse. `MIN_SLICE_N` is now 150,
   and a deviation counts against a model only when it exceeds 2.5 binomial
   standard errors.

## What is measured

| Metric | Where |
|---|---|
| Pinball loss per quantile | `evaluate()` |
| Empirical coverage + Wilson CI | `SliceResult.coverage_ci` |
| Interval coverage [0.15, 0.85] | `SliceResult` |
| Quantile crossing rate (pre-rearrangement) | `crossing_rate()` |
| Worst reliable slice, noise-adjusted | `BenchmarkResult.worst_slice()` |
| Train/test distribution shift | `distribution_shift()` |
| Cluster leakage (must be 0) | `Split.leakage()` |

## Baselines, in order

```
GlobalQuantiles       corpus quantiles, no features — the floor
ComparableQuantiles   empirical quantiles over comparables — the bar to beat
LogLinearQuantiles    ridge on log-price + residual quantiles
<your model>          must beat comparables on pinball, or be rejected
```

**If a sophisticated model does not beat the comparable baseline, ship the
baseline.** The gate's rejection message says so in as many words. That is a
product decision encoded as a test, not a preference.

## Quantile crossing

Repaired by rearrangement — legitimate, not a hack: rearranging a non-monotone
quantile curve is provably no worse in estimation error (Chernozhukov,
Fernández-Val & Galichon). But the **rate is still reported**, because frequent
crossing means something is wrong upstream. `AcceptanceGate` tolerates zero.

## Honest limitations

- **The corpus is synthetic.** Every number in this repo demonstrates that the
  implementation is correct. None demonstrates market validity.
- **`y` is an asking price.** Quantile regression here learns the distribution
  of *asking prices*. It is not a transaction-price model, and the interval
  coverage metric is named `asking_price_interval_coverage` for that reason.
- **A synthetic world matching a model family cannot say which family wins.**
  Ridge edges out the population oracle in these tests because the world is
  exactly log-linear. On real data that question is open.
- **Confidence bands are not calibrated.** They are policy, set by judgement.
  Calibrating them against observed decision quality needs real data.
