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
logo. It is counted, and read as a shop's badge: D26 allows a type only from
a badge known to be one, and the owner ruled on 2026-10-30 that this is one,
so a card that carries it is a dealer's (`build`). Every other card's seller
stays `unknown`.

The title is the seller's own words, and everything read from it is recorded
as such: make and model by the table of thirteen, the condition by the prose
table (source `description`), the class (a حواله is an assignment), a year
only where the title states one, an odometer only next to its word.

THE LISTING PAGE, as the owner's probe of two found it (2026-10-29): one
`application/ld+json` script holds an object whose `mainEntity` is the car --
`mileageFromOdometer` with a unit code, `vehicleModelDate`, `vehicleTransmission`,
`knownVehicleDamages`, `color`, `vehicleEngine.fuelType`, `bodyType`, `category`,
`brand.name`, and `offers` with `priceCurrency`, `Price` (a capital P) and `sku`, the
listing's id. The page also carries six cards of other listings, which are not
read. A listing page merges into the listing its card made in the same run: the
card's place and the price it showed stay, and the price the page states is
checked against it (D20), as bama's and Divar's are. Which currency code and
which unit code the pages use, and what the Persian values say, were not known
when this was written; they are counted (`report`).

WHAT IS NEVER READ: the photo, the bookmark, the time line (other than to
tell it from the place), and any seller field: there is none on a card or in
the listing page's entity, so `seller_raw` stays None and no fingerprint is
made. The description is read for what the prose table finds in it and is
not kept beyond the listing object.
"""

from __future__ import annotations

import html as _html
import re
from collections import Counter
from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import unquote

from caro.ingest.bama import (
    jsonld_blocks, ld_mileage_km, ld_year_jalali, reconcile_price,
)
from caro.ingest.divar_car import (
    BODY_CONDITION, CarListing, extract_body_condition, extract_color,
    extract_fuel, extract_gearbox, extract_make_model, extract_trim,
    has_document_issue, mileage_in_prose,
)
from caro.ingest.paging import NextLinkAdapter, url_shape
from caro.tracking import FetchStatus, classify_http
from caro.ingest.persian import (
    PROVINCES, digits_only, normalize, parse_year_jalali, province_from_city,
)
from caro.ingest.quality import (
    PriceStatus, Validity, classify_mileage, classify_price_kind,
    classify_price_value, classify_product,
)

SHEYPOOR_ORIGIN = "https://www.sheypoor.com"
CATEGORY_URL = SHEYPOOR_ORIGIN + "/s/{city}/car"

# The currency codes bama's reader knows, and nothing more: a code not here
# gives the listing page's price no value, and the report names the code.
TO_TOMAN = {"IRR": 0.1, "IRT": 1.0, "TOMAN": 1.0, "IRT-TOMAN": 1.0}
# The keys that make a JSON-LD object a car's, two of them at least.
_VEHICLE_KEYS = ("mileageFromOdometer", "vehicleModelDate", "vehicleTransmission",
                 "knownVehicleDamages", "vehicleEngine")
# What a listing page's entity holds that is a category, and is counted.
ENUM_KEYS = ("priceCurrency", "unitCode", "vehicleTransmission",
             "knownVehicleDamages", "bodyType", "category", "fuelType",
             "itemCondition", "brand")
_SEVERITY = tuple(label for label, _ in BODY_CONDITION)

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
        if (tag in ("link", "a") and self._card is None
                and self.next_href is None):
            rel = (a.get("rel") or "").lower().split()
            href = a.get("href") or ""
            if "next" in rel and href and "/v/" not in href:
                self.next_href = href
                return
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
    # A listing page (kind «listing»): how its id, its price and its fields
    # read, and the values of its entity's categories.
    kind: str = "list"
    merged: Counter = field(default_factory=Counter)
    id_check: Counter = field(default_factory=Counter)
    price_check: Counter = field(default_factory=Counter)
    price_key: Counter = field(default_factory=Counter)
    enums: dict = field(default_factory=lambda: {k: Counter() for k in ENUM_KEYS})
    refused: Counter = field(default_factory=Counter)


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
        # The owner's rule (2026-10-30): the image
        # at the top right of the photo is a shop's badge (on the owner's
        # page every card with one was titled «فروش سازمانی» or «فروش دولتی»).
        price_kind_source=kind_src,
        seller_type="dealer" if card.corner_image else "unknown",
        province_source=p_source, location_raw=place, source_url=url,
    )


# ---------------------------------------------------------------------------
# A listing page
# ---------------------------------------------------------------------------

def vehicle_entity(html: str) -> dict | None:
    """The JSON-LD object that describes the car: at the top level, under
    `mainEntity`, or in a `@graph`; None on a page that has none."""
    def is_vehicle(c) -> bool:
        return isinstance(c, dict) and sum(k in c for k in _VEHICLE_KEYS) >= 2

    for node in jsonld_blocks(html):
        if not isinstance(node, dict):
            continue
        cands = [node.get("mainEntity"), node] + list(node.get("@graph") or [])
        for c in cands:
            if is_vehicle(c):
                return c
    return None


def _schema_term(v):
    if isinstance(v, str):
        m = re.fullmatch(r"https?://schema\.org/([A-Za-z]{1,40})", v.strip())
        if m:
            return m.group(1)
    return v


def _categorical(v) -> str | None:
    """A value that may be counted: at most 40 characters, no «@», at most
    four digits (divar_page's guard)."""
    if not isinstance(v, str):
        return None
    v = re.sub(r"\s+", " ", v).strip()
    if not v or len(v) > 40 or "@" in v or sum(c.isdigit() for c in v) > 4:
        return None
    return v


def _offers(entity: dict) -> dict:
    o = entity.get("offers")
    if isinstance(o, list):
        o = o[0] if o else None
    return o if isinstance(o, dict) else {}


def _num(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)) and v > 0:
        return int(v)
    if isinstance(v, str):
        d = digits_only(v)
        return int(d) if d.isdigit() and int(d) > 0 else None
    return None


def _text(v) -> str:
    if isinstance(v, dict):
        v = v.get("name") or v.get("fuelType") or ""
    return re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else ""


def _count_enums(entity: dict, trace: SheypoorTrace) -> None:
    mil = entity.get("mileageFromOdometer")
    eng = entity.get("vehicleEngine")
    seen = {"priceCurrency": _offers(entity).get("priceCurrency"),
            "unitCode": mil.get("unitCode") if isinstance(mil, dict) else None,
            "vehicleTransmission": entity.get("vehicleTransmission"),
            "knownVehicleDamages": entity.get("knownVehicleDamages"),
            "bodyType": entity.get("bodyType"),
            "category": entity.get("category"),
            "fuelType": eng.get("fuelType") if isinstance(eng, dict) else None,
            "itemCondition": _schema_term(entity.get("itemCondition")),
            "brand": _text(entity.get("brand")) or None}
    for key, v in seen.items():
        c = _categorical(v)
        if c is None:
            trace.refused[key] += 1
        elif c in trace.enums[key] or len(trace.enums[key]) < 20:
            trace.enums[key][c] += 1
        else:
            trace.enums[key]["(other)"] += 1


def _worse(field_c: str, prose_c: str) -> tuple[str, str]:
    """The condition the site's field gives against the prose's: the worse
    claim wins, a tie goes to the field (divar_page's rule)."""
    f = None if field_c == "unknown" else field_c
    p = None if prose_c == "unknown" else prose_c
    if f and p:
        return (p, "description") if _SEVERITY.index(p) < _SEVERITY.index(f) else (f, "field")
    if f:
        return f, "field"
    if p:
        return p, "description"
    return "unknown", "none"


_PRICE_STATUS = {
    "agree": PriceStatus.DISPLAY_CONFIRMED, "ld_only": PriceStatus.STRUCTURED_ONLY,
    "text_only": PriceStatus.DISPLAYED_ONLY,
    "label_wrong_ld_10x_low": PriceStatus.LABEL_CORRECTED,
    "label_wrong_ld_10x_high": PriceStatus.LABEL_CORRECTED,
    "unexplained_disagreement": PriceStatus.AMBIGUOUS,
}


def build_from_page(entity: dict, lid: str, base: CarListing | None,
                    trace: SheypoorTrace) -> CarListing:
    """The listing a listing page states, merged into the one its card made
    (`base`, None when the page is read alone)."""
    _count_enums(entity, trace)
    offers = _offers(entity)
    key = "price" if "price" in offers else "Price" if "Price" in offers else "none"
    trace.price_key[key] += 1
    raw = offers.get("price", offers.get("Price"))
    cur = str(offers.get("priceCurrency") or "").upper().strip()
    factor = TO_TOMAN.get(cur)
    stated = _num(raw)
    ld_toman = int(round(stated * factor)) if stated and factor else None
    if stated and factor is None:
        trace.price_check[f"unrecognised currency {cur or '(none)'}"] += 1
    shown = base.price_displayed_toman if base else None
    price, code = reconcile_price(ld_toman, shown)
    status = _PRICE_STATUS.get(code)
    if status is None:
        negotiable = bool(base and base.price_status == PriceStatus.NEGOTIABLE.value)
        status = PriceStatus.NEGOTIABLE if negotiable else PriceStatus.ABSENT
        code = "negotiable" if negotiable else "none"
    trace.price_check[code] += 1
    prov = {"agree": "jsonld+text", "ld_only": "jsonld",
            "text_only": "text"}.get(code, "text" if price is not None else "none")
    # A page merged into its card adds no price to the report's: the card's
    # figure is counted already, and the run's listings are counted once.
    if price is not None and base is None:
        trace.prices.append(price)
        if not classify_price_value(price).usable:
            trace.odd["price below the floor"].append((price,))

    name = _text(entity.get("name")) or (base.title if base else "")
    description = _text(entity.get("description"))
    brand = _text(entity.get("brand"))
    year = ld_year_jalali(entity)
    trace.year["page" if year else "none"] += 1
    km = ld_mileage_km(entity)
    trace.mileage["page" if km is not None else "none"] += 1
    if km is None:
        m_status, m_reason = Validity.UNKNOWN, "not stated"
    else:
        j = classify_mileage(km, year)
        m_status, m_reason = j.status, j.reason
    transmission = _text(entity.get("vehicleTransmission"))
    eng = entity.get("vehicleEngine")
    fuel = _text(eng.get("fuelType")) if isinstance(eng, dict) else ""
    color = _text(entity.get("color"))
    condition, c_source = _worse(
        extract_body_condition(_text(entity.get("knownVehicleDamages"))),
        extract_body_condition(f"{name} {description}"))
    make, model = extract_make_model(f"{brand} {name}")
    pclass, psource = classify_product(name, from_canonical=False)
    trace.product[pclass] += 1
    if base is not None:
        kind, kind_src = base.price_kind, base.price_kind_source
        if price is None and kind == "cash":
            kind, kind_src = "absent", "none"
        elif price is not None and kind == "absent":
            kind, kind_src = "cash", "no_contrary_evidence"
    else:
        kind, kind_src = ("cash", "no_contrary_evidence") if price is not None else ("absent", "none")
    url = (base.url if base else "") or (entity.get("url") if isinstance(entity.get("url"), str) else "")
    return CarListing(
        listing_id=lid, url=url, title=name, description=description,
        asking_price_toman=price, make=make, model=model,
        trim=extract_trim(name), year_jalali=year, mileage_km=km,
        gearbox=extract_gearbox(transmission) or extract_gearbox(name),
        fuel=extract_fuel(fuel) or extract_fuel(name),
        color=extract_color(color) or extract_color(name),
        body_condition=condition, condition_source=c_source,
        document_issue=has_document_issue(f"{name} {description}"),
        city=base.city if base else None, seller_raw=None,
        price_raw=str(raw) if raw is not None else None,
        price_currency_raw=cur or None, price_displayed_toman=shown,
        price_status=status.value, price_provenance=prov,
        mileage_status=m_status.value, mileage_note=m_reason,
        product_class=pclass, product_class_source=psource,
        # the card's seller type: a dealer's where the card carried the corner
        # image (the owner's rule), else unknown
        price_kind=kind, price_kind_source=kind_src,
        seller_type=base.seller_type if base else "unknown",
        province_source=base.province_source if base else "none",
        location_raw=base.location_raw if base else None, source_url=url or None,
    )


def page_id(entity: dict, trace: SheypoorTrace) -> str | None:
    """`offers.sku`, checked against the digits before `.html` in the
    entity's url; the url's digits where there is no sku; else None."""
    sku = str(_offers(entity).get("sku") or "").strip()
    url = entity.get("url") if isinstance(entity.get("url"), str) else ""
    try:
        path = unquote(re.sub(r"^https?://[^/]+", "", url.split("?")[0]))
    except Exception:
        path = url
    m = _ID_IN_HREF.search(path)
    from_url = m.group(1) if m else None
    sku = sku if _ID.match(sku) else None
    trace.id_check["sku and url agree" if sku and from_url and sku == from_url
                   else "sku and url differ" if sku and from_url
                   else "sku only" if sku else "url only" if from_url else "none"] += 1
    return sku or from_url


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
        entity = vehicle_entity(html) if html else None
        if entity is not None:
            # a listing page: its own car only, not the cards of others on it
            tr.kind = "listing"
            self.next_url = None
            lid = page_id(entity, tr)
            if lid is None:
                tr.skipped["listing page without an id"] += 1
                return []
            at = next((i for i, x in enumerate(self.listings) if x.listing_id == lid), None)
            base = self.listings[at] if at is not None else None
            merged = build_from_page(entity, lid, base, tr)
            tr.merged["into its card" if base is not None else "alone"] += 1
            if at is not None:
                self.listings[at] = merged
            else:
                self.seen.add(lid)
                self.listings.append(merged)
            tr.emitted = 1
            return [merged]
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
    robots.txt allows it (caro/ingest/paging.py).

    The list's cards give no year and no odometer, so the listing page of
    each new listing is asked for too, up to `max_listings` in the run, each
    through the robots gate and after the pause. A listing page that does not
    answer leaves the card's listing as it was and is counted; three in a row
    that do not answer end the listing pages for the run, and the list goes
    on. `listing_pages` says what happened."""
    origin: str = SHEYPOOR_ORIGIN
    start_url: str = ""
    name: str = "sheypoor"
    city: str = "iran"
    max_listings: int = 20
    listing_pages: Counter = field(default_factory=Counter, init=False, compare=False)
    _failures: int = field(default=0, init=False, repr=False, compare=False)

    def __post_init__(self):
        if not self.start_url:
            self.start_url = CATEGORY_URL.format(city=self.city)
        super().__post_init__()

    def enrich(self, listings):
        for x in listings:
            asked = sum(v for k, v in self.listing_pages.items() if k != "not allowed")
            if (not x.url or asked >= self.max_listings or self._failures >= 3):
                yield x
                continue
            if not self.robots.allows(x.url):
                self.listing_pages["not allowed"] += 1
                yield x
                continue
            self.sleeper(self.policy.sleep())
            try:
                status, body = self.page_fetcher(x.url)
            except Exception:
                status, body = None, ""
            if classify_http(status) is FetchStatus.OK and body:
                got = [g for g in self.parser(body) if g.listing_id == x.listing_id]
                if got:
                    self._failures = 0
                    self.listing_pages["read"] += 1
                    yield got[0]
                    continue
                self.listing_pages["not this listing"] += 1
            else:
                self._failures += 1
                self.listing_pages[f"http {status}"] += 1
                if self._failures >= 3:
                    self.listing_pages["stopped: three in a row did not answer"] += 1
            yield x


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
    # a listing page merged into its card is not another listing
    listings = sum(t.emitted for t in traces if t.kind == "list") + sum(
        t.merged["alone"] for t in traces if t.kind == "listing")
    L = ["", "SHEYPOOR PAGE READ  (what each page was; counts and categories only)",
         "-" * 62,
         f"  pages {len(traces)}   listings {listings}"
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
    # the last list page's: a listing page names no next page
    lists = [t for t in traces if t.kind == "list"]
    L.append(f"  next page      {lists[-1].next_shape if lists else '(none)'}")
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
    pages = [t for t in traces if t.kind == "listing"]
    if pages:
        L.append(f"  listing pages  {len(pages)}")
        for label, attr in (("merged", "merged"), ("id", "id_check"),
                            ("price check", "price_check"), ("price key", "price_key")):
            c = Counter()
            for t in pages:
                c.update(getattr(t, attr))
            if c:
                L.append(f"    {label:<14}" + "  ".join(f"{k}:{v}" for k, v in c.most_common()))
        L.append("    values the pages use:")
        for key in ENUM_KEYS:
            c = Counter()
            for t in pages:
                c.update(t.enums[key])
            if c:
                L.append(f"      {key:<20}" + "  ".join(f"{k}:{v}" for k, v in c.most_common(8)))
        refused = Counter()
        for t in pages:
            refused.update(t.refused)
        if refused:
            L.append("    not counted: " + "  ".join(f"{k} {v}" for k, v in sorted(refused.items())))
    years = sum(t.year["title"] + t.year["page"] for t in traces)
    n = sum(t.emitted for t in traces if t.kind == "list")
    if n and years < n:
        L.append(f"  ⚠ the cards give no year and no odometer: {n - years} of {n} have no "
                 "year (a title or a listing page gave the rest). The listing page "
                 "gives both: a live run asks for up to --limit of them.")
    corner = sum(t.marks["corner image"] for t in traces)
    if corner:
        L.append(f"  ⚠ {corner} card(s) carry an image at the top right of the photo, "
                 "read as a shop's badge (seller_type dealer), the owner's "
                 "rule; see one on the site before trusting it.")
    return L
