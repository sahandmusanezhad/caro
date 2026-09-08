"""Tests for W3 — intent parsing and ranking.

The centrepiece is the last block: does ranking actually beat sorting by
price? Everything else in CARO is machinery in service of that number.

Run: PYTHONPATH=. python3 tests/test_ranking.py
"""

import numpy as np

from caro.appraisal import (
    ComparableQuantiles, GlobalQuantiles, LogLinearQuantiles, MarketEstimator,
    Row, cluster_temporal_split, run_benchmark,
)
from caro.ranking import (
    IntentSpec, RankingPipeline, Ranker, RuleIntentParser, Weights,
    diversify, normalize_fa, parse_amount, retrieve, winrate_vs_price_sort,
    LEDGER_INPUTS, CONDITION_RISK, IMPUTED_MARK, decision_ledger,
    features_from_listing, risk_from_condition, _passes,
)

FAILS: list[str] = []
rng = np.random.default_rng(11)


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# A corpus where the thesis is TRUE by construction:
# some cars are cheap because they are damaged. If ranking cannot separate
# "cheap and sound" from "cheap and wrecked", it deserves to lose.
# ---------------------------------------------------------------------------

MODELS = {"pride": 20.4, "206": 21.0, "tiba": 20.6, "pars": 21.2,
          "207": 21.35, "quik": 20.75}
SIGMA = 0.16


def true_mu(m, year, km):
    return MODELS[m] + 0.06 * (year - 1395) - 0.0000012 * km


def make_corpus(n=1800):
    rows = []
    for i in range(n):
        m = list(MODELS)[i % len(MODELS)]
        year = int(rng.integers(1392, 1403))
        km = float(rng.integers(15_000, 280_000))
        clean = float(np.exp(rng.normal(true_mu(m, year, km), SIGMA)))

        # 30% of cars carry damage. A damaged car is discounted in the ASKING
        # price by less than the damage actually costs the buyer — which is
        # exactly why the cheapest listing is usually the worst buy.
        risk = float(rng.beta(1.4, 6.0))
        damaged = risk > 0.25
        asking = clean * (1 - 0.55 * risk) if damaged else clean * float(
            rng.normal(1.0, 0.03))

        rows.append(Row(
            listing_id=f"l{i}", cluster_id=f"c{i}",
            first_seen_ordinal=int(rng.integers(0, 100)),
            model_key=m, year_jalali=year, mileage_km=km,
            asking_price_toman=float(asking),
            features={
                "risk": risk,
                "ownership_risk": float(rng.beta(2, 5)),
                "liquidity": 0.8 if m in ("pride", "206") else 0.4,
                "has_accident": 1.0 if risk > 0.45 else 0.0,
                "_clean_value": clean,
            }))
    return rows


def true_utility(r: Row) -> float:
    """What the buyer actually gains: the car's real worth, minus what they
    pay, minus what the damage will cost them. The ranker never sees this."""
    clean = r.features["_clean_value"]
    damage_cost = clean * 0.85 * r.features["risk"]
    return clean - r.asking_price_toman - damage_cost


ROWS = make_corpus()
SPLIT = cluster_temporal_split(ROWS, test_fraction=0.30)
BASE = {
    "global-quantiles": run_benchmark(GlobalQuantiles(), SPLIT,
                                      name="global-quantiles"),
    "comparable-quantiles": run_benchmark(ComparableQuantiles(), SPLIT,
                                          name="comparable-quantiles"),
}
EST = MarketEstimator(LogLinearQuantiles())
OK, WHY = EST.benchmark(SPLIT, BASE, name="log-linear-ridge")
PIPE = RankingPipeline(RuleIntentParser(), Ranker(EST))
POOL = SPLIT.test


# ---------------------------------------------------------------------------
print("\npersian normalisation and amounts")
check("digit folding", normalize_fa("۱۴۰۲") == "1402")
check("arabic yeh/kaf folded", normalize_fa("كمي") == "کمی")
check("ZWNJ becomes a space", "کم کارکرد" in normalize_fa("کم‌کارکرد"))
for text, want in [("۱.۵ میلیارد", 1_500_000_000),
                   ("1 میلیارد و 480", 1_480_000_000),
                   ("۸۰۰ میلیون", 800_000_000),
                   ("1480م", 1_480_000_000),
                   ("2 میلیارد", 2_000_000_000)]:
    got = parse_amount(normalize_fa(text))
    check(f"«{text}» → {want:,}", got == want, f"got {got:,}" if got else "None")


# ---------------------------------------------------------------------------
print("\nintent parsing")
P = RuleIntentParser()

s = P.parse("یه ۲۰۶ اتومات کم‌کارکرد تا ۱.۵ میلیارد میخوام")
check("budget parsed", s.budget_max_toman == 1_500_000_000, str(s.budget_max_toman))
check("model recognised", "206" in s.model_hints, str(s.model_hints))
check("low-mileage inferred", s.max_mileage_km == 120_000)
check("  and the inference is disclosed",
      any("کم‌کارکرد" in a for a in s.assumptions), str(s.assumptions))
check("automatic became a deal-breaker", "manual" in s.deal_breakers)

s2 = P.parse("ماشین برای اسنپ، کم‌مصرف، قطعاتش ارزون باشه، زیر ۸۰۰ میلیون")
check("use case = ride hailing", s2.use_case == "ride_hailing", s2.use_case)
check("running cost outweighs value for a driver",
      s2.weights.running_cost > s2.weights.value,
      f"{s2.weights.running_cost:.2f} vs {s2.weights.value:.2f}")

s3 = P.parse("ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۲ میلیارد")
check("use case = family", s3.use_case == "family_first_car")
check("accident is a deal-breaker", "accident" in s3.deal_breakers)
check("family buyer is risk averse", s3.risk_profile == "risk_averse")
check("risk outweighs value for a family",
      s3.weights.risk > s3.weights.value)

s4 = P.parse("مدل ۹۸ به بالا، کارکرد زیر ۹۰ هزار")
check("2-digit year expands to 1398", s4.year_min == 1398, str(s4.year_min))
check("explicit mileage cap", s4.max_mileage_km == 90_000, str(s4.max_mileage_km))

s5 = P.parse("یه ماشین خوب میخوام حدود ۱ میلیارد")
check("soft budget detected", s5.budget_hard is False)
check("nothing is invented when nothing was said",
      s5.use_case == "unspecified" and not s5.deal_breakers)
check("unmapped text is kept, not dropped", isinstance(s5.unparsed, tuple))

check("weights always normalise to 1",
      abs(sum([s3.weights.value, s3.weights.risk, s3.weights.running_cost,
               s3.weights.liquidity, s3.weights.mileage,
               s3.weights.recency]) - 1.0) < 1e-9)


# ---------------------------------------------------------------------------
print("\nretrieval and the relaxation ladder")
tight = IntentSpec(raw_query="", budget_max_toman=100_000_000,
                   model_hints=("206",), year_min=1402,
                   max_mileage_km=20_000)
got, used, rep = retrieve(POOL, tight)
check("impossible query never returns an empty list silently",
      rep.relaxed or len(got) == 0)
check("  and says what was loosened",
      "بودجه" in rep.text_fa() or not rep.relaxed, rep.text_fa())

easy = IntentSpec(raw_query="", budget_max_toman=10_000_000_000)
got2, _, rep2 = retrieve(POOL, easy)
check("a satisfiable query relaxes nothing", not rep2.relaxed)
check("  and returns candidates", len(got2) > 50)

db = IntentSpec(raw_query="", budget_max_toman=10_000_000_000,
                deal_breakers=("accident",))
got3, used3, _ = retrieve(POOL, db)
check("a deal-breaker is never relaxed away",
      all(r.features.get("has_accident", 0) < 0.5 for r in got3))
check("  and it actually excluded cars", len(got3) < len(got2))

# The corpus above is built with model_key = the parser's own slug, so it
# could never have caught this: ingest emits `make|model|trim`, and the
# retrieval filter compared a hint against the WHOLE key. On Run 5's real
# rows every model-constrained query returned zero while six matching cars
# sat inside the stated budget. These rows carry Bama's key shape verbatim.
INGEST_SHAPED = [
    Row(listing_id=f"r{i}", cluster_id=f"r{i}", first_seen_ordinal=0,
        model_key=k, year_jalali=1398, mileage_km=120_000.0,
        asking_price_toman=float(p), features={})
    for i, (k, p) in enumerate([
        ("Peugeot|206|type1", 495_000_000),
        ("Peugeot|206|type2", 540_000_000),
        ("Saipa|Pride|111 ex", 488_000_000),
        ("Saipa|Quik|r automatic", 700_000_000),
        ("BMW|3seriesconvertible|320i 2011", 9_000_000_000),
    ])]
for hint, want in [("206", 2), ("pride", 1), ("quik", 1)]:
    spec = IntentSpec(raw_query="", budget_max_toman=2_000_000_000,
                      model_hints=(hint,))
    hits = [r for r in INGEST_SHAPED if _passes(r, spec)]
    check(f"hint '{hint}' matches make|model|trim keys", len(hits) == want,
          f"got {len(hits)}, want {want}")
check("a hint does not match an unrelated model",
      not _passes(INGEST_SHAPED[4], IntentSpec(raw_query="",
                                               model_hints=("206",))))
check("case is folded, not assumed",
      _passes(INGEST_SHAPED[2], IntentSpec(raw_query="",
                                           model_hints=("pride",))))
check("bare-slug keys still match (the synthetic corpora)",
      _passes(Row(listing_id="s", cluster_id="s", first_seen_ordinal=0,
                  model_key="206", year_jalali=1398, mileage_km=1.0,
                  asking_price_toman=1.0),
              IntentSpec(raw_query="", model_hints=("206",))))



def replace_row(r: Row) -> Row:
    """The same car as Bama actually gives it to us: no derived features."""
    return Row(listing_id=r.listing_id, cluster_id=r.cluster_id,
               first_seen_ordinal=0, model_key=r.model_key,
               year_jalali=r.year_jalali, mileage_km=r.mileage_km,
               asking_price_toman=r.asking_price_toman, features={})




# ---------------------------------------------------------------------------
print("\ncondition → risk, the published table")
# The table that took features["risk"] from absent-on-every-real-row to a
# six-valued column (D45). It is policy, not a fit, so what is testable is its
# ORDERING and its treatment of silence — not its calibration, which no data
# in this repository could check.
order = ["intact", "minor_paint", "unknown", "multi_paint",
         "replaced_part", "accident"]
vals = [CONDITION_RISK[k] for k in order]
check("risk is monotone across the declared ordering",
      all(a < b for a, b in zip(vals, vals[1:])), str(vals))
check("intact is not zero — a clean car is not a certainty", vals[0] > 0)
check("accident is not one — a damaged car is not a total loss", vals[-1] < 1)

# The row that matters most, and the one it would be easiest to get wrong.
check("UNKNOWN is not treated as intact",
      CONDITION_RISK["unknown"] > CONDITION_RISK["intact"],
      "silence would otherwise rank undisclosed cars above disclosed ones")
check("  and it sits between the good and bad disclosures",
      CONDITION_RISK["minor_paint"] < CONDITION_RISK["unknown"]
      < CONDITION_RISK["multi_paint"])
check("an unrecognised label falls back to unknown, not to zero",
      risk_from_condition("something new") == CONDITION_RISK["unknown"])
check("  and so does None", risk_from_condition(None) == CONDITION_RISK["unknown"])


class _L:
    def __init__(self, cond, doc=None):
        self.body_condition, self.document_issue = cond, doc


f = features_from_listing(_L("accident"))
check("an accident listing sets both risk and the deal-breaker flag",
      f["risk"] == CONDITION_RISK["accident"] and f["has_accident"] == 1.0)
check("  a clean one sets the flag to 0, not absent",
      features_from_listing(_L("intact"))["has_accident"] == 0.0)
check("a listing with no condition at all yields NO risk key",
      "risk" not in features_from_listing(_L(None)),
      "absent must stay absent so the ledger can report it — "
      "defaulting here would turn a missing input into a fake one")
check("ownership_risk and liquidity are never invented",
      not ({"ownership_risk", "liquidity"} & set(f)),
      "no observation in this repository supports either")
check("a document issue is carried through",
      features_from_listing(_L("intact", True))["has_unclear_documents"] == 1.0)

# ---------------------------------------------------------------------------
print("\nthe decision ledger — construct validity, not ranking quality")
# There is no ground truth for ranking quality on real listings, so the ledger
# answers a different question that needs none: were the inputs the scoring
# function reads actually PRESENT? On the synthetic corpus everything is
# present by construction — which is exactly why the interesting assertions
# below are the ones about absence.
spec_l = IntentSpec(raw_query="", budget_max_toman=2_000_000_000)
cands_l, _, _ = retrieve(POOL, spec_l)
rows_l = decision_ledger(cands_l[:20], spec_l, estimator=EST)
check("a ledger row per candidate", len(rows_l) == 20)
check("with a gated estimator the price delta is recorded",
      all("price_delta_to_estimate" in r.values for r in rows_l))
check("the synthetic corpus is fully fed", 
      all(r.completeness == 1.0 for r in rows_l),
      f"{rows_l[0].values.keys()}")

# The real case: no estimator. The ledger must still produce rows, and must
# name the reason rather than leave a blank — refusing to print here would
# hide the single most informative line it has.
bare = decision_ledger(cands_l[:5], spec_l, estimator=None)
check("without an estimator the ledger still runs", len(bare) == 5)
check("  and the price delta is MISSING, with a reason",
      all("price_delta_to_estimate" in r.missing
          and "gate" in r.missing["price_delta_to_estimate"] for r in bare))
check("  an absent input is never silently zero",
      all("price_delta_to_estimate" not in r.values for r in bare))

featureless = [replace_row(r) for r in cands_l[:5]]
bare2 = decision_ledger(featureless, spec_l, estimator=None)
check("a row with no features reports every proxy missing",
      all({"risk_score", "running_cost_signals", "reliability_signals"}
          <= set(r.missing) for r in bare2))
check("  and completeness falls accordingly",
      all(r.completeness < 0.5 for r in bare2),
      f"{bare2[0].completeness:.0%}")
check("hard_filter_pass is always recorded — it needs nothing external",
      all("hard_filter_pass" in r.values for r in bare2))
check("the ledger declares its inputs", len(LEDGER_INPUTS) == 9)


# ---------------------------------------------------------------------------
print("\nobserved vs imputed vs absent")
# The three-state rule. `unknown` is FILLED rather than left out, because
# Ranker.score reads risk with .get("risk", 0.0) and an absent key would score
# silence as a perfect car — the one failure CONDITION_RISK exists to prevent.
# Filling it silently would have been the other failure: a number we chose,
# indistinguishable downstream from one Bama printed. So: filled AND flagged.
f_known = features_from_listing(_L("minor_paint"))
f_unk = features_from_listing(_L("unknown"))
check("a stated condition is not marked imputed", IMPUTED_MARK not in f_known)
check("an unstated one IS", f_unk.get(IMPUTED_MARK) == ["risk"])
check("  and it still has a value — absence would score silence as perfect",
      f_unk["risk"] == CONDITION_RISK["unknown"])

_R = lambda i, feats: Row(listing_id=f"i{i}", cluster_id=f"i{i}",
                          first_seen_ordinal=0, model_key="pride",
                          year_jalali=1398, mileage_km=100_000.0,
                          asking_price_toman=5e8, features=feats)
spec_i = IntentSpec(raw_query="", budget_max_toman=2_000_000_000)
lr_known, lr_unk = decision_ledger([_R(0, f_known), _R(1, f_unk)], spec_i)
check("the ledger reports an imputed input separately",
      not lr_known.imputed and set(lr_unk.imputed) == {"risk_score"})
check("  and says whose number it is",
      "this project chose" in lr_unk.imputed["risk_score"])
check("completeness counts imputed values",
      lr_unk.completeness == lr_known.completeness)
check("  and observed_completeness does not",
      lr_unk.observed_completeness < lr_known.observed_completeness,
      "the stricter number is the one to quote when it matters")

# ---------------------------------------------------------------------------
print("\nscoring and shortlist")
check("ridge passed the gate before ranking used it", OK, str(WHY))

sl = PIPE.run("یه ۲۰۶ تا ۲ میلیارد میخوام، تصادفی نباشه", POOL)
check("shortlist is produced", len(sl.items) > 0)
check("every term is inspectable",
      all({"value", "risk", "running_cost", "liquidity", "mileage", "recency"}
          <= set(s.breakdown) for s in sl.items))
check("score equals the sum of its terms",
      all(abs(s.score - sum(v for k, v in s.breakdown.items()
                            if not k.startswith("_"))) < 1e-9
          for s in sl.items))
check("each pick is labelled with its role",
      all(s.breakdown.get("_role") for s in sl.items))
check("summary discloses assumptions", "فرض" in sl.summary_fa()
      or not sl.spec.assumptions)

risk_averse = PIPE.parser.parse("ماشین خانواده، تصادفی نباشه، تا ۲ میلیارد")
flip = PIPE.parser.parse("برای فروش مجدد و سود، تا ۲ میلیارد")
ra_items = PIPE.ranker.score(retrieve(POOL, risk_averse)[0], risk_averse)
fl_items = PIPE.ranker.score(retrieve(POOL, flip)[0], flip)
ra_top = sorted(ra_items, key=lambda s: s.score, reverse=True)[:5]
fl_top = sorted(fl_items, key=lambda s: s.score, reverse=True)[:5]
check("a risk-averse buyer gets lower-risk cars than a flipper",
      np.mean([s.row.features["risk"] for s in ra_top])
      < np.mean([s.row.features["risk"] for s in fl_top]),
      f'{np.mean([s.row.features["risk"] for s in ra_top]):.3f} vs '
      f'{np.mean([s.row.features["risk"] for s in fl_top]):.3f}')

check("intent changes the ordering",
      [s.row.listing_id for s in ra_top] != [s.row.listing_id for s in fl_top])

heavy = risk_averse.with_weights(Weights(value=0.9, risk=0.02, running_cost=0.02,
                                         liquidity=0.02, mileage=0.02,
                                         recency=0.02))
hv = sorted(PIPE.ranker.score(retrieve(POOL, heavy)[0], heavy),
            key=lambda s: s.score, reverse=True)[:5]
check("dragging a weight re-ranks",
      [s.row.listing_id for s in hv] != [s.row.listing_id for s in ra_top])

check("diversify returns at most k", len(diversify(ra_items, k=4)) <= 4)
check("diversify on an empty set is empty", diversify([], k=5) == [])

ungated = Ranker(MarketEstimator(GlobalQuantiles()))
try:
    ungated.score(POOL[:5], risk_averse)
    check("an ungated estimator cannot rank", False, "it ranked anyway")
except Exception as e:
    check("an ungated estimator cannot rank",
          type(e).__name__ == "NotBenchmarked", type(e).__name__)


# ---------------------------------------------------------------------------
print("\nTHE NUMBER — does ranking beat sorting by price?")
QUERIES = [
    "یه ۲۰۶ تا ۲ میلیارد میخوام",
    "ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۵ میلیارد",
    "ماشین برای اسنپ، کم‌مصرف، زیر ۱ میلیارد",
    "پراید کم‌کارکرد تا ۸۰۰ میلیون",
    "تیبا مدل ۹۸ به بالا تا ۱ میلیارد",
    "پارس تا ۱.۸ میلیارد، کارکرد زیر ۱۵۰ هزار",
    "یه ماشین خوب حدود ۱.۲ میلیارد",
    "کوییک تا ۱.۱ میلیارد، تصادفی نباشه",
    "۲۰۷ اتومات تا ۲.۵ میلیارد",
    "ارزون‌ترین ماشین سالم تا ۹۰۰ میلیون",
    "ماشین برای رفت و آمد سرکار، کم‌خرج، تا ۱.۳ میلیارد",
    "پژو ۴۰۵ مدل ۹۶ به بالا تا ۱.۲ میلیارد",
]
res = winrate_vs_price_sort(PIPE, POOL, QUERIES, true_utility, k=3)
print(f"     {res}")
check("price-sort is beaten on mean buyer utility",
      res.caro_mean_utility > res.price_sort_mean_utility,
      f"{res.caro_mean_utility:,.0f} vs {res.price_sort_mean_utility:,.0f}")
check("win-rate is a majority", res.win_rate >= 0.6, f"{res.win_rate:.0%}")
check("CARO beats picking at random", res.caro_mean_utility > res.random_mean_utility)
# NOT asserted: that price-sort is worse than random. It is not, and the
# reason is worth recording. Utility here is absolute tomans, and the damage
# penalty scales with a car's clean value — so sorting by price selects
# cheap, low-value cars where the absolute stakes are small either way. That
# makes price-sorting look defensible on this metric while still being the
# wrong advice: it systematically hands the buyer the damaged end of whatever
# price band they are shopping in. The thesis is "CARO beats price-sort",
# which is what the win-rate measures; "price-sort is worse than chance" was
# speculation and the experiment did not support it.
check("all three baselines were actually evaluated",
      res.n_queries >= 8, f"only {res.n_queries} queries produced shortlists")
check("uplift is material, not noise", res.uplift > 0.10, f"{res.uplift:+.1%}")

# Regression for the bug this benchmark caught. The first ranker normalised
# risk to [0,1] across the candidate set, which is scale-free — so the same
# risk score cost the same whether the car was worth 800M or 2B, and the
# ranker kept choosing expensive damaged cars and lost to price-sorting.
# Risk must be priced in tomans against the car's own value.
print("\nregression: risk is priced, not scored")
from caro.ranking import DAMAGE_COST_FACTOR
cheap = Row("x1", "cx1", 10, "pride", 1398, 100_000, 700_000_000,
            {"risk": 0.30, "liquidity": 0.8})
dear = Row("x2", "cx2", 10, "pars", 1398, 100_000, 1_900_000_000,
           {"risk": 0.30, "liquidity": 0.4})
spec = P.parse("تا ۳ میلیارد")
sc = {s.row.listing_id: s for s in PIPE.ranker.score([cheap, dear], spec)}
check("identical risk costs more on the more valuable car",
      sc["x2"].expected_damage_toman > sc["x1"].expected_damage_toman * 2,
      f'{sc["x2"].expected_damage_toman:,.0f} vs {sc["x1"].expected_damage_toman:,.0f}')
check("the damage charge is proportional to the estimate",
      all(abs(s.expected_damage_toman
              - s.row.features["risk"] * s.conservative_estimate_toman
              * DAMAGE_COST_FACTOR) < 1.0 for s in sc.values()))
check("opportunity is net of the damage charge",
      all(abs(s.adjusted_opportunity_toman
              - (s.conservative_estimate_toman - s.row.asking_price_toman
                 - s.expected_damage_toman)) < 1.0 for s in sc.values()))
check("a zero-risk car carries no damage charge",
      PIPE.ranker.score(
          [Row("x3", "cx3", 10, "pride", 1398, 100_000, 700_000_000,
               {"risk": 0.0})], spec)[0].expected_damage_toman == 0.0)
print(f"     uplift over price-sort: {res.uplift:+.1%}")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
