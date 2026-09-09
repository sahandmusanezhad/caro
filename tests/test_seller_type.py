"""The ported seller-type primitives — and the two ways they could go wrong.

Run: PYTHONPATH=. python3 tests/test_seller_type.py

`caro/ingest/seller_type.py` is a port from another project (D48). A port has
two characteristic failure modes and both are checked here rather than assumed:

**A cue that travelled but should not have.** The source is a property
scraper. «املاک» and «مستغلات» name a different trade; if one survived the
translation it would sit in the list doing nothing until the day it matched
something by accident.

**A cue that is too short to be evidence.** «اتو» is a substring of «اتومات».
Adding it would mark a large share of listings as dealer-posted on the
strength of the gearbox, and the failure would look like a market finding
rather than a bug.

The third thing checked is not a port question at all. D26 says the absence of
a badge yields `unknown`, never `private`. The source project returns
`personal` in that case. That divergence is the single most consequential line
of the port and it gets its own block.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.seller_type import (                              # noqa: E402
    DEALER_NAME_HINTS, decide_seller_type, dealer_name_from_panel,
    is_private_value, looks_like_dealer, norm_cell, panel_says_dealer,
)

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
print("norm_cell — one definition of 'the same string'")
for a, b in [("شخصی ", "شخصی"), (" شخصی:", "شخصی"), ("مالك", "مالک"),
             ("۱۲۳", "123"), ("نمایشگاه‌دار", "نمایشگاه دار")]:
    check(f"«{a}» normalises to «{b}»", norm_cell(a) == norm_cell(b),
          f"{norm_cell(a)!r} vs {norm_cell(b)!r}")


# ---------------------------------------------------------------------------
print("\nis_private_value — the whole cell, never a substring")
check("«شخصی» alone is a private value", is_private_value("شخصی"))
check("«مالک» alone is a private value", is_private_value("مالک"))
check("«شخصی » with trailing space still is", is_private_value("شخصی "))
# The reason the whole-cell rule exists. «شخصی» is an ordinary adjective and
# a substring test would read every one of these as a seller type.
for prose in ("استفاده شخصی", "فقط استفاده شخصی بوده", "بیمه شخص ثالث دارد",
              "خودروی شخصی و بدون کارکرد تاکسی"):
    check(f"  «{prose}» is NOT a private value", not is_private_value(prose))


# ---------------------------------------------------------------------------
print("\nlooks_like_dealer — a name that reads like a business")
for name in ("نمایشگاه پارسیان", "اتوگالری رضا", "بنگاه معاملات خودرو مهر",
             "شرکت تجارت خودرو", "نمایندگی ۱۰۵۲", "Tehran Motors",
             "AutoGallery Karimi"):
    check(f"«{name}» reads as a dealer", looks_like_dealer(name))

for name in ("رضا محمدی", "علی", "مریم ک.", "حسین رضایی"):
    check(f"  «{name}» does not", not looks_like_dealer(name))

check("an empty name is not evidence of anything",
      not looks_like_dealer(None) and not looks_like_dealer(""))


# ---------------------------------------------------------------------------
# The port-specific checks. These are the two ways this file could be wrong in
# a way that no amount of reading it would reveal.
print("\nthe port did not carry the wrong vocabulary")

_PROPERTY_ONLY = ("املاک", "املاك", "مستغلات", "مسکن", "ساختمانی", "عمران",
                  "انبوه ساز", "انبوه‌ساز", "بساز بفروش", "real estate",
                  "realestate", "realty", "realtor", "properties", "homes")
for w in _PROPERTY_ONLY:
    check(f"  «{w}» did not travel from the property scraper",
          w not in DEALER_NAME_HINTS, "it is in DEALER_NAME_HINTS")

# «اتو» is a substring of «اتومات». If it were a hint, the gearbox would
# decide the seller type — and the resulting bias would look like a finding.
check("«اتو» is not a hint on its own", "اتو" not in DEALER_NAME_HINTS)
for automatic in ("اتومات", "اتوماتیک", "گیربکس اتوماتیک", "206 اتومات"):
    check(f"  «{automatic}» does not read as a dealer",
          not looks_like_dealer(automatic))

# Same trap, latin: bare "car"/"auto" would match ordinary words.
for w in ("car", "auto"):
    check(f"  bare «{w}» is not a hint", w not in DEALER_NAME_HINTS)


# ---------------------------------------------------------------------------
print("\npanel lines — labels, not prose")
check("a dealer word on a short line is read",
      panel_says_dealer(["نمایشگاه اتومبیل", "همه آگهی ها"]))
check("  a line over 80 characters is prose and ignored",
      not panel_says_dealer(["نمایشگاه " + "ت" * 200]))
check("  no lines says nothing", not panel_says_dealer([]) and
      not panel_says_dealer(None))

check("the longer business line is the shop, not the role word",
      dealer_name_from_panel(["نمایشگاه", "نمایشگاه اتومبیل پارسیان",
                              "همه آگهی ها"])
      == "نمایشگاه اتومبیل پارسیان",
      str(dealer_name_from_panel(["نمایشگاه", "نمایشگاه اتومبیل پارسیان"])))
check("  the ORIGINAL string is returned, not the normalised one",
      dealer_name_from_panel(["نمایشگاه‌داران البرز"])
      == "نمایشگاه‌داران البرز",
      repr(dealer_name_from_panel(["نمایشگاه‌داران البرز"])))
check("  a personal name yields nothing",
      dealer_name_from_panel(["رضا محمدی", "چت"]) is None)


# ---------------------------------------------------------------------------
print("\ndecide_seller_type")
check("a type row naming a showroom → dealer",
      decide_seller_type([("نوع آگهی دهنده", "نمایشگاه")]) == "dealer")
check("a business poster name → dealer",
      decide_seller_type([("نام", "اتوگالری رضا")]) == "dealer")
check("dealer language in the contact block → dealer",
      decide_seller_type([], contact_text="نمایندگی مجاز") == "dealer")
check("an explicit «شخصی» cell → private",
      decide_seller_type([("نوع آگهی دهنده", "شخصی")]) == "private")

check("dealer evidence outranks a «شخصی» claim",
      decide_seller_type([("نوع آگهی دهنده", "شخصی"),
                          ("نام", "نمایشگاه پارسیان")]) == "dealer",
      "a business posting under «شخصی» is the case this exists to catch")


# ---------------------------------------------------------------------------
# D26, and the line where this port stops following its source.
print("\nD26 — absence of a badge is `unknown`, never `private`")
check("a page that says nothing → unknown, not private",
      decide_seller_type([("سال", "1393"), ("کارکرد", "120000")]) == "unknown",
      "the source project returns `personal` here; D26 forbids it")
check("  a fully rendered page that still says nothing → unknown",
      decide_seller_type(
          [("سال", "1393"), ("کارکرد", "120000"), ("رنگ", "سفید")],
          panel_lines=["همه آگهی ها", "اطلاعات تماس", "چت", "گزارش",
                       "اشتراک"]) == "unknown",
      "rendering is not evidence about a seller")
check("  no rows at all → unknown",
      decide_seller_type([]) == "unknown")
check("  and `private` is never returned without an explicit cell",
      all(decide_seller_type([("نام", n)]) != "private"
          for n in ("رضا محمدی", "علی", "")),
      "a personal-looking NAME is not a declaration of seller type")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
