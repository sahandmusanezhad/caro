"""A model's page, as Torob gives a product one: every listing, cheapest first,
the range of asking prices, and those prices in every published run.

    GET /api/models                       one summary per make and model
    GET /api/model?make=Saipa&model=Pride that model: its listings, by year, by run

What a figure here is, and what it is not. Every number is an ASKING price a
listing stated, and every count says how many stand behind it. There is no
estimate and no statement about the market (D36): «the middle asking price of
the Prides in run16 was N» is something the corpus shows; «Prides got dearer»
is something it cannot. So a middle is given only where three priced listings
or more stand behind it, a run with fewer gives its count and no middle, and
the page draws no line through a point that is not there.

«Priced» is the listing gate's own reading of a price (caro.ingest.quality): a
status that is not unusable and a kind that is cash. A listing with no such
price is still a listing of the model and is shown, after the priced ones.
Only vehicles are models' listings: an assignment (حواله) carries a make, a
model and a price, and is not a car.
"""

from __future__ import annotations

from functools import lru_cache
from statistics import median

from fastapi import APIRouter, Query, Response

from caro.ingest.quality import UNUSABLE_PRICE
from webapp.api import corpus as corpus_mod
from webapp.api.schemas import (
    Fault, HistoryPoint, ModelResponse, ModelsResponse, ModelSummary, YearPoint,
)

router = APIRouter()

MIN_MIDDLE = 3
MAX_NAME = 60
_UNUSABLE = frozenset(s.value for s in UNUSABLE_PRICE)


def _key(make, model) -> tuple[str, str]:
    return ((make or "").strip(), (model or "").strip())


def priced(x) -> int | None:
    """The asking price if the gate would take it as one, else None."""
    p = getattr(x, "asking_price_toman", None)
    status = getattr(x, "price_status", None)
    kind = getattr(x, "price_kind", None)
    if p is None or p <= 0:
        return None
    if status in _UNUSABLE or (status is not None and getattr(status, "value", status) in _UNUSABLE):
        return None
    if kind not in (None, "cash"):
        return None
    return int(p)


def _vehicles(c) -> list:
    """The served corpus's listings that are cars; its appraisal rows where it
    has no listings (a synthetic corpus), which are cars by construction."""
    if c.listings:
        return [x for x in c.listings if getattr(x, "product_class", "vehicle") == "vehicle"]
    out = []
    for r in c.rows:
        parts = (r.model_key.split("|") + ["", "", ""])[:3] if "|" in r.model_key else ["", r.model_key, ""]
        out.append(type("RowListing", (), {
            "listing_id": r.listing_id, "url": "", "make": parts[0] or None,
            "model": parts[1] or None, "trim": parts[2] or None,
            "year_jalali": r.year_jalali, "mileage_km": r.mileage_km,
            "asking_price_toman": r.asking_price_toman, "gearbox": None, "fuel": None,
            "color": None, "body_condition": None, "city": None,
            "province_source": None, "seller_type": None, "product_class": "vehicle",
            "price_status": None, "price_kind": None, "mileage_status": None})())
    return out


def _middle(values: list[int]) -> int | None:
    return int(median(values)) if len(values) >= MIN_MIDDLE else None


def summarise(make, model, xs: list) -> ModelSummary:
    prices = sorted(p for p in (priced(x) for x in xs) if p is not None)
    years = [x.year_jalali for x in xs if getattr(x, "year_jalali", None)]
    return ModelSummary(
        make=make or None, model=model, listings=len(xs), priced=len(prices),
        price_min=prices[0] if prices else None, price_median=_middle(prices),
        price_max=prices[-1] if prices else None,
        year_min=min(years) if years else None, year_max=max(years) if years else None)


def _groups(xs: list) -> dict[tuple[str, str], list]:
    out: dict[tuple[str, str], list] = {}
    for x in xs:
        mk, md = _key(getattr(x, "make", None), getattr(x, "model", None))
        if md:
            out.setdefault((mk, md), []).append(x)
    return out


@lru_cache(maxsize=1)
def published_runs() -> tuple:
    """((run_id, collected_on, listings), ...) for every corpus in
    data/corpora, by collection date. Read once per process."""
    from caro.corpus_reader import CORPORA, load_corpus, rows_from_corpus   # noqa: PLC0415
    out = []
    for path in sorted(CORPORA.glob("*.json")):
        run_id = path.stem
        try:
            artifact = load_corpus(run_id)
            listings, _rows = rows_from_corpus(artifact)
            collected = str(artifact.get("collected_on") or "")
        except Exception:                       # noqa: BLE001 — a run that does not load is not a point
            continue
        out.append((run_id, collected, tuple(
            x for x in listings if getattr(x, "product_class", "vehicle") == "vehicle")))
    out.sort(key=lambda t: (t[1], t[0]))
    return tuple(out)


@router.get("/api/models", response_model=ModelsResponse)
def models() -> ModelsResponse:
    from webapp.api.main import _envelope                                    # noqa: PLC0415
    c = corpus_mod.active()
    if c.kind == "UNUSABLE":
        return ModelsResponse(**_envelope(c, served=False).model_dump(), models=[])
    groups = _groups(_vehicles(c))
    out = [summarise(mk, md, xs) for (mk, md), xs in groups.items()]
    out.sort(key=lambda s: (-s.listings, s.make or "", s.model))
    return ModelsResponse(**_envelope(c, served=False).model_dump(), models=out)


@router.get("/api/model", response_model=ModelResponse)
def model(make: str = Query("", max_length=MAX_NAME),
          model: str = Query(..., min_length=1, max_length=MAX_NAME),
          response: Response = None) -> ModelResponse:
    from webapp.api.main import _envelope, _listing_evidence                 # noqa: PLC0415
    c = corpus_mod.active()
    if c.kind == "UNUSABLE":
        return ModelResponse(**_envelope(c, served=False).model_dump())
    want = _key(make, model)
    xs = [x for x in _vehicles(c)
          if _key(getattr(x, "make", None), getattr(x, "model", None)) == want
          or (not want[0] and _key(None, getattr(x, "model", None))[1] == want[1])]
    if not xs:
        if response is not None:
            response.status_code = 404
        return ModelResponse(**_envelope(c, served=False, fault=Fault(
            code="MODEL_NOT_FOUND",
            message=f"no listing of {make!r} {model!r} in the corpus being served ({c.source})",
            fa="این مدل در پیکره‌ای که همین حالا سرو می‌شود آگهی‌ای ندارد.",
            still_available=["models"])).model_dump())

    # the priced cheapest first, then the rest as they were
    xs_sorted = sorted(xs, key=lambda x: (priced(x) is None, priced(x) or 0))
    by_year: dict[int, list[int]] = {}
    for x in xs:
        p = priced(x)
        if p is not None and getattr(x, "year_jalali", None):
            by_year.setdefault(int(x.year_jalali), []).append(p)
    years = [YearPoint(year_jalali=y, priced=len(v), price_median=_middle(v))
             for y, v in sorted(by_year.items())]
    history = []
    for run_id, collected, listings in published_runs():
        same = [x for x in listings
                if _key(getattr(x, "make", None), getattr(x, "model", None)) == want
                or (not want[0] and _key(None, getattr(x, "model", None))[1] == want[1])]
        prices = [p for p in (priced(x) for x in same) if p is not None]
        history.append(HistoryPoint(run_id=run_id, collected_on=collected,
                                    priced=len(prices), price_median=_middle(prices)))
    return ModelResponse(
        **_envelope(c, served=False).model_dump(),
        summary=summarise(want[0] or getattr(xs[0], "make", None), want[1], xs),
        offers=[_listing_evidence(x) for x in xs_sorted],
        by_year=years, history=history)
