"""
Sheypoor's car list -> `CarListing`s, and the adapter that asks for it.

WHAT THE PAGE IS, as the owner's probe found it on 2026-10-29 (`/s/iran/car`,
600,924 bytes, a plain HTTP GET, no browser):

    · a Next.js page whose data stream holds the category tree and no listing,
      so the cards are the only source here. 26 links
      `a[href=/v/<percent-encoded slug>-<digits>.html]`, each with a
      `data-test-id`, in five grids. A card is an image block, an h2 (the
      seller's title), on some a badge «Ad تابلو شده», a figure followed by the
      toman icon (`data-test-id=icon-toman`) or «قیمت» «توافقی», and two
      `small`s: the place («قم», «بابل، بندارکلاآغوزین», «سراسر استان گلستان»)
      and the time («ساعاتی پیش»).
    · the next page is the page's own `rel=next`: `/s/iran/car?page_num=2`.
    · the cards give NO year and NO odometer. What they give is the title, the
      price a buyer is shown and the place. So a listing read from the list
      alone is not appraisal-eligible, and the funnel will say so: the listing
      page, which a probe has not read yet, is where those two are.

WHAT WAS NOT KNOWN, and is counted rather than assumed. Some cards carry a
40-px bordered image at the top right of the photo: on the owner's page every
one of them was titled «فروش سازمانی» or «فروش دولتی», so it may be a shop's
logo. It is counted, and `seller_type` stays `unknown`: D26 allows a type only
from a badge known to be one, and what this image is has not been read.

The title is the seller's own words, and everything read from it is recorded
as such: make and model by the table of thirteen, the condition by the prose
table (source `description`), the class (a حواله is an assignment), a year
only where the title states one, an odometer only next to its word.

WHAT IS NEVER READ: the photo, the bookmark, the time line (other than to
tell it from the place), and any seller field: there is none on a card, so
`seller_raw` stays None and no fingerprint is made.
"""

from __future__ import annotations

import html as _html
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote

from caro.ingest.divar_car import (
    CarListing, extract_body_condition, extract_color, extract_fuel,
    extract_gearbox, extract_make_model, extract_trim, has_document_issue,
    mileage_in_prose,
)
from caro.ingest.paging import NextLinkAdapter, url_shape
from caro.ingest.persian import (
    PROVINCES, digits_only, normalize, parse_year_jalali, province_from_city,
)
from caro.ingest.quality import (
    PriceStatus, Validity, classify_mileage, classify_price_kind,
    classify_price_value, classify_product,
)

SHEYPOOR_ORIGIN = "https://www.sheypoor.com"
CATEGORY_URL = SHEYPOOR_ORIGIN + "/s/{city}/car"

_ID_IN_HREF = re.compile(r"-(\d{5,12})\.html$")
_ID = re.compile(r"^\d{5,12}$")
# The time line of a card ends in one of these: «ساعاتی پیش», «دیروز».
_TIME = re.compile(r"(پیش|دیروز|امروز)$")
_PROVINCE_BY_NORM = {normalize(p): p for p in PROVINCES}
_STATEWIDE = re.compile(r"^(?:سراسر\s+)?استان\s+(.+)$")
_YEAR_STATED = re.compile(r"(?:مدل|model)\s*[:\-]?\s*(\d{4}|\d{2})(?!\d)", re.I)
_YEAR_FOUR = re.compile(r"(?<!\d)(1[34]\d{2})(?!\d)")


# ---------------------------------------------------------------------------
# The cards
# ---------------------------------------------------------------------------

@dataclass
class Card:
    href: str = ""                                    # the path, no host
    test_id: str = ""
    title: str = ""
    texts: list[str] = field(default_factory=list)    # every text but the title's
    smalls: list[str] = field(default_factory=list)
    price_text: str | None = None     # the text just before the toman icon
    corner_image: bool = False        # the image at the top right of the photo
    promoted: bool = False            # «تابلو شده»


class _CardReader(HTMLParser):
    """Collects every link to a listing page (`/v/…html`) and what is in it.

    By the path, the toman icon's test id and the tags (`h2`, `small`), not by
    the Tailwind classes, which say how a card looks. The one class read is
    the corner's (`absolute`, `top-1`, `right-1`), where the image is.
    """

    _VOID = frozenset({"img", "br", "hr", "input", "meta", "link", "source",
                       "area", "base", "col", "embed", "param", "track", "wbr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[Card] = []
        self.next_href: str | None = None
        self._card: Card | None = None
        self._stack: list[str] = []
        self._h2 = 0
        self._small = 0
        self._small_buf: list[str] = []
        self._corner = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "link" and self.next_href is None:
            rel = (a.get("rel") or "").lower().split()
            if "next" in rel and a.get("href"):
                self.next_href = a["href"]
        if self._card is None:
            if tag == "a":
                path = re.sub(r"^https?://[^/]+", "",
                              (a.get("href") or "").split("#")[0].split("?")[0])
                if path.startswith("/v/") and path.endswith(".html"):
                    self._card = Card(href=path, test_id=a.get("data-test-id") or "")
                    self._stack, self._h2, self._small, self._corner = [], 0, 0, 0
            return
        c = self._card
        if tag == "img" and self._corner:
            c.corner_image = True
        if tag in self._VOID:
            return
        self._stack.append(tag)
        cls = set((a.get("class") or "").split())
        if tag == "h2" and not self._h2:
            self._h2 = len(self._stack)
        elif tag == "small" and not self._small:
            self._small, self._small_buf = len(self._stack), []
        if not self._corner and {"absolute", "top-1", "right-1"} <= cls:
            self._corner = len(self._stack)
        if a.get("data-test-id") == "icon-toman":
            c.price_text = c.texts[-1] if c.texts else None

    def handle_data(self, data):
        if self._card is None:
            return
        t = re.sub(r"\s+", " ", data).strip()
        if not t:
            return
        c = self._card
        if self._h2:
            c.title = f"{c.title} {t}".strip()
            return
        c.texts.append(t)
        if self._small:
            self._small_buf.append(t)
        if normalize(t).endswith("تابلو شده"):
            c.promoted = True

    def _close_to(self, depth: int) -> None:
        if self._h2 and depth <= self._h2:
            self._h2 = 0
        if self._small and depth <= self._small:
            text = " ".join(self._small_buf).strip()
            if text:
                self._card.smalls.append(text)
            self._small, self._small_buf = 0, []
        if self._corner and depth <= self._corner:
            self._corner = 0

    def handle_endtag(self, tag):
        if self._card is None or tag in self._VOID:
            return
        if tag == "a" and "a" not in self._stack:
            self._close_to(0)
            self.cards.append(self._card)
            self._card = None
            return
        if tag not in self._stack:
            return
        while self._stack:
            self._close_to(len(self._stack))
            if self._stack.pop() == tag:
                break


def read_page(html: str) -> tuple[list[Card], str | None]:
    """(the cards, the page's rel=next href or None)."""
    if not html:
        return [], None
    r = _CardReader()
    try:
        r.feed(html)
        r.close()
    except Exception:             # a page that cannot be read has what was read
        pass
    return r.cards, r.next_href


def id_of(card: Card) -> tuple[str | None, str]:
    """(the listing's id, where it came from): the digits before `.html`, or
    the `data-test-id` where the link has none."""
    try:
        path = unquote(card.href)
    except Exception:
        path = card.href
    m = _ID_IN_HREF.search(path)
    if m:
        return m.group(1), "href"
    if _ID.match(card.test_id or ""):
        return card.test_id, "test id"
    return None, "none"


def _figure(text: str | None) -> int | None:
    """A text that is a figure and nothing else («۲۵۰٬۰۰۰٬۰۰۰»), as a number."""
    if not text:
        return None
    s = normalize(text)
    if not re.fullmatch(r"[\d٬،,\s]+", s):
        return None
    d = digits_only(s)
    return int(d) if d.isdigit() else None


def year_in_title(title: str) -> int | None:
    """A year the title STATES: «مدل ۹۵», «مدل ۱۳۹۸», «model 2018», or a
    four-digit 13xx/14xx. «پراید ۱۳۱» and «پیکان وانت ۱۵۰» state none."""
    s = normalize(title)
    m = _YEAR_STATED.search(s)
    if m:
        return parse_year_jalali(m.group(1))
    m = _YEAR_FOUR.search(s)
    return int(m.group(1)) if m else None


def place_of(card: Card) -> str | None:
    """The first `small` that is neither «قیمت» nor a time."""
    for s in card.smalls:
        n = normalize(s)
        if n and n != "قیمت" and not _TIME.search(n):
            return s.strip()
    return None


def province_of_place(place: str | None) -> tuple[str | None, str]:
    """(province, source): one of the thirteen capitals named as their
    province is (`city`), or «سراسر استان X» / «استان X» naming one of the 31
    (`stated`); else (None, `none`)."""
    if not place:
        return None, "none"
    p = province_from_city(place)
    if p:
        return p, "city"
    m = _STATEWIDE.match(normalize(place))
    if m and m.group(1).strip() in _PROVINCE_BY_NORM:
        return _PROVINCE_BY_NORM[m.group(1).strip()], "stated"
    return None, "none"


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------

ODD_KINDS = ("price below the floor",)
_ODD_CAP = 12


@dataclass
class SheypoorTrace:
    """What one page was, in counts. Every field is a count or a category."""
    cards: int = 0
    emitted: int = 0
    duplicates: int = 0
    next_shape: str = "(none)"
    skipped: Counter = field(default_factory=Counter)
    ids: Counter = field(default_factory=Counter)
    price: Counter = field(default_factory=Counter)
    year: Counter = field(default_factory=Counter)
    mileage: Counter = field(default_factory=Counter)
    province: Counter = field(default_factory=Counter)
    product: Counter = field(default_factory=Counter)
    marks: Counter = field(default_factory=Counter)
    odd: dict = field(default_factory=lambda: {k: [] for k in ODD_KINDS})
    prices: list = field(default_factory=list)


# ---------------------------------------------------------------------------
# One listing, one page, a run of them
# ---------------------------------------------------------------------------

def build(card: Card, listing_id: str, trace: SheypoorTrace) -> CarListing:
    title = card.title
    shown = _figure(card.price_text)
    negotiable = any("توافقی" in normalize(t) for t in card.texts)
    if shown is not None:
        price, status, prov, code = shown, PriceStatus.DISPLAYED_ONLY, "text", "card figure"
    elif negotiable:
        price, status, prov, code = None, PriceStatus.NEGOTIABLE, "none", "negotiable"
    elif card.price_text:
        price, status, prov, code = None, PriceStatus.AMBIGUOUS, "none", "not a figure"
    else:
        price, status, prov, code = None, PriceStatus.ABSENT, "none", "none"
    trace.price[code] += 1
    if price is not None:
        trace.prices.append(price)
        if not classify_price_value(price).usable:
            trace.odd["price below the floor"].append((price,))

    year = year_in_title(title)
    trace.year["title" if year else "none"] += 1
    km = mileage_in_prose(title)
    trace.mileage["title" if km is not None else "none"] += 1
    if km is None:
        m_status, m_reason = Validity.UNKNOWN, "not stated"
    else:
        j = classify_mileage(km, year)
        m_status, m_reason = j.status, j.reason

    place = place_of(card)
    province, p_source = province_of_place(place)
    trace.province[p_source] += 1
    for mark, on in (("corner image", card.corner_image),
                     ("تابلو شده", card.promoted)):
        if on:
            trace.marks[mark] += 1

    make, model = extract_make_model(title)
    condition = extract_body_condition(title)
    pclass, psource = classify_product(title, from_canonical=False)
    trace.product[pclass] += 1
    # Read from what the card says around the title, not from the title: a
    # «توافقی» the site prints is the site's, and in a title it is copy.
    kind, kind_src = classify_price_kind(" ".join(card.texts),
                                         has_price=price is not None)
    url = SHEYPOOR_ORIGIN + card.href
    return CarListing(
        listing_id=listing_id, url=url, title=title, description="",
        asking_price_toman=price, make=make, model=model,
        trim=extract_trim(title), year_jalali=year, mileage_km=km,
        gearbox=extract_gearbox(title), fuel=extract_fuel(title),
        color=extract_color(title), body_condition=condition,
        condition_source="description" if condition != "unknown" else "none",
        document_issue=has_document_issue(title), city=province,
        seller_raw=None, price_raw=card.price_text, price_currency_raw=None,
        price_displayed_toman=shown, price_status=status.value,
        price_provenance=prov, mileage_status=m_status.value,
        mileage_note=m_reason, product_class=pclass,
        product_class_source=psource, price_kind=kind,
        price_kind_source=kind_src, seller_type="unknown",
        province_source=p_source, location_raw=place, source_url=url,
    )


class SheypoorParser:
    """One instance per run. Remembers the ids it has returned, so a promoted
    card that a later page shows again is counted and not believed new.
    `next_url` is the page's own rel=next."""

    def __init__(self):
        self.seen: set[str] = set()
        self.traces: list[SheypoorTrace] = []
        self.listings: list[CarListing] = []
        self.next_url: str | None = None

    def __call__(self, html: str) -> list[CarListing]:
        tr = SheypoorTrace()
        self.traces.append(tr)
        cards, nxt = read_page(html)
        nxt = _html.unescape(nxt).strip() if nxt else None
        if nxt and nxt.startswith("/"):
            nxt = SHEYPOOR_ORIGIN + nxt
        self.next_url = nxt or None
        tr.next_shape = url_shape(self.next_url)
        tr.cards = len(cards)
        fresh: list[CarListing] = []
        page_ids: set[str] = set()
        for c in cards:
            lid, src = id_of(c)
            tr.ids[src] += 1
            if lid is None:
                tr.skipped["card without an id"] += 1
                continue
            if lid in page_ids:
                continue                  # the same card twice on one page
            page_ids.add(lid)
            if lid in self.seen:
                tr.duplicates += 1
                continue
            self.seen.add(lid)
            fresh.append(build(c, lid, tr))
        tr.emitted = len(fresh)
        self.listings.extend(fresh)
        return fresh


def parse_sheypoor(html: str, trace_into: list | None = None) -> list[CarListing]:
    p = SheypoorParser()
    out = p(html)
    if trace_into is not None:
        trace_into.extend(p.traces)
    return out


@dataclass
class SheypoorAdapter(NextLinkAdapter):
    """Collects Sheypoor's public car list. No login, no contact, no
    rotation; the next page is the page's own rel=next, asked for only where
    robots.txt allows it (caro/ingest/paging.py)."""
    origin: str = SHEYPOOR_ORIGIN
    start_url: str = ""
    name: str = "sheypoor"
    city: str = "iran"

    def __post_init__(self):
        if not self.start_url:
            self.start_url = CATEGORY_URL.format(city=self.city)
        super().__post_init__()


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _b(v: int) -> str:
    return f"{v / 1e9:.2f}B"


def report(traces: list[SheypoorTrace]) -> list[str]:
    """Counts and categories only: no title, no id, no listing's price except
    the smallest, the middle and the largest."""
    if not traces:
        return []
    L = ["", "SHEYPOOR PAGE READ  (what each page was; counts and categories only)",
         "-" * 62,
         f"  pages {len(traces)}   listings {sum(t.emitted for t in traces)}"
         f"   cards {sum(t.cards for t in traces)}"]
    for label, attr in (("id from", "ids"), ("price", "price"), ("year", "year"),
                        ("mileage", "mileage"), ("province", "province"),
                        ("product", "product"), ("marks", "marks")):
        c = Counter()
        for t in traces:
            c.update(getattr(t, attr))
        if c:
            L.append(f"  {label:<14}" + "  ".join(f"{k}:{v}" for k, v in c.most_common()))
    prices = sorted(p for t in traces for p in t.prices)
    if prices:
        L.append(f"  price shown    min {_b(prices[0])}   median "
                 f"{_b(prices[len(prices) // 2])}   max {_b(prices[-1])}   (toman)")
    L.append(f"  next page      {traces[-1].next_shape}")
    dup = sum(t.duplicates for t in traces)
    if dup:
        L.append(f"  duplicates     {dup}")
    sk = Counter()
    for t in traces:
        sk.update(t.skipped)
    for k, v in sk.most_common():
        L.append(f"  skipped: {k}: {v}")
    odd = [x for t in traces for x in t.odd["price below the floor"]]
    if odd:
        L += ["", "  odd cases (numbers only):"]
        for row in odd[:_ODD_CAP]:
            L.append(f"    {'price below the floor':<24}{row[0]:,}")
        if len(odd) > _ODD_CAP:
            L.append(f"    {'price below the floor':<24}… and {len(odd) - _ODD_CAP} more")
    years = sum(t.year["title"] for t in traces)
    n = sum(t.emitted for t in traces)
    if n and years < n:
        L.append(f"  ⚠ the cards give no year and no odometer: {n - years} of {n} have no "
                 "year (a title stated the rest). The listing page is where both "
                 "are, and it has not been probed.")
    corner = sum(t.marks["corner image"] for t in traces)
    if corner:
        L.append(f"  ⚠ {corner} card(s) carry an image at the top right of the photo; "
                 "seller_type stays unknown until what it is has been read.")
    return L
