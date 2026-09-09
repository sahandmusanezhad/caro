"""Dealer or private, decided from what the page states about the business.

Ported from `Tecso-Dev/SorinFlow-DaTA-mAmager` (MIT), `app/scraper/parsers.py`.
Five primitives, named in D48, carried across because the *shape* of the
decision transfers exactly even though every cue word had to change:

    _norm_value            → norm_cell
    is_personal_value      → is_private_value
    looks_like_agency      → looks_like_dealer
    panel_says_agency      → panel_says_dealer
    decide_advertiser_type → decide_seller_type
    agency_name_from_panel → dealer_name_from_panel

Nothing else from that project is here. No CAPTCHA solving, no stealth or
fingerprinting, no phone extraction, no auth, OTP or session handling — all of
which `caro/ingest/base.py` forbids every adapter from having, and all of
which exist in the source repository. D48 records why the boundary is where it
is.

## The one place the logic diverges, and it is not a detail

SorinFlow's `decide_advertiser_type` ends with a default: if the page rendered
and nothing said "agency", it returns `personal`. That is sound there — it
rests on an observed property of the source's own layout — and it is
**forbidden here**. D26:

    absence of a badge yields `unknown`, never `private` — small dealers post
    like individuals, and asserting otherwise would invent a fact

So the final step is dropped and this returns `"unknown"` where the original
returns `"personal"`. `private` is produced only from an explicit cell that
*is* the word. The result is a function that says "I do not know" far more
often, which is the correct behaviour for a signal whose only job is telling
`coverage` whether a comparable set is one forecourt's inventory.

## Vocabulary

`dealer | private | unknown`, matching `CarListing.seller_type`. The source
project's `agency | personal` is a different pair of words for a similar
distinction and is not used anywhere here.
"""

from __future__ import annotations

import re

from caro.ingest.persian import normalize

# Words that make a seller NAME read like a business rather than a person.
#
# Matched against a name field only — never against a description. That
# restriction is inherited deliberately: the source project records that
# matching prose turns every owner who writes «مشاورین املاک تماس نگیرند» into
# an agency, and the vehicle equivalent is just as easy to write.
#
# The property vocabulary is gone: املاک, مستغلات, مسکن, ساختمانی, انبوه‌ساز,
# real estate, realty and the rest describe a different trade and would match
# nothing here except by accident.
#
# `اتو` on its own is deliberately ABSENT. It is a substring of «اتومات» and
# «اتوماتیک», so it would mark a large share of listings as dealer-posted on
# the strength of the gearbox. There is a test for exactly that.
DEALER_NAME_HINTS = (
    # the trade, as it names itself
    "نمایشگاه", "اتوگالری", "اتو گالری", "گالری خودرو", "گالری اتومبیل",
    "بنگاه", "عاملیت", "نمایندگی", "کارگزار", "کارگزاری",
    # a business that happens to sell cars
    "شرکت", "موسسه", "مؤسسه", "هلدینگ", "تعاونی", "گروه", "سازمان",
    "اتحادیه", "دپارتمان", "واحد فروش",
    # latin, as written on Iranian dealer signage. Bare "car" and "auto" are
    # excluded for the same reason as «اتو»: too short to be evidence.
    "autogallery", "auto gallery", "car gallery", "motors", "showroom",
    "dealership", "trading",
)

# A type row whose VALUE says one of these is a business.
DEALER_VALUE_HINTS = (
    "نمایشگاه", "نمایشگاه دار", "اتوگالری", "اتو گالری", "بنگاه",
    "عاملیت فروش", "نمایندگی",
)

# Row titles that label WHO posted the ad, or WHAT they are.
TYPE_ROW_LABELS = ("نوع آگهی", "نوع فروشنده", "آگهی دهنده", "اگهی دهنده",
                   "فروشنده", "نوع آگهی دهنده")
NAME_ROW_LABELS = ("نام", "آگهی دهنده", "فروشنده", "نمایشگاه")

# Values that mean the owner posted it. Compared as WHOLE CELLS, never as
# substrings — see `is_private_value`.
PRIVATE_VALUES = frozenset({"شخصی", "مالک", "شخصی/مالک", "شخصی / مالک"})

# A line longer than this is prose, not a label.
PANEL_LINE_MAX = 80

_WS = re.compile(r"\s+")


def norm_cell(text: str | None) -> str:
    """Collapse a cell so «شخصی » and «شخصی» compare equal.

    Uses CARO's own `normalize` — Persian and Arabic digits to ASCII, ك→ک,
    ي→ی, ZWNJ removed — rather than the source project's, so one definition of
    "the same string" holds across this package.
    """
    v = normalize(text or "")
    return _WS.sub(" ", v).strip(" :،.-‏‎")


def is_private_value(text: str | None) -> bool:
    """True only when the cell IS the word, never when prose contains it.

    A substring test cannot be used. «شخصی» is an ordinary Persian adjective
    and turns up inside phrases that are not advertiser types at all — the
    shape to picture is «استفاده شخصی» sitting in a description. Reading one
    of those as a seller type marks a dealer's listing as owner-posted, and it
    then passes any filter built on that field.
    """
    return norm_cell(text) in PRIVATE_VALUES


def looks_like_dealer(*texts: str | None) -> bool:
    """True when a posted seller NAME reads like a business.

    Call this on a name field. Calling it on a description is the misuse the
    hint list is not designed to survive.
    """
    blob = normalize(" ".join(t for t in texts if t)).lower()
    if not blob.strip():
        return False
    return any(h.lower() in blob for h in DEALER_NAME_HINTS)


def panel_says_dealer(lines) -> bool:
    """True when short standalone lines from the page name a dealer panel.

    `lines` are labels and link text harvested off the listing — never the
    description, and never anything over `PANEL_LINE_MAX`, because at that
    length it is prose and prose produces false dealers.

    The mechanism is ported; the marker list is NOT seeded with a source's
    profile-link text, because no vehicle listing page has been observed here
    closely enough to state what it renders. Inventing one would be a claim
    about a website dressed as a constant. It fires today on the value hints,
    which are words a page shows about the business either way, and a marker
    table can be added the day a page is actually read.
    """
    for raw in (lines or []):
        line = norm_cell(raw)
        if not line or len(line) > PANEL_LINE_MAX:
            continue
        if any(normalize(h) in line for h in DEALER_VALUE_HINTS):
            return True
    return False


def dealer_name_from_panel(lines) -> str | None:
    """The business's own name out of the panel lines, e.g. «نمایشگاه پارسیان».

    Between «نمایشگاه» and «نمایشگاه اتومبیل پارسیان» the longer one is the
    shop; the bare role word is a label. Matching happens on the normalised
    form and the ORIGINAL is returned, because this is a name that gets stored
    and shown rather than only compared.

    This is a business name, not a person's. A line that reads as a private
    individual is not picked up, because `looks_like_dealer` gates it.
    """
    best = None
    for raw in (lines or []):
        original = _WS.sub(" ", (raw or "")).strip()
        line = norm_cell(raw)
        if not line or len(line) > PANEL_LINE_MAX:
            continue
        if line in ("همه آگهی ها", "اطلاعات تماس", "چت", "تماس"):
            continue
        if not looks_like_dealer(line):
            continue
        if best is None or len(original) > len(best):
            best = original
    return best


def decide_seller_type(rows, *, contact_text: str | None = None,
                       panel_lines=None) -> str:
    """(title, value) pairs off a listing page → `dealer | private | unknown`.

    All the judgement is here rather than in a page script, so it is testable
    without a browser.

    Order matters, and it is the source project's: dealer evidence outranks a
    «شخصی» claim, because a business posting under it is the failure this
    exists to catch, and the name it posts under gives it away.

    Where this deliberately differs is the end. The original returns
    `personal` when a rendered page says nothing; D26 forbids that, so the
    answer is `unknown`. A caller filtering on seller type must treat
    `unknown` as a miss, not as a match.
    """
    pairs = [(norm_cell(t), (v or "")) for t, v in (rows or [])]

    # 1. the page's own block about the business
    if panel_says_dealer(panel_lines):
        return "dealer"

    # 2. a type row naming a business
    for title, value in pairs:
        if any(normalize(lbl) in title for lbl in TYPE_ROW_LABELS):
            if any(normalize(h) in norm_cell(value) for h in DEALER_VALUE_HINTS):
                return "dealer"

    # 3. a poster name that reads like a business
    for title, value in pairs:
        if any(normalize(lbl) in title for lbl in NAME_ROW_LABELS):
            if not is_private_value(value) and looks_like_dealer(value):
                return "dealer"

    # 4. dealer language in the contact block. Only dealer: «شخصی» is never
    #    trusted from free text, for the reason in `is_private_value`.
    contact = norm_cell(contact_text)
    if contact and any(normalize(h) in contact for h in DEALER_VALUE_HINTS):
        return "dealer"

    # 5. an explicit private value, as the whole cell
    for title, value in pairs:
        if any(normalize(lbl) in title for lbl in TYPE_ROW_LABELS) \
                and is_private_value(value):
            return "private"

    # 6. D26. The original returns `personal` here; that would be inventing a
    #    fact about a seller from the absence of a badge, and small dealers
    #    post like individuals.
    return "unknown"
