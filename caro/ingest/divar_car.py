"""
Divar car-listing adapter.

Adapted from the Divar collection approach in SorinFlow
(Tecso-Dev/SorinFlow-DaTA-mAmager, MIT) — that project scrapes property
listings; this one scrapes cars. Two things carried over, and three
deliberately did not.

CARRIED OVER
    · Playwright over the public listing pages, because Divar renders
      client-side and a plain HTTP fetch returns an empty shell.
    · Persian numeral, separator and amount-word normalisation, which is the
      genuinely reusable half of any Iranian marketplace scraper.
    · Heavy-tailed jittered delays between requests.

DELIBERATELY LEFT BEHIND
    · **Contact reveal.** The source project reveals and stores advertiser
      phone numbers. CARO's ingest contract says no adapter may emit a
      personal identifier, and `seller_fingerprint` is a salted hash for
      deduplication only. Porting contact extraction would make that
      contract a lie, and a corpus of phone numbers is a liability in a
      public repository whatever the licence says.
    · **Account rotation and session replay.** The source rotates logged-in
      Divar accounts to spread reveal budgets and avoid blocking. That is
      evasion, and `caro/ingest/base.py` states that CARO builds none: if a
      source blocks us, we stop and record it. Rotating accounts to keep
      going is precisely the behaviour that rule forbids.
    · **OTP handling.** Follows from the above — nothing here authenticates,
      so nothing here needs to solve a login challenge.

The cost of leaving those behind is real: no contact details, lower ceiling
on volume, and we stop when Divar says stop. That is the correct trade for a
system whose entire pitch is that it does not overclaim.

FIELD MAPPING
Property fields do not transfer at all. Area, rooms, floor and rent/deposit
are replaced by make, model, trim, year, mileage, gearbox, fuel and — the
field that actually decides a used car's value — body condition, which on
Divar lives in free text rather than in any structured field.
"""

from __future__ import annotations

import random
import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterable, Iterator

from caro.ingest.base import salted_fingerprint
from caro.ingest.persian import (
    normalize, parse_mileage_km, parse_price, parse_year_jalali,
)
from caro.ingest.quality import classify_price_kind, classify_product
from caro.tracking import FetchOutcome, FetchStatus, classify_http

# Divar's car categories. Kept as data so a new one is a line, not a patch.
CATEGORIES = {
    "light": "https://divar.ir/s/{city}/light",           # سواری
    "car": "https://divar.ir/s/{city}/car",
}

USER_AGENT = ("CARO-research/0.3 (used-car price research; "
              "contact: sahand.mosanejad4488@gmail.com)")

# Politeness. These are floors, not targets.
DELAY_MIN_S = 2.0
DELAY_MAX_S = 5.0
MAX_CONSECUTIVE_FAILURES = 3


# ---------------------------------------------------------------------------
# Car field extraction — the domain half, which shares nothing with property
# ---------------------------------------------------------------------------

MAKE_MODEL: dict[str, tuple[str, ...]] = {
    ("Peugeot", "206"): ("پژو 206", "206", "پژو206"),
    ("Peugeot", "207"): ("پژو 207", "207i", "207"),
    ("Peugeot", "405"): ("پژو 405", "405"),
    ("Peugeot", "Pars"): ("پژو پارس", "پارس"),
    ("Saipa", "Pride"): ("پراید", "سایپا 131", "131", "111", "132"),
    ("Saipa", "Tiba"): ("تیبا",),
    ("Saipa", "Quik"): ("کوییک", "کوئیک"),
    ("Saipa", "Saina"): ("ساینا",),
    ("Saipa", "Shahin"): ("شاهین",),
    ("IKCO", "Dena"): ("دنا",),
    ("IKCO", "Runna"): ("رانا",),
    ("IKCO", "Samand"): ("سمند",),
    ("IKCO", "Tara"): ("تارا",),
}

TRIM_CUES = ("تیپ 2", "تیپ 3", "تیپ 5", "تیپ 6", "SD", "ELX", "LX", "TU5",
             "XU7", "پانوراما", "پلاس", "plus", "اتوماتیک", "دنده ای")

GEARBOX = {"automatic": ("اتوماتیک", "اتومات", "گیربکس اتومات"),
           "manual": ("دنده ای", "دنده‌ای", "معمولی", "مکانیکی")}

FUEL = {"dual": ("دوگانه سوز", "دوگانه", "cng", "گازسوز"),
        "hybrid": ("هیبرید", "هیبریدی"),
        "ev": ("برقی", "الکتریکی"),
        "petrol": ("بنزینی", "بنزین")}

COLORS = ("سفید", "مشکی", "نقره ای", "خاکستری", "نوک مدادی", "آبی", "قرمز",
          "سبز", "بژ", "قهوه ای", "نقرآبی", "زرد", "بادمجانی", "سربی")

# Body condition. This is the field that decides a used car's value and the
# one no marketplace filter exposes, because it lives in prose. Ordered most
# to least severe — the first match wins, so a listing that says both
# «تصادفی» and «بدون رنگ» is classified by the worse claim.
BODY_CONDITION: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("accident", ("تصادفی", "چپ کرده", "شاسی خورده", "شاسی تعویض",
                  "سگدست", "اتاق تعویض")),
    ("replaced_part", ("تعویض شده", "تعویضی", "درب تعویض", "گلگیر تعویض",
                       "کاپوت تعویض", "صندوق تعویض")),
    ("multi_paint", ("دور رنگ", "دوررنگ", "کامل رنگ", "تمام رنگ",
                     "چند لکه رنگ", "چندلکه رنگ")),
    ("minor_paint", ("لکه رنگ", "خط و خش", "خط وخش", "صافکاری",
                     "در حد خط و خش", "رودری رنگ")),
    ("intact", ("بدون رنگ", "بی رنگ", "فول بدون رنگ", "بدون خط و خش",
                "سالم و بدون رنگ")),
)

DOC_ISSUE_CUES = ("در گرو", "وکالتی", "سند در رهن", "سند نداره", "کارخانه ای")


def extract_make_model(text: str) -> tuple[str | None, str | None]:
    s = normalize(text)
    for (make, model), aliases in MAKE_MODEL.items():
        if any(normalize(a) in s for a in aliases):
            return make, model
    return None, None


def extract_trim(text: str) -> str | None:
    s = normalize(text)
    hits = [t for t in TRIM_CUES if normalize(t) in s]
    return " ".join(hits[:2]) if hits else None


def _first_match(text: str, table: dict[str, tuple[str, ...]]) -> str | None:
    s = normalize(text)
    for key, cues in table.items():
        if any(normalize(c) in s for c in cues):
            return key
    return None


def extract_gearbox(text: str) -> str | None:
    return _first_match(text, GEARBOX)


def extract_fuel(text: str) -> str | None:
    return _first_match(text, FUEL)


def extract_color(text: str) -> str | None:
    s = normalize(text)
    for c in COLORS:
        if normalize(c) in s:
            return c
    return None


def extract_body_condition(text: str) -> str:
    """Severity-ordered, so the worst disclosed claim wins.

    A listing whose title says «بدون رنگ» and whose body says «گلگیر تعویض»
    is a replaced-part car. Taking the title at face value is exactly the
    mistake a filter makes and a buyer regrets.
    """
    s = normalize(text)
    for label, cues in BODY_CONDITION:
        if any(normalize(c) in s for c in cues):
            return label
    return "unknown"


def has_document_issue(text: str) -> bool | None:
    s = normalize(text)
    if any(normalize(c) in s for c in DOC_ISSUE_CUES):
        return True
    if re.search(r"(سند آزاد|سند تک برگ|سند دست اول)", s):
        return False
    return None


@dataclass
class CarListing:
    """One parsed Divar car listing. Deliberately close to `FetchOutcome`."""
    listing_id: str
    url: str
    title: str
    description: str
    asking_price_toman: int | None
    make: str | None
    model: str | None
    trim: str | None
    year_jalali: int | None
    mileage_km: int | None
    gearbox: str | None
    fuel: str | None
    color: str | None
    body_condition: str
    document_issue: bool | None
    city: str | None
    seller_raw: str | None = None      # hashed on the way out, never stored
    image_urls: tuple[str, ...] = ()

    # ---- provenance, so every derived number stays auditable --------------
    # `asking_price_toman` is a *conclusion*: it may have been corrected
    # against the price shown to buyers when the source's currency label
    # disagreed (D20). Keeping the inputs means the conclusion can be
    # re-derived, disputed, or replayed after the rule changes — without
    # them, a corrected price is indistinguishable from a raw one.
    price_raw: str | None = None            # verbatim from the source
    price_currency_raw: str | None = None   # what the source *claimed*
    price_displayed_toman: int | None = None  # what the buyer actually sees
    price_status: str = "absent"            # quality.PriceStatus
    price_provenance: str = "none"          # which path produced the value

    # Present-but-false is a different state from absent, and neither is the
    # same as usable. See caro.ingest.quality.
    mileage_status: str = "unknown"         # quality.Validity
    mileage_note: str | None = None

    # Where `body_condition` came from: a spec row the page publishes, the
    # seller's prose, or nowhere. It lived only on the per-page ParseTrace,
    # which is printed and discarded — so a value extracted from a
    # description could not be told apart downstream from one the site
    # actually stated. Promotion labels provenance, and a label it has to
    # guess is a label that eventually says "field" about a guess.
    condition_source: str = "none"          # field | description | none

    # What this record IS. A حواله — an assignment, a claim on a car not yet
    # built — carries a year, a model and a price, and is not a used car at
    # any of them. `unknown` is a third state and never decays to `vehicle`:
    # see quality.classify_product and the gate in quality.eligibility.
    product_class: str = "unknown"          # vehicle | assignment | unknown
    product_class_source: str = "none"      # canonical_name | listing_title | none

    # The canonical address the SOURCE publishes, when it publishes one.
    # `url` above is the address that was requested; they are the same page
    # and only the first is the source's own statement of where it lives.
    source_url: str | None = None

    # What the number MEANS, as opposed to whether it was extracted right.
    # A financing total can be display-confirmed and cross-checked and still
    # not be what anyone is asking for the car. See quality.classify_price_kind.
    price_kind: str = "absent"              # cash | negotiable | financing_total | absent
    price_kind_source: str = "none"

    # dealer | private | unknown — inferred ONLY from a dealership block the
    # page publishes about itself (a trade badge, a showroom address). Never
    # from a phone number, which CARO does not read. It is a coarse proxy for
    # sample independence: thirty listings from one dealer are not thirty
    # observations of a market.
    seller_type: str = "unknown"

    def to_fetch_outcome(self, source: str = "divar",
                         salt: str | None = None) -> FetchOutcome:
        return FetchOutcome(
            listing_id=f"{source}:{self.listing_id}",
            status=FetchStatus.OK,
            http_status=200,
            asking_price_toman=self.asking_price_toman,
            make=self.make, model=self.model, trim=self.trim,
            year_jalali=self.year_jalali, color=self.color,
            province=self.city, mileage_km=self.mileage_km,
            # Carried because `listing_from_record` reads all three off a
            # published row and nothing could ever supply them. See the block
            # on FetchOutcome for how that was found and what it cost.
            gearbox=self.gearbox, fuel=self.fuel,
            price_currency_raw=self.price_currency_raw,
            # Both halves, or neither. A condition without its provenance is
            # a value promotion has to label by guessing, and it would guess
            # "field" — passing a phrase mined out of ad copy off as
            # something the source stated.
            body_condition=self.body_condition,
            condition_source=self.condition_source,
            document_issue=self.document_issue,
            seller_type=self.seller_type,
            product_class=self.product_class,
            product_class_source=self.product_class_source,
            price_kind=self.price_kind,
            price_kind_source=self.price_kind_source,
            source_url=self.source_url or self.url or None,
            # Whatever eligibility reads must cross. Not the whole provenance
            # set — `price_provenance` and `mileage_note` stay behind because
            # no gate depends on them — but these two decide admission and a
            # gate that cannot see them refuses everything.
            price_status=self.price_status,
            mileage_status=self.mileage_status,
            # The raw seller value dies here. Only the salted hash continues.
            seller_fingerprint=(salted_fingerprint(self.seller_raw, salt)
                                if self.seller_raw else None),
        )


def parse_listing(listing_id: str, url: str, title: str, description: str,
                  *, price_text: str = "", mileage_text: str = "",
                  year_text: str = "", city: str | None = None,
                  seller_raw: str | None = None,
                  image_urls: Iterable[str] = ()) -> CarListing:
    """Structured fields first, then free text — never the other way round.

    Divar's structured fields are cheap and usually right; the description is
    where the condition lives. Both are searched for make/model because
    sellers frequently put the trim only in the title.
    """
    blob = f"{title} {description}"
    make, model = extract_make_model(blob)
    # Divar publishes no «وضعیت بدنه» spec row, so there is one path here and
    # it is the prose. Saying "description" when nothing was found would
    # claim evidence that does not exist, so an empty result has no source.
    condition = extract_body_condition(blob)
    # Divar publishes no canonical product name; the title is the seller's.
    # Read anyway, and the weaker provenance is recorded rather than hidden.
    pclass, psource = classify_product(title, from_canonical=False)
    price = parse_price(price_text) or parse_price(blob)
    pkind, pksource = classify_price_kind(blob, has_price=price is not None)
    return CarListing(
        listing_id=listing_id, url=url, title=title, description=description,
        asking_price_toman=price,
        make=make, model=model, trim=extract_trim(blob),
        year_jalali=parse_year_jalali(year_text) or parse_year_jalali(title),
        mileage_km=(parse_mileage_km(mileage_text)
                    if mileage_text else parse_mileage_km(blob)),
        gearbox=extract_gearbox(blob), fuel=extract_fuel(blob),
        color=extract_color(blob),
        body_condition=condition,
        condition_source="description" if condition != "unknown" else "none",
        product_class=pclass, product_class_source=psource,
        price_kind=pkind, price_kind_source=pksource,
        document_issue=has_document_issue(blob),
        city=city, seller_raw=seller_raw, image_urls=tuple(image_urls),
    )


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

@dataclass
class PolitenessPolicy:
    """Delays and stop conditions, stated rather than tuned in secret.

    Heavy-tailed by design: a fixed sleep is a fingerprint, and a source that
    can identify a bot by its metronome is entitled to block it. This is
    about being a well-behaved client, not about being hard to detect — the
    difference matters, and the stop-on-failure rule below is what keeps it
    honest.
    """
    delay_min_s: float = DELAY_MIN_S
    delay_max_s: float = DELAY_MAX_S
    max_consecutive_failures: int = MAX_CONSECUTIVE_FAILURES
    user_agent: str = USER_AGENT

    def sleep(self, rng: random.Random | None = None) -> float:
        r = rng or random
        d = r.uniform(self.delay_min_s, self.delay_max_s)
        if r.random() < 0.15:                    # occasional longer pause
            d *= r.uniform(1.5, 3.0)
        return d


class SourceBlocked(RuntimeError):
    """Raised when the source stops answering. We stop too."""


@dataclass
class DivarCarAdapter:
    """Collects public car listings. No login, no contact reveal, no rotation.

    `page_fetcher` is injected so the adapter is testable without a browser
    and without the network: pass a callable returning (status_code, html).
    The Playwright implementation lives in `playwright_fetcher` and is only
    imported when actually used.
    """
    city: str = "tehran"
    category: str = "light"
    max_pages: int = 5
    name: str = "divar"
    policy: PolitenessPolicy = field(default_factory=PolitenessPolicy)
    salt: str | None = None
    page_fetcher: Callable[[str], tuple[int, str]] | None = None
    parse_page: Callable[[str], list[CarListing]] | None = None
    sleeper: Callable[[float], None] = time.sleep

    def search_url(self, page: int = 1) -> str:
        base = CATEGORIES[self.category].format(city=self.city)
        url = base if page <= 1 else f"{base}?page={page}"
        assert_allowed(url)
        return url

    def fetch_all(self, on: date) -> Iterator[FetchOutcome]:
        if self.page_fetcher is None or self.parse_page is None:
            raise RuntimeError(
                "DivarCarAdapter needs a page_fetcher and parse_page. Use "
                "playwright_fetcher() for live collection, or inject fixtures "
                "in tests. Refusing to guess.")

        consecutive = 0
        for page in range(1, self.max_pages + 1):
            url = self.search_url(page)          # raises on a robots violation
            try:
                status, html = self.page_fetcher(url)
            except Exception:
                status, html = None, ""

            fs = classify_http(status)
            if fs is FetchStatus.OK and html:
                consecutive = 0
                for listing in self.parse_page(html):
                    yield listing.to_fetch_outcome(self.name, self.salt)
            else:
                consecutive += 1
                # An unresolved page is ignorance about that page, not
                # absence of its listings. Emitting ABSENT here would
                # fabricate disappearances downstream.
                yield FetchOutcome(
                    listing_id=f"__page__:{self.name}:{page}",
                    status=FetchStatus.UNKNOWN, http_status=status)
                if consecutive >= self.policy.max_consecutive_failures:
                    # We stop. We do not rotate, retry harder, or change
                    # identity. A blocked source is a documented gap in
                    # coverage, not a puzzle to solve.
                    raise SourceBlocked(
                        f"{self.name} stopped answering after {consecutive} "
                        f"consecutive failures at page {page}; halting")

            if page < self.max_pages:
                self.sleeper(self.policy.sleep())


def playwright_fetcher(policy: PolitenessPolicy | None = None):
    """Live fetcher. Imported lazily so the package works without Playwright.

    Divar renders client-side, so a plain HTTP GET returns a shell with no
    listings — this is the one place a real browser is required rather than
    merely convenient.
    """
    p = policy or PolitenessPolicy()

    def fetch(url: str) -> tuple[int, str]:
        from playwright.sync_api import sync_playwright     # noqa: PLC0415
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            try:
                ctx = browser.new_context(user_agent=p.user_agent,
                                          locale="fa-IR")
                page = ctx.new_page()
                resp = page.goto(url, wait_until="domcontentloaded",
                                 timeout=30_000)
                page.wait_for_timeout(1500)
                return (resp.status if resp else 0), page.content()
            finally:
                browser.close()

    return fetch


# ---------------------------------------------------------------------------
# robots.txt compliance, verified rather than assumed
#
# Fetched from https://divar.ir/robots.txt on 2026-09-07:
#
#     User-agent: *
#     Disallow: /my-divar/*
#     Disallow: /new
#     Disallow: /s/*/*?*q=*
#     Disallow: /adminbot
#
# Two things follow, and the second is the one that would have been easy to
# get wrong:
#
#   · Category browsing (/s/{city}/light) is ALLOWED, as are individual
#     listing pages (/v/...). That is exactly the surface this adapter uses.
#   · Free-text SEARCH urls are DISALLOWED. Any url carrying `q=` is off
#     limits, so "just search for پژو 206" is not available to us — we browse
#     categories and filter locally instead.
#
# No Crawl-delay is published, which is not permission to go fast. The
# politeness floor in PolitenessPolicy stands on its own.
# ---------------------------------------------------------------------------

DIVAR_ROBOTS_CHECKED = "2026-09-07"
DIVAR_DISALLOWED = ("/my-divar/", "/new", "/adminbot")


class RobotsViolation(RuntimeError):
    """Raised before a request that robots.txt forbids."""


def assert_allowed(url: str) -> None:
    """Refuse a disallowed url at the call site, not in a code review.

    A rule that lives only in a comment gets violated the first time someone
    adds a feature. This one raises.
    """
    u = url.split("#", 1)[0]
    path = re.sub(r"^https?://[^/]+", "", u)
    if re.search(r"[?&]q=", path):
        raise RobotsViolation(
            f"divar robots.txt disallows search urls (/s/*/*?*q=*): {url}. "
            "Browse the category and filter locally instead.")
    for bad in DIVAR_DISALLOWED:
        if path.startswith(bad):
            raise RobotsViolation(f"divar robots.txt disallows {bad}: {url}")
