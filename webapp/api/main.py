"""CARO web API.

    uvicorn webapp.api.main:app --reload

The backend is thin on purpose. CARO is a Python package, so this imports it
rather than talking to it over a socket: no service boundary, no serialisation
round-trip, no second place for a number to change on the way past. What lives
here is HTTP shape and nothing else — every decision, every refusal and every
number comes from `caro.ranking` and is passed through unaltered.

Three rules the endpoints enforce, because a website is where they are easiest
to lose:

**Every response carries the same envelope.** `corpus` says what the data is,
`status` says what may be done with it, `fault` says why. Those were one flat
dictionary until they were separated, and the separation is what lets a client
ask "did something break?" without first knowing which endpoint it called. See
webapp/api/schemas.py.

**A refusal is a 200, not a 500.** When the estimator has not cleared the
acceptance gate, `Ranker.score` raises `NotBenchmarked`, and that is a product
state (D11) rather than an error: the response says what it cannot serve, what
it still has, and why. An HTTP 500 would tell the client something broke, and
nothing has.

**The schema may not out-run the evidence (D50).** A refusal returns
`EvidenceItem`s, and that model has no estimate field at all — so a refusal
that carried an estimate is unrepresentable rather than merely wrong. The
types are the enforcement; `tests/test_api_contract.py` is the proof.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dataclasses import dataclass, replace                         # noqa: E402
from typing import Annotated                                       # noqa: E402

from fastapi import Depends, FastAPI, HTTPException, Path, Query, Response  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                 # noqa: E402

from caro.appraisal import NotBenchmarked                          # noqa: E402
from caro.ranking import Weights as RankWeights                    # noqa: E402
from caro.ingest.persian import PROVINCES                          # noqa: E402
from caro.ranking import IntentSpec, diversify, retrieve           # noqa: E402
from webapp.api import constraints                                 # noqa: E402
from webapp.api import corpus as corpus_mod                        # noqa: E402
from webapp.api import market                                      # noqa: E402
from webapp.api.accounts import router as accounts_router          # noqa: E402
from webapp.api.collection import router as collection_router      # noqa: E402
from webapp.api.contact import router as contact_router            # noqa: E402
from webapp.api.listings import router as listings_router          # noqa: E402
from webapp.api.market import router as market_router              # noqa: E402
from webapp.api.review import router as review_router              # noqa: E402
from webapp.api.security import SecurityHeaders, cors_origins      # noqa: E402
from webapp.api.edge import EdgeCache                              # noqa: E402
from webapp.api.metrics import Measure                             # noqa: E402
from webapp.api.metrics import router as metrics_router            # noqa: E402
from webapp.api.schemas import (                                   # noqa: E402
    CompareRequest, CompareResponse, CorpusMeta, CorpusResponse, Envelope,
    EvidenceItem, Fault, HealthResponse, Intent, ListingResponse,
    ReweightRequest, ScoredItem, SearchResponse, ServingStatus, SortKey,
    UncheckedItem, Weights,
)
from webapp.api.observability import init_sentry                   # noqa: E402
from webapp.api.observability import router as observability_router # noqa: E402

# Error reports, before the app exists so that the SDK sees it built. Off
# without SENTRY_DSN; with it, nothing personal leaves (observability.py).
init_sentry()

app = FastAPI(title="CARO", version="0.2.0",
              description="سامانه‌ی تصمیم‌یار خرید خودروی کارکرده")

# The contact inbox is a separate module because it touches disk and CARO's
# decision endpoints do not. Keeping them apart means a change to how messages
# are stored can never reach the ranking path.
app.include_router(contact_router)
# A model's page (webapp/api/market.py): its listings, cheapest first, and
# the asking prices of every published run.
app.include_router(market_router)
# The seller's login (webapp/api/accounts.py), the first of the listings
# sellers post on CARO itself. Its store is not the corpus, and nothing in
# the decision path reads it.
app.include_router(accounts_router)
# The listings sellers post (webapp/api/listings.py), read by no part of the
# decision path either.
app.include_router(listings_router)
# What the operator decides about them, and what the public reports
# (webapp/api/review.py).
app.include_router(review_router)
# The operator's test of the error reports (webapp/api/observability.py).
app.include_router(observability_router)
# The collection's records, from the worker (webapp/api/collection.py); off
# until its token and the runs' database are set.
app.include_router(collection_router)
# The API's own numbers, for the server's collector alone (webapp/api/metrics.py).
app.include_router(metrics_router)

# CORS is for development (webapp/api/security.py): production serves the
# site and the API from one origin. No cookie is used, so no credentials.
app.add_middleware(
    CORSMiddleware, allow_origins=cors_origins(), allow_credentials=False,
    allow_methods=["GET", "POST"], allow_headers=["Content-Type", "X-Admin-Token", "X-Admin-Code"])
app.add_middleware(SecurityHeaders)
# What the edge may keep: three GETs, by the served corpus's digest
# (webapp/api/edge.py, the plan's phase 4).
app.add_middleware(EdgeCache)
# Every answer counted and timed by its route; added last, so it is the
# outermost and times the others too (webapp/api/metrics.py).
app.add_middleware(Measure)

# The longest question the search reads, and the longest id a listing has.
# An unbounded string is work an attacker chooses the size of.
MAX_Q = 500
MAX_ID = 120

# The most listings one answer carries, a search's, a reweight's and a
# filter's alike (section 14 of tests/test_api_contract.py holds the three to
# one bound). It was 24 until 2026-11-25, when the owner asked that a reader
# choose how many to see; run17 holds 492 cars, and a hundred listings are
# some forty kilobytes.
MAX_K = 100
# The longest make or model a filter names, as a model's page bounds it.
MAX_NAME = market.MAX_NAME
# The bounds of a filter's numbers: a price in toman, a model year in the
# Jalali calendar the corpus writes, an odometer in kilometres.
MAX_TOMAN = 10**12
YEARS = (1300, 1499)
MAX_KM = 10_000_000


# ---------------------------------------------------------------------------
# the filter panel — the owner's choice of 2026-11-25
# ---------------------------------------------------------------------------
#
# A reader filters as on Divar: the price between two amounts, the model year
# between two years, the mileage between two readings, a make and a model, a
# province; and chooses the order and how many listings to see. The panel
# stands beside the sentence on the search page, where a constraint both
# state is the filter's, end by end, and alone on the filter page
# (`/api/filter`). A filter is judged as a sentence's constraint is
# (webapp/api/constraints.py): a listing that carries no value for one is
# held apart and says which, never let through.

@dataclass(frozen=True)
class Filters:
    price_min: int | None = None
    price_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None
    km_min: int | None = None
    km_max: int | None = None
    make: str | None = None
    model: str | None = None
    province: str | None = None


def filters(
        price_min: int | None = Query(None, ge=0, le=MAX_TOMAN, description="کمترین قیمت، تومان"),
        price_max: int | None = Query(None, ge=0, le=MAX_TOMAN, description="بیشترین قیمت، تومان"),
        year_min: int | None = Query(None, ge=YEARS[0], le=YEARS[1], description="از سال ساخت"),
        year_max: int | None = Query(None, ge=YEARS[0], le=YEARS[1], description="تا سال ساخت"),
        km_min: int | None = Query(None, ge=0, le=MAX_KM, description="کمترین کارکرد، کیلومتر"),
        km_max: int | None = Query(None, ge=0, le=MAX_KM, description="بیشترین کارکرد، کیلومتر"),
        make: str | None = Query(None, max_length=MAX_NAME, description="برند، همان‌طور که پیکره می‌نویسد"),
        model: str | None = Query(None, max_length=MAX_NAME, description="مدل، همان‌طور که پیکره می‌نویسد"),
        province: str | None = Query(None, max_length=40, description="استان")) -> Filters:
    """A filter's fields, each None where the panel left it empty. An empty
    string is a field left empty. A range whose low end is above its high end
    asks for nothing that could exist, and a province not of the thirty-one
    for nothing a listing carries: each is a 422 that says which."""
    for lo, hi, what in ((price_min, price_max, "price"), (year_min, year_max, "year"),
                         (km_min, km_max, "km")):
        if lo is not None and hi is not None and lo > hi:
            raise HTTPException(422, f"{what}_min ({lo}) is above {what}_max ({hi})")
    make = (make or "").strip() or None
    model = (model or "").strip() or None
    province = (province or "").strip() or None
    if province is not None and province not in PROVINCES:
        raise HTTPException(422, f"province {province!r} is not one of the thirty-one")
    return Filters(price_min, price_max, year_min, year_max, km_min, km_max,
                   make, model, province)


def _with_filters(spec, f: Filters | None):
    """The spec with the filter's constraints in it, and which came from the
    filter. An end the filter states replaces the sentence's same end; one it
    leaves empty keeps the sentence's."""
    if f is None:
        return spec, []
    changes: dict = {}
    keys: list[str] = []
    if f.price_min is not None or f.price_max is not None:
        if f.price_min is not None:
            changes["budget_min_toman"] = f.price_min
        if f.price_max is not None:
            changes["budget_max_toman"] = f.price_max
        changes["budget_hard"] = True
        keys.append("budget")
    if f.year_min is not None or f.year_max is not None:
        if f.year_min is not None:
            changes["year_min"] = f.year_min
        if f.year_max is not None:
            changes["year_max"] = f.year_max
        keys.append("year")
    if f.km_min is not None or f.km_max is not None:
        if f.km_min is not None:
            changes["min_mileage_km"] = f.km_min
        if f.km_max is not None:
            changes["max_mileage_km"] = f.km_max
        keys.append("mileage")
    if f.province is not None:
        changes["provinces"] = (f.province,)
        keys.append("province")
    if f.make is not None:
        changes["makes"] = (f.make,)
        keys.append("make")
    if f.model is not None:
        changes["model_hints"] = (f.model.lower(),)
        keys.append("model")
    return (replace(spec, **changes) if changes else spec), keys


# ---------------------------------------------------------------------------
# envelope — assembled in one place so three endpoints cannot disagree
# ---------------------------------------------------------------------------

def _fault(c) -> Fault | None:
    """Why nothing is being served, or None. Four reasons, never merged.

    Collapsing them would tell an operator whose artifact failed to load that
    the estimator has not been benchmarked: true, and not their problem. The
    same holds one level down — an operator who typed a run name that has no
    artifact is not looking at a corrupt file, and telling them so sends them
    to inspect bytes that are fine.
    """
    if c.fault_code == "RUN_NOT_FOUND":
        return Fault(
            code="RUN_NOT_FOUND",
            message=c.fault or "the configured run has no artifact on disk",
            fa="این استقرار صریحاً یک run را برای سرو انتخاب کرده و فایل آن "
               "روی دیسک نیست، پس هیچ چیز سرو نمی‌شود. عمداً به پیکره‌ی "
               "ساختگی برنمی‌گردیم: وقتی کسی گفته کدام شواهد باید سرو شود، "
               "جایگزینی خاموشِ آن با داده‌ی تولیدشده دقیقاً همان چیزی است "
               "که برچسب پیکره برای جلوگیری از آن هست.",
            still_available=["intent"])
    if c.fault_code == "CATALOG_UNAVAILABLE":
        return Fault(
            code="CATALOG_UNAVAILABLE",
            message=c.fault or "the catalog cannot serve the configured run",
            fa="این استقرار آگهی‌ها را از انبار کاتالوگ می‌خواند و آن انبار "
               "الان نمی‌تواند این run را سرو کند، پس هیچ چیز سرو نمی‌شود. به "
               "فایل‌ها یا داده‌ی ساختگی برنمی‌گردیم: وقتی گفته شده شواهد از "
               "کجا خوانده شود، خواندن از جای دیگر جایگزینی بی‌صداست.",
            still_available=["intent"])
    if c.kind == "UNUSABLE":
        return Fault(
            code="CORPUS_INVALID",
            message=c.fault or "the artifact on disk could not be loaded",
            fa="یک پیکره‌ی واقعی روی دیسک هست و بارگذاری نمی‌شود، پس هیچ چیز "
               "سرو نمی‌شود. به داده‌ی ساختگی هم برنمی‌گردیم: آن‌وقت سایت "
               "سالم به‌نظر می‌رسید و کسی نمی‌فهمید شواهد واقعی رد شده است.",
            still_available=["intent"])
    if not c.gated:
        return Fault(
            code="ESTIMATOR_NOT_GATED",
            message="no estimator has cleared AcceptanceGate on this corpus, "
                    "so no ranking may be served on it (D43)",
            fa="برای این پیکره هیچ برآوردگری از دروازه‌ی پذیرش عبور نکرده "
               "است، پس رتبه‌بندی سرو نمی‌شود. آنچه داریم شواهد است: "
               "آگهی‌های منطبق، ویژگی‌های استخراج‌شده و منبع هرکدام.",
            still_available=["intent", "candidates", "evidence"])
    return None


def _envelope(c, *, served: bool, fault: Fault | None = None) -> Envelope:
    """The envelope for this response.

    `fault` overrides the corpus-level one, and the precedence is deliberate:
    `_fault(c)` answers "what is wrong with this deployment", while an explicit
    fault answers "what happened to THIS request". When both are true — a
    healthy corpus whose estimator is not gated, asked for an id it does not
    hold — the specific one is what the client needs, because the gate is not
    why this request failed and nothing would be ranked anyway.

    There is one `fault` field rather than a list on purpose. A response that
    carried two reasons would leave the client choosing between them, which is
    this function's job and not the client's.
    """
    ident = c.identity.as_dict() if c.identity is not None else None
    return Envelope(
        corpus=CorpusMeta(
            label_fa=c.label_fa, source=c.source, note_fa=c.note_fa,
            rows=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            identity=ident),
        status=ServingStatus(kind=c.kind, gated=c.gated, served=served),
        fault=fault if fault is not None else _fault(c))


# ---------------------------------------------------------------------------
# serialisation — nothing invented on the way out
# ---------------------------------------------------------------------------

def _split_key(model_key: str, i: int) -> str | None:
    parts = model_key.split("|")
    return (parts[i] or None) if len(parts) > i else None


def _row_evidence(r) -> EvidenceItem:
    """An appraisal Row as evidence. No estimate: the model has no room.

    `product_class`, `price_status` and `price_kind` stay None here, and
    deliberately. A Row carries none of them, and a Row exists only where
    eligibility admitted the listing — which is exactly where the class is
    `vehicle` and both price gates passed. Stamping those values would be
    reading the gate's own decision back as an observation about the page.
    Under-informative is the right direction: a client that is not told
    cannot pretend to know (D50).
    """
    return EvidenceItem(
        id=r.listing_id, model_key=r.model_key,
        make=_split_key(r.model_key, 0) if "|" in r.model_key else None,
        model=(_split_key(r.model_key, 1) if "|" in r.model_key
               else r.model_key),
        trim=_split_key(r.model_key, 2),
        year_jalali=r.year_jalali, mileage_km=int(r.mileage_km),
        asking_price_toman=int(r.asking_price_toman))


def _middle_key(x) -> tuple | None:
    y = getattr(x, "year_jalali", None)
    return (*market._key(getattr(x, "make", None), getattr(x, "model", None)), int(y)) if y else None


def _year_middles(c) -> dict:
    """{(make, model, year): (priced listings, their middle or None)} over the
    served corpus's cars: the middles a model's page draws by year, by its own
    rules -- the gate's reading of a price, and no middle under three
    (webapp/api/market.py)."""
    by: dict = {}
    for x in market._vehicles(c):
        p, key = market.priced(x), _middle_key(x)
        if p is not None and key is not None:
            by.setdefault(key, []).append(p)
    return {key: (len(v), market._middle(v)) for key, v in by.items()}


def _vs_middle(x, middles: dict) -> float | None:
    """How far this listing's price stands from its make, model and year's
    middle, as a fraction of it: -0.1 is a tenth below. None where either is
    missing."""
    p = market.priced(x)
    mid = middles.get(_middle_key(x), (0, None))[1]
    return (p - mid) / mid if p is not None and mid else None


def _ordered(pairs: list, sort: str | None, middles: dict) -> list:
    """(listing, missing) pairs in the order the reader chose; the corpus's
    own order where none was. What a listing has no value for -- a price, a
    middle, a plausible odometer -- puts it after those that have one, and a
    tie keeps the corpus's order."""
    if sort is None:
        return pairs

    def key(item):
        i, (x, _) = item
        price = market.priced(x)
        if sort == "price":
            return (price is None, price or 0, i)
        if sort == "mileage":
            km = constraints.odometer(x)
            return (km is None, km or 0, i)
        # «ارزان نسبت به بازار»: the furthest below its middle first; then the
        # listings with no middle to compare with, the priced cheapest first.
        gap = _vs_middle(x, middles)
        return (gap is None, gap if gap is not None else 0, price is None, price or 0, i)

    return [p for _, p in sorted(enumerate(pairs), key=key)]


def _listing_evidence(x, middles: dict | None = None) -> EvidenceItem:
    extra = {}
    if middles is not None:
        n, mid = middles.get(_middle_key(x), (0, None))
        extra = {"year_middle_toman": mid, "year_middle_priced": n}
    return EvidenceItem(**extra,
        id=x.listing_id, url=x.url or "",
        model_key="|".join(p or "" for p in (x.make, x.model, x.trim)),
        make=x.make, model=x.model, trim=x.trim,
        year_jalali=x.year_jalali,
        mileage_km=(int(x.mileage_km) if x.mileage_km is not None else None),
        asking_price_toman=(int(x.asking_price_toman)
                            if x.asking_price_toman is not None else None),
        gearbox=x.gearbox, fuel=x.fuel, color=x.color,
        condition=x.body_condition, province=x.city,
        province_source=getattr(x, "province_source", None),
        seller_type=getattr(x, "seller_type", None),
        product_class=x.product_class,
        price_status=x.price_status, price_kind=x.price_kind,
        mileage_status=x.mileage_status)


def _scored(s, rank: int) -> ScoredItem:
    base = _row_evidence(s.row)
    return ScoredItem(
        **base.model_dump(),
        rank=rank,
        role_fa=s.breakdown.get("_role", ""),
        score=s.score,
        estimate_toman=int(s.conservative_estimate_toman),
        opportunity_toman=int(s.adjusted_opportunity_toman),
        expected_damage_toman=int(s.expected_damage_toman),
        # Every term separately, so the card can say WHY this car ranked here
        # and the client can recompute a reweighting without a round trip.
        terms={k: v for k, v in s.breakdown.items() if not k.startswith("_")},
        features={k: float(v) for k, v in (s.row.features or {}).items()
                  if not k.startswith("_") and isinstance(v, (int, float))})


def _intent(spec, from_filter=()) -> Intent:
    w = spec.weights.normalized()
    return Intent(
        year_max=spec.year_max, min_mileage_km=spec.min_mileage_km,
        makes=list(spec.makes), from_filter=list(from_filter),
        query=spec.raw_query,
        budget_max_toman=spec.budget_max_toman,
        budget_min_toman=spec.budget_min_toman,
        budget_hard=spec.budget_hard,
        models=list(spec.model_hints),
        year_min=spec.year_min,
        max_mileage_km=spec.max_mileage_km,
        provinces=list(spec.provinces),
        use_case=spec.use_case,
        risk_profile=spec.risk_profile,
        deal_breakers=list(spec.deal_breakers),
        # Surfaced, never silent. An assumption the user cannot see is one
        # they cannot correct, and `unparsed` is kept rather than dropped.
        assumptions=list(spec.assumptions),
        unparsed=[u.strip() for u in spec.unparsed if u.strip()],
        weights=Weights(**{f: getattr(w, f) for f in
                           ("value", "risk", "running_cost", "liquidity",
                            "mileage", "recency")}))


def _evidence(c, spec, cands, k: int, sort: str | None = None) -> dict:
    """What can still be shown when no ranking may be served — the four
    evidence fields of a SearchResponse.

    On a corpus whose rows all fail eligibility, `cands` is empty and serving
    it would show an empty table under a heading promising matching listings.
    So the listings are matched directly: first the gate, which nobody
    chooses, and then ONLY the constraints the buyer stated — model, budget,
    year, odometer. No relaxation ladder, no ordering, no estimate. It is a
    filter, not a retrieval, and it is not pretending to be the second one.

    A listing that carries no value for a constraint is not let through it:
    it is not a match, and it goes apart, saying which constraint it could
    not be checked against. The rule is `constraints.judge`.
    """
    if cands:
        # Appraisal Rows: eligibility required every value judged here, so
        # nothing in them is unknown. They are in the order retrieval left
        # them, and the answer says no other.
        return {"evidence": [_row_evidence(r) for r in cands[:k]],
                "evidence_total": len(cands), "sort": None}

    matched, apart = [], []
    makes = {market._key(m, None)[0] for m in spec.makes}
    for x in c.listings:
        # The gate (D52): only `vehicle` is shown as a car. `unknown` does
        # not pass — a record whose class was never determined is not a car,
        # which is the rule eligibility already applies before a row can be
        # scored. Rows above need no check for the same reason.
        if x.product_class != "vehicle":
            continue
        # A model two makes write is named by its make and model («jac|s5»).
        if spec.model_hints and (x.model or "").lower() not in spec.model_hints \
                and f"{x.make or ''}|{x.model or ''}".lower() not in spec.model_hints:
            continue
        # A make a filter names is a listing's make as the corpus writes it,
        # as a model's page matches one (market._key); like a model, another
        # make is not a candidate at all.
        if makes and market._key(x.make, None)[0] not in makes:
            continue
        missing = constraints.unchecked(constraints.judge(x, spec))
        if missing is None:
            continue
        (apart if missing else matched).append((x, missing))

    middles = _year_middles(c)
    matched, apart = _ordered(matched, sort, middles), _ordered(apart, sort, middles)
    return {
        "evidence": [_listing_evidence(x, middles) for x, _ in matched[:k]],
        "evidence_total": len(matched),
        "evidence_unchecked": [
            UncheckedItem(**_listing_evidence(x, middles).model_dump(), unchecked=m)
            for x, m in apart[:k]],
        "evidence_unchecked_total": len(apart),
        "sort": sort,
    }


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

def _build() -> str | None:
    """The commit this process runs: the one its image was built from
    (CARO_BUILD), or else the one Vercel deployed (VERCEL_GIT_COMMIT_SHA,
    which Vercel gives its functions), or None where neither says."""
    return os.environ.get("CARO_BUILD") or os.environ.get("VERCEL_GIT_COMMIT_SHA") or None


@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    c = corpus_mod.active()
    return HealthResponse(ok=True, build=_build(),
                          corpus=c.identity.sha256 if c.identity is not None else None)


@app.get("/api/corpus", response_model=CorpusResponse)
def which_corpus() -> CorpusResponse:
    c = corpus_mod.active()
    return CorpusResponse(**_envelope(c, served=False).model_dump())


@app.get("/api/search", response_model=SearchResponse)
def search(q: str = Query(..., min_length=2, max_length=MAX_Q, description="پرسش فارسی"),
           k: int = Query(6, ge=1, le=MAX_K),
           sort: Annotated[SortKey | None, Query(description="ترتیب آگهی‌ها")] = None,
           flt: Annotated[Filters | None, Depends(filters)] = None) -> SearchResponse:
    """A Persian sentence in, a defensible ranked decision out — or a refusal.

    The refusal path is the interesting one and it returns 200: the estimator
    may not have cleared the gate on this corpus, in which case there is no
    shortlist to serve and the response says so, keeping the parsed intent and
    the evidence that are still true.

    The filter panel's fields ride along (`filters`); where the sentence and
    the panel state the same end of a constraint, the panel's stands.
    """
    c = corpus_mod.active()
    spec, keys = _with_filters(c.pipeline.parser.parse(q), flt)
    return _answer(c, spec, keys, k, sort)


@app.get("/api/filter", response_model=SearchResponse)
def filter_listings(k: Annotated[int, Query(ge=1, le=MAX_K)] = 12,
                    sort: Annotated[SortKey, Query(description="ترتیب آگهی‌ها")] = "market",
                    flt: Annotated[Filters | None, Depends(filters)] = None) -> SearchResponse:
    """The filter page: no sentence, only the panel's fields, the order the
    reader chose -- «ارزان نسبت به بازار» unless they chose another -- and as
    many listings as they asked for. It answers as a search does, from the
    same code: the same gate, the same constraints, the same envelope."""
    c = corpus_mod.active()
    spec, keys = _with_filters(IntentSpec(raw_query=""), flt)
    return _answer(c, spec, keys, k, sort)


def _answer(c, spec, keys, k: int, sort: str | None) -> SearchResponse:
    """A search's answer once its spec is known: a sentence's, a filter's, or
    both."""
    # The gate is a property of the CORPUS, not of this query, so it is
    # answered before the query is retrieved against — and the retrieval
    # ladder is not run at all.
    #
    # Two bugs lived in doing it the other way round. `Ranker.score` returns
    # [] for an empty candidate set BEFORE it calls `predict()`, so on a real
    # corpus — where eligibility fails closed on every row and `cands` is
    # therefore always empty — the refusal never fired and the response said
    # `served: true` with zero items. And `retrieve` would then relax the
    # buyer's stated constraints hunting for a shortlist that cannot be
    # served, so every query reported «قیدها شل شد» when the constraints were
    # never the problem.
    if not c.gated:
        return SearchResponse(
            **_envelope(c, served=False).model_dump(),
            intent=_intent(spec, keys),     # as stated, not as relaxed
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=0, relaxed=False, relaxation_fa="",
            items=[], **_evidence(c, spec, [], k, sort))

    cands, used, rep = retrieve(c.rows, spec)
    try:
        scored = c.pipeline.ranker.score(cands, used)
    except NotBenchmarked:
        # Defence in depth: `gated` is a summary the corpus reports,
        # `NotBenchmarked` is the mechanism refusing. If they ever disagree,
        # the mechanism wins.
        return SearchResponse(
            **_envelope(c, served=False).model_dump(),
            intent=_intent(used, keys),
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=len(cands), relaxed=rep.relaxed,
            relaxation_fa=rep.text_fa() if rep.relaxed else "",
            items=[], **_evidence(c, used, cands, k, sort))

    # A served ranking is in the ranking's order, whatever order was asked
    # for: the order is the decision, and the answer says so (`sort` null).
    items = diversify(scored, k=k)
    return SearchResponse(
        **_envelope(c, served=True).model_dump(),
        intent=_intent(used, keys),
        considered=len(c.listings) or len(c.rows),
        appraisable=len(c.rows),
        candidates=len(cands), relaxed=rep.relaxed,
        relaxation_fa=rep.text_fa() if rep.relaxed else "",
        items=[_scored(s, i + 1) for i, s in enumerate(items)],
        evidence=[])


@app.post("/api/search/reweight", response_model=SearchResponse)
def search_reweight(weights: ReweightRequest, q: str = Query(..., max_length=MAX_Q),
                    k: int = Query(6, ge=1, le=MAX_K),
                    sort: Annotated[SortKey | None, Query(description="ترتیب آگهی‌ها")] = None,
                    flt: Annotated[Filters | None, Depends(filters)] = None) -> SearchResponse:
    """The same query with the user's own weights. «بهترین» is a function.

    `k` is bounded as `/api/search` bounds it; D60 recorded that it was not.
    Unbounded, on run11 «پراید» — 56 matches — answered k=0 with 200 and an
    empty table, and k=-1 with 200 and every match but the last: a slice,
    silently.
    """
    c = corpus_mod.active()
    spec, keys = _with_filters(c.pipeline.parser.parse(q), flt)
    given = {f: v for f, v in weights.model_dump().items() if v is not None}
    if given:
        was = spec.weights
        spec = spec.with_weights(RankWeights(**{
            f: given.get(f, getattr(was, f)) for f in
            ("value", "risk", "running_cost", "liquidity", "mileage",
             "recency")}))

    if not c.gated:
        return SearchResponse(
            **_envelope(c, served=False).model_dump(),
            intent=_intent(spec, keys),
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=0, relaxed=False, relaxation_fa="",
            items=[], **_evidence(c, spec, [], k, sort))

    cands, used, rep = retrieve(c.rows, spec)
    try:
        items = diversify(c.pipeline.ranker.score(cands, used), k=k)
    except NotBenchmarked:
        return SearchResponse(
            **_envelope(c, served=False).model_dump(),
            intent=_intent(used, keys),
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=len(cands), relaxed=rep.relaxed,
            relaxation_fa=rep.text_fa() if rep.relaxed else "",
            items=[], **_evidence(c, used, cands, k, sort))

    return SearchResponse(
        **_envelope(c, served=True).model_dump(),
        intent=_intent(used, keys),
        considered=len(c.listings) or len(c.rows),
        appraisable=len(c.rows),
        candidates=len(cands), relaxed=rep.relaxed,
        relaxation_fa=rep.text_fa() if rep.relaxed else "",
        items=[_scored(s, i + 1) for i, s in enumerate(items)], evidence=[])


@app.get("/api/listing/{listing_id}", response_model=ListingResponse)
def listing(listing_id: str = Path(..., max_length=MAX_ID),
            response: Response = None) -> ListingResponse:
    """One listing, or the envelope saying why there is none.

    `response` is FastAPI's, injected, and is how the 404 below is set without
    leaving the typed path: `raise HTTPException` produces `{"detail": "..."}`
    and nothing else, so a client had to read English prose out of a body that
    carried no corpus, no status and no fault code. Setting the status on the
    injected response instead keeps `response_model=` validating what goes out,
    so a 404 is a ListingResponse like any other — same envelope, same fields,
    a different `fault.code`.

    The default of None is for direct calls from the suite, where FastAPI is
    not the one calling; over HTTP it is always injected.
    """
    c = corpus_mod.active()

    # Nothing loaded, so this id cannot be looked up — not "is absent". The
    # 404 below is a statement about a corpus that EXISTS and does not hold
    # this listing; returning it here would say the same words about a corpus
    # that was never read, and the page would tell a buyer their car is gone
    # when the truth is that this deployment is serving nothing (D54).
    #
    # Kept narrow deliberately: only UNUSABLE. A healthy corpus that genuinely
    # lacks the id still 404s, because turning every miss into a 200 would
    # hide the one case this endpoint is actually for.
    if c.kind == "UNUSABLE":
        return ListingResponse(**_envelope(c, served=False).model_dump(),
                               listing=None)

    got = next((x for x in c.listings if x.listing_id == listing_id), None)
    if got is not None:
        return ListingResponse(**_envelope(c, served=False).model_dump(),
                               listing=_listing_evidence(got))

    row = next((r for r in c.rows if r.listing_id == listing_id), None)
    if row is None:
        # A corpus WAS read and does not hold this id. 404 is the right status
        # and it keeps the envelope: the client learns which corpus answered,
        # how big it is and what its digest was, alongside the fact that the
        # id is not in it. That is a claim we have standing to make, and the
        # code says so without the client parsing the sentence.
        if response is not None:
            response.status_code = 404
        return ListingResponse(
            **_envelope(c, served=False, fault=Fault(
                code="LISTING_NOT_FOUND",
                message=f"no listing {listing_id!r} in the corpus being "
                        f"served ({c.source})",
                fa="این شناسه در پیکره‌ای که همین حالا سرو می‌شود نیست. "
                   "پیکره خوانده شده و سالم است؛ این آگهی در آن نبود — که "
                   "با «این آگهی وجود ندارد» یکی نیست، چون پیکره تنها یک "
                   "برداشت از یک روز است.",
                still_available=[])).model_dump(),
            listing=None)
    return ListingResponse(**_envelope(c, served=False).model_dump(),
                           listing=_row_evidence(row))


@app.post("/api/compare", response_model=CompareResponse)
def compare(req: CompareRequest, response: Response = None) -> CompareResponse:
    """Side by side, with each scoring term kept apart.

    The cheapest car is not the best opportunity, and a comparison table that
    shows only price is the product this one exists to argue against.

    `response` is FastAPI's — see `listing()` for why the 404 is set on it
    rather than raised.
    """
    c = corpus_mod.active()

    # Same as `listing()` above, for the same reason: «none of those ids are
    # in this corpus» is true of a corpus, and there is no corpus here.
    if c.kind == "UNUSABLE":
        return CompareResponse(**_envelope(c, served=False).model_dump(),
                               rows=[], evidence=[])

    wanted = [r for r in c.rows if r.listing_id in set(req.ids)]
    if not c.gated:
        # Nothing may be ranked, so what compare can show is the listings
        # themselves — every requested one the corpus holds, whether or not
        # it became a Row. This branch used to run only when NO requested id
        # was a Row. Beside one, the answer came from the Rows alone, and an
        # id that was not a Row — the assignment, a listing with no price —
        # was dropped with nothing on the screen to say it had been asked
        # for. A listing carries its own class, so the screen can say what
        # it is instead of losing it.
        keep = [x for x in c.listings if x.listing_id in set(req.ids)]
        if keep:
            return CompareResponse(
                **_envelope(c, served=False).model_dump(),
                rows=[], evidence=[_listing_evidence(x) for x in keep])
    if not wanted:
        # Not one of them matched, in a corpus that was read. Its own code
        # rather than LISTING_NOT_FOUND: compare answers about a SET, and when
        # only some ids match it returns 200 with those, so this means "none
        # of them" — which sends the reader back to a selection, not back to a
        # car.
        if response is not None:
            response.status_code = 404
        return CompareResponse(
            **_envelope(c, served=False, fault=Fault(
                code="COMPARE_IDS_NOT_FOUND",
                message=f"none of {len(req.ids)} requested id(s) are in the "
                        f"corpus being served ({c.source})",
                fa="هیچ‌کدام از این شناسه‌ها در پیکره‌ای که سرو می‌شود نبودند. "
                   "پیکره سالم است و خوانده شده؛ این شناسه‌ها در آن نیستند — "
                   "احتمالاً از یک پیکره‌ی دیگر یا از یک نشانی قدیمی آمده‌اند.",
                still_available=[])).model_dump(),
            rows=[], evidence=[])

    spec = c.pipeline.parser.parse(req.q)
    try:
        if not c.gated:
            raise NotBenchmarked("corpus is not gated")
        scored = c.pipeline.ranker.score(wanted, spec)
    except NotBenchmarked:
        return CompareResponse(**_envelope(c, served=False).model_dump(),
                               rows=[],
                               evidence=[_row_evidence(r) for r in wanted])

    order = {s.row.listing_id: s for s in scored}
    return CompareResponse(
        **_envelope(c, served=True).model_dump(),
        rows=[_scored(order[i], n + 1)
              for n, i in enumerate(req.ids) if i in order],
        evidence=[])
