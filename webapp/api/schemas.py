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

from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# The envelope every response carries
# ---------------------------------------------------------------------------

CorpusKind = Literal["SYNTHETIC", "REAL", "UNUSABLE"]

# Two members, deliberately. A code is for a client to branch on; a message is
# for a person to read. Growing this list one string at a time is how an enum
# becomes a second copy of the message.
FaultCode = Literal["CORPUS_INVALID", "ESTIMATOR_NOT_GATED"]


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
    seller_type: str | None = None


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
    evidence: list[EvidenceItem] = Field(default_factory=list)


class ListingResponse(Envelope):
    listing: EvidenceItem


class CompareResponse(Envelope):
    rows: list[ScoredItem] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class HealthResponse(BaseModel):
    """No envelope. Health is about the process, not about the evidence."""

    ok: bool


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
    ids: list[str]
    q: str = "خودرو"
