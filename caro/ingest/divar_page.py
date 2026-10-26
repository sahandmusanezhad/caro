"""
Divar's category page -> `CarListing`s. Offline: it reads a string.

WHAT THE PAGE IS, as the owner's probe found it on 2026-10-26 (`/s/tehran/car`,
816,689 bytes, a plain HTTP GET, no browser):

    · the page is server-rendered. The listings are in the bytes that come back,
      so the Chromium that `playwright_fetcher` starts is not needed for a
      category page, and the module docstring of divar_car.py that says a plain
      GET returns an empty shell is wrong for this page.
    · one `application/ld+json` script holds a list of 24 vehicle objects:
      name, brand, model, productionDate, vehicleModelDate, mileageFromOdometer,
      color, vehicleTransmission, knownVehicleDamages, offers (price and
      currency), url, and a web_info block with the title and the city and
      district. That list is the SPINE here, for the reason bama's JSON-LD is:
      it is one object per vehicle and cannot be mis-anchored the way a text
      heuristic can.
    · the same 24 are `article.kt-post-card` elements, each with a link to
      /v/<slug>/<token>, a title, two description lines and a bottom line.
      Those are read for the one thing the node cannot give: what a buyer is
      shown. The price on the card is the ground truth for the unit, exactly as
      on bama (D20), and the mileage on the card is a second reading of the
      odometer.

WHAT IS NOT KNOWN, and is counted rather than assumed. The probe printed shapes
and no values. So this module does not know what `priceCurrency` holds, what
unit `mileageFromOdometer` is in, what the card's two description lines say, or
what `knownVehicleDamages` and `vehicleTransmission` hold. Each is read in a way
that is right whatever the answer is, and each answer is counted on the way
(`PageTrace`, `report`) so that the first run on the real page says what they
were. The price and the mileage are cross-checked against the card; a number
that the two readings do not explain is dropped, not chosen.

WHAT IS NEVER READ. `vehicleIdentificationNumber` (a vehicle identifier whose
meaning here is unknown), the image, anything on a node that is not a vehicle
(the publisher block holds an email and a telephone, and is not a listing), and
any seller field. No seller identifier is on the page, so `seller_raw` stays
None and no fingerprint is made; nothing here reveals a contact, because there
is nothing to reveal on a list page.

Not done here, and said so: body condition from a structured field (the nodes
carry `knownVehicleDamages`, but its values have not been seen), the province of
a city that is not one of the thirteen that share their province's name, and the
list pagination (`has_next_page` is in the page state, but whether `?page=2` is
served has not been probed).
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field, replace
from html.parser import HTMLParser
from urllib.parse import unquote, urlsplit

from caro.ingest.bama import (
    jsonld_blocks, ld_mileage_km, ld_price_toman, ld_year_jalali,
    reconcile_price,
)
from caro.ingest.divar_car import (
    DIVAR_ORIGIN, CarListing, extract_color, extract_gearbox, parse_listing,
)
from caro.ingest.persian import (
    normalize, parse_mileage_km, parse_price, parse_year_jalali,
    province_from_city,
)
from caro.ingest.quality import (
    PriceStatus, Validity, classify_mileage, classify_price_kind,
)

# Every key whose values are counted, and no other. These are categories, not
# content: a colour, a name or a number is not here and is never tallied.
ENUM_KEYS = ("@type", "priceCurrency", "unitCode", "vehicleTransmission",
             "knownVehicleDamages", "category")

_VEHICLE_TYPES = frozenset({"car", "vehicle", "motorvehicle"})
_VEHICLE_KEYS = ("vehicleModelDate", "productionDate", "mileageFromOdometer")

_TOKEN = re.compile(r"^[A-Za-z0-9_-]{5,40}$")

# What a line of a card says, by its words. Not by its position: the probe
# showed two description lines and not which is which.
_INSTALMENT = ("پیش پرداخت", "اقساط", "قسط", "ماهانه", "ودیعه", "رهن", "اجاره")
_TOMAN = ("تومان", "تومن")
_NEGOTIABLE = ("توافقی",)
_MILEAGE = ("کیلومتر", "کارکرد")

# A card says «۱۲۰ هزار» and the node says 119,800: the card rounds. Beyond
# this the two are different numbers.
_KM_ROUNDING = 1_000
_KM_REL = 0.02


# ---------------------------------------------------------------------------
# The cards
# ---------------------------------------------------------------------------

@dataclass
class Card:
    href: str = ""
    title: str = ""
    lines: list[str] = field(default_factory=list)   # the description lines
    bottom: str = ""
    tags: list[str] = field(default_factory=list)


class _CardReader(HTMLParser):
    """Collects every `article` whose class holds `kt-post-card`.

    By class and not by position, so that a card whose divs nest one level
    deeper than the probe saw still reads. Only the four classes below are
    read; everything else on a card is dropped without being looked at.
    """

    _VOID = frozenset({"img", "br", "hr", "input", "meta", "link", "source",
                       "area", "base", "col", "embed", "param", "track",
                       "wbr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[Card] = []
        self._card: Card | None = None
        self._stack: list[str] = []
        self._depth_in_card = 0
        self._caps: list[tuple[str, int, list[str]]] = []

    @staticmethod
    def _classes(attrs) -> set[str]:
        for k, v in attrs:
            if k == "class" and v:
                return set(v.split())
        return set()

    def handle_starttag(self, tag, attrs):
        cls = self._classes(attrs)
        if self._card is None:
            if tag == "article" and "kt-post-card" in cls:
                self._card = Card()
                self._stack = []
                self._caps = []
            return
        if tag in self._VOID:
            return
        self._stack.append(tag)
        if tag == "a" and "kt-post-card__action" in cls and not self._card.href:
            self._card.href = dict(attrs).get("href") or ""
        kind = None
        if "kt-post-card__title" in cls:
            kind = "title"
        elif "kt-post-card__description" in cls:
            kind = "line"
        elif "kt-post-card__bottom-description" in cls:
            kind = "bottom"
        elif "kt-tag__text" in cls:
            kind = "tag"
        if kind:
            self._caps.append((kind, len(self._stack), []))

    def handle_data(self, data):
        for _, _, buf in self._caps:
            buf.append(data)

    def _flush(self, depth: int) -> None:
        """Close every capture opened at `depth` or deeper."""
        while self._caps and self._caps[-1][1] >= depth:
            kind, _, buf = self._caps.pop()
            text = re.sub(r"\s+", " ", "".join(buf)).strip()
            c = self._card
            if kind == "title":
                c.title = c.title or text
            elif kind == "line":
                if text:
                    c.lines.append(text)
            elif kind == "bottom":
                c.bottom = c.bottom or text
            elif kind == "tag" and text:
                c.tags.append(text)

    def handle_endtag(self, tag):
        if self._card is None or tag in self._VOID:
            return
        if tag == "article" and "article" not in self._stack:
            # The card's own end tag. Whatever was left open inside it is
            # closed with it, so one unclosed tag cannot swallow the next card.
            self._flush(1)
            self.cards.append(self._card)
            self._card = None
            return
        if tag not in self._stack:
            return                    # closes nothing this reader opened
        while self._stack:
            self._flush(len(self._stack))
            if self._stack.pop() == tag:
                break


def read_cards(html: str) -> list[Card]:
    if not html:
        return []
    r = _CardReader()
    try:
        r.feed(html)
        r.close()
    except Exception:             # a page that cannot be read has no cards
        return r.cards
    return r.cards


def token_of(url: str) -> str | None:
    """`/v/<slug>/<token>` -> token. The slug may be percent-encoded Persian."""
    try:
        parts = [unquote(p) for p in urlsplit(url).path.split("/") if p]
    except ValueError:
        return None
    if len(parts) >= 2 and parts[0] == "v" and _TOKEN.match(parts[-1]):
        return parts[-1]
    return None


def _on_divar(url: str) -> bool:
    try:
        host = urlsplit(url).netloc.lower()
    except ValueError:
        return False
    return host in ("divar.ir", "www.divar.ir")


def _has(s: str, words) -> bool:
    return any(normalize(w) in s for w in words)


def read_card_lines(lines: list[str]) -> dict:
    """What a buyer is shown, from the words of the description lines.

    price        the toman on the one line that has «تومان», or None
    price_lines  how many lines had it (two is not one price)
    negotiable   a line says «توافقی»
    instalment   a line has a deposit, instalment or rent word
    mileage      the km on the line that has «کیلومتر» or «کارکرد», or None
    """
    out = {"price": None, "price_lines": 0, "negotiable": False,
           "instalment": False, "mileage": None}
    prices = []
    for raw in lines:
        s = normalize(raw)
        if _has(s, _NEGOTIABLE):
            out["negotiable"] = True
        if _has(s, _INSTALMENT):
            out["instalment"] = True
        if _has(s, _TOMAN):
            out["price_lines"] += 1
            prices.append(parse_price(s))
        if _has(s, _MILEAGE):
            km = parse_mileage_km(s)
            if km is not None and out["mileage"] is None:
                out["mileage"] = km
    if out["price_lines"] == 1:
        out["price"] = prices[0]
    return out


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------

@dataclass
class PageTrace:
    """What one page was, in counts. Every field is a count or a category."""
    source: str = "none"                  # jsonld | cards | none
    ld_nodes: int = 0
    cards: int = 0
    emitted: int = 0
    duplicates: int = 0
    cards_without_ld: int = 0
    ld_without_card: int = 0
    skipped: Counter = field(default_factory=Counter)
    price: Counter = field(default_factory=Counter)
    mileage: Counter = field(default_factory=Counter)
    year: Counter = field(default_factory=Counter)
    enums: dict = field(default_factory=lambda: {k: Counter()
                                                 for k in ENUM_KEYS})


def _is_vehicle(node) -> bool:
    if not isinstance(node, dict):
        return False
    t = node.get("@type")
    types = t if isinstance(t, list) else [t]
    if any(str(x).lower() in _VEHICLE_TYPES for x in types):
        return True
    return any(k in node for k in _VEHICLE_KEYS)


def vehicle_nodes(html: str) -> list[dict]:
    out = []
    for node in jsonld_blocks(html):
        if _is_vehicle(node):
            out.append(node)
        elif isinstance(node, dict) and isinstance(node.get("@graph"), list):
            out.extend(n for n in node["@graph"] if _is_vehicle(n))
    return out


# A value is counted only if it can be a category: short, with no digit and
# no address in it. A field that turns out to hold the seller's own words
# would otherwise put a phone number into a report that is pasted into a chat.
_CATEGORICAL = re.compile(r"^[^\d@]{1,40}$")
_MAX_DISTINCT = 20


def _offers(node: dict) -> dict:
    o = node.get("offers")
    if isinstance(o, list):
        o = o[0] if o else None
    return o if isinstance(o, dict) else {}


def _count_enums(node: dict, trace: PageTrace) -> None:
    mil = node.get("mileageFromOdometer")
    seen = {"@type": node.get("@type"), "category": node.get("category"),
            "vehicleTransmission": node.get("vehicleTransmission"),
            "knownVehicleDamages": node.get("knownVehicleDamages"),
            "priceCurrency": _offers(node).get("priceCurrency"),
            "unitCode": mil.get("unitCode") if isinstance(mil, dict) else None}
    for key, raw in seen.items():
        for v in raw if isinstance(raw, list) else [raw]:
            if not isinstance(v, str) or not _CATEGORICAL.match(v.strip()):
                continue
            c = trace.enums[key]
            v = v.strip()
            if v in c or len(c) < _MAX_DISTINCT:
                c[v] += 1
            else:
                c["(other)"] += 1


# ---------------------------------------------------------------------------
# One listing
# ---------------------------------------------------------------------------

def _price(ld_toman, shown: dict | None):
    """(toman, status, provenance, displayed, code).

    `code` is what the two readings did (bama's agreement codes) or why there
    is no price, and is what the report counts.
    """
    displayed = shown["price"] if shown else None
    if shown and shown["instalment"]:
        # The number on the card is a deposit or a rent. Whatever the node
        # says, there is no cash asking price here, and picking one of the two
        # would fabricate it.
        return None, PriceStatus.AMBIGUOUS, "none", displayed, "instalment"
    price, code = reconcile_price(ld_toman, displayed)
    status = {
        "agree": PriceStatus.DISPLAY_CONFIRMED,
        "ld_only": PriceStatus.STRUCTURED_ONLY,
        "text_only": PriceStatus.DISPLAYED_ONLY,
        "label_wrong_ld_10x_low": PriceStatus.LABEL_CORRECTED,
        "label_wrong_ld_10x_high": PriceStatus.LABEL_CORRECTED,
        "unexplained_disagreement": PriceStatus.AMBIGUOUS,
    }.get(code)
    if status is None:                             # nothing from either side
        # «توافقی» on the card is the seller declining to name a number. A
        # card that says nothing is not that: it is a price we did not find.
        negotiable = bool(shown and shown["negotiable"])
        status = PriceStatus.NEGOTIABLE if negotiable else PriceStatus.ABSENT
        code = "negotiable" if negotiable else "none"
    prov = {"agree": "jsonld+text", "ld_only": "jsonld",
            "text_only": "text"}.get(code,
                                     "text" if price is not None else "none")
    return price, status, prov, displayed, code


def _mileage(ld_km, shown_km):
    """(km, code, note). Two readings of one odometer."""
    if ld_km is None and shown_km is None:
        return None, "none", None
    if shown_km is None:
        return ld_km, "ld_only", None
    if ld_km is None:
        return shown_km, "text_only", None
    if abs(ld_km - shown_km) <= max(_KM_ROUNDING, shown_km * _KM_REL):
        return ld_km, "agree", None
    return (None, "disagree",
            f"structured and displayed odometer disagree "
            f"({ld_km} vs {shown_km})")


def _gearbox(raw, blob: str):
    if isinstance(raw, str):
        low = raw.lower()
        if "manual" in low:
            return "manual"
        if "auto" in low:
            return "automatic"
        g = extract_gearbox(raw)
        if g:
            return g
    return extract_gearbox(blob)


def _title(node: dict, card: Card | None) -> str:
    wi = node.get("web_info") if isinstance(node.get("web_info"), dict) else {}
    seen: list[str] = []
    for t in (node.get("name"), wi.get("title"), card.title if card else ""):
        t = re.sub(r"\s+", " ", t).strip() if isinstance(t, str) else ""
        if t and not any(t in s or s in t for s in seen):
            seen.append(t)
    return " ".join(seen)


def build(url: str, token: str, node: dict | None, card: Card | None,
          trace: PageTrace) -> CarListing:
    node = node or {}
    wi = node.get("web_info") if isinstance(node.get("web_info"), dict) else {}
    shown = read_card_lines(card.lines) if card else None
    title = _title(node, card)

    y_ld = ld_year_jalali(node)
    y_title = parse_year_jalali(title) if title else None
    if y_ld and y_title:
        trace.year["agree" if y_ld == y_title else "differ"] += 1
    else:
        trace.year["ld_only" if y_ld else "title_only" if y_title
                   else "none"] += 1
    year = y_ld or y_title

    ld_price, _ = ld_price_toman(node.get("offers"))
    price, p_status, p_prov, displayed, p_code = _price(ld_price, shown)
    trace.price[p_code] += 1

    km, m_code, m_note = _mileage(ld_mileage_km(node) if node else None,
                                  shown["mileage"] if shown else None)
    trace.mileage[m_code] += 1
    if km is None:
        judge = (Validity.UNKNOWN, m_note or "not stated")
        m_status, m_reason = judge
    else:
        j = classify_mileage(km, year)
        m_status, m_reason = j.status, j.reason

    offers = _offers(node)

    city_raw = wi.get("city_persian")
    district = wi.get("district_persian")
    city_raw = city_raw.strip() if isinstance(city_raw, str) else ""
    district = district.strip() if isinstance(district, str) else ""
    province = province_from_city(city_raw) if city_raw else None
    loc = "، ".join(x for x in (city_raw, district) if x) or None

    listing = parse_listing(
        token, url, title, "", year_text=str(year) if year else "",
        city=province)
    # Read from the card's lines and not from the title: «توافقی» in a card is
    # the site saying so, and in a title it is the seller's copy (quality.py).
    kind, kind_src = classify_price_kind(
        " ".join(card.lines) if card else "", has_price=price is not None)
    ld_color = node.get("color") if isinstance(node.get("color"), str) else ""
    return replace(
        listing,
        asking_price_toman=price, mileage_km=km, year_jalali=year,
        gearbox=_gearbox(node.get("vehicleTransmission"), title),
        color=extract_color(ld_color) or listing.color,
        price_raw=(str(offers.get("price"))
                   if offers.get("price") is not None else None),
        price_currency_raw=offers.get("priceCurrency") or None,
        price_displayed_toman=displayed,
        price_status=p_status.value, price_provenance=p_prov,
        price_kind=kind, price_kind_source=kind_src,
        mileage_status=m_status.value, mileage_note=m_reason,
        province_source="city" if province else "none",
        location_raw=loc, source_url=url, seller_raw=None, image_urls=(),
    )


# ---------------------------------------------------------------------------
# One page
# ---------------------------------------------------------------------------

def _absolute(href: str) -> str:
    return href if href.startswith("http") else DIVAR_ORIGIN + (
        href if href.startswith("/") else "/" + href)


def parse_divar_page(html: str | None, trace: PageTrace | None = None,
                     ) -> list[CarListing]:
    """The listings of one category page, in page order."""
    tr = trace if trace is not None else PageTrace()
    if not html:
        return []
    nodes = vehicle_nodes(html)
    cards = read_cards(html)
    tr.ld_nodes, tr.cards = len(nodes), len(cards)

    by_token: dict[str, Card] = {}
    for c in cards:
        t = token_of(c.href) if c.href else None
        if t is None:
            tr.skipped["card without a token"] += 1
        elif t not in by_token:
            by_token[t] = c

    out: list[CarListing] = []
    seen: set[str] = set()
    if nodes:
        tr.source = "jsonld"
        node_tokens: set[str] = set()
        for node in nodes:
            _count_enums(node, tr)
            url = node.get("url")
            if not isinstance(url, str):
                tr.skipped["no url"] += 1
                continue
            if not _on_divar(url):
                tr.skipped["foreign url"] += 1
                continue
            tok = token_of(url)
            if tok is None:
                tr.skipped["no token"] += 1
                continue
            node_tokens.add(tok)
            if tok in seen:
                continue
            seen.add(tok)
            card = by_token.get(tok)
            if card is None:
                tr.ld_without_card += 1
            out.append(build(url, tok, node, card, tr))
        tr.cards_without_ld = sum(1 for t in by_token if t not in node_tokens)
    elif cards:
        tr.source = "cards"
        for tok, card in by_token.items():
            out.append(build(_absolute(card.href), tok, None, card, tr))
    tr.emitted = len(out)
    return out


class DivarPageParser:
    """`parse_page` for the adapter: one instance per run.

    Remembers the tokens it has returned, so that a page that is served again
    (a `?page=` the site ignores) adds nothing and is counted rather than
    believed to be new listings.
    """

    def __init__(self):
        self.seen: set[str] = set()
        self.traces: list[PageTrace] = []

    def __call__(self, html: str) -> list[CarListing]:
        tr = PageTrace()
        self.traces.append(tr)
        fresh = []
        for x in parse_divar_page(html, tr):
            if x.listing_id in self.seen:
                tr.duplicates += 1
                continue
            self.seen.add(x.listing_id)
            fresh.append(x)
        tr.emitted = len(fresh)
        return fresh


# ---------------------------------------------------------------------------
# The report, which is how the unknowns above get answered
# ---------------------------------------------------------------------------

def report(traces: list[PageTrace]) -> list[str]:
    """Counts only: no title, no price, no token."""
    if not traces:
        return []
    L = ["", "DIVAR PAGE READ  (what each page was; counts and categories only)",
         "-" * 62]
    L.append(f"  pages {len(traces)}   listings {sum(t.emitted for t in traces)}"
             f"   json-ld vehicles {sum(t.ld_nodes for t in traces)}"
             f"   cards {sum(t.cards for t in traces)}")
    srcs = Counter(t.source for t in traces)
    L.append("  read from      " + "  ".join(f"{k}:{v}" for k, v in
                                             srcs.most_common()))
    for label, attr in (("price", "price"), ("mileage", "mileage"),
                        ("year vs title", "year")):
        c = Counter()
        for t in traces:
            c.update(getattr(t, attr))
        if c:
            L.append(f"  {label:<14}" + "  ".join(f"{k}:{v}" for k, v in
                                                  c.most_common()))
    extra = {
        "duplicates": sum(t.duplicates for t in traces),
        "cards without a node": sum(t.cards_without_ld for t in traces),
        "nodes without a card": sum(t.ld_without_card for t in traces),
    }
    for k, v in extra.items():
        if v:
            L.append(f"  {k:<22}{v}")
    sk = Counter()
    for t in traces:
        sk.update(t.skipped)
    for k, v in sk.most_common():
        L.append(f"  skipped: {k}: {v}")
    L.append("")
    L.append("  values the page uses (what the parser had to assume):")
    for key in ENUM_KEYS:
        c = Counter()
        for t in traces:
            c.update(t.enums[key])
        if c:
            L.append(f"    {key:<22}" + "  ".join(f"{k}:{v}" for k, v in
                                                  c.most_common(8)))
    ld_only = sum(t.price["ld_only"] for t in traces)
    if ld_only:
        L.append(f"  ⚠ {ld_only} price(s) rest on the structured block alone. "
                 "The unit of that number is unconfirmed by anything a buyer "
                 "sees; read the priceCurrency line above.")
    return L
