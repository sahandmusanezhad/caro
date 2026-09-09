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

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query                  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                 # noqa: E402

from caro.appraisal import NotBenchmarked                          # noqa: E402
from caro.ranking import Weights as RankWeights                    # noqa: E402
from caro.ranking import diversify, retrieve                       # noqa: E402
from webapp.api import corpus as corpus_mod                        # noqa: E402
from webapp.api.contact import router as contact_router            # noqa: E402
from webapp.api.schemas import (                                   # noqa: E402
    CompareRequest, CompareResponse, CorpusMeta, CorpusResponse, Envelope,
    EvidenceItem, Fault, HealthResponse, Intent, ListingResponse,
    ReweightRequest, ScoredItem, SearchResponse, ServingStatus, Weights,
)

app = FastAPI(title="CARO", version="0.2.0",
              description="سامانه‌ی تصمیم‌یار خرید خودروی کارکرده")

# The contact inbox is a separate module because it touches disk and CARO's
# decision endpoints do not. Keeping them apart means a change to how messages
# are stored can never reach the ranking path.
app.include_router(contact_router)

app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# envelope — assembled in one place so three endpoints cannot disagree
# ---------------------------------------------------------------------------

def _fault(c) -> Fault | None:
    """Why nothing is being served, or None. Two reasons, never merged.

    Collapsing them would tell an operator whose artifact failed to load that
    the estimator has not been benchmarked: true, and not their problem.
    """
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


def _envelope(c, *, served: bool) -> Envelope:
    ident = c.identity.as_dict() if c.identity is not None else None
    return Envelope(
        corpus=CorpusMeta(
            label_fa=c.label_fa, source=c.source, note_fa=c.note_fa,
            rows=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            identity=ident),
        status=ServingStatus(kind=c.kind, gated=c.gated, served=served),
        fault=_fault(c))


# ---------------------------------------------------------------------------
# serialisation — nothing invented on the way out
# ---------------------------------------------------------------------------

def _split_key(model_key: str, i: int) -> str | None:
    parts = model_key.split("|")
    return (parts[i] or None) if len(parts) > i else None


def _row_evidence(r) -> EvidenceItem:
    """An appraisal Row as evidence. No estimate: the model has no room."""
    return EvidenceItem(
        id=r.listing_id, model_key=r.model_key,
        make=_split_key(r.model_key, 0) if "|" in r.model_key else None,
        model=(_split_key(r.model_key, 1) if "|" in r.model_key
               else r.model_key),
        trim=_split_key(r.model_key, 2),
        year_jalali=r.year_jalali, mileage_km=int(r.mileage_km),
        asking_price_toman=int(r.asking_price_toman))


def _listing_evidence(x) -> EvidenceItem:
    return EvidenceItem(
        id=x.listing_id, url=x.url or "",
        model_key="|".join(p or "" for p in (x.make, x.model, x.trim)),
        make=x.make, model=x.model, trim=x.trim,
        year_jalali=x.year_jalali,
        mileage_km=(int(x.mileage_km) if x.mileage_km is not None else None),
        asking_price_toman=(int(x.asking_price_toman)
                            if x.asking_price_toman is not None else None),
        gearbox=x.gearbox, fuel=x.fuel, color=x.color,
        condition=x.body_condition, province=x.city,
        seller_type=getattr(x, "seller_type", None))


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


def _intent(spec) -> Intent:
    w = spec.weights.normalized()
    return Intent(
        query=spec.raw_query,
        budget_max_toman=spec.budget_max_toman,
        budget_min_toman=spec.budget_min_toman,
        budget_hard=spec.budget_hard,
        models=list(spec.model_hints),
        year_min=spec.year_min,
        max_mileage_km=spec.max_mileage_km,
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


def _evidence(c, spec, cands, k: int) -> list[EvidenceItem]:
    """What can still be shown when no ranking may be served.

    On a corpus whose rows all fail eligibility, `cands` is empty and serving
    it would show an empty table under a heading promising matching listings.
    So the listings are matched directly, using ONLY the constraints the buyer
    stated — model, budget, year, odometer. No relaxation ladder, no ordering,
    no estimate. It is a filter, not a retrieval, and it is not pretending to
    be the second one.
    """
    if cands:
        return [_row_evidence(r) for r in cands[:k]]

    def keeps(x) -> bool:
        if spec.model_hints and (x.model or "").lower() not in spec.model_hints:
            return False
        p = x.asking_price_toman
        if spec.budget_max_toman is not None and p is not None \
                and p > spec.budget_max_toman:
            return False
        if spec.budget_min_toman is not None and p is not None \
                and p < spec.budget_min_toman:
            return False
        if spec.year_min is not None and x.year_jalali is not None \
                and x.year_jalali < spec.year_min:
            return False
        if spec.max_mileage_km is not None and x.mileage_km is not None \
                and x.mileage_km > spec.max_mileage_km:
            return False
        return True

    return [_listing_evidence(x) for x in c.listings if keeps(x)][:k]


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(ok=True)


@app.get("/api/corpus", response_model=CorpusResponse)
def which_corpus() -> CorpusResponse:
    c = corpus_mod.active()
    return CorpusResponse(**_envelope(c, served=False).model_dump())


@app.get("/api/search", response_model=SearchResponse)
def search(q: str = Query(..., min_length=2, description="پرسش فارسی"),
           k: int = Query(6, ge=1, le=24)) -> SearchResponse:
    """A Persian sentence in, a defensible ranked decision out — or a refusal.

    The refusal path is the interesting one and it returns 200: the estimator
    may not have cleared the gate on this corpus, in which case there is no
    shortlist to serve and the response says so, keeping the parsed intent and
    the evidence that are still true.
    """
    c = corpus_mod.active()
    spec = c.pipeline.parser.parse(q)

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
            intent=_intent(spec),           # as stated, not as relaxed
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=0, relaxed=False, relaxation_fa="",
            items=[], evidence=_evidence(c, spec, [], k))

    cands, used, rep = retrieve(c.rows, spec)
    try:
        scored = c.pipeline.ranker.score(cands, used)
    except NotBenchmarked:
        # Defence in depth: `gated` is a summary the corpus reports,
        # `NotBenchmarked` is the mechanism refusing. If they ever disagree,
        # the mechanism wins.
        return SearchResponse(
            **_envelope(c, served=False).model_dump(),
            intent=_intent(used),
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=len(cands), relaxed=rep.relaxed,
            relaxation_fa=rep.text_fa() if rep.relaxed else "",
            items=[], evidence=_evidence(c, used, cands, k))

    items = diversify(scored, k=k)
    return SearchResponse(
        **_envelope(c, served=True).model_dump(),
        intent=_intent(used),
        considered=len(c.listings) or len(c.rows),
        appraisable=len(c.rows),
        candidates=len(cands), relaxed=rep.relaxed,
        relaxation_fa=rep.text_fa() if rep.relaxed else "",
        items=[_scored(s, i + 1) for i, s in enumerate(items)],
        evidence=[])


@app.post("/api/search/reweight", response_model=SearchResponse)
def search_reweight(q: str, weights: ReweightRequest,
                    k: int = 6) -> SearchResponse:
    """The same query with the user's own weights. «بهترین» is a function."""
    c = corpus_mod.active()
    spec = c.pipeline.parser.parse(q)
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
            intent=_intent(spec),
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=0, relaxed=False, relaxation_fa="",
            items=[], evidence=_evidence(c, spec, [], k))

    cands, used, rep = retrieve(c.rows, spec)
    try:
        items = diversify(c.pipeline.ranker.score(cands, used), k=k)
    except NotBenchmarked:
        return SearchResponse(
            **_envelope(c, served=False).model_dump(),
            intent=_intent(used),
            considered=len(c.listings) or len(c.rows),
            appraisable=len(c.rows),
            candidates=len(cands), relaxed=rep.relaxed,
            relaxation_fa=rep.text_fa() if rep.relaxed else "",
            items=[], evidence=_evidence(c, used, cands, k))

    return SearchResponse(
        **_envelope(c, served=True).model_dump(),
        intent=_intent(used),
        considered=len(c.listings) or len(c.rows),
        appraisable=len(c.rows),
        candidates=len(cands), relaxed=rep.relaxed,
        relaxation_fa=rep.text_fa() if rep.relaxed else "",
        items=[_scored(s, i + 1) for i, s in enumerate(items)], evidence=[])


@app.get("/api/listing/{listing_id}", response_model=ListingResponse)
def listing(listing_id: str) -> ListingResponse:
    c = corpus_mod.active()
    got = next((x for x in c.listings if x.listing_id == listing_id), None)
    if got is not None:
        return ListingResponse(**_envelope(c, served=False).model_dump(),
                               listing=_listing_evidence(got))

    row = next((r for r in c.rows if r.listing_id == listing_id), None)
    if row is None:
        raise HTTPException(404, f"no listing {listing_id!r} in this corpus")
    return ListingResponse(**_envelope(c, served=False).model_dump(),
                           listing=_row_evidence(row))


@app.post("/api/compare", response_model=CompareResponse)
def compare(req: CompareRequest) -> CompareResponse:
    """Side by side, with each scoring term kept apart.

    The cheapest car is not the best opportunity, and a comparison table that
    shows only price is the product this one exists to argue against.
    """
    c = corpus_mod.active()
    wanted = [r for r in c.rows if r.listing_id in set(req.ids)]
    if not wanted and not c.gated:
        # Nothing appraisable, and nothing may be ranked anyway: return the
        # listings as evidence rather than a 404 that hides the real reason.
        keep = [x for x in c.listings if x.listing_id in set(req.ids)]
        if keep:
            return CompareResponse(
                **_envelope(c, served=False).model_dump(),
                rows=[], evidence=[_listing_evidence(x) for x in keep])
    if not wanted:
        raise HTTPException(404, "none of those ids are in this corpus")

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
