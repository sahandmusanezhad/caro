"""What a screen may draw, declared once, in code.

`docs/FIELD_PROVENANCE.md` states the same table in prose, measured against
`data/corpora/run11.json`. This module states it as data, and
`tests/test_corpus.py` asserts the two agree. Neither is derived from the
other, which is the point: a value written in one place and read in the other
is one declaration, and one declaration cannot disagree with itself.

WHY NOT PARSE THE DOCUMENT AND BE DONE

Because then the test would compare the document with itself and pass on
anything. The duplication is the guard. The same reasoning is in
`tests/test_claims.py`, which verifies a glob against an independent os.walk
rather than trusting the pattern that produced it.

THE FOUR FLAGS, AND WHY `filter` IS TWO OF THEM

    card    the grid may draw it
    detail  the listing page may draw it
    gate    the query applies it before a reader sees a row; nobody chooses it
    facet   a reader chooses it

A gate and a facet are both filters to a query engine and are not the same act.
`product_class` is the only gate — only `vehicle` renders as a car (D52) — and
it would fail a facet's variety condition, having two values. Collapsing them
into one flag is how a gate becomes a checkbox.

NONE OF THESE FOLLOW FROM COVERAGE

A field can be filled on every row and still be `facet=False`: `make` has one
distinct value on run11, so a filter over it offers one choice. Coverage and
variety are inputs to the judgement, not the judgement.
"""

from __future__ import annotations

from dataclasses import dataclass

STATUSES = frozenset({
    "SOURCE_BACKED",            # the published corpus carries it
    "DERIVED",                  # computed by CARO from source-backed fields
    "EVIDENCE_ONLY",            # an operational channel, under its own scope
    "UNAVAILABLE",              # no published field carries it today
    "PENDING_LIVE_VALIDATION",  # the code path exists, no real run has run it
})


@dataclass(frozen=True)
class Eligibility:
    status: str
    card: bool = False
    detail: bool = False
    gate: bool = False
    facet: bool = False

    def __post_init__(self) -> None:
        if self.status not in STATUSES:
            raise ValueError(f"unknown status {self.status!r}")
        # A field whose extractor has never returned a value on a real page
        # cannot be drawn or chosen. Enforced here rather than left to the
        # test, because a rule that only a test knows is a rule a refactor
        # deletes. The test asserts it anyway, against the document.
        if self.status == "PENDING_LIVE_VALIDATION" and (
                self.card or self.gate or self.facet):
            raise ValueError(
                f"PENDING_LIVE_VALIDATION may not be card, gate or facet")


FIELDS: dict[str, Eligibility] = {
    "listing_id": Eligibility("SOURCE_BACKED"),
    "source_url": Eligibility("SOURCE_BACKED", card=True, detail=True),
    "make": Eligibility("SOURCE_BACKED", card=True, detail=True),
    "model": Eligibility("SOURCE_BACKED", card=True, detail=True, facet=True),
    "trim": Eligibility("SOURCE_BACKED", card=True, detail=True, facet=True),
    "year_jalali": Eligibility("SOURCE_BACKED", card=True, detail=True,
                               facet=True),
    "color": Eligibility("SOURCE_BACKED", detail=True, facet=True),
    "asking_price_toman": Eligibility("SOURCE_BACKED", card=True, detail=True,
                                      facet=True),
    "price_status": Eligibility("SOURCE_BACKED", card=True, detail=True),
    "price_kind": Eligibility("SOURCE_BACKED", card=True, detail=True),
    "price_kind_source": Eligibility("SOURCE_BACKED", detail=True),
    "mileage_km": Eligibility("SOURCE_BACKED", card=True, detail=True,
                              facet=True),
    "mileage_status": Eligibility("SOURCE_BACKED", card=True, detail=True),
    "mileage_line_canonical": Eligibility("SOURCE_BACKED", detail=True),
    "condition": Eligibility("SOURCE_BACKED", detail=True, facet=True),
    "condition_source": Eligibility("SOURCE_BACKED", detail=True),
    "product_class": Eligibility("SOURCE_BACKED", detail=True, gate=True),
    "product_class_source": Eligibility("SOURCE_BACKED", detail=True),
    "dealer_badge": Eligibility("SOURCE_BACKED"),
    "document_issue": Eligibility("DERIVED"),
    "seller_type": Eligibility("PENDING_LIVE_VALIDATION"),
    "province": Eligibility("PENDING_LIVE_VALIDATION"),
    "gearbox": Eligibility("PENDING_LIVE_VALIDATION"),
    "fuel": Eligibility("PENDING_LIVE_VALIDATION"),
    "derived_title": Eligibility("DERIVED", card=True, detail=True),
    "observed_at": Eligibility("DERIVED", card=True, detail=True),
    "listing_age": Eligibility("EVIDENCE_ONLY", card=True, detail=True),
    "image": Eligibility("UNAVAILABLE"),
}


def may(field: str, surface: str) -> bool:
    """Whether `field` may appear on `surface` — card, detail, gate or facet.

    An unknown field is not eligible for anything. A renderer asking about a
    field this table has never heard of is a renderer about to draw something
    nobody has judged, and the answer to that is no, not a KeyError somewhere
    downstream.
    """
    e = FIELDS.get(field)
    return bool(e and getattr(e, surface))


# Fields a renderer actually consumes, declared by the renderer and checked
# against the table above.
#
# It is EMPTY, and that is a fact rather than an oversight: no renderer exists
# yet. The check that reads it is written now so that it has teeth on the day
# one does, and the test prints the zero rather than passing quietly over it —
# a guard whose input set is empty proves nothing, and should say so.
RENDERER_CONSUMES: dict[str, frozenset[str]] = {
    "card": frozenset(),
    "detail": frozenset(),
}
