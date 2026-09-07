"""D32 — partial pooling must SHOW its borrowing, not hide it.

The failure these tests exist to catch is not a bad error metric. It is a
hierarchical model that learns `thin trim -> parent mean`, posts a decent
average error because the corpus is dominated by well-observed trims, and
presents borrowed numbers as conditional estimates.

Run: PYTHONPATH=. python3 tests/test_hierarchical.py
"""

import numpy as np

from caro.appraisal import Row
from caro.hierarchical import (
    MATERIAL_EXTRAPOLATION_BELOW, PartialPoolingQuantiles, held_out_trim_split,
    thin_trim_rows,
)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def row(i, trim, year, km, price):
    return Row(listing_id=f"r{i}", cluster_id=f"c{i}", first_seen_ordinal=i,
               model_key=f"Saipa|Pride|{trim}", year_jalali=year,
               mileage_km=km, asking_price_toman=price)


rng = np.random.default_rng(7)


def corpus():
    """A long-tailed corpus shaped like the real one: a few fat trims and
    many with one or two listings. The fat trims carry a genuine premium so
    a model that ignores trim is detectably wrong."""
    rows, i = [], 0
    spec = [("131 se", 24, 1.00), ("131 sl", 18, 0.94), ("111 se", 14, 1.06),
            ("132 se", 11, 0.97), ("141 sx", 6, 0.91)]
    spec += [(f"thin{k}", 1 + k % 2, 1.15) for k in range(14)]
    for trim, n, mult in spec:
        for _ in range(n):
            yr = int(rng.integers(1385, 1401))
            km = float(rng.integers(30_000, 400_000))
            base = 3.0e8 + (yr - 1385) * 4.2e7 - km * 260
            rows.append(row(i, trim, yr, km,
                            max(5e7, base * mult * float(rng.normal(1, 0.05)))))
            i += 1
    return rows


ROWS = corpus()
m = PartialPoolingQuantiles().fit(ROWS)

print("\nshrinkage is COMPUTED, and ordered by evidence")
fat = m.trace(row(0, "131 se", 1395, 100_000, 5e8))
thin = m.trace(row(0, "thin0", 1395, 100_000, 5e8))
check("a well-observed trim keeps most of its own signal",
      fat.shrinkage > 0.5, f"{fat.shrinkage:.2f} on n={fat.n_trim}")
check("a one-listing trim keeps far less",
      thin.shrinkage < fat.shrinkage,
      f"thin {thin.shrinkage:.2f} vs fat {fat.shrinkage:.2f}")
check("  and shrinkage rises with n, monotonically",
      all(m._lam[a] <= m._lam[b] for a, b in
          [(f"Saipa|Pride|{x}", f"Saipa|Pride|{y}") for x, y in
           [("141 sx", "132 se"), ("132 se", "111 se"), ("111 se", "131 sl")]]),
      "empirical Bayes, not a hand-set constant")

print("\nthe trace makes borrowed estimates visible")
check("A THIN-TRIM ESTIMATE DECLARES ITSELF EXTRAPOLATION",
      thin.material_extrapolation,
      "otherwise a borrowed number is indistinguishable from a measured one")
check("  a well-observed one does not", not fat.material_extrapolation)
check("  and the explanation names the parent it borrowed from",
      "Saipa|Pride" in thin.explain() and "MATERIAL" in thin.explain(),
      thin.explain())
check("  and states how many listings the trim actually had",
      f"{thin.n_trim} listing" in thin.explain())
check("the trace reports the offset it APPLIED, not just the raw one",
      abs(thin.trim_offset_applied) < abs(thin.trim_offset_raw),
      "the raw deviation of a one-listing trim is mostly noise")

print("\nthe rate of borrowing is reportable alongside any metric")
counts = {k: v for k, v in m._n.items()}
thins = thin_trim_rows(ROWS, counts)
check("thin-trim rows are identifiable", 10 <= len(thins) <= 30, str(len(thins)))
rate = m.extrapolation_rate(thins)
check("  and most of them are flagged as extrapolated", rate > 0.5,
      f"{rate:.0%} — a fine average error can hide this entirely")
check("the whole corpus's rate is lower than the thin subset's",
      m.extrapolation_rate(ROWS) < rate,
      "which is exactly why the aggregate number cannot be trusted alone")

print("\nheld-out TRIMS, not held-out rows")
tr, te = held_out_trim_split(ROWS, fraction=0.25, seed=1)
train_trims = {r.model_key for r in tr}
test_trims = {r.model_key for r in te}
check("no trim appears on both sides", not (train_trims & test_trims),
      "a row-level split cannot ask what happens to an UNSEEN trim")
check("  and the held-out side is non-empty", len(te) > 0)

m2 = PartialPoolingQuantiles().fit(tr)
check("an unseen trim gets zero shrinkage — it has no signal of its own",
      m2.trace(te[0]).shrinkage == 0.0)
check("  and is reported as extrapolation, not as a conditional estimate",
      m2.trace(te[0]).material_extrapolation)
p = m2.predict(te[:5])
check("  while still producing a usable number from the parent",
      np.all(np.isfinite(p)) and np.all(p > 0))
check("  with quantiles that do not cross",
      np.all(np.diff(p, axis=1) >= -1e-9))

print("\nthe model must beat 'ignore trim entirely', or it adds nothing")
flat = PartialPoolingQuantiles()
flat.fit(ROWS)
saved = dict(flat._offsets)
flat._offsets = {k: 0.0 for k in saved}          # pooled-only counterfactual
med = list(PartialPoolingQuantiles.quantiles).index(0.50)
truth = np.array([r.asking_price_toman for r in ROWS])
err_pool = float(np.mean(np.abs(flat.predict(ROWS)[:, med] - truth)))
flat._offsets = saved
err_pp = float(np.mean(np.abs(flat.predict(ROWS)[:, med] - truth)))
check("partial pooling beats pooling on this corpus",
      err_pp < err_pool, f"{err_pp:,.0f} vs {err_pool:,.0f}")
check("  and the gain is not merely rounding",
      (err_pool - err_pp) / err_pool > 0.01,
      f"{(err_pool - err_pp) / err_pool:.1%} — if it were, trim conditioning "
      "would be decoration")

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
