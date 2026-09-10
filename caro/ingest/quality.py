"""
Semantic validation: is this value *meaningful*, not merely *in range*.

The distinction this module exists for. A bound like `0 <= mileage <= 1_000_000`
is syntactic — it asks whether the number could be typed. Semantic validation
asks whether it could be true of this car. The 2026-09-07 Bama corpus contained
three odometer readings that pass every syntactic check and are all false:

    999,990 km on a 1384 Pride     the 999999 placeholder
          1 km on a 1385 Pride     "ask me", typed as a digit
      6,000 km on a 1385 Pride     a 21-year-old car at ~300 km/year

Left unmarked they enter the appraiser as genuine low-mileage cars and drag
the mileage coefficient toward zero. That failure is invisible to any error
metric computed on the same corpus, because the corrupted rows sit in both
halves of the split — the model is consistently wrong and consistently
confident.

Two principles run through everything here.

**Status, not deletion.** A suspicious value is kept, with a label. Dropping
it would destroy the evidence that the source publishes placeholders at all,
which is a fact about the source worth knowing. The appraiser filters on the
label; the inventory reports the rate.

**Suspicious is not impossible.** 1 km on a 21-year-old car is implausible,
not physically impossible — someone may have replaced the odometer.
-5,000 km is impossible. Collapsing the two would either discard real edge
cases or admit corrupt ones, so they stay separate and the caller decides.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from caro.ingest.persian import normalize

# The Jalali year the plausibility rules are anchored to. Bump it, or pass
# `now` explicitly, rather than letting an old constant silently make every
# recent car look implausible.
CURRENT_JALALI_YEAR = 1405

# Below this sustained annual rate a used car is a placeholder or a typo.
# Genuinely unused cars say «صفر» and are almost always current-model-year,
# which is why the rule only applies from three years old.
MIN_PLAUSIBLE_KM_PER_YEAR = 1_500
MIN_AGE_FOR_RATE_CHECK = 3

# The 999999 family. Sellers reach for a row of nines to mean "very high" or
# "not telling you", and it is the single most common odometer placeholder on
# Iranian marketplaces.
PLACEHOLDER_KM_FLOOR = 900_000

# Beyond any passenger car's service life.
MAX_POSSIBLE_KM = 1_500_000

# Under this, a "price" is a listing fee, a deposit, or a typo — not a car.
MIN_PLAUSIBLE_PRICE_TOMAN = 10_000_000


class Validity(str, Enum):
    """Three-state, plus the absence that is not a failure.

    UNKNOWN is deliberately distinct from SUSPICIOUS: a missing odometer is
    the seller declining to say, which is information about the listing;
    a suspicious one is the seller saying something untrue, which is
    information about the seller. They should never be counted together.
    """
    PLAUSIBLE = "plausible"
    SUSPICIOUS = "suspicious"
    IMPOSSIBLE = "impossible"
    UNKNOWN = "unknown"


class PriceStatus(str, Enum):
    """How much the asking price is worth believing.

    DISPLAY_CONFIRMED is the strong case and the one to prefer: the site's
    structured data and the number rendered to buyers agree, so the currency
    label has been checked rather than trusted. See D20.
    """
    DISPLAY_CONFIRMED = "display_confirmed"
    STRUCTURED_ONLY = "structured_only"
    DISPLAYED_ONLY = "displayed_only"
    LABEL_CORRECTED = "label_corrected"
    AMBIGUOUS = "ambiguous"
    NEGOTIABLE = "negotiable"
    ABSENT = "absent"


# Prices we will not price against. AMBIGUOUS covers the instalment listing
# whose only visible numbers are a deposit and a monthly payment: neither is a
# cash asking price, and picking one would fabricate a valuation.
UNUSABLE_PRICE = (PriceStatus.AMBIGUOUS, PriceStatus.NEGOTIABLE,
                  PriceStatus.ABSENT)


@dataclass(frozen=True)
class Judgement:
    status: Validity
    reason: str | None = None

    @property
    def usable(self) -> bool:
        return self.status is Validity.PLAUSIBLE


def classify_mileage(km: int | None, year_jalali: int | None = None,
                     now: int = CURRENT_JALALI_YEAR) -> Judgement:
    """Odometer plausibility, given the car's age.

    Age is what makes this possible at all: 6,000 km is unremarkable on a
    current-model-year car and absurd on a twenty-year-old one, and no
    check on the number alone can tell those apart.
    """
    if km is None:
        return Judgement(Validity.UNKNOWN, "not stated")
    if km < 0 or km > MAX_POSSIBLE_KM:
        return Judgement(Validity.IMPOSSIBLE, f"{km:,} km is outside any "
                         "passenger car's service life")
    if km >= PLACEHOLDER_KM_FLOOR:
        return Judgement(Validity.SUSPICIOUS,
                         f"{km:,} km is the 999999-style placeholder")
    if year_jalali:
        age = max(0, now - year_jalali)
        if age >= MIN_AGE_FOR_RATE_CHECK and km < MIN_PLAUSIBLE_KM_PER_YEAR * age:
            return Judgement(
                Validity.SUSPICIOUS,
                f"{km:,} km over {age} years is "
                f"{km // max(1, age):,} km/year")
    return Judgement(Validity.PLAUSIBLE)


def classify_price_value(toman: int | None) -> Judgement:
    """Magnitude sanity only. Whether the *unit* is right is a separate
    question, answered by the source's cross-check (see D20) — this cannot
    detect a uniformly tenfold-wrong corpus, and is not meant to."""
    if toman is None:
        return Judgement(Validity.UNKNOWN, "no price")
    if toman <= 0:
        return Judgement(Validity.IMPOSSIBLE, "non-positive price")
    if toman < MIN_PLAUSIBLE_PRICE_TOMAN:
        return Judgement(Validity.SUSPICIOUS,
                         f"{toman:,} toman is below any car's floor")
    return Judgement(Validity.PLAUSIBLE)


# ---------------------------------------------------------------------------
# Fields that describe the SAMPLE, and must never describe the CAR
# ---------------------------------------------------------------------------
#
# `seller_type` exists so `coverage` can ask whether a comparable set is one
# forecourt's inventory pretending to be a market. That is a question about
# our sampling. It is not a fact about the vehicle.
#
# The failure it guards against is subtle and would look like a result. Feed
# `seller_type` to the estimator and it will find that dealer listings are
# priced differently — they are — and encode that as *fair value depends on
# who is selling*. What the corpus actually establishes is only that this
# sample may be dominated by a particular seller population. The model would
# then quote a lower fair value for a private seller's identical car, and
# every metric would improve, because the correlation is real. It is the
# inference that is wrong.
#
# Worse, the signal is a coarse proxy built from a trade badge (D26), so the
# "effect" it would learn is partly just badge-availability. Diagnostics that
# quietly become features is a standard way a pipeline starts modelling
# itself, so the boundary is enforced rather than documented.
DIAGNOSTIC_ONLY_FIELDS = frozenset({
    "seller_type",
    "price_status", "price_provenance", "price_raw", "price_currency_raw",
    "mileage_status", "mileage_note",
})


class DiagnosticLeakedIntoModel(RuntimeError):
    """A sampling diagnostic reached the design matrix."""


def assert_not_features(names) -> None:
    """Raise if a diagnostic is being used as a predictor.

    Called by the estimator on its own column list. A type error at fit time
    is a boundary; a paragraph in a design doc is a hope.
    """
    leaked = sorted(set(map(str, names)) & DIAGNOSTIC_ONLY_FIELDS)
    if leaked:
        raise DiagnosticLeakedIntoModel(
            f"{', '.join(leaked)} describe how this SAMPLE was collected, not "
            "the car. Using them as predictors would encode 'fair value "
            "depends on who is selling' from a correlation that is real and "
            "an inference that is not. They belong to caro.ingest.coverage.")


# The floor for "this stratum has too few observations to speak for itself".
# Lives here because two modules need it — stratification's conditional-scope
# check (D30) and the hierarchical estimator's extrapolation flag (D32) — and
# two constants meaning the same thing would drift, surfacing as a confident
# estimate the contract says is out of scope.
MIN_PER_TRIM_FLOOR = 5


# What W1 needs before a listing can inform an estimate. Deliberately narrow:
# these are the terms that appear in the appraisal itself, so a row missing
# any of them cannot contribute a comparable, only noise.
# ---------------------------------------------------------------------------
# What the record IS, as opposed to whether its numbers came out right
# ---------------------------------------------------------------------------
#
# `PriceStatus` answers "can I trust this number was extracted correctly?".
# It cannot answer "is this number an asking price at all?", and a corpus
# needs both. Run 9 made the gap concrete: a listing whose price was
# display-confirmed, cross-checked and perfectly extracted, and which was the
# corpus maximum at 1.83B toman — and which is the TOTAL COST OF A FINANCING
# PLAN, not what anyone is asking for a Pride. Every quality check passed
# because every quality check was about the extraction.
#
# The same run carried two «حواله» listings at 30M and 80M toman. Those are
# assignments — a claim on a car not yet built — and they are not used cars
# at any price. `classify_price_value` let them through because its floor is
# 10M and flat, while `classify_mileage` right above it conditions on age
# precisely because a number alone cannot carry that judgement. Price had the
# same problem inverted and no such conditioning.
#
# Neither field is a threshold and neither is tuned. Both are read off what
# the source publishes, and both keep the evidence that produced them.

# Observed on bama 2026-09-10 in the canonical `name` of two listings:
#
#     «حواله کوییک،  دنده ای S»        price 30M toman, model year 1405
#
# The control is the same field on an ordinary listing: «پراید،  151». So the
# word is a real marker in a site-authored string, not a coincidence in
# seller prose — which is why this reads `name` and never `description`.
#
# ONE cue, because one is what has been observed. This list is not
# market-complete and must not be widened by imagination; a class this gate
# cannot recognise stays `unknown`, which fails closed.
ASSIGNMENT_CUES = ("حواله",)


def classify_product(name: str | None, *, from_canonical: bool
                     ) -> tuple[str, str]:
    """(product_class, product_class_source) from a product NAME.

    `from_canonical` is the difference between reading a string the SOURCE
    authored — bama's schema.org `name` — and a headline the seller wrote.
    On a canonical name, the absence of an assignment cue is evidence: bama
    names assignments «حواله …», so a name without it is a vehicle. On a
    seller's headline the same absence establishes much less, so the reading
    is kept but its provenance is recorded rather than averaged in.

    No name at all is `unknown`. That is not a car and not an assignment —
    it is a record whose class was never determined, and D26's rule applies:
    absence of a marker is not evidence of its opposite.
    """
    if not name or not name.strip():
        return "unknown", "none"
    s = normalize(name)
    if any(normalize(c) in s for c in ASSIGNMENT_CUES):
        return "assignment", "canonical_name" if from_canonical else "listing_title"
    return "vehicle", "canonical_name" if from_canonical else "listing_title"


APPRAISAL_REQUIRED = ("asking_price_toman", "year_jalali", "mileage_km",
                      "model")


def eligibility(listing) -> tuple[bool, list[str]]:
    """(may enter W1, reasons it may not).

    Kept separate from parsing on purpose. A listing that cannot be priced is
    still a real observation — it counts toward supply, toward time-on-market,
    and toward what the source publishes — so it is excluded from the
    estimator, not from the corpus.
    """
    missing: list[str] = []
    for f in APPRAISAL_REQUIRED:
        if getattr(listing, f, None) is None:
            missing.append(f"no {f}")

    # Absence of a provenance field is UNKNOWN, and unknown fails CLOSED.
    #
    # Both reads below are getattr-with-default, which means this function
    # accepts objects that never set the field — and until this was written it
    # let them through, because `None in UNUSABLE_PRICE` is False. Nothing
    # exploits that today: CarListing defaults price_status to "absent", which
    # is already unusable, so the guarantee rested on a dataclass default
    # rather than on this gate. A gate whose correctness depends on every
    # caller remembering a default is not a gate, and D1's rule is the whole
    # reason: a fetch we could not make is not an absence, and a provenance we
    # never recorded is not a clean one.
    ps = getattr(listing, "price_status", None)
    if ps is None:
        missing.append("price provenance unknown — no price_status recorded")
    elif ps in UNUSABLE_PRICE or (isinstance(ps, str)
                                  and ps in {s.value for s in UNUSABLE_PRICE}):
        missing.append(f"price is {ps.value if hasattr(ps, 'value') else ps}")

    # A record whose class was never determined is not a car. `unknown`
    # never decays to `vehicle`: the whole point of the class is that a
    # حواله and a Pride are indistinguishable by year, mileage and price,
    # and the estimator would price the assignment as the cheapest Pride on
    # the market.
    pc = getattr(listing, "product_class", None)
    if pc is None:
        missing.append("product class unknown — no product_class recorded")
    elif pc != "vehicle":
        missing.append(f"product class is {pc}, not a vehicle")

    ms = getattr(listing, "mileage_status", None)
    if ms is None:
        missing.append("mileage provenance unknown — no mileage_status recorded")
    else:
        ms_val = ms.value if hasattr(ms, "value") else ms
        if ms_val in (Validity.SUSPICIOUS.value, Validity.IMPOSSIBLE.value):
            missing.append(f"mileage is {ms_val}")

    return (not missing), missing
