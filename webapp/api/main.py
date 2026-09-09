"""CARO web API.

    uvicorn webapp.api.main:app --reload

The backend is thin on purpose. CARO is a Python package, so this imports it
rather than talking to it over a socket: no service boundary, no serialisation
round-trip, no second place for a number to change on the way past. What lives
here is HTTP shape and nothing else — every decision, every refusal and every
number comes from `caro.ranking` and is passed through unaltered.

Two rules the endpoints enforce, because a website is where they are easiest
to lose:

**Every response carries its corpus label.** A listing card looks the same
whether it came from a real Bama page or a generated fixture, so the label
travels with the payload rather than being painted on one screen. See
webapp/api/corpus.py.

**A refusal is a 200, not a 500.** When the estimator has not cleared the
acceptance gate, `Ranker.score` raises `NotBenchmarked`, and that is a product
state (D11) rather than an error: the response says what it cannot serve, what
it still has, and why. An HTTP 500 would tell the client something broke, and
nothing has.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi import FastAPI, HTTPException, Query                  # noqa: E402
from fastapi.middleware.cors import CORSMiddleware                 # noqa: E402
from pydantic import BaseModel                                     # noqa: E402

from caro.appraisal import NotBenchmarked                          # noqa: E402
from caro.ranking import Weights, diversify, retrieve              # noqa: E402
from webapp.api import corpus as corpus_mod                      # noqa: E402
from webapp.api.contact import router as contact_router          # noqa: E402

app = FastAPI(title="CARO", version="0.1.0",
              description="سامانه‌ی تصمیم‌یار خرید خودروی کارکرده")

# The contact inbox is a separate module because it touches disk and CARO's
# decision endpoints do not. Keeping them apart means a change to how messages
# are stored can never reach the ranking path.
app.include_router(contact_router)

app.add_middleware(
    CORSMiddleware, allow_origins=["http://localhost:3000"],
    allow_credentials=True, allow_methods=["*"], allow_headers=["*"])


# ---------------------------------------------------------------------------
# serialisation — flat, and nothing invented on the way out
# ---------------------------------------------------------------------------

def _row(r) -> dict:
    return {
        "id": r.listing_id,
        "model_key": r.model_key,
        "make": (r.model_key.split("|")[0] if "|" in r.model_key else None),
        "model": (r.model_key.split("|")[1] if "|" in r.model_key
                  else r.model_key),
        "trim": (r.model_key.split("|")[2] if r.model_key.count("|") > 1
                 else None),
        "year_jalali": r.year_jalali,
        "mileage_km": int(r.mileage_km),
        "asking_price_toman": int(r.asking_price_toman),
        "features": {k: v for k, v in (r.features or {}).items()
                     if not k.startswith("_")},
    }


def _scored(s, rank: int) -> dict:
    return {
        **_row(s.row),
        "rank": rank,
        "role_fa": s.breakdown.get("_role", ""),
        "score": s.score,
        "estimate_toman": int(s.conservative_estimate_toman),
        "opportunity_toman": int(s.adjusted_opportunity_toman),
        "expected_damage_toman": int(s.expected_damage_toman),
        # Every term separately, so the card can say WHY this car ranked here
        # and the client can recompute a reweighting without a round trip.
        "terms": {k: v for k, v in s.breakdown.items()
                  if not k.startswith("_")},
    }


def _intent(spec) -> dict:
    w = spec.weights.normalized()
    return {
        "query": spec.raw_query,
        "budget_max_toman": spec.budget_max_toman,
        "budget_min_toman": spec.budget_min_toman,
        "budget_hard": spec.budget_hard,
        "models": list(spec.model_hints),
        "year_min": spec.year_min,
        "max_mileage_km": spec.max_mileage_km,
        "use_case": spec.use_case,
        "risk_profile": spec.risk_profile,
        "deal_breakers": list(spec.deal_breakers),
        # Surfaced, never silent. An assumption the user cannot see is one
        # they cannot correct, and `unparsed` is kept rather than dropped.
        "assumptions": list(spec.assumptions),
        "unparsed": [u.strip() for u in spec.unparsed if u.strip()],
        "weights": {k: getattr(w, k) for k in
                    ("value", "risk", "running_cost", "liquidity",
                     "mileage", "recency")},
    }


def _envelope(c) -> dict:
    return {"corpus": c.as_dict()}


# ---------------------------------------------------------------------------
# endpoints
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/corpus")
def which_corpus() -> dict:
    return _envelope(corpus_mod.active())


class Reweight(BaseModel):
    value: float | None = None
    risk: float | None = None
    running_cost: float | None = None
    liquidity: float | None = None
    mileage: float | None = None
    recency: float | None = None


@app.get("/api/search")
def search(q: str = Query(..., min_length=2, description="پرسش فارسی"),
           k: int = Query(6, ge=1, le=24)) -> dict:
    """A Persian sentence in, a defensible ranked decision out — or a refusal.

    The refusal path is the interesting one and it returns 200: the estimator
    may not have cleared the gate on this corpus, in which case there is no
    shortlist to serve and the response says so, keeping the parsed intent and
    the candidate count that are still true.
    """
    c = corpus_mod.active()
    spec = c.pipeline.parser.parse(q)
    cands, used, rep = retrieve(c.rows, spec)

    base = {
        **_envelope(c),
        "intent": _intent(used),
        "considered": len(c.rows),
        "candidates": len(cands),
        "relaxed": rep.relaxed,
        "relaxation_fa": rep.text_fa() if rep.relaxed else "",
    }

    try:
        scored = c.pipeline.ranker.score(cands, used)
    except NotBenchmarked as e:
        return {**base, "served": False, "items": [],
                # `still_available` names three things, so all three are in
                # the payload. A refusal that advertises evidence it does not
                # send is a refusal that has to be taken on trust — which is
                # the posture this whole endpoint exists to avoid. `evidence`
                # carries no estimate, no score and no ordering: these are the
                # matching listings as parsed, and nothing more.
                "evidence": [_row(r) for r in cands[:k]],
                "refusal": {
                    "reason": "estimator_not_gated",
                    "detail": str(e),
                    "fa": "برای این پیکره هیچ برآوردگری از دروازه‌ی پذیرش "
                          "عبور نکرده است، پس رتبه‌بندی سرو نمی‌شود. آنچه "
                          "داریم شواهد است: آگهی‌های منطبق، ویژگی‌های "
                          "استخراج‌شده و منبع هرکدام.",
                    "still_available": ["intent", "candidates", "evidence"],
                }}

    items = diversify(scored, k=k)
    return {**base, "served": True, "refusal": None, "evidence": [],
            "items": [_scored(s, i + 1) for i, s in enumerate(items)]}


@app.post("/api/search/reweight")
def search_reweight(q: str, weights: Reweight, k: int = 6) -> dict:
    """The same query with the user's own weights. «بهترین» is a function."""
    c = corpus_mod.active()
    spec = c.pipeline.parser.parse(q)
    given = {k_: v for k_, v in weights.model_dump().items() if v is not None}
    if given:
        base = spec.weights
        spec = spec.with_weights(Weights(**{
            f: given.get(f, getattr(base, f)) for f in
            ("value", "risk", "running_cost", "liquidity", "mileage",
             "recency")}))

    cands, used, rep = retrieve(c.rows, spec)
    try:
        items = diversify(c.pipeline.ranker.score(cands, used), k=k)
    except NotBenchmarked as e:
        return {**_envelope(c), "served": False, "items": [],
                "refusal": {"reason": "estimator_not_gated", "detail": str(e)}}
    return {**_envelope(c), "served": True, "intent": _intent(used),
            "candidates": len(cands),
            "items": [_scored(s, i + 1) for i, s in enumerate(items)]}


@app.get("/api/listing/{listing_id}")
def listing(listing_id: str) -> dict:
    c = corpus_mod.active()
    row = next((r for r in c.rows if r.listing_id == listing_id), None)
    if row is None:
        raise HTTPException(404, f"no listing {listing_id!r} in this corpus")
    return {**_envelope(c), "listing": _row(row)}


class CompareRequest(BaseModel):
    ids: list[str]
    q: str = "خودرو"


@app.post("/api/compare")
def compare(req: CompareRequest) -> dict:
    """Side by side, with each scoring term kept apart.

    The cheapest car is not the best opportunity, and a comparison table that
    shows only price is the product this one exists to argue against.
    """
    c = corpus_mod.active()
    wanted = [r for r in c.rows if r.listing_id in set(req.ids)]
    if not wanted:
        raise HTTPException(404, "none of those ids are in this corpus")

    spec = c.pipeline.parser.parse(req.q)
    try:
        scored = c.pipeline.ranker.score(wanted, spec)
    except NotBenchmarked as e:
        return {**_envelope(c), "served": False,
                "rows": [_row(r) for r in wanted],
                "refusal": {"reason": "estimator_not_gated", "detail": str(e)}}
    order = {s.row.listing_id: s for s in scored}
    return {**_envelope(c), "served": True, "refusal": None,
            "rows": [_scored(order[i], n + 1)
                     for n, i in enumerate(req.ids) if i in order]}
