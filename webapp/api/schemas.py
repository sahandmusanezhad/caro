"""The API's contract, as types rather than as dictionaries.

Until now every response was assembled by hand from `dict` literals, and the
client's `lib/api.ts` was a second hand-written description of the same shapes.
Two hand-written descriptions of one contract drift, and nothing fails when
they do — TypeScript validates the client against its own belief about the
server, which is exactly the belief that went stale.

## Three concepts, three places

The single most useful thing here is not the typing. It is that one dictionary
carrying `kind`, `gated`, `identity`, `fault` and `appraisable` side by side
has been split into three fields that answer three different questions:

    corpus   WHAT the data is        — label, source, counts, identity
    status   WHAT MAY BE DONE with it — kind, gated, served
    fault    WHY we are in that state — code and message, or null

They were entangled because they arrived one at a time. `fault` in particular
was living inside the refusal object on one endpoint and nowhere on the
others, so a client had to know which endpoint it was talking to before it
could ask "did something break?".

`fault.code` is a small closed set — two members today — and the specific
detail lives in `message`. Turning every distinct failure string into an enum
member produces a large enum nobody can switch on and a client that breaks
whenever a message is reworded.

## What the models refuse to express (D50)

A refusal returns `SearchResponse` with `items: []` and `evidence: [...]`,
where `EvidenceItem` HAS NO estimate, opportunity or damage field at all. A
refusal that carried an estimate is therefore not a badly-formed response —
it is not a response. That is the difference between a rule and a check: this
one cannot be forgotten, because there is no field to fill.

`CorpusIdentity` is one nullable object rather than four nullable scalars, so
"no evidence identity" is expressible exactly once and cannot be half
answered.
"""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# The envelope every response carries
# ---------------------------------------------------------------------------

CorpusKind = Literal["SYNTHETIC", "REAL", "UNUSABLE"]

# Small and closed, deliberately. A code is for a client to branch on; a
# message is for a person to read. Growing this list one string at a time is
# how an enum becomes a second copy of the message, so a member has to earn its
# place by leading somewhere different. Each of these does:
#
#   about the SOURCE — nothing can be served at all
#     CORPUS_INVALID          an artifact exists and will not load → fix the
#                             file
#     RUN_NOT_FOUND           CARO_RUN names a run with no artifact → fix the
#                             configuration, or collect that run
#
#   about the CLAIM — a corpus was read, and a number may not be published
#     ESTIMATOR_NOT_GATED     nothing has cleared the gate here → not a defect
#
#   about the RESOURCE — a corpus was read and does not contain this
#     LISTING_NOT_FOUND       that id is not in the corpus being served
#     COMPARE_IDS_NOT_FOUND   not one of the requested ids is
#
# The last two are the ones that ride on a 404, and they exist because a 404
# with a free-text `detail` forces the client to read English prose to find out
# what happened. The distinction from the first group is the whole point of the
# split: «this listing is not here» is a statement about a corpus we READ, and
# saying it when no corpus was read at all is a claim we have no standing to
# make (D54). A client that branched on the status code alone could not tell
# the two apart — both were 404 — which is exactly what went wrong.
#
# COMPARE_IDS_NOT_FOUND is separate from LISTING_NOT_FOUND rather than reused
# because it answers about a SET: compare returns 200 with whatever it found
# when some ids match, so this code means "not one of them", which is a
# different fact from "this one is missing" and leads the client somewhere
# else — back to a selection, not back to a listing.
FaultCode = Literal[
    "CORPUS_INVALID",
    "RUN_NOT_FOUND",
    "ESTIMATOR_NOT_GATED",
    "LISTING_NOT_FOUND",
    "COMPARE_IDS_NOT_FOUND",
    "MODEL_NOT_FOUND",
]


class CorpusIdentity(BaseModel):
    """Which exact bytes a served number rests on."""

    run_id: str
    path: str
    sha256: str = Field(min_length=64, max_length=64)
    bytes: int


class CorpusMeta(BaseModel):
    """WHAT the data is. Nothing here says whether it may be served."""

    label_fa: str
    source: str
    note_fa: str
    # Everything the corpus holds, and the subset that cleared eligibility.
    # On a published artifact these are N and 0, and the gap is the point.
    rows: int
    appraisable: int
    # Null when there is no artifact to hash — a generated corpus, or one that
    # would not load. Never a placeholder: see D50.
    identity: CorpusIdentity | None = None


class ServingStatus(BaseModel):
    """WHAT MAY BE DONE with it. Separate from what it is, on purpose."""

    kind: CorpusKind
    gated: bool          # has an estimator cleared AcceptanceGate here?
    served: bool         # did THIS request produce a ranking?


class Fault(BaseModel):
    """WHY we are in this state. Null when nothing is wrong."""

    code: FaultCode
    message: str         # the specific detail, for a person
    fa: str              # the same thing, for the person actually reading it
    still_available: list[str] = Field(default_factory=list)


class Envelope(BaseModel):
    corpus: CorpusMeta
    status: ServingStatus
    fault: Fault | None = None


# ---------------------------------------------------------------------------
# Payload pieces
# ---------------------------------------------------------------------------

# What an odometer reading is worth, as `caro.ingest.quality.Validity` grades
# it (D21, D22): `plausible`, a reading; `unknown`, no number; `suspicious`, a
# number the seller should not be believed on — the 999999 placeholder, or
# under 1,500 km a year on a car three or more years old; `impossible`, one
# no passenger car can have. The contract suite holds this to Validity.
MileageStatus = Literal["plausible", "suspicious", "impossible", "unknown"]

# How a province was known (FIELD_PROVENANCE.md): `stated` where the page
# names it, `city` where a city that shares its province's name gave it,
# `none` where there is no province. `corpus_reader` derives the value for a
# row published before the field existed — every province then was stated —
# so a published corpus yields these three and nothing else; the contract
# suite checks that against every corpus in data/corpora/.
ProvinceSource = Literal["stated", "city", "none"]


class EvidenceItem(BaseModel):
    """A listing as parsed. D50: there is no field here for an estimate.

    This is what a refusal is allowed to return, and the absence of those
    fields is the enforcement rather than a convention — a refusal carrying an
    estimate cannot be constructed.
    """

    id: str
    url: str = ""
    model_key: str
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    year_jalali: int | None = None
    mileage_km: int | None = None
    asking_price_toman: int | None = None
    gearbox: str | None = None
    fuel: str | None = None
    color: str | None = None
    condition: str | None = None
    province: str | None = None
    # How it was known, beside it, so that no screen draws a province read
    # from a city's name as one the listing stated. Null on an appraisal
    # Row, which carries no province.
    province_source: ProvinceSource | None = None
    seller_type: str | None = None
    # The gate, and the only one (D52): a client renders a listing as a car
    # only where this says `vehicle`. It is here because a gate the client is
    # not sent is a gate the client cannot apply — run11 holds an assignment
    # with a make, a model, a trim, a year and a price, and without this
    # field every cell the detail page draws says "car".
    product_class: str | None = None
    # The two fields FIELD_PROVENANCE.md names in its rule for a price on a
    # card — `price_status` grades the extraction, `price_kind` says what the
    # number means (D52) — and a card cannot apply a rule it is not sent.
    # Null on an appraisal Row, which carries neither: see `_row_evidence`.
    price_status: str | None = None
    price_kind: str | None = None
    # The odometer's status, beside the number it grades. FIELD_PROVENANCE.md:
    # it "travels with the number or neither renders", and a card cannot draw
    # a number with its status when it is sent the number alone. Null on an
    # appraisal Row, which carries none: a real one exists only after
    # eligibility refused every odometer but a plausible one.
    mileage_status: MileageStatus | None = None


# The constraints a listing can fail to be checked against, by the names
# `webapp/api/constraints.py` judges them under: the three the buyer states as
# numbers, the province, then the red lines under their `DEAL_BREAKER_CUES`
# names. A Literal for the same reason `FaultCode` is one: the client draws a
# sentence for each member, and a member it has no sentence for would reach the
# screen as a bare token.
ConstraintKey = Literal["budget", "year", "mileage", "province",
                        "accident", "unclear_documents", "manual", "repaint"]


class UncheckedItem(EvidenceItem):
    """A listing that breaks none of the buyer's constraints and could not be
    checked against at least one, because it carries no value for it.

    It is not a match, and it does not travel in `evidence`. `unchecked` names
    what could not be checked and is never empty: a listing with nothing
    unchecked is a match.
    """

    unchecked: list[ConstraintKey]


class ScoredItem(EvidenceItem):
    """A listing with a decision attached. Only reachable when served.

    Every term is separate so a card can say WHY this car ranked here, and the
    subtraction can be checked on screen:

        opportunity = estimate − asking − expected_damage
    """

    year_jalali: int
    mileage_km: int
    asking_price_toman: int
    rank: int
    role_fa: str
    score: float
    estimate_toman: int
    opportunity_toman: int
    expected_damage_toman: int
    terms: dict[str, float] = Field(default_factory=dict)
    features: dict[str, float] = Field(default_factory=dict)


class Weights(BaseModel):
    value: float
    risk: float
    running_cost: float
    liquidity: float
    mileage: float
    recency: float


class Intent(BaseModel):
    """What was understood, what was assumed, what was not understood.

    `assumptions` and `unparsed` are not diagnostics that could be dropped in
    production. An assumption the buyer cannot see is one they cannot correct.
    """

    query: str
    budget_max_toman: int | None = None
    budget_min_toman: int | None = None
    budget_hard: bool = True
    models: list[str] = Field(default_factory=list)
    year_min: int | None = None
    max_mileage_km: int | None = None
    # The provinces named as where the car should be; any one meets it. Empty
    # when none was stated.
    provinces: list[str] = Field(default_factory=list)
    use_case: str | None = None
    risk_profile: str | None = None
    deal_breakers: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    unparsed: list[str] = Field(default_factory=list)
    weights: Weights


# ---------------------------------------------------------------------------
# Responses
# ---------------------------------------------------------------------------

class CorpusResponse(Envelope):
    """`/api/corpus` — the envelope and nothing else. That is the whole point."""


class SearchResponse(Envelope):
    intent: Intent
    considered: int
    appraisable: int
    candidates: int
    relaxed: bool
    relaxation_fa: str = ""
    items: list[ScoredItem] = Field(default_factory=list)
    # What is still true when nothing may be ranked. Carries no estimate by
    # construction — see `EvidenceItem`.
    #
    # Only listings that MEET every constraint the buyer stated. One that
    # carries no value for some constraint and breaks none is not a match; it
    # travels in `evidence_unchecked`, saying which. Each list is the first k
    # of its kind, and each total is how many there are in all, so a page can
    # say «8 of 51» instead of letting 8 stand for every match.
    evidence: list[EvidenceItem] = Field(default_factory=list)
    evidence_total: int = 0
    evidence_unchecked: list[UncheckedItem] = Field(default_factory=list)
    evidence_unchecked_total: int = 0


class ListingResponse(Envelope):
    # Null exactly when the corpus is UNUSABLE. Not a convenience: with no
    # corpus loaded, "is this id in the corpus?" has no answer at all, and the
    # 404 that used to be returned instead answered it — «no listing 'b0' in
    # this corpus» — which is a claim about the LISTING made from a fact about
    # the SOURCE (D54). The listing may well exist; there is nowhere to look.
    #
    # No default, so every construction site has to say which it is. A
    # `= None` here would let a healthy corpus return a listing-less 200 by
    # omission, which is the failure this field is meant to make visible.
    listing: EvidenceItem | None


class CompareResponse(Envelope):
    rows: list[ScoredItem] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """No envelope. Health is about the process, not about the evidence."""

    ok: bool


# ---------------------------------------------------------------------------
# A model, as Torob shows a product: every listing, the range, the runs
# ---------------------------------------------------------------------------
#
# Every figure below is an ASKING price a listing stated, counted (D36): there
# is no estimate here and no statement about the market. «Priced» is a price
# whose status is not unusable and whose kind is cash; a middle is given only
# where three priced listings or more stand behind it.

class ModelSummary(BaseModel):
    make: str | None = None
    model: str
    listings: int
    priced: int
    price_min: int | None = None
    price_median: int | None = None
    price_max: int | None = None
    year_min: int | None = None
    year_max: int | None = None


class YearPoint(BaseModel):
    year_jalali: int
    priced: int
    price_median: int | None = None


class HistoryPoint(BaseModel):
    run_id: str
    collected_on: str
    source: str
    priced: int
    price_median: int | None = None


class ModelsResponse(Envelope):
    models: list[ModelSummary] = Field(default_factory=list)


class ModelResponse(Envelope):
    summary: ModelSummary | None = None
    offers: list[EvidenceItem] = Field(default_factory=list)
    by_year: list[YearPoint] = Field(default_factory=list)
    history: list[HistoryPoint] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------

class ReweightRequest(BaseModel):
    value: float | None = None
    risk: float | None = None
    running_cost: float | None = None
    liquidity: float | None = None
    mileage: float | None = None
    recency: float | None = None


class CompareRequest(BaseModel):
    # At most twelve ids of at most 120 characters, and a question of at most
    # 500: the bounds of what a compare is (webapp/api/main.py, MAX_Q).
    ids: list[Annotated[str, Field(max_length=120)]] = Field(max_length=12)
    q: str = Field(default="خودرو", max_length=500)
