"""
CARO W3 — intent parsing and ranking.

The half the brief asks for that W0-W2 did not have. W2 evaluates ONE listing;
this turns a Persian sentence into a ranked shortlist, and every item on that
shortlist can then be handed to the decision layer.

The thesis, made testable
-------------------------
Sorting by price can systematically favour damaged cars, and where it does,
it actively harms the buyer. `winrate_vs_price_sort` is the experiment that
settles whether ranking answers that better than price order does. If it
cannot beat sort-by-price, the product has no reason to exist and the honest
move is to find that out here rather than in the demo.

What the experiment tests, precisely: in a world where the cheapest listings
*are* disproportionately damaged, does ranking respond correctly while price
order does not. Whether Iranian used-car prices actually have that property
is a separate, open question — the generating process was built with it, so
this benchmark cannot also be evidence for it. See D36.

Where the LLM is, and is not
----------------------------
Intent parsing is the one place in CARO where a language model genuinely
earns its keep — Persian free text is exactly what deterministic code is bad
at. So `IntentParser` is a Protocol with two implementations: a deterministic
parser that ships and runs offline, and a slot for an LLM parser that must
produce the same frozen `IntentSpec`.

Everything after parsing — filtering, the relaxation ladder, scoring,
diversity — is deterministic. The ranking must be reproducible, inspectable
term by term, and recomputable client-side when a user drags a weight.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Protocol, Sequence

import numpy as np

from caro.appraisal import QUANTILES, MarketEstimator, NotBenchmarked, Row

# ---------------------------------------------------------------------------
# Persian text normalisation
# ---------------------------------------------------------------------------

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ZWNJ = "‌"


def normalize_fa(s: str) -> str:
    """Fold the variants a real query actually arrives in.

    Arabic yeh/kaf for Persian ones, both digit sets to Latin, ZWNJ to a
    space so «کم‌کارکرد» and «کم کارکرد» are one token.
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_DIGITS)
    s = s.replace("ي", "ی").replace("ك", "ک").replace(_ZWNJ, " ")
    return re.sub(r"\s+", " ", s).strip()


# Amount words, in IRR. Iranian sellers quote in both tomans and rials and
# the unit is usually implied by scale, so `parse_amount` disambiguates on
# magnitude rather than trusting the word.
_SCALE = {"میلیارد": 1_000_000_000, "ملیارد": 1_000_000_000,
          "میلیون": 1_000_000, "ملیون": 1_000_000, "م": 1_000_000}

_AMOUNT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(میلیارد|ملیارد|میلیون|ملیون|م)?(?:\s*و\s*(\d+))?")


def parse_amount(text: str) -> int | None:
    """«۱.۵ میلیارد» · «1 میلیارد و 480» · «۸۰۰ میلیون» · «۱۴۸۰م» → IRR."""
    m = _AMOUNT.search(text)
    if not m:
        return None
    base = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    tail = m.group(3)
    if unit in ("میلیارد", "ملیارد"):
        total = base * 1e9 + (float(tail) * 1e6 if tail else 0.0)
    elif unit:
        total = base * _SCALE[unit]
    else:
        total = base * 1e6 if base < 10_000 else base
    return int(total)


# Model aliases. Sellers and buyers type the same car a dozen ways; the
# taxonomy is data, not code, so a new model is one line.
MODEL_ALIASES: dict[str, tuple[str, ...]] = {
    "206": ("206", "پژو 206", "پژو206", "دویست و شش"),
    "207": ("207", "پژو 207", "پژو207"),
    "pride": ("پراید", "pride", "131", "111"),
    "tiba": ("تیبا", "tiba"),
    "quik": ("کوییک", "quick", "quik"),
    "pars": ("پارس", "پژو پارس", "pars"),
    "405": ("405", "پژو 405"),
    "dena": ("دنا", "dena"),
    "shahin": ("شاهین", "shahin"),
    "saina": ("ساینا", "saina"),
}

USE_CASE_CUES: dict[str, tuple[str, ...]] = {
    "ride_hailing": ("اسنپ", "تپسی", "مسافرکشی", "تاکسی", "کار "),
    "family_first_car": ("خانواده", "خانوادگی", "ماشین اول", "بچه"),
    "commute": ("سرکار", "رفت و آمد", "شهری", "داخل شهر"),
    "resale_flip": ("سرمایه", "فروش مجدد", "سود"),
    "cargo": ("بار", "وانت", "باربری"),
}

DEAL_BREAKER_CUES: dict[str, tuple[str, ...]] = {
    "accident": ("تصادفی نباشه", "تصادفی نباش", "بدون تصادف", "سالم باشه"),
    "repaint": ("بدون رنگ", "رنگ نداشته باشه", "بی رنگ"),
    "unclear_documents": ("سند آزاد", "سند تک برگ", "در گرو نباشه"),
    "manual": ("اتومات", "اتوماتیک", "دنده اتومات"),
}


# ---------------------------------------------------------------------------
# IntentSpec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Weights:
    """Sums to 1.0. Shown to the user and adjustable — the tradeoff is theirs."""
    value: float = 0.35
    risk: float = 0.25
    running_cost: float = 0.15
    liquidity: float = 0.10
    mileage: float = 0.10
    recency: float = 0.05

    def normalized(self) -> "Weights":
        t = (self.value + self.risk + self.running_cost + self.liquidity
             + self.mileage + self.recency)
        if t <= 0:
            return Weights()
        return Weights(self.value / t, self.risk / t, self.running_cost / t,
                       self.liquidity / t, self.mileage / t, self.recency / t)


# A use case is a starting point for the weights, never a verdict on them.
# The user's slider always wins.
WEIGHT_PRESETS: dict[str, Weights] = {
    "ride_hailing": Weights(value=0.25, risk=0.25, running_cost=0.30,
                            liquidity=0.10, mileage=0.08, recency=0.02),
    "family_first_car": Weights(value=0.22, risk=0.40, running_cost=0.12,
                                liquidity=0.08, mileage=0.15, recency=0.03),
    "commute": Weights(value=0.30, risk=0.25, running_cost=0.22,
                       liquidity=0.08, mileage=0.12, recency=0.03),
    "resale_flip": Weights(value=0.45, risk=0.18, running_cost=0.05,
                           liquidity=0.22, mileage=0.08, recency=0.02),
    "cargo": Weights(value=0.30, risk=0.28, running_cost=0.22,
                     liquidity=0.10, mileage=0.08, recency=0.02),
    "unspecified": Weights(),
}


@dataclass(frozen=True)
class IntentSpec:
    raw_query: str
    budget_max_toman: int | None = None
    budget_min_toman: int | None = None
    budget_hard: bool = True
    model_hints: tuple[str, ...] = ()
    year_min: int | None = None
    max_mileage_km: int | None = None
    use_case: str = "unspecified"
    deal_breakers: tuple[str, ...] = ()
    weights: Weights = field(default_factory=Weights)
    risk_profile: str = "balanced"
    # What we INFERRED rather than were told. Surfaced so the user can correct
    # it — an assumption the user cannot see is an assumption they cannot fix.
    assumptions: tuple[str, ...] = ()
    # Text we saw and could not map. Never silently dropped: this is a
    # roadmap of what the parser is missing.
    unparsed: tuple[str, ...] = ()

    def with_weights(self, w: Weights) -> "IntentSpec":
        return replace(self, weights=w.normalized())


class IntentParser(Protocol):
    def parse(self, query: str) -> IntentSpec: ...


@dataclass
class RuleIntentParser:
    """Deterministic Persian parser. Ships, runs offline, never hallucinates.

    An LLM parser can replace this by producing the same `IntentSpec` — the
    contract is the frozen dataclass, not the mechanism. This one is the
    fallback that keeps the product working when the model is unavailable.
    """

    def parse(self, query: str) -> IntentSpec:
        q = normalize_fa(query)
        assumptions: list[str] = []
        consumed: list[str] = []

        budget_max = budget_min = None
        hard = True
        m = re.search(r"(?:زیر|تا|حداکثر|کمتر از)\s*([^،]*)", q)
        if m:
            budget_max = parse_amount(m.group(1))
            consumed.append(m.group(0))
        if budget_max is None:
            budget_max = parse_amount(q)
            if budget_max is not None:
                assumptions.append("عدد قیمت را سقف بودجه فرض کردیم")
        m = re.search(r"(?:بالای|از)\s*([^،]*?)\s*(?:به بالا)", q)
        if m:
            budget_min = parse_amount(m.group(1))
        if re.search(r"(انعطاف|تقریبا|حدود|کمی بیشتر)", q):
            hard = False
            assumptions.append("بودجه را انعطاف‌پذیر در نظر گرفتیم")

        models = tuple(k for k, al in MODEL_ALIASES.items()
                       if any(a in q for a in al))

        year_min = None
        m = re.search(r"مدل\s*(\d{2,4})", q)
        if m:
            y = int(m.group(1))
            year_min = 1300 + y if y < 100 else y
            consumed.append(m.group(0))

        max_km = None
        if re.search(r"(کم کارکرد|کم کار|کارکرد کم|کم کارکرده)", q):
            max_km = 120_000
            assumptions.append("«کم‌کارکرد» را حداکثر ۱۲۰٬۰۰۰ کیلومتر گرفتیم")
        m = re.search(
            r"کارکرد\s*(?:زیر|تا|کمتر از)\s*(\d+)\s*(هزار|k|کیلومتر|کیلو)?", q)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            v = n * 1000 if unit in ("هزار", "k") else n
            # Without a unit, a small number is not a distance — it is the
            # budget phrase leaking in ("کارکرد ... تا ۱.۵ میلیارد").
            if unit or v >= 1000:
                max_km = v

        use_case = "unspecified"
        for uc, cues in USE_CASE_CUES.items():
            if any(c in q for c in cues):
                use_case = uc
                break
        if use_case == "unspecified" and re.search(r"(کم مصرف|کم خرج|کم هزینه)", q):
            use_case = "commute"
            assumptions.append("از «کم‌خرج» کاربری روزمره برداشت شد")

        breakers = tuple(k for k, cues in DEAL_BREAKER_CUES.items()
                         if any(c in q for c in cues))

        risk = ("risk_averse" if ("accident" in breakers or
                                  use_case == "family_first_car")
                else "risk_tolerant" if use_case == "resale_flip"
                else "balanced")

        w = WEIGHT_PRESETS.get(use_case, Weights())
        if re.search(r"(کم مصرف|کم خرج|کم هزینه|بنزین)", q):
            w = replace(w, running_cost=w.running_cost + 0.10)
        if use_case != "unspecified":
            assumptions.append(
                f"وزن‌ها از پیش‌فرض «{use_case}» شروع شد — قابل تغییر است")

        rest = q
        for c in consumed:
            rest = rest.replace(c, " ")
        unparsed = tuple(t for t in re.split(r"[،.]| و ", rest)
                         if len(t.strip()) > 6
                         and not any(a in t for al in MODEL_ALIASES.values()
                                     for a in al))[:4]

        return IntentSpec(
            raw_query=query, budget_max_toman=budget_max,
            budget_min_toman=budget_min, budget_hard=hard,
            model_hints=models, year_min=year_min, max_mileage_km=max_km,
            use_case=use_case, deal_breakers=breakers,
            weights=w.normalized(), risk_profile=risk,
            assumptions=tuple(assumptions), unparsed=unparsed)


# ---------------------------------------------------------------------------
# Retrieval and the relaxation ladder
# ---------------------------------------------------------------------------

MIN_SHORTLIST = 3


@dataclass
class RelaxationReport:
    """What we loosened, in the user's words.

    Trading off FOR the user is fine. Doing it silently is not: a shortlist
    that quietly ignores the stated budget is worse than an empty one,
    because the user cannot tell it happened.
    """
    steps: list[str] = field(default_factory=list)

    @property
    def relaxed(self) -> bool:
        return bool(self.steps)

    def text_fa(self) -> str:
        if not self.steps:
            return ""
        return "با شرایط دقیق شما گزینه‌ی کافی نبود، پس: " + "؛ ".join(self.steps)


def _model_matches(model_key: str, hints: Sequence[str]) -> bool:
    """Does this row's model_key satisfy any of the parsed model hints?

    Two vocabularies meet here and they were never the same one. The parser
    emits a bare canonical slug — `206`, `pride` — from `MODEL_ALIASES`.
    Ingest emits `make|model|trim`: `Peugeot|206|type1`, `Saipa|Pride|111 ex`.
    The original test was `row.model_key not in spec.model_hints`, an exact
    equality against the WHOLE key, so on real data every model-constrained
    query retrieved nothing — six real 206s inside the stated budget, all
    filtered out, and the relaxation ladder then loosened a budget that was
    never the binding constraint.

    Nothing caught it because every ranking test builds its corpus with
    `model_key=m` where m is already the canonical slug. The ranker was being
    tested against its own vocabulary; W3 and W4 had never been run against
    each other. That is the general lesson and it is bigger than this line:
    a passing suite over a corpus the code shaped is not evidence about data
    the code did not shape.

    Compare the MODEL SEGMENT, case-folded, against the canonical slug and
    its latin aliases. Persian aliases are the query's vocabulary, not the
    key's, so they are not matched here. Keys without a separator (the
    synthetic corpora) are their own model segment.
    """
    seg = model_key.split("|")[1] if "|" in model_key else model_key
    seg = seg.casefold()
    for h in hints:
        if seg == h.casefold():
            return True
        for alias in MODEL_ALIASES.get(h, ()):
            if alias.isascii() and seg == alias.casefold():
                return True
    return False


def _passes(row: Row, spec: IntentSpec) -> bool:
    if spec.budget_max_toman and row.asking_price_toman > spec.budget_max_toman:
        return False
    if spec.budget_min_toman and row.asking_price_toman < spec.budget_min_toman:
        return False
    if spec.model_hints and not _model_matches(row.model_key, spec.model_hints):
        return False
    if spec.year_min and row.year_jalali < spec.year_min:
        return False
    if spec.max_mileage_km and row.mileage_km > spec.max_mileage_km:
        return False
    for db in spec.deal_breakers:
        if row.features.get(f"has_{db}", 0.0) > 0.5:
            return False
    return True


def retrieve(rows: Sequence[Row], spec: IntentSpec,
             min_results: int = MIN_SHORTLIST) -> tuple[list[Row], IntentSpec,
                                                        RelaxationReport]:
    """Hard filters, then walk the ladder if too few survive.

    Never returns an empty shortlist without saying what was loosened to
    avoid one — and never loosens a deal-breaker, which is the difference
    between a preference and a requirement.
    """
    rep = RelaxationReport()
    cur = spec
    out = [r for r in rows if _passes(r, cur)]
    if len(out) >= min_results:
        return out, cur, rep

    ladder = [
        ("budget", lambda s: replace(
            s, budget_max_toman=int(s.budget_max_toman * 1.10))
         if s.budget_max_toman else None,
         "بودجه ۱۰٪ افزایش یافت"),
        ("mileage", lambda s: replace(
            s, max_mileage_km=int(s.max_mileage_km * 1.30))
         if s.max_mileage_km else None,
         "سقف کارکرد ۳۰٪ بالاتر رفت"),
        ("year", lambda s: replace(s, year_min=s.year_min - 1)
         if s.year_min else None,
         "یک سال مدل پایین‌تر هم بررسی شد"),
        ("budget2", lambda s: replace(
            s, budget_max_toman=int(s.budget_max_toman * 1.10))
         if s.budget_max_toman and not s.budget_hard else None,
         "بودجه ۱۰٪ دیگر افزایش یافت"),
    ]
    for _, step, label in ladder:
        nxt = step(cur)
        if nxt is None:
            continue
        cur = nxt
        rep.steps.append(label)
        out = [r for r in rows if _passes(r, cur)]
        if len(out) >= min_results:
            break
    return out, cur, rep


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

RISK_PROFILE_QUANTILE = {"risk_averse": 0.15, "balanced": 0.35,
                         "risk_tolerant": 0.50}

# What a unit of risk costs, as a fraction of the car's value.
#
# This constant exists because of a bug the win-rate benchmark caught. The
# first implementation normalised risk to [0,1] across the candidate set and
# blended it as a weighted term — which throws away magnitude. A 20% defect
# probability on a 2B car costs the buyer ~240M; the same 20% on an 800M car
# costs ~96M. Scale-free risk cannot see that difference, so the ranker kept
# picking expensive moderately-damaged cars and LOST to sorting by price.
#
# The fix restores the product thesis as originally stated:
#
#     value = estimate − asking − risk_discount
#
# with every term in tomans, subtracted before any normalisation. Risk is
# priced, not scored.
#
# The value is policy, not a fitted parameter, and is deliberately
# conservative — a defect usually costs less than the full proportional
# share of the car because not every flagged risk materialises.
DAMAGE_COST_FACTOR = 0.60


def _norm(v: np.ndarray) -> np.ndarray:
    """Min-max to [0,1]; a constant column contributes nothing rather than NaN."""
    if v.size == 0:
        return v
    lo, hi = float(np.min(v)), float(np.max(v))
    return np.full_like(v, 0.5) if hi - lo < 1e-9 else (v - lo) / (hi - lo)


@dataclass
class ScoredRow:
    row: Row
    score: float
    breakdown: dict[str, float]
    conservative_estimate_toman: float
    adjusted_opportunity_toman: float
    expected_damage_toman: float = 0.0

    @property
    def role_fa(self) -> str:
        return self.breakdown.get("_role", "")  # set by the diversity pass


@dataclass
class Ranker:
    """Deterministic scoring over a retrieved candidate set.

    Every term is kept separately in `breakdown` so the card can show why a
    car ranked where it did, and so a weight change recomputes client-side
    without a round trip.

    Value uses a LOWER QUANTILE of the estimate rather than the median: an
    uncertain estimate is a riskier bet, not a smaller opportunity, and
    scaling a delta by a confidence scalar encodes the wrong claim. The
    quantile comes straight from the user's risk profile.
    """
    estimator: MarketEstimator

    def score(self, rows: Sequence[Row], spec: IntentSpec) -> list[ScoredRow]:
        if not rows:
            return []
        preds = self.estimator.predict(rows)            # raises if ungated
        alpha = RISK_PROFILE_QUANTILE[spec.risk_profile]
        qi = min(range(len(QUANTILES)),
                 key=lambda i: abs(QUANTILES[i] - alpha))

        asking = np.array([r.asking_price_toman for r in rows], dtype=float)
        conservative = preds[:, qi]
        risk = np.array([r.features.get("risk", 0.0) for r in rows])

        # Risk is priced in tomans against the car's own value, then
        # subtracted — not normalised and blended. See DAMAGE_COST_FACTOR.
        expected_damage_toman = risk * conservative * DAMAGE_COST_FACTOR
        opportunity = conservative - asking - expected_damage_toman
        owning = np.array([r.features.get("ownership_risk", 0.0) for r in rows])
        liquid = np.array([r.features.get("liquidity", 0.5) for r in rows])
        mileage = np.array([r.mileage_km for r in rows], dtype=float)
        recency = np.array([float(r.first_seen_ordinal) for r in rows])

        w = spec.weights.normalized()
        terms = {
            "value": w.value * _norm(opportunity),
            "risk": -w.risk * _norm(risk),
            "running_cost": -w.running_cost * _norm(owning),
            "liquidity": w.liquidity * _norm(liquid),
            "mileage": -w.mileage * _norm(mileage),
            "recency": w.recency * _norm(recency),
        }
        total = sum(terms.values())

        return [ScoredRow(
            row=r, score=float(total[i]),
            breakdown={k: float(v[i]) for k, v in terms.items()},
            conservative_estimate_toman=float(conservative[i]),
            adjusted_opportunity_toman=float(opportunity[i]),
            expected_damage_toman=float(expected_damage_toman[i]),
        ) for i, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# Diversity and shortlist
# ---------------------------------------------------------------------------

def diversify(scored: Sequence[ScoredRow], k: int = 5) -> list[ScoredRow]:
    """Pick the top item, then the best of each distinct role.

    Three near-identical Prides is a failed shortlist even if all three score
    well. The roles are also what the card labels each pick with, so the
    diversity pass is user-visible rather than a hidden reranking.
    """
    if not scored:
        return []
    ordered = sorted(scored, key=lambda s: s.score, reverse=True)
    picks: list[ScoredRow] = [ordered[0]]
    ordered[0].breakdown["_role"] = "بهترین تطابق کلی"

    def best(pred, label):
        for s in ordered:
            if s in picks:
                continue
            if pred(s):
                s.breakdown["_role"] = label
                picks.append(s)
                return

    best(lambda s: s.row.features.get("risk", 0.0) <= 0.15, "امن‌ترین گزینه")
    best(lambda s: s.adjusted_opportunity_toman > 0, "بیشترین صرفه")
    best(lambda s: s.row.asking_price_toman <= np.percentile(
        [x.row.asking_price_toman for x in ordered], 25), "ارزان‌ترین قابل قبول")
    for s in ordered:
        if len(picks) >= k:
            break
        if s not in picks:
            s.breakdown.setdefault("_role", "گزینه‌ی جایگزین")
            picks.append(s)
    return picks[:k]


@dataclass
class Shortlist:
    spec: IntentSpec
    items: list[ScoredRow]
    relaxation: RelaxationReport
    considered: int

    def summary_fa(self) -> str:
        L = [f"{self.considered} آگهی بررسی شد؛ {len(self.items)} گزینه انتخاب شد."]
        if self.relaxation.relaxed:
            L.append(self.relaxation.text_fa())
        if self.spec.assumptions:
            L.append("فرض‌های ما: " + "؛ ".join(self.spec.assumptions))
        return "\n".join(L)


@dataclass
class RankingPipeline:
    parser: IntentParser
    ranker: Ranker

    def run(self, query: str, rows: Sequence[Row], k: int = 5) -> Shortlist:
        spec = self.parser.parse(query)
        cands, used_spec, rep = retrieve(rows, spec)
        scored = self.ranker.score(cands, used_spec)
        return Shortlist(used_spec, diversify(scored, k), rep, len(cands))


# ---------------------------------------------------------------------------
# The experiment that decides whether this product should exist
# ---------------------------------------------------------------------------

@dataclass
class WinRateResult:
    n_queries: int
    caro_mean_utility: float
    price_sort_mean_utility: float
    random_mean_utility: float
    caro_wins: int
    ties: int

    @property
    def win_rate(self) -> float:
        return self.caro_wins / self.n_queries if self.n_queries else 0.0

    @property
    def uplift(self) -> float:
        base = abs(self.price_sort_mean_utility) or 1.0
        return (self.caro_mean_utility - self.price_sort_mean_utility) / base

    def __str__(self) -> str:
        return (f"queries={self.n_queries}  win-rate={self.win_rate:.0%}  "
                f"CARO={self.caro_mean_utility:,.0f}  "
                f"price-sort={self.price_sort_mean_utility:,.0f}  "
                f"random={self.random_mean_utility:,.0f}")


def winrate_vs_price_sort(pipeline: RankingPipeline, rows: Sequence[Row],
                          queries: Sequence[str],
                          utility_fn, k: int = 3) -> WinRateResult:
    """Compare CARO's shortlist against sorting by price, and against chance.

    `utility_fn(row) -> float` is the ground truth: what the buyer actually
    gains. On a synthetic corpus it comes from the generating process, which
    the ranker never sees — the ranker works from a FITTED estimator, so this
    is not circular.

    On real data there is no such function, and the honest substitute is a
    blind human panel: same queries, shuffled unlabelled shortlists, one
    question — "which list is more useful to buy from". That result belongs
    in EVAL.md whatever it says.

    Random is included because beating price-sort is only impressive if
    price-sort is not itself worse than chance.
    """
    rng = np.random.default_rng(0)
    caro_u, price_u, rand_u = [], [], []
    wins = ties = 0

    for q in queries:
        sl = pipeline.run(q, rows, k=k)
        if not sl.items:
            continue
        cands, _, _ = retrieve(rows, pipeline.parser.parse(q))
        if not cands:
            continue

        c = float(np.mean([utility_fn(s.row) for s in sl.items[:k]]))
        p = float(np.mean([utility_fn(r) for r in sorted(
            cands, key=lambda r: r.asking_price_toman)[:k]]))
        idx = rng.choice(len(cands), size=min(k, len(cands)), replace=False)
        rnd = float(np.mean([utility_fn(cands[i]) for i in idx]))

        caro_u.append(c); price_u.append(p); rand_u.append(rnd)
        if c > p:
            wins += 1
        elif c == p:
            ties += 1

    n = len(caro_u)
    return WinRateResult(
        n_queries=n,
        caro_mean_utility=float(np.mean(caro_u)) if n else 0.0,
        price_sort_mean_utility=float(np.mean(price_u)) if n else 0.0,
        random_mean_utility=float(np.mean(rand_u)) if n else 0.0,
        caro_wins=wins, ties=ties)
