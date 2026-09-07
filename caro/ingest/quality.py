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


# What W1 needs before a listing can inform an estimate. Deliberately narrow:
# these are the terms that appear in the appraisal itself, so a row missing
# any of them cannot contribute a comparable, only noise.
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

    ps = getattr(listing, "price_status", None)
    if ps in UNUSABLE_PRICE or (isinstance(ps, str)
                                and ps in {s.value for s in UNUSABLE_PRICE}):
        missing.append(f"price is {ps.value if hasattr(ps, 'value') else ps}")

    ms = getattr(listing, "mileage_status", None)
    ms_val = ms.value if hasattr(ms, "value") else ms
    if ms_val in (Validity.SUSPICIOUS.value, Validity.IMPOSSIBLE.value):
        missing.append(f"mileage is {ms_val}")

    return (not missing), missing
