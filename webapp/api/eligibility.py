"""What a screen may draw, declared once, in code.

`docs/FIELD_PROVENANCE.md` states the same table in prose, measured against
the corpus the site serves by default. This module states it as data, and
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
distinct value on the served corpus, so a filter over it offers one choice.
Coverage and variety are inputs to the judgement, not the judgement.
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
    # A facet since 2026-11-25, when the owner chose the filter panel: 45
    # makes on run17 pass the variety condition one make on run16 did not.
    "make": Eligibility("SOURCE_BACKED", card=True, detail=True, facet=True),
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
    # Diagnostic only: quality.DIAGNOSTIC_ONLY_FIELDS, and assert_not_features
    # refuses it as a predictor. Carried because a consumer reads it.
    "price_currency_raw": Eligibility("SOURCE_BACKED"),
    "mileage_km": Eligibility("SOURCE_BACKED", card=True, detail=True,
                              facet=True),
    "mileage_status": Eligibility("SOURCE_BACKED", card=True, detail=True),
    "mileage_line_canonical": Eligibility("SOURCE_BACKED", detail=True),
    "condition": Eligibility("SOURCE_BACKED", detail=True, facet=True),
    "condition_source": Eligibility("SOURCE_BACKED", detail=True),
    # `card` because compare shows a non-vehicle row labelled with its class
    # rather than dropping it: the class is drawn there, as a fact about
    # the row. Search never draws it — nothing but `vehicle` reaches it.
    "product_class": Eligibility("SOURCE_BACKED", card=True, detail=True,
                                 gate=True),
    "product_class_source": Eligibility("SOURCE_BACKED", detail=True),
    "dealer_badge": Eligibility("SOURCE_BACKED"),
    "document_issue": Eligibility("DERIVED"),
    # `dealer` on the two rows of run16 that carry a business badge, the
    # only value a badge can give: a car with none is never `private` (D26).
    # Out of PENDING_LIVE_VALIDATION now that a real run has produced it;
    # every flag stays no — no screen has been designed to draw it.
    "seller_type": Eligibility("SOURCE_BACKED"),
    # On all 73 rows of run16 (FIELD_PROVENANCE.md). The car page draws
    # it, with how it was known, and so do the lists an ungated corpus
    # serves — search's tables and compare's evidence rows (D81). A facet
    # since D82: «در تهران» is a constraint a buyer states, and the search
    # judges it against this field (webapp/api/constraints.py) — a listing
    # in the province meets it, one in another is left out, and one with
    # none is held apart and named, not dropped. On run14, 76 of 77; on
    # run13, 34 of 74.
    "province": Eligibility("SOURCE_BACKED", card=True, detail=True,
                            facet=True),
    # `stated` on 42 rows of run16 and `city` on 31. Drawn beside the
    # province wherever the province is drawn, so that a province read from
    # a city's name is never shown as stated. Not a key in run13, which
    # predates it.
    "province_source": Eligibility("SOURCE_BACKED", card=True, detail=True),
    # A facet: «اتومات» is a red line a buyer states, and the search checks it
    # against this field (webapp/api/constraints.py). On run16 one row is
    # automatic, a Quik; on run14 every row was manual, and the check left
    # every row out, which was the answer.
    "gearbox": Eligibility("SOURCE_BACKED", facet=True),
    "fuel": Eligibility("SOURCE_BACKED"),
    # The key the payload carries, `make|model|trim`, rendered through
    # `modelLabel`. `card` was `no` while nothing had judged the card
    # surface; the guard in `tests/test_corpus.py` now reads that surface
    # out of its renderers, and all three of them draw this field. The
    # alternative the table had in mind for a card heading, `derived_title`,
    # is not a key in any published corpus and is not on the payload, so it
    # could not be drawn instead.
    "model_key": Eligibility("DERIVED", card=True, detail=True),
    "derived_title": Eligibility("DERIVED", card=True, detail=True),
    "observed_at": Eligibility("DERIVED", card=True, detail=True),
    # The middle asking price of a listing's make, model and year in the
    # served run, and how many priced listings stand behind it, as a model's
    # page draws them by year (webapp/api/market.py): on a search's and a
    # filter's rows since 2026-11-25, beside each price, so that the order
    # «ارزان نسبت به بازار» says what it compared. Not an estimate (D50).
    "year_middle_toman": Eligibility("DERIVED", card=True),
    "year_middle_priced": Eligibility("DERIVED", card=True),
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


# What a renderer consumes is NOT declared here. It is read out of the
# renderer's own source by `tests/test_corpus.py` and checked against the
# table above. A hand-kept list stood in this place once, empty because no
# renderer was thought to exist; one did, and drew four fields this table
# forbids while the check over the list reported nothing wrong.
