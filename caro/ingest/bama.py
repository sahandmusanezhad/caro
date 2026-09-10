"""
Bama adapter — written against the site's actual structure, not an assumption.

What the first live run corrected
---------------------------------
The first version assumed `https://bama.ir/sitemap/car` enumerated listings.
It does not. It enumerates **brand and category pages**:

    <loc>https://bama.ir/car/peugeot</loc>
    <loc>https://bama.ir/car/peugeot?mileage=0</loc>

So discovery is two-stage — sitemap → brand pages → listing links — and the
first run collected zero listings while reporting success, which is exactly
the failure mode `first_run.py` exists to surface. Verified 2026-09-07 by
fetching the sitemap and a brand page.

Also corrected: `/car/saipa` and `/car/ikco` **redirect to `/car`** and
return generic inventory. They are not brand slugs. The real category slugs
are model-level — `pride`, `peugeot`, `dena`, `tiba`, `samand`, `shahin`,
`tara`, `runna`, `saina` — which matters because a run that follows the
manufacturer slugs collects the general listing feed while believing it has
sampled two manufacturers.

What the second live run corrected
----------------------------------
Extraction was rebuilt on **structured data**. Bama is a Nuxt application
and every detail page carries a schema.org `["Product", "Car"]` block, which
supplies identifier, brand, model year, odometer, colour, transmission, fuel
and the offer price — typed, from the site itself.

The reason for the switch was a live failure, not a preference. The site's
global navigation renders *above* the article and contains real prices
(«قیمت روز خودرو»). The old text heuristic — find «تومان», take the line
before — has no way to tell that block from the car, so a mis-anchored parse
attributes a navigation number to a vehicle and nothing downstream can
detect it. The structured block is one object about one vehicle and cannot
be mis-anchored.

The text path survives as a fallback for pages without the block, but it is
now anchored at the article and records that it was used, because a corpus
where the fill rate holds up while the extraction quality collapses is the
specific way this layer would fail quietly.

What Bama gives that Divar does not
-----------------------------------
Body condition as a **structured field**:

    وضعیت بدنه
    درب تعویض

On Divar that fact lives in prose or nowhere. This is the concrete reason
Bama is `primary_offers` and sets the canonical schema — the field that
decides a used car's value is published rather than inferred.

Two hazards the page layout creates
-----------------------------------
1. Every detail page carries a **"آگهی های مرتبط"** block with five other
   cars, each with its own price and mileage. Naive text extraction pulls
   those in and silently attributes another car's price to this one. The
   parser truncates at that heading.
2. The phone number appears partially masked (`۰۹۳۶۱۰۴۲۹XX`). It is never
   read, never parsed, never stored — masked or not.

The URL slug is itself structured: `detail-ffdrszax-peugeot-206ir-type5-1396`
carries id, make, model, trim and year, so identity survives even when a
detail page fails to load.
"""

from __future__ import annotations

import json
import random
import re
import time
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterator, Sequence

from caro.ingest.divar_car import (
    CarListing, PolitenessPolicy, SourceBlocked, USER_AGENT,
    extract_body_condition, extract_color, extract_fuel, extract_gearbox,
    has_document_issue,
)
from caro.ingest.persian import (
    digits_only, normalize, parse_mileage_km, parse_price, parse_year_jalali,
)
from caro.ingest.quality import (
    PriceStatus, classify_mileage, classify_price_kind, classify_product,
)
from caro.tracking import FetchOutcome, FetchStatus, classify_http

# Phrases a page shows when the offer is gone but the server still answers
# 200. Without these, a removed listing reads as a successful fetch of an
# empty car and quietly enters the corpus.
GONE_MARKERS = ("این آگهی موجود نیست", "آگهی حذف شده", "آگهی منقضی",
                "یافت نشد", "صفحه مورد نظر یافت نشد", "آگهی فروخته شده")

# What a real listing page must contain. A 200 that has none of these is not
# a listing — it is a challenge page, a redirect landing, or a partial
# render, and calling it ABSENT would fabricate a disappearance.
REQUIRED_MARKERS = ("کارکرد", "تومان")

SITEMAP_CAR = "https://bama.ir/sitemap/car"
BASE = "https://bama.ir"

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# The boundary between this listing and the five unrelated cars below it.
RELATED_MARKER = "آگهی های مرتبط"

# Marks a trade seller. These are things the page states about the *business*
# — a tenure badge Bama itself awards, a showroom address, union membership —
# never anything about a person. CARO does not read the phone number, so this
# is the only seller signal available, and it is deliberately coarse.
#
# It matters for one reason: thirty listings from one dealer are not thirty
# independent observations of a market. Without some seller signal, a
# comparable set can look varied on year and mileage while being one
# forecourt's inventory. See caro.ingest.coverage.
DEALER_MARKERS = (
    "فعالیت مداوم در باما",              # Bama's own tenure badge
    "اتحادیه نمایشگاه داران",            # dealers' union membership
    "عاملیت فروش",                       # agency sales
)


def detect_seller_type(lines: Sequence[str]) -> str:
    text = normalize(" ".join(lines))
    if any(normalize(m) in text for m in DEALER_MARKERS):
        return "dealer"
    # Absence of a badge is not proof of a private seller — small dealers
    # post like individuals — so this stays "unknown" rather than "private".
    return "unknown"

# Slug → make/model/trim/year, from the observed url shape.
_SLUG = re.compile(
    r"detail-(?P<id>[a-z0-9]+)-(?P<make>[a-z]+)-(?P<rest>[a-z0-9-]*?)"
    r"(?:-(?P<year>1[34]\d{2}))?$")

# Slug model forms → the canonical name. Bama's url uses market codes
# (206ir, 206sd) that must fold to the same model key the rest of CARO uses,
# or comparables split across spellings of one car.
SLUG_MODELS = {
    "206ir": "206", "206": "206", "206sd": "206 SD",
    "207": "207", "405": "405", "pars": "Pars", "roa": "Roa",
    "pride": "Pride", "tiba": "Tiba", "quick": "Quik", "quik": "Quik",
    "saina": "Saina", "shahin": "Shahin", "dena": "Dena", "runna": "Runna",
    "samand": "Samand", "tara": "Tara", "rana": "Runna",
}

SLUG_MAKES = {"peugeot": "Peugeot", "saipa": "Saipa", "ikco": "IKCO",
              "kia": "Kia", "hyundai": "Hyundai", "renault": "Renault",
              "toyota": "Toyota", "mazda": "Mazda", "audi": "Audi",
              "benz": "Mercedes", "bmw": "BMW", "chery": "Chery",
              "mvm": "MVM", "jac": "JAC", "lifan": "Lifan"}

# Bama's url puts the MODEL FAMILY where a make would go on a western site:
#
#     /car/detail-xproyaln-saina-manuals-mtgas-1404
#                           ^^^^^ model, not manufacturer
#
# Read naively that yields `make="Saina"`, which is wrong — Saina is a Saipa
# model. The 2026-09-07 run printed "Saina manuals" and "Runna plus" as makes
# and models, which is how this surfaced. Domestic families are therefore
# mapped to their manufacturer, and the family itself becomes the model.
FAMILY_MAKE = {
    "pride": "Saipa", "tiba": "Saipa", "saina": "Saipa", "quick": "Saipa",
    "quik": "Saipa", "shahin": "Saipa", "aria": "Saipa", "atlas": "Saipa",
    "samand": "IKCO", "dena": "IKCO", "runna": "IKCO", "rana": "IKCO",
    "tara": "IKCO", "soren": "IKCO", "arisun": "IKCO", "haima": "IKCO",
}

FAMILY_NAME = {
    "pride": "Pride", "tiba": "Tiba", "saina": "Saina", "quick": "Quik",
    "quik": "Quik", "shahin": "Shahin", "samand": "Samand", "dena": "Dena",
    "runna": "Runna", "rana": "Runna", "tara": "Tara", "soren": "Soren",
    "aria": "Aria", "atlas": "Atlas", "arisun": "Arisun",
}


# ---------------------------------------------------------------------------
# Discovery — two stages, because the sitemap lists categories
# ---------------------------------------------------------------------------

def parse_sitemap(xml_text: str) -> list[str]:
    """Urls from a sitemap or sitemap index, regex fallback for bad XML."""
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text)
    locs = [e.text.strip() for e in root.findall(".//sm:loc", _SM_NS)
            if e.text and e.text.strip()]
    if not locs:
        locs = [e.text.strip() for e in root.iter()
                if e.tag.endswith("loc") and e.text and e.text.strip()]
    return locs


def is_listing_url(url: str) -> bool:
    return "/car/detail-" in url


def is_category_url(url: str) -> bool:
    """A brand or model page, and not one of its filter permutations.

    The sitemap publishes `?mileage=0` and `?mileage=1` variants of every
    brand. They resolve to the same inventory sliced differently, so
    following them multiplies requests without adding cars.
    """
    if is_listing_url(url) or "?" in url:
        return False
    return bool(re.match(r"^https?://bama\.ir/car/[a-z0-9-]+/?$", url))


def extract_listing_links(html: str) -> list[str]:
    """Detail links from a category page, in order, deduplicated."""
    seen, out = set(), []
    for href in re.findall(r'href="(/car/detail-[^"#?]+)"', html):
        if href not in seen:
            seen.add(href)
            out.append(BASE + href)
    return out


# ---------------------------------------------------------------------------
# Trim pages — the two guards the Run 5 pre-flight bought
# ---------------------------------------------------------------------------
#
# Both of these are things a reasonable collector would get wrong, and both
# were measured on 2026-09-07 rather than guessed.

# A trim page carries a schema.org ItemList, and it is TRUNCATED. `/car/pride`
# — the site's entire Pride inventory — reports five items, and so does
# `/car/pride-131` and every thin trim tested. Five is the cap, not the count.
#
# The temptation is obvious: the ItemList is structured data, and D19 says to
# prefer structured data over rendered text. That rule is about which source
# is AUTHORITATIVE for a field, not about which is COMPLETE. Reading inventory
# size off this block puts an artefact of the page into the corpus as a fact
# about the market — the same error as Run 1's `/car/saipa` and D31's
# `-page-N` redirect, on a third route.
ITEMLIST_CAP = 5

# The rendered list is itself paginated at thirty. A page returning thirty
# means "at least thirty", never "thirty".
TRIM_PAGE_CAP = 30

_DETAIL_SLUG = re.compile(r"/car/(detail-[a-z0-9]+-[a-z0-9-]+)")


@dataclass(frozen=True)
class TrimPage:
    """What one `/car/<model>-<trim>` page actually contains.

    `contaminated` is the important field. Two of twelve slugs sampled in the
    Run 5 pre-flight served a generic feed instead of the trim — `tara-v1` and
    `renault-l90-e2` each returned 32 listings with none belonging to the
    trim, the same Hyundai first in both. A collector that trusted the slug
    would have entered 64 unrelated cars as observations of those trims.

    That corruption is invisible downstream: it lands in the trim conditioning
    the estimator is built on, the rows sit on both sides of any split, and no
    error metric can see it because the model is consistently wrong about a
    trim that does not exist as described.
    """
    slug: str
    on_trim: tuple[str, ...]
    off_trim: tuple[str, ...]

    @property
    def contaminated(self) -> bool:
        """No listing on this page belongs to the trim it claims to be.

        Deliberately "none", not "most". A real trim page can carry a
        neighbouring car in a related-listings rail, so a threshold would need
        a rationale nobody has measured. Total absence is unambiguous, and it
        is what both observed cases looked like.
        """
        return not self.on_trim and bool(self.off_trim)

    @property
    def n(self) -> int:
        """Listings usable as observations of this trim. Zero when
        contaminated — the off-trim rows are real cars, but they are not
        evidence about this trim, and counting them is the whole failure."""
        return 0 if self.contaminated else len(self.on_trim)

    @property
    def at_page_cap(self) -> bool:
        return len(self.on_trim) + len(self.off_trim) >= TRIM_PAGE_CAP


def parse_trim_page(html: str, slug: str) -> TrimPage:
    """Count a trim page's listings, and check they are that trim's.

    Counting is done on the RENDERED detail links, never on the ItemList: see
    `ITEMLIST_CAP`. Membership is decided by the slug the site itself puts in
    each detail URL, which is the site's own claim about what the car is —
    not our inference from a title.
    """
    seen, on, off = set(), [], []
    for m in _DETAIL_SLUG.finditer(html):
        d = m.group(1)
        if d in seen:
            continue
        seen.add(d)
        (on if f"-{slug}-" in d else off).append(d)
    return TrimPage(slug=slug, on_trim=tuple(on), off_trim=tuple(off))


def parse_slug(url: str) -> dict:
    """Identity from the url alone, so it survives a failed page load.

    Two url shapes, and getting them confused mislabels the whole corpus:

        detail-ffdrszax-peugeot-206ir-type5-1396   make, model, trim, year
        detail-xproyaln-saina-manuals-mtgas-1404   MODEL, trim, trim, year

    Domestic cars use the second shape — the first token is the model family,
    not the manufacturer — so it is mapped through FAMILY_MAKE and the whole
    remainder becomes the trim. Variant then lives where the comparable
    ladder already knows how to relax it, instead of splitting one model
    across a dozen spellings of its trim.
    """
    m = _SLUG.search(url.split("?")[0].rstrip("/"))
    if not m:
        return {}
    head = m.group("make")
    rest = m.group("rest") or ""
    parts = [p for p in rest.split("-") if p]

    if head in FAMILY_MAKE:
        make = FAMILY_MAKE[head]
        model = FAMILY_NAME.get(head, head.title())
        trim_parts, raw_model = parts, head
    else:
        make = SLUG_MAKES.get(head, head.title())
        raw_model = parts[0] if parts else None
        model = SLUG_MODELS.get(raw_model, raw_model)
        trim_parts = parts[1:]

    return {
        "listing_id": m.group("id"),
        "make": make,
        "model": model,
        "raw_model_slug": raw_model,
        "trim": " ".join(trim_parts) or None,
        "year_jalali": int(m.group("year")) if m.group("year") else None,
    }


# ---------------------------------------------------------------------------
# Detail page — structured first
# ---------------------------------------------------------------------------
#
# Bama is a Nuxt application, and every detail page carries a schema.org
# `["Product", "Car"]` block in <script type="application/ld+json">. Verified
# 2026-09-07 against a live page; it contains:
#
#     identifier, name, brand, productionDate, vehicleModelDate,
#     mileageFromOdometer{value,unitCode}, color, vehicleTransmission,
#     fuelType, bodyType, offers{price,priceCurrency,availability}
#
# That is the whole spine of the record, typed, from the site itself. The
# second live run replaced text scraping with this for one reason: the text
# path had to *infer* the price by finding «تومان» and taking the previous
# line, and the page's global navigation sits above the article, so any
# mis-anchoring silently attributed a nav number to a car. The JSON-LD block
# cannot be mis-anchored — it is one object about one vehicle.
#
# What JSON-LD does NOT carry is `وضعیت بدنه` — body condition. That is the
# field the whole risk layer rests on, so the parser stays hybrid on purpose:
# structured for the spine, text for the condition. See parse_detail_page.

_LD_BLOCK = re.compile(
    r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
    re.S | re.I)

# The correct reading of the ISO codes. A price in the wrong unit is the
# single most destructive parse error in this codebase — every estimate,
# every ranking, every «ارزش» claim inherits it — so an unrecognised
# currency yields None and is counted, never coerced.
_TO_TOMAN = {"IRR": 0.1, "IRT": 1.0, "TOMAN": 1.0, "IRT-TOMAN": 1.0}

# Bama's actual convention, established 2026-09-07 across 76 live listings.
#
# Every detail page declares `"priceCurrency": "IRR"` and publishes a **toman**
# figure. Verified against the number rendered to buyers on the same page:
#
#     JSON-LD  "price": "850000000", "priceCurrency": "IRR"
#     page     ۸۵۰,۰۰۰,۰۰۰ تومان
#
# Reading the label literally would divide every price by ten. That is the
# nastiest class of bug available here, because the currency whitelist above
# cannot catch it: `IRR` *is* a code we recognise, so nothing raises, nothing
# is counted, and the corpus is uniformly wrong by an order of magnitude.
#
# So the site's observed convention overrides its declared one, and
# reconcile_price() keeps checking that override against the rendered price on
# every page that shows one. If Bama ever fixes the label, the run report
# starts logging `label_wrong_*` and this constant is what needs revisiting.
BAMA_TO_TOMAN = {"IRR": 1.0, "IRT": 1.0, "TOMAN": 1.0, "IRT-TOMAN": 1.0}

# UN/CEFACT codes. KMT = kilometre, SMI = statute mile.
_TO_KM = {"KMT": 1.0, "KM": 1.0, "SMI": 1.609344}


def jsonld_blocks(html: str) -> list[dict]:
    out = []
    for raw in _LD_BLOCK.findall(html or ""):
        try:
            parsed = json.loads(raw.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        out.extend(parsed if isinstance(parsed, list) else [parsed])
    return out


def _is_car(node) -> bool:
    if not isinstance(node, dict):
        return False
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    return any(str(x).lower() == "car" for x in types)


def jsonld_car(html: str) -> dict | None:
    """The one node describing *this* vehicle, or None.

    Searches @graph too: pages routinely nest their real payload one level
    down, and a parser that only reads top level reports "no structured data"
    on a page that is full of it.
    """
    for node in jsonld_blocks(html):
        if _is_car(node):
            return node
        graph = node.get("@graph")
        if isinstance(graph, list):
            for sub in graph:
                if _is_car(sub):
                    return sub
    return None


def _num(v):
    """A number from a JSON-LD scalar or QuantitativeValue."""
    if isinstance(v, dict):
        v = v.get("value")
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = digits_only(str(v))
    return float(s) if s.isdigit() else None


def ld_price_toman(offers, factors: dict | None = None,
                   ) -> tuple[int | None, str | None]:
    """(toman, reason-it-is-missing).

    Returns the reason as well as the value because "no price" has three
    different meanings here — negotiable, absent, and a currency we do not
    recognise — and collapsing them into None loses the only signal that
    would tell us the site changed.
    """
    if isinstance(offers, list):
        offers = offers[0] if offers else None
    if not isinstance(offers, dict):
        return None, "no offers block"
    raw = _num(offers.get("price"))
    if raw is None or raw <= 0:
        return None, "negotiable or unpriced"
    cur = str(offers.get("priceCurrency") or "").upper().strip()
    factor = (factors if factors is not None else _TO_TOMAN).get(cur)
    if factor is None:
        return None, f"unrecognised currency {cur!r}"
    return int(round(raw * factor)), None


def reconcile_price(ld_toman: int | None, text_toman: int | None,
                    ) -> tuple[int | None, str]:
    """Cross-check the structured price against the one shown to buyers.

    Why this exists rather than trusting the structured block outright: a
    site's `priceCurrency` label is metadata, and metadata can be wrong in a
    way that the currency whitelist cannot catch. If a page declares `IRR`
    but publishes a toman figure, dividing by ten is *silently* a tenfold
    error — the guard does not fire, because `IRR` is a code we recognise.

    The number rendered on the page is what a buyer reads and acts on, so it
    is the ground truth for the unit. Agreement between the two is the
    evidence that the conversion is right; a clean factor of ten is evidence
    the label is wrong; anything else is unexplained, and unexplained means
    no price rather than a chosen one.

    Returns (toman, agreement-code).
    """
    if ld_toman is None and text_toman is None:
        return None, "none"
    if text_toman is None:
        return ld_toman, "ld_only"
    if ld_toman is None:
        return text_toman, "text_only"
    # Rounding differs between a rendered string and a raw integer, so exact
    # equality is the wrong test.
    if abs(ld_toman - text_toman) <= max(1, text_toman // 100):
        return ld_toman, "agree"
    if abs(ld_toman * 10 - text_toman) <= max(1, text_toman // 100):
        # The block's number was already toman despite its label.
        return text_toman, "label_wrong_ld_10x_low"
    if abs(ld_toman - text_toman * 10) <= max(1, text_toman // 10):
        return text_toman, "label_wrong_ld_10x_high"
    return None, "unexplained_disagreement"


def ld_mileage_km(node: dict) -> int | None:
    m = node.get("mileageFromOdometer")
    v = _num(m)
    if v is None or v < 0:
        return None
    unit = str((m or {}).get("unitCode") or "KMT").upper() \
        if isinstance(m, dict) else "KMT"
    factor = _TO_KM.get(unit)
    if factor is None:
        return None
    return int(round(v * factor))


def ld_year_jalali(node: dict) -> int | None:
    """Jalali year, converting the Gregorian years imported cars carry."""
    for key in ("vehicleModelDate", "productionDate", "modelDate"):
        v = _num(node.get(key))
        if v is None:
            continue
        y = int(v)
        if 1300 <= y <= 1450:
            return y
        if 1900 <= y <= 2100:
            return y - 621
    return None


def _text(html: str) -> list[str]:
    """Tag-stripped lines. Robust to markup changes in a way selectors are not."""
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</(div|p|li|h\d|span|td|tr)>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", " ", t)
    t = (t.replace("&nbsp;", " ").replace("&amp;", "&")
          .replace("&quot;", '"').replace("&#39;", "'"))
    return [ln.strip() for ln in t.split("\n") if ln.strip()]


def _labelled(lines: Sequence[str], label: str) -> str | None:
    """Value following a label. Bama renders these as consecutive lines."""
    for i, ln in enumerate(lines[:-1]):
        if normalize(ln) == normalize(label):
            return lines[i + 1]
    return None


@dataclass
class ParseTrace:
    """Where each field came from, and why the missing ones are missing.

    A field inventory that says "price 85% filled" is only half the story;
    what changes the design is *which* path filled it. If the structured
    block silently disappears one day, the text fallback keeps the fill rate
    looking healthy while the quality quietly collapses. Counting the source
    is how that gets noticed on the run it happens, not a month later.
    """
    used_jsonld: bool = False
    price_source: str = "none"        # jsonld+text | jsonld | text | none
    price_reason: str | None = None
    price_agreement: str = "none"     # see reconcile_price()
    mileage_source: str = "none"
    condition_source: str = "none"    # field | description | none


def parse_detail_page(url: str, html: str,
                      trace: ParseTrace | None = None) -> CarListing | None:
    """Parse ONE listing: structured block for the spine, text for condition.

    Two independent hazards on this page, handled separately.

    *Related listings.* Every detail page carries five other cars under
    «آگهی های مرتبط», each with its own price and mileage, so the text half
    is truncated there. Without the cut the first price after this car's
    might belong to a different vehicle and nothing downstream could tell.

    *Global navigation.* The site's menu renders **above** the article, so
    the text half's first lines are chrome, not the car. That is what made
    the price heuristic ("find تومان, take the line before") unsafe, and it
    is why price and mileage now come from the JSON-LD block, which is one
    object about one vehicle and cannot be mis-anchored. The text path
    remains only as a fallback, and records that it was used.
    """
    tr = trace if trace is not None else ParseTrace()

    lines = _text(html)
    for i, ln in enumerate(lines):
        if RELATED_MARKER in normalize(ln):
            lines = lines[:i]
            break
    if not lines:
        return None

    slug = parse_slug(url)
    blob = " ".join(lines)
    ld = jsonld_car(html) or {}
    tr.used_jsonld = bool(ld)

    # The article begins at this car's own mileage line. Everything above it
    # is site navigation, which on the live page includes «قیمت روز خودرو»
    # and real prices — none of them this car's. Any text-based number must
    # be taken from below this anchor or not at all.
    body_from = next((i for i, ln in enumerate(lines)
                      if "کارکرد" in normalize(ln)), None)

    # ---- price ------------------------------------------------------------
    # Both readings are taken and then reconciled. Neither source is trusted
    # alone: the structured block can carry a wrong currency *label*, which
    # no whitelist can catch, and the text is anchored but still a heuristic.
    # Agreement between them is the evidence that the number is right.
    ld_price, ld_reason = (None, "no structured block")
    if ld:
        ld_price, ld_reason = ld_price_toman(ld.get("offers"), BAMA_TO_TOMAN)

    text_price = None
    if body_from is not None:
        for i in range(body_from, len(lines)):
            if normalize(lines[i]) in ("تومان", "تومن") and i:
                text_price = parse_price(lines[i - 1])
                if text_price:
                    break
    # There is deliberately no page-wide `parse_price(blob)` fallback. A
    # wrong price is worse than a missing one: the missing one shows up in
    # the inventory and is excluded from fitting; the wrong one is neither.

    price, agreement = reconcile_price(ld_price, text_price)
    tr.price_agreement = agreement
    # The agreement code and the status are different things: the first says
    # what the two readings did, the second says how much the result is worth
    # believing. Downstream cares about the second and should not have to
    # re-derive it from the first.
    price_status = {
        "agree": PriceStatus.DISPLAY_CONFIRMED,
        "ld_only": PriceStatus.STRUCTURED_ONLY,
        "text_only": PriceStatus.DISPLAYED_ONLY,
        "label_wrong_ld_10x_low": PriceStatus.LABEL_CORRECTED,
        "label_wrong_ld_10x_high": PriceStatus.LABEL_CORRECTED,
        "unexplained_disagreement": PriceStatus.AMBIGUOUS,
    }.get(agreement, PriceStatus.ABSENT)
    if price is None:
        tr.price_source = "none"
        tr.price_reason = (ld_reason if agreement == "none"
                           else f"structured and displayed prices disagree "
                                f"({ld_price} vs {text_price})")
        if agreement == "none" and ld_reason == "negotiable or unpriced":
            # «توافقی» is the seller declining to name a price, which is a
            # different fact from the page failing to carry one.
            price_status = PriceStatus.NEGOTIABLE
    elif agreement == "agree":
        tr.price_source = "jsonld+text"
        tr.price_reason = None
    elif agreement == "ld_only":
        tr.price_source = "jsonld"
        tr.price_reason = None
    elif agreement == "text_only":
        tr.price_source = "text"
        tr.price_reason = ld_reason
    else:                                   # a mislabelled currency
        tr.price_source = "text"
        tr.price_reason = None

    # ---- mileage ----------------------------------------------------------
    mileage = ld_mileage_km(ld) if ld else None
    if mileage is not None:
        tr.mileage_source = "jsonld"
    elif body_from is not None:
        mileage = parse_mileage_km(lines[body_from])
        if mileage is not None:
            tr.mileage_source = "text"

    # ---- body condition: text only; JSON-LD does not carry it -------------
    # `itemCondition: UsedCondition` is true of every car on the site and
    # says nothing about paint, replacement or accident history. The field
    # CARO actually needs is «وضعیت بدنه», which lives in the spec table.
    body_field = _labelled(lines, "وضعیت بدنه")
    desc = _labelled(lines, "توضیحات") or ""
    if body_field:
        condition = extract_body_condition(body_field)
        tr.condition_source = "field"
    else:
        condition = extract_body_condition(desc)
        tr.condition_source = "description" if desc else "none"

    ld_color = ld.get("color") if isinstance(ld.get("color"), str) else ""
    ld_gear = (ld.get("vehicleTransmission")
               if isinstance(ld.get("vehicleTransmission"), str) else "")
    ld_fuel = ld.get("fuelType") if isinstance(ld.get("fuelType"), str) else ""

    year = (slug.get("year_jalali") or ld_year_jalali(ld)
            or parse_year_jalali(blob))
    # Judged here, at the point the year is known, and carried on the record.
    # Doing it in the report instead would leave the appraiser free to consume
    # 999,990 km as a fact — which is exactly how a plausibility check that
    # "exists" fails to protect anything.
    km_judgement = classify_mileage(mileage, year)

    offers = ld.get("offers") if isinstance(ld.get("offers"), dict) else {}

    # bama's schema.org `name` is the SITE's string, not the seller's — it is
    # «پراید،  151» on an ordinary listing and «حواله کوییک،  دنده ای S» on an
    # assignment. That is why the class is read from it and never from
    # `description`, which is the seller's. A page with no structured block
    # has no canonical name, and a class we cannot determine stays unknown.
    ld_name = ld.get("name") if isinstance(ld.get("name"), str) else ""
    # On a page with no structured block the rendered heading is the best
    # product name available, and it carries the same cue — the حواله page's
    # <h1> and its `name` were the identical string. Reading it keeps the
    # text-fallback path usable instead of making every such page
    # unclassifiable, and `product_class_source` records which of the two it
    # was, so the weaker evidence is visible rather than averaged in.
    #
    # `unknown` is reserved for a page with NO name at all. That is a record
    # whose class was never determined, which is not the same as a record
    # classified on weaker evidence.
    page_name = ld_name or " ".join(lines[:4])
    pclass, psource = classify_product(page_name,
                                       from_canonical=bool(ld_name))

    # Read BELOW the anchor, for the same reason every other text derivation
    # is: the navigation above the article is not this car. With no anchor
    # there is no article to restrict to, and the whole page is searched —
    # the two markers are specific enough that chrome cannot produce one, and
    # a false positive there costs a row rather than corrupting an estimate.
    article = " ".join(lines[body_from:] if body_from is not None else lines)
    pkind, pksource = classify_price_kind(article, has_price=price is not None)

    return CarListing(
        listing_id=(ld.get("identifier") or slug.get("listing_id")
                    or url.rsplit("-", 1)[-1]),
        url=url,
        title=str(ld.get("name") or " ".join(lines[:4])),
        description=desc or str(ld.get("description") or ""),
        asking_price_toman=price,
        make=slug.get("make"),
        model=slug.get("model"),
        trim=slug.get("trim"),
        # The slug is the identity of record — it is what comparables and
        # repost matching key on — so JSON-LD fills the year only when the
        # slug carried none, rather than competing with it.
        year_jalali=year,
        mileage_km=mileage,
        gearbox=(extract_gearbox(ld_gear)
                 or extract_gearbox(_labelled(lines, "گیربکس") or "")),
        fuel=extract_fuel(ld_fuel) or extract_fuel(blob),
        color=(extract_color(ld_color)
               or extract_color(_labelled(lines, "رنگ بدنه") or "")),
        body_condition=condition,
        # The trace is per-page and is discarded with the run; the record is
        # what reaches a snapshot. Both carry the same value so that where
        # the condition came from survives past the console.
        condition_source=tr.condition_source,
        document_issue=has_document_issue(desc),
        city=_labelled(lines, "موقعیت") or None,
        seller_raw=None,          # the masked phone is never read
        # Everything the reconciliation was based on, kept verbatim.
        price_raw=(str(offers.get("price"))
                   if offers.get("price") is not None else None),
        price_currency_raw=offers.get("priceCurrency") or None,
        price_displayed_toman=text_price,
        price_status=price_status.value,
        price_provenance=tr.price_source,
        mileage_status=km_judgement.status.value,
        mileage_note=km_judgement.reason,
        seller_type=detect_seller_type(lines),
        product_class=pclass,
        product_class_source=psource,
        price_kind=pkind,
        price_kind_source=pksource,
        # bama states where the listing lives, in the same block it states
        # the price and the odometer. Measured 2026-09-10: the `url` field
        # carries the full slug form, and the short `detail-<id>` form we
        # request resolves too — so neither is guessed and either can be
        # opened by a person checking a row.
        source_url=(ld.get("url") if isinstance(ld.get("url"), str) else None),
    )


# ---------------------------------------------------------------------------
# Adapter
# ---------------------------------------------------------------------------

def http_fetcher(policy: PolitenessPolicy | None = None):
    """Plain HTTP. Correct for the sitemap and for anything server-rendered.

    Driving a whole browser to download static XML wastes several seconds and
    a Chromium process per request. Playwright is for pages that need
    JavaScript, and nothing else.
    """
    p = policy or PolitenessPolicy()

    def fetch(url: str) -> tuple[int, str]:
        req = urllib.request.Request(url, headers={"User-Agent": p.user_agent,
                                                   "Accept-Language": "fa-IR"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            return e.code, ""
        except Exception:
            return 0, ""

    return fetch


class DiscoveryUnavailable(SourceBlocked):
    """Discovery failed, so we do not know what exists.

    Distinct from every other failure on purpose: an empty result here means
    "we could not look", never "there is nothing". Without the distinction a
    sitemap outage would flow downstream as a corpus of zero valid listings,
    and every count computed from it would be confidently wrong.
    """


def classify_detail_page(status: int | None, html: str) -> FetchStatus:
    """Three-way, because HTTP status alone is not enough.

        404 / explicit "gone" text  -> ABSENT
        200 + no listing markers    -> UNKNOWN  (challenge, redirect, partial)
        200 + listing markers       -> OK
        anything else               -> UNKNOWN

    The middle case is the one that matters. A soft-404 answers 200, and
    treating it as a successful fetch puts an empty car in the corpus;
    treating it as ABSENT invents a disappearance. Neither is acceptable, so
    it is recorded as what it is: we do not know.
    """
    base = classify_http(status)
    if base is FetchStatus.ABSENT:
        return FetchStatus.ABSENT
    if base is not FetchStatus.OK:
        return FetchStatus.UNKNOWN
    text = normalize(html)
    if any(normalize(m) in text for m in GONE_MARKERS):
        return FetchStatus.ABSENT
    if not any(normalize(m) in text for m in REQUIRED_MARKERS):
        return FetchStatus.UNKNOWN
    return FetchStatus.OK


@dataclass
class DiscoveryStats:
    """What discovery actually did. Printed by first_run.py.

    Coverage claims need these numbers: 50 listings all drawn from one brand
    page says nothing about the corpus, and without the per-category counts
    that bias is invisible.
    """
    sitemap_urls: int = 0
    categories_found: int = 0
    categories_tried: int = 0
    categories_ok: int = 0
    listings_per_category: dict = field(default_factory=dict)
    listing_urls_raw: int = 0
    listing_urls_unique: int = 0
    detail_status: dict = field(default_factory=dict)
    sample_seed: int | None = None
    category_budget: int = 0
    category_rule: str = "sitemap order (a prefix — i.e. the alphabet)"

    def report(self) -> str:
        L = ["DISCOVERY", "-" * 62,
             f"  sitemap urls          {self.sitemap_urls}",
             f"  category pages found  {self.categories_found}",
             f"  category selection    {self.category_rule}",
             f"  category budget       {self.category_budget}",
             f"  category pages tried  {self.categories_tried}"
             f"  (ok: {self.categories_ok})"]
        for cat, n in self.listings_per_category.items():
            L.append(f"      {cat.rsplit('/', 1)[-1]:<24}{n:>4} listings")
        L += [f"  listing urls          {self.listing_urls_raw} "
              f"({self.listing_urls_unique} unique)"]
        if self.detail_status:
            L.append("  detail fetch outcomes")
            for k, v in sorted(self.detail_status.items()):
                L.append(f"      {str(k):<24}{v:>4}")
        # The budget binding is not the same as the market being thin, and
        # run 6 could not tell the operator which it had hit.
        if (self.category_budget
                and self.categories_tried >= self.category_budget
                and self.categories_found > self.category_budget):
            L.append(f"  ⚠ discovery stopped because the category BUDGET ran "
                     f"out ({self.category_budget} of "
                     f"{self.categories_found} pages), not because the "
                     "listing target was met. Raise --categories.")
        if self.categories_ok == 1 and self.listing_urls_unique > 20:
            L.append("  ⚠ every listing came from ONE category page. This "
                     "corpus is one brand, not the market — widen before "
                     "drawing any conclusion from it.")
        return "\n".join(L)


@dataclass
class BamaAdapter:
    """Sitemap → category pages → listings, stopping when told to.

    `fetcher` is injected so every path is testable offline.
    """
    name: str = "bama"
    max_listings: int = 50
    max_categories: int = 5
    policy: PolitenessPolicy = field(default_factory=PolitenessPolicy)
    salt: str | None = None
    fetcher: Callable[[str], tuple[int, str]] | None = None
    parse_detail: Callable[[str, str], CarListing | None] = parse_detail_page
    sleeper: Callable[[float], None] = time.sleep
    sitemap_url: str = SITEMAP_CAR
    only_makes: tuple[str, ...] = ()
    # Which of the 1600+ category pages to draw, when `only_makes` names none.
    #
    # `cats[:max_categories]` took a prefix, and the sitemap is ordered, so a
    # prefix is the alphabet. Run 6 asked for 50 listings across the market
    # and got `audi`, `amg`, `arya` — 18 luxury EVs with a 15B toman ceiling.
    # Every rate that run measured describes those three pages. Nothing was
    # broken; the sample was decided by sort order, which is not a sampling
    # rule anyone would state out loud.
    #
    # A seed makes the draw uniform over the whole category space, stated in
    # advance, and reproducible: the same seed returns the same categories,
    # so a later run can be compared with this one rather than merely
    # resembling it. `None` keeps the prefix, because the existing tests
    # assert on a deterministic order and a silent change of sampling is
    # worse than an explicit one.
    sample_seed: int | None = None
    on_listing: Callable[[CarListing], None] | None = None
    stats: DiscoveryStats = field(default_factory=DiscoveryStats)
    traces: list = field(default_factory=list)

    def _get(self, url: str) -> tuple[int, str]:
        if self.fetcher is None:
            raise RuntimeError("BamaAdapter needs a fetcher. Refusing to guess.")
        try:
            return self.fetcher(url)
        except Exception:
            return 0, ""

    def discover_categories(self) -> list[str]:
        status, body = self._get(self.sitemap_url)
        if classify_http(status) is not FetchStatus.OK or not body:
            raise DiscoveryUnavailable(
                f"bama sitemap returned {status}; halting rather than "
                "falling back to crawling search pages. This means we could "
                "not look — not that bama has no listings.")
        urls = parse_sitemap(body)
        self.stats.sitemap_urls = len(urls)
        cats = [u for u in urls if is_category_url(u)]
        if self.only_makes:
            cats = [u for u in cats
                    if any(m in u.lower() for m in self.only_makes)]
        self.stats.categories_found = len(cats)
        if self.only_makes:
            self.stats.category_rule = (
                f"pinned to {len(self.only_makes)} make(s) by --makes")
        if self.sample_seed is not None and not self.only_makes:
            self.stats.category_rule = f"seeded draw, seed={self.sample_seed}"
            # Drawn, not sorted. A named make list is a deliberate
            # pre-registration and is left in the order it was written.
            cats = list(cats)
            random.Random(self.sample_seed).shuffle(cats)
            self.stats.sample_seed = self.sample_seed
        self.stats.category_budget = self.max_categories
        return cats[:self.max_categories]

    def discover_listings(self) -> list[str]:
        urls: list[str] = []
        for cat in self.discover_categories():
            self.stats.categories_tried += 1
            status, html = self._get(cat)
            if classify_http(status) is FetchStatus.OK and html:
                found = extract_listing_links(html)
                self.stats.categories_ok += 1
                self.stats.listings_per_category[cat] = len(found)
                urls.extend(found)
            else:
                self.stats.listings_per_category[cat] = 0
            self.sleeper(self.policy.sleep())
            if len(urls) >= self.max_listings:
                break
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        self.stats.listing_urls_raw = len(urls)
        self.stats.listing_urls_unique = len(out)
        return out[:self.max_listings]

    def fetch_all(self, on: date) -> Iterator[FetchOutcome]:
        consecutive = 0
        for url in self.discover_listings():
            status, html = self._get(url)
            fs = classify_detail_page(status, html)
            key = f"{status} -> {fs.value}"
            self.stats.detail_status[key] = self.stats.detail_status.get(key, 0) + 1

            if fs is FetchStatus.OK and html:
                consecutive = 0
                # The trace is per-page and kept even when the parse yields
                # nothing, because "20 pages fetched, 3 parsed" is a fact the
                # inventory must be able to state.
                tr = ParseTrace()
                try:
                    listing = self.parse_detail(url, html, trace=tr)
                except TypeError:            # a parser that takes no trace
                    listing = self.parse_detail(url, html)
                self.traces.append(tr)
                if listing is not None:
                    if self.on_listing:
                        self.on_listing(listing)
                    yield listing.to_fetch_outcome(self.name, self.salt)
            elif fs is FetchStatus.ABSENT:
                # A 404 on a url a category page just advertised is a real
                # absence: it was there moments ago and is gone now.
                yield FetchOutcome(
                    listing_id=f"{self.name}:{listing_id_from_url(url)}",
                    status=FetchStatus.ABSENT, http_status=status)
                consecutive = 0
            else:
                consecutive += 1
                yield FetchOutcome(
                    listing_id=f"{self.name}:{listing_id_from_url(url)}",
                    status=FetchStatus.UNKNOWN, http_status=status)
                if consecutive >= self.policy.max_consecutive_failures:
                    raise SourceBlocked(
                        f"bama stopped answering after {consecutive} "
                        "consecutive failures; halting")

            self.sleeper(self.policy.sleep())


def listing_id_from_url(url: str) -> str:
    m = re.search(r"/car/detail-([a-z0-9]+)", url)
    return m.group(1) if m else url.rsplit("/", 1)[-1]
