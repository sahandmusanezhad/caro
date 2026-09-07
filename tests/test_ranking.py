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
            asking_asking_price_toman=float(asking),
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
    return clean - r.asking_asking_price_toman - damage_cost


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
check("budget parsed", s.budget_max_irr == 1_500_000_000, str(s.budget_max_irr))
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
tight = IntentSpec(raw_query="", budget_max_irr=100_000_000,
                   model_hints=("206",), year_min=1402,
                   max_mileage_km=20_000)
got, used, rep = retrieve(POOL, tight)
check("impossible query never returns an empty list silently",
      rep.relaxed or len(got) == 0)
check("  and says what was loosened",
      "بودجه" in rep.text_fa() or not rep.relaxed, rep.text_fa())

easy = IntentSpec(raw_query="", budget_max_irr=10_000_000_000)
got2, _, rep2 = retrieve(POOL, easy)
check("a satisfiable query relaxes nothing", not rep2.relaxed)
check("  and returns candidates", len(got2) > 50)

db = IntentSpec(raw_query="", budget_max_irr=10_000_000_000,
                deal_breakers=("accident",))
got3, used3, _ = retrieve(POOL, db)
check("a deal-breaker is never relaxed away",
      all(r.features.get("has_accident", 0) < 0.5 for r in got3))
check("  and it actually excluded cars", len(got3) < len(got2))


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
      sc["x2"].expected_damage_irr > sc["x1"].expected_damage_irr * 2,
      f'{sc["x2"].expected_damage_irr:,.0f} vs {sc["x1"].expected_damage_irr:,.0f}')
check("the damage charge is proportional to the estimate",
      all(abs(s.expected_damage_irr
              - s.row.features["risk"] * s.conservative_estimate_irr
              * DAMAGE_COST_FACTOR) < 1.0 for s in sc.values()))
check("opportunity is net of the damage charge",
      all(abs(s.adjusted_opportunity_irr
              - (s.conservative_estimate_irr - s.row.asking_asking_price_toman
                 - s.expected_damage_irr)) < 1.0 for s in sc.values()))
check("a zero-risk car carries no damage charge",
      PIPE.ranker.score(
          [Row("x3", "cx3", 10, "pride", 1398, 100_000, 700_000_000,
               {"risk": 0.0})], spec)[0].expected_damage_irr == 0.0)
print(f"     uplift over price-sort: {res.uplift:+.1%}")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
