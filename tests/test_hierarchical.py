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

print("\nANTI-LEAKAGE — a held-out trim must be unseen by EVERY parameter")
tr2, te2 = held_out_trim_split(ROWS, fraction=0.25, seed=3)
held = sorted({r.model_key for r in te2})
m_train = PartialPoolingQuantiles().fit(tr2)

check("no held-out trim appears in the fitted per-trim tables",
      not (set(held) & (set(m_train._n) | set(m_train._lam)
                        | set(m_train._offsets) | set(m_train._raw))),
      "an offset for a trim we held out would be direct leakage")

# tau^2 is the parameter most likely to leak silently: it is a GLOBAL summary,
# so computing it on the full corpus would look correct and still let the
# held-out trims inform their own predictions.
m_all = PartialPoolingQuantiles().fit(ROWS)
shared = sorted(set(m_train._lam) & set(m_all._lam))
check("SHRINKAGE DIFFERS WHEN THE HELD-OUT TRIMS ARE ADDED BACK",
      any(abs(m_train._lam[t] - m_all._lam[t]) > 1e-9 for t in shared),
      "identical lambdas would mean tau^2 was computed globally, and the "
      "held-out split would be cosmetic")
check("  and so does the ridge fit",
      not np.allclose(m_train._coef, m_all._coef),
      "scaling and coefficients must also come from train alone")
check("  and the residual quantiles",
      not np.allclose(m_train._resid_q, m_all._resid_q))
check("the parent one-hot columns are train-derived",
      m_train._cols == sorted({"|".join(r.model_key.split("|")[:2])
                               for r in tr2}))

print("\nthe trace cannot be dropped by the serving path")
from caro.hierarchical import (                                      # noqa: E402
    HierarchicalGate, NotAccepted, TracedEstimate, four_slices,
    serve_or_refuse, slice_metrics,
)
traced = m_train.predict_traced(te2[:3])
check("predict_traced returns numbers WELDED to their provenance",
      all(isinstance(t, TracedEstimate) and t.trace is not None
          for t in traced))
check("  and rendering one shows the borrowing",
      "borrowed from" in str(traced[0]), str(traced[0]))

def make_corpus(seed, thin_spread):
    """Same shape at a size where calibration is actually judgeable.

    The 221-listing corpus cannot support a per-slice calibration verdict —
    a real property of the data, reported as such. The GATE's behaviour is a
    property of the gate and must be tested where a verdict is possible.

    The adversarial world here is subtler than "thin trims are dearer", which
    turned out NOT to break anything: a uniform premium inflates the
    between-trim variance τ², the intervals widen accordingly, and coverage
    holds. Writing that test and watching it pass is what identified the real
    hazard:

        τ² is estimated from the trims we can see, and the trims we cannot
        see may be more dispersed than they are.

    So the fixture makes the FAT trims nearly identical and the THIN ones
    wildly scattered. τ² comes out small, the bands stay tight, and an unseen
    trim's price falls outside them — a model that is confident exactly where
    it has no information.

        thin_spread = 0.30   the tail is far more variable than the head
        thin_spread = 0.04   the tail is thin by chance, not by kind
    """
    rg = np.random.default_rng(seed)
    rows, i = [], 0
    spec = ([(f"fat{k}", 100) for k in range(6)]
            + [(f"thin{k}", 3) for k in range(90)])
    for trim, n in spec:
        thin = trim.startswith("thin")
        mult = float(rg.normal(1.0, thin_spread if thin else 0.01))
        for _ in range(n):
            yr = int(rg.integers(1385, 1401))
            km = float(rg.integers(30_000, 400_000))
            base = 3.0e8 + (yr - 1385) * 4.2e7 - km * 260
            rows.append(row(i, trim, yr, km,
                            max(5e7, base * mult * float(rg.normal(1, 0.05)))))
            i += 1
    return rows


def verdict(corpus, seed):
    tr, te = held_out_trim_split(corpus, fraction=0.25, seed=seed)
    mm = PartialPoolingQuantiles().fit(tr)
    sls = four_slices(mm, tr, dict(mm._n), held_out=te)
    return g.check(sls, baseline_mae=1e9, model_mae=1e8), sls


print("\nfour slices, because the aggregate answers none of them")
counts = dict(m_train._n)
sl = four_slices(m_train, tr2, counts, held_out=te2)
names = {s.name for s in sl}
check("well-observed, thin and held-out are reported separately",
      {"well-observed trim", "thin trim", "held-out trim"} <= names, str(names))
BIG = make_corpus(31, 0.04)
btr_, bte_ = held_out_trim_split(BIG, fraction=0.25, seed=4)
BIGM = PartialPoolingQuantiles().fit(btr_)
BIGSL = four_slices(BIGM, btr_, dict(BIGM._n), held_out=bte_)
check("  plus the worst reliable slice, once slices are big enough to judge",
      any(s.name.startswith("worst reliable") for s in BIGSL),
      str({s.name: s.n for s in BIGSL}))
check("  and each carries coverage, not just error",
      all(0.0 <= s.coverage <= 1.0 for s in sl))
check("  and the shrinkage actually applied",
      all(0.0 <= s.mean_shrinkage <= 1.0 for s in sl))
check("a slice too small to trust says so rather than being averaged in",
      slice_metrics(m_train, tr2[:3], "tiny").reliable is False)

print("\nthe gate is conjunctive, and refuses rather than falling back")
g = HierarchicalGate()
ok, fails = g.check(sl, baseline_mae=1e9, model_mae=1e8)
# ROWS is adversarial on purpose: its thin trims all carry a systematic +15%
# premium that the fat trims do not. Partial pooling cannot know that — the
# thin trims have one or two listings each, so their offsets are shrunk to
# almost nothing and unseen trims are priced at the parent level. The point
# estimate is defensible; the INTERVAL is not, and the gate says so.
#
# Keeping this fixture and asserting the rejection is the honest choice. The
# alternative — softening the fixture until the model passes — is the exact
# move every gate in this project exists to prevent.
check("A CORPUS TOO SMALL TO JUDGE DOES NOT PASS", not ok,
      str(fails))
check("  and the reason distinguishes 'cannot judge' from 'model failed'",
      any("corpus cannot judge" in f for f in fails), str(fails))



# Two fixture families made the gate pass, and each pass identified a real
# property rather than a gap. A uniform thin-trim premium inflates τ² and the
# bands widen correctly; a highly-dispersed tail does the same, because τ² is
# estimated over ALL trims including the thin ones. The estimator is better
# behaved than the first two adversarial guesses assumed.
#
# The hazard that survives is narrower and is the one worth testing: the
# held-out trims are drawn from somewhere the training trims never went. τ²
# then measures the variation we saw, the bands are sized for it, and the
# model is confident exactly where it has no information. Generalisation
# failure, not noise.
def split_with_offset_holdout(seed, holdout_offset):
    rg = np.random.default_rng(seed)
    rows, i = [], 0

    def block(trim, n, mult):
        nonlocal i
        out = []
        for _ in range(n):
            yr = int(rg.integers(1385, 1401))
            km = float(rg.integers(30_000, 400_000))
            base = 3.0e8 + (yr - 1385) * 4.2e7 - km * 260
            out.append(row(i, trim, yr, km,
                           max(5e7, base * mult * float(rg.normal(1, 0.05)))))
            i += 1
        return out

    train = []
    for k in range(6):
        train += block(f"fat{k}", 100, float(rg.normal(1.0, 0.02)))
    for k in range(40):
        train += block(f"thin{k}", 3, float(rg.normal(1.0, 0.02)))
    test = []
    for k in range(30):
        test += block(f"held{k}", 3, holdout_offset * float(rg.normal(1, 0.02)))
    return train, test


def verdict_explicit(train, test):
    mm = PartialPoolingQuantiles().fit(train)
    sls = four_slices(mm, train, dict(mm._n), held_out=test)
    return g.check(sls, baseline_mae=1e9, model_mae=1e8), sls


tr_a, te_a = split_with_offset_holdout(5, holdout_offset=1.45)
(adv_ok, adv_f), adv_sl = verdict_explicit(tr_a, te_a)
tr_b, te_b = split_with_offset_holdout(5, holdout_offset=1.00)
(ben_ok, ben_f), ben_sl = verdict_explicit(tr_b, te_b)

check("AT A JUDGEABLE SIZE, held-out trims OFF-DISTRIBUTION are REJECTED",
      not adv_ok, str(adv_f))
check("  on calibration, not on average error",
      any("coverage" in f for f in adv_f) and all("MAE" not in f
                                                  for f in adv_f), str(adv_f))
check("  and the same gate PASSES when they are on-distribution", ben_ok,
      str(ben_f) + " | " + " | ".join(x.line().strip() for x in ben_sl))
check("  so the gate discriminates rather than always refusing",
      ben_ok and not adv_ok,
      "a gate that always fails is as useless as one that always passes")


def benign_corpus():
    """The same shape WITHOUT the systematic thin-trim offset: trims differ,
    but thin ones are not special. This is what a market looks like when the
    tail is thin by chance rather than by kind."""
    rows, i = [], 0
    rg = np.random.default_rng(11)
    spec = [("131 se", 24), ("131 sl", 18), ("111 se", 14), ("132 se", 11),
            ("141 sx", 6)] + [(f"thin{k}", 1 + k % 2) for k in range(14)]
    for trim, n in spec:
        mult = float(rg.normal(1.0, 0.04))       # trim effect, not tail effect
        for _ in range(n):
            yr = int(rg.integers(1385, 1401))
            km = float(rg.integers(30_000, 400_000))
            base = 3.0e8 + (yr - 1385) * 4.2e7 - km * 260
            rows.append(row(i, trim, yr, km,
                            max(5e7, base * mult * float(rg.normal(1, 0.05)))))
            i += 1
    return rows


BEN = benign_corpus()
btr, bte = held_out_trim_split(BEN, fraction=0.25, seed=5)
bm = PartialPoolingQuantiles().fit(btr)
bsl = four_slices(bm, btr, dict(bm._n), held_out=bte)
bok, _ = g.check(bsl, baseline_mae=1e9, model_mae=1e8)
check("a small benign corpus ALSO does not pass — size, not quality",
      not bok,
      "this is the finding about the real corpus, stated as a verdict")

bad = [s for s in sl if s.name != "held-out trim"]
ok2, fails2 = g.check(bad, baseline_mae=1e9, model_mae=1e8)
check("UNMEASURED held-out behaviour is a FAILURE, not a pass",
      not ok2 and any("held-out" in f for f in fails2),
      "the gate cannot pass on evidence it does not have")

ok3, fails3 = g.check(sl, baseline_mae=1e8, model_mae=1e9)
check("a much worse MAE fails", not ok3)
ok4, fails4 = g.check(sl, baseline_mae=1e9, model_mae=1e8,
                      population_weighted=True)
check("introducing population weighting fails the gate outright",
      not ok4 and any("P(inclusion)" in f for f in fails4))

from caro.hierarchical import SliceMetrics                           # noqa: E402
wrecked = [SliceMetrics(s.name, s.n, s.mae, s.median_ae, 0.20, 0.50,
                        s.mean_shrinkage, s.extrapolation_rate)
           if s.name == "thin trim" else s for s in BIGSL]
ok5, fails5 = g.check(wrecked, baseline_mae=1e9, model_mae=1e8)
check("BETTER ERROR WITH BROKEN BANDS IS A FAILURE", not ok5,
      "more confident and less right is worse than a little further off")
check("  and the message says why", any("more confident" in f for f in fails5))

raised = False
try:
    serve_or_refuse(m_train, te2[:2], accepted=False)
except NotAccepted as e:
    raised = "NOT substituted" in str(e)
check("A REJECTED MODEL SERVES NOTHING — no quiet pooled fallback", raised,
      "a conditional appraisal that silently becomes a pooled one is the "
      "exact claim D30 refused, and it is invisible in the output")
check("  while an accepted one serves traced estimates",
      len(serve_or_refuse(m_train, te2[:2], accepted=True)) == 2)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
