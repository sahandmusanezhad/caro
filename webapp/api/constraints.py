"""What one listing says to each constraint the buyer stated.

On a corpus no estimator has cleared, search answers from the listings
directly (`_evidence` in main.py), and until this module its filter ran a
comparison only when the listing carried the value: a listing with no price
passed «زیر ۳۰۰ میلیون», and one with no odometer passed «کم‌کارکرد». D60 and
D61 recorded it as the buyer's constraints failing open where the gate fails
closed. Measured on run11 with the five examples under the search box, at the
k=8 the results page asks for: of the 36 rows drawn as «آگهی‌های منطبق», 3
were there only because a value was missing — two of the four rows answering
«پراید زیر ۳۰۰ میلیون», both listings whose price is «توافقی».

So a constraint has three answers for a listing, not two:

    met       the listing carries the value, and the value satisfies it
    broken    the listing carries the value, and it does not
    unknown   the listing carries no value to check it against

A listing is a match only when every constraint the buyer stated is met. One
that breaks any is left out. One that breaks none and cannot be checked
against some is neither: it is shown apart, with what could not be checked
named, and never under a heading that calls it a match.
"""

from __future__ import annotations

from typing import Literal

from caro.ingest.divar_car import GEARBOX
from caro.ingest.quality import UNUSABLE_PRICE

Verdict = Literal["met", "broken", "unknown"]

_UNUSABLE = frozenset(s.value for s in UNUSABLE_PRICE)


def asking_price(x) -> int | None:
    """The amount the site shows as this listing's asking price, or None.

    The rule is `askingPrice()` in webapp/web/lib/format.ts, which is the rule
    FIELD_PROVENANCE.md states for a price on a card: a figure whose kind is
    not `cash`, or whose status is unusable, is not an asking price, and the
    card says what it is instead of drawing it. A budget is checked against
    the same figure the card draws, so a financing total — which reads like a
    bargain beside real prices — is unknown to the budget, not inside it. On
    run11 no listing carries such a figure: its two non-cash prices carry no
    amount at all. The rule is here so that the next corpus is held to it
    too.

    Both fields null is the appraisal-row case the card also allows: a row
    that was scored passed both checks in eligibility before it got here.
    """
    status = getattr(x, "price_status", None)
    kind = getattr(x, "price_kind", None)
    if kind is not None and kind != "cash":
        return None
    if status is not None and status in _UNUSABLE:
        return None
    return x.asking_price_toman


# The buyer's red lines — `DEAL_BREAKER_CUES` in caro/ranking.py, which the
# intent panel prints under «خط قرمز» as understood. `_evidence`'s filter
# never read them: «تصادفی نباشه» let an accident through, and «اتومات» let
# anything through. Each is judged from the one field that answers it, and
# silence is `unknown`, never `met`.
#
#   accident           body_condition — `accident` breaks it. The rule the
#                      ranked path's `has_accident` already uses.
#   unclear_documents  document_issue — True breaks it. Likewise the ranked
#                      path's `has_unclear_documents`.
#   manual             gearbox — «اتومات» makes a manual gearbox the red
#                      line, so `manual` breaks it and `automatic` meets it.
#                      With no gearbox recorded, a trim word that IS one of
#                      those two answers it: the page draws trim `manual` as
#                      «دنده‌ای», and a row so named cannot be shown as not
#                      knowing. Nothing else in a trim is read — `manualr` is
#                      a parse artefact (format.ts) and stays one. run11
#                      carries no gearbox (FIELD_PROVENANCE.md), and one of
#                      its trims is the bare word.
#   repaint            body_condition — «بدون رنگ» is the bottom rung of a
#                      ladder on which the worst disclosed claim wins
#                      (BODY_CONDITION in caro/ingest/divar_car.py), so only
#                      `intact` meets it and every rung above breaks it: a
#                      replaced panel is not a body without paint.
#
# The ranked path has no rule for the last two, and lets an unknown through
# all four. It ranks nothing on a real corpus yet (D43), and it is not
# changed here.
#
# A province the buyer names is the one constraint that is not a number and
# not a red line. It is judged from the one field that answers it, the
# province the listing carries — `city` on the object the reader returns, the
# corpus's `province` — and a province known from the city's name meets it as
# a stated one does: «تهران، آذری» is in Tehran (D74). The table beside the
# answer says which it was («از روی نام شهر», D81), so the match is never
# presented as more than it is. Several named are any-of. A listing with no
# province is `unknown`, which is the common case on run13, where 34 of 74 rows
# carry one: the answer there is the few that meet it and the many held apart,
# not the few alone. The ranked path has no rule for this either — `Row`
# carries no province — and it is the same pinned omission.
_LADDER_ABOVE_INTACT = frozenset(
    {"minor_paint", "multi_paint", "replaced_part", "accident"})


def _accident(x) -> Verdict:
    c = getattr(x, "body_condition", None)
    if c in (None, "unknown"):
        return "unknown"
    return "broken" if c == "accident" else "met"


def _unclear_documents(x) -> Verdict:
    d = getattr(x, "document_issue", None)
    if d is None:
        return "unknown"
    return "broken" if d else "met"


def _gearbox(x) -> str | None:
    g = getattr(x, "gearbox", None)
    if g in GEARBOX:
        return g
    named = set((getattr(x, "trim", None) or "").lower().split()) & set(GEARBOX)
    return named.pop() if len(named) == 1 else None


def _manual(x) -> Verdict:
    g = _gearbox(x)
    if g == "manual":
        return "broken"
    return "met" if g == "automatic" else "unknown"


def _repaint(x) -> Verdict:
    c = getattr(x, "body_condition", None)
    if c == "intact":
        return "met"
    return "broken" if c in _LADDER_ABOVE_INTACT else "unknown"


RED_LINES = {"accident": _accident, "unclear_documents": _unclear_documents,
             "manual": _manual, "repaint": _repaint}


def odometer(x) -> int | None:
    """The odometer reading a constraint may use, or None.

    Only a `plausible` reading decides anything (D22's grades,
    caro.ingest.quality.Validity). `unknown` has no number. `suspicious` has
    one the seller should not be believed on — the 999999 placeholder, or
    fewer than 1,500 km a year on a car three or more years old. `impossible`
    has one no passenger car can have. Each is unknown to the constraint, and
    stays itself on the listing: the reason travels as `mileage_status`, and
    the page says which.

    The filter before this compared every number alike, so D21's own examples
    went both wrong ways: 1 km on a 1385 Pride met «کم‌کارکرد», and 999,990 km
    broke it. A record that states no status at all is not trusted either.
    On run11 every reading is plausible, so nothing there changes.
    """
    if getattr(x, "mileage_status", None) != "plausible":
        return None
    return x.mileage_km


def judge(x, spec) -> dict[str, Verdict]:
    """Each constraint the buyer stated, and what this listing says to it.

    Keyed by the names the payload carries in `UncheckedItem.unchecked`. A
    constraint the buyer did not state is absent, not `met`: there is nothing
    to report about it. A red line with no rule here is `unknown` — it was
    stated, and nothing checked it.
    """
    out: dict[str, Verdict] = {}

    if spec.budget_max_toman is not None or spec.budget_min_toman is not None:
        p = asking_price(x)
        if p is None:
            out["budget"] = "unknown"
        elif ((spec.budget_max_toman is not None and p > spec.budget_max_toman)
              or (spec.budget_min_toman is not None
                  and p < spec.budget_min_toman)):
            out["budget"] = "broken"
        else:
            out["budget"] = "met"

    # A year and a mileage are each one constraint with two ends, a floor and
    # a ceiling. The sentence states one end of each («مدل ۹۸ به بالا»,
    # «زیر ۱۰۰ هزار کیلومتر»); the filter panel can state both (the owner's
    # choice of 2026-11-25), and a value outside either end breaks it.
    y_lo, y_hi = spec.year_min, getattr(spec, "year_max", None)
    if y_lo is not None or y_hi is not None:
        y = x.year_jalali
        out["year"] = ("unknown" if y is None
                       else "broken" if ((y_lo is not None and y < y_lo)
                                         or (y_hi is not None and y > y_hi))
                       else "met")

    m_lo, m_hi = getattr(spec, "min_mileage_km", None), spec.max_mileage_km
    if m_lo is not None or m_hi is not None:
        m = odometer(x)
        out["mileage"] = ("unknown" if m is None
                          else "broken" if ((m_hi is not None and m > m_hi)
                                            or (m_lo is not None and m < m_lo))
                          else "met")

    if spec.provinces:
        p = getattr(x, "city", None)
        out["province"] = ("unknown" if not p
                           else "met" if p in spec.provinces else "broken")

    for line in spec.deal_breakers:
        rule = RED_LINES.get(line)
        out[line] = rule(x) if rule is not None else "unknown"

    return out


def unchecked(verdicts: dict[str, Verdict]) -> list[str] | None:
    """None if any constraint is broken; otherwise what could not be checked,
    in the order the constraints were judged — empty for a match."""
    if "broken" in verdicts.values():
        return None
    return [k for k, v in verdicts.items() if v == "unknown"]
