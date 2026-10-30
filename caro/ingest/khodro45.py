"""
Khodro45's car list -> `CarListing`s, and the adapter that asks for it.

WHAT THE PAGE IS, as the owner's probe found it on 2026-10-29 (`/buy-car/`,
577,043 bytes, a plain HTTP GET, no browser):

    · a Next.js page. The listings are in its data stream
      (caro/ingest/nextjs.py), a react-query cache whose
      `state.queries[].state.data.pages[]` holds `count` (1812), `next` (a page
      of the site's own API, `/api/v#/car_listing/?limit=12&offset=12&…`),
      `previous` and `results`: twelve objects, one per car, with `slug`,
      `price_type`, `price`, `final_price`, `car_properties` (brand, model,
      option, trim, year), `city`, `car_specifications.klm` and `fmp_tags`.
      That list is the SPINE here, as bama's JSON-LD is there: one object per
      car, which cannot be mis-anchored the way a text heuristic can.
    · the same twelve are cards, `a[href=/buy-car/<brand>-<model>/<city>/<slug>/]`:
      an h2 of brand | model | year, a line of option | «# km» | city, the
      platform's tags, and «قیمت» with a number and the toman icon. The card is
      read for what a buyer is shown, which is the ground truth for the price
      (D20) and a second reading of the odometer and the year.

WHAT WAS NOT KNOWN, and is decided by the page rather than assumed. The survey
masks the card's digits, so nothing said which of `price` and `final_price` the
card shows (on the owner's page the second is the first plus 2.02%, at the
smallest, the middle and the largest alike). The asking price is the number the
card shows, whichever field it equals, and the trace counts which. A page of
the API carries no card; there the field the cards of the same run showed is
used, and only if three or more showed it and none showed the other. What
`price_type` means is not known either: 2 is the type of 11 of the 12, and any
other type carries no price until someone reads such a card and says what it
is.

WHAT IS NEVER READ. The image, `views`, `identifier`, `branch` and any seller
field: there is none on the list, so `seller_raw` stays None and no fingerprint
is made, and `seller_type` is `unknown` (D26: no badge, no type).

READ AS AN AUDIT ONLY. `created_time`, when the site says the listing was
created, written on the owner's saved page as «2026-10-28T18:20:42.930075+03:30».
It is kept as written, in `listed_at`, where it reads as a time, and crosses to
the snapshot and no further; it is never a feature and never a split key. It
checks our own first sighting (TEMPORAL_CONTRACT §11; the owner's decision of
2026-10-30), and the report counts the listings by its date, newest first.

NOT DONE HERE, and said so: the colour (the list does not give it), the
province of a city that is no province's capital (the 31 give theirs, by the
owner's choice of 2026-10-30), and the meaning of a tag the condition table
does not know (the tags are counted in the report).
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

from caro.ingest.bama import ld_year_jalali
from caro.ingest.divar_car import (
    CarListing, extract_body_condition, extract_fuel, extract_gearbox,
    extract_make_model, extract_trim,
)
from caro.ingest.nextjs import page_rows
from caro.ingest.paging import NextLinkAdapter, url_shape
from caro.ingest.persian import digits_only, normalize, province_from_city
from caro.ingest.quality import (
    PriceStatus, Validity, classify_mileage, classify_price_value,
    classify_product,
)

KHODRO45_ORIGIN = "https://khodro45.com"
LIST_URL = KHODRO45_ORIGIN + "/buy-car/"

# The one price type whose cards are known to show a plain asking price: 11 of
# the 12 on the owner's page, every card printed showing «قیمت», a number and
# the toman icon. A listing of any other type carries no price.
ACCEPTED_PRICE_TYPES = frozenset({2})

PRICE_FIELDS = ("price", "final_price")
# How many cards must have shown one field, and none the other, before a
# result with no card (a page of the API) is priced by that field.
LEARN_MIN_CARDS = 3
# A card's figure equals a field to within a toman in ten thousand.
_PRICE_TOL = 10_000
# Two readings of one odometer agree within the larger of these.
_KM_ABS = 1_000
_KM_REL = 0.02

_CARD_HREF = re.compile(r"^/buy-car/[^/?#]+/[^/?#]+/([A-Za-z0-9_-]{3,40})/?$")
_SLUG = re.compile(r"^[A-Za-z0-9_-]{3,40}$")
_FIGURE = re.compile(r"[\d٬،,]+")


# ---------------------------------------------------------------------------
# The cards
# ---------------------------------------------------------------------------

@dataclass
class Card:
    href: str = ""                                    # the path, no host
    h2: list[str] = field(default_factory=list)       # brand | model | year
    texts: list[str] = field(default_factory=list)
    price_text: str | None = None     # the text just before the toman icon
    km_text: str | None = None        # the first text with «km» in it
    tags: list[str] = field(default_factory=list)


class _CardReader(HTMLParser):
    """Collects every link whose path is a listing's, and the texts in it.

    By the path and the toman icon, not by a class: Tailwind's classes say
    how a card looks, and a redesign changes them all. The h2 is read for the
    year, and an element whose `data-testid` holds `.listing-tag.` for a tag.
    """

    _VOID = frozenset({"img", "br", "hr", "input", "meta", "link", "source",
                       "area", "base", "col", "embed", "param", "track", "wbr"})

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cards: list[Card] = []
        self._card: Card | None = None
        self._stack: list[str] = []
        self._h2 = 0                       # depth of the open h2, 0 if none
        self._tag_at = 0                   # depth of the open tag element
        self._tag_buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if self._card is None:
            if tag == "a":
                path = re.sub(r"^https?://[^/]+", "",
                              (a.get("href") or "").split("#")[0].split("?")[0])
                if _CARD_HREF.match(path):
                    self._card = Card(href=path)
                    self._stack, self._h2, self._tag_at = [], 0, 0
            return
        if tag in self._VOID:
            return
        self._stack.append(tag)
        if tag == "h2" and not self._h2:
            self._h2 = len(self._stack)
        if "icon-toman" in (a.get("class") or "").split():
            c = self._card
            c.price_text = c.texts[-1] if c.texts else None
        if ".listing-tag." in (a.get("data-testid") or "") and not self._tag_at:
            self._tag_at, self._tag_buf = len(self._stack), []

    def handle_data(self, data):
        if self._card is None:
            return
        t = re.sub(r"\s+", " ", data).strip()
        if not t:
            return
        c = self._card
        c.texts.append(t)
        if self._h2:
            c.h2.append(t)
        if self._tag_at:
            self._tag_buf.append(t)
        if c.km_text is None and re.search(r"(?i)(?<![a-z])km(?![a-z])|کیلومتر", t):
            c.km_text = t

    def _close_to(self, depth: int) -> None:
        if self._h2 and depth <= self._h2:
            self._h2 = 0
        if self._tag_at and depth <= self._tag_at:
            text = " ".join(self._tag_buf).strip()
            if text:
                self._card.tags.append(text)
            self._tag_at, self._tag_buf = 0, []

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


def slug_of(path: str) -> str | None:
    m = _CARD_HREF.match(path or "")
    return m.group(1) if m else None


def _figure(text: str | None) -> int | None:
    """The first figure in a text, separators dropped: «127,860 km» -> 127860.
    No scale word is read: the card writes the whole number."""
    if not text:
        return None
    m = _FIGURE.search(normalize(text))
    if not m:
        return None
    d = digits_only(m.group(0))
    return int(d) if d.isdigit() else None


def _card_price(card: Card | None) -> int | None:
    """The figure before the toman icon, if that text is a figure and nothing
    else («۱٬۲۱۲٬۰۰۰٬۰۰۰»). A text with a word in it is not read."""
    if card is None or not card.price_text:
        return None
    if not re.fullmatch(r"[\d٬،,\s]+", normalize(card.price_text)):
        return None
    return _figure(card.price_text)


def _card_year(card: Card | None) -> int | None:
    for t in reversed(card.h2 if card else []):
        d = digits_only(t)
        if re.fullmatch(r"\d{4}", d):
            return int(d)
    return None


# ---------------------------------------------------------------------------
# The results
# ---------------------------------------------------------------------------

def _num(v) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().isdigit():
        return int(v.strip())
    return None


# A mark nobody sees, at either end of a value: the zero-width non-joiner and
# joiner, the direction marks, the byte-order mark (Unicode category Cf).
# Khodro45 wrote one brand «\u200cBeijing», and the invisible first letter made
# it another make. Inside a value they stay: «دنده‌ای» needs its non-joiner.
_EDGE_MARKS = re.compile(r"^[\u00ad\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]+|"
                         r"[\u00ad\u061c\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]+$")


def _str(v) -> str:
    if not isinstance(v, str):
        return ""
    s = re.sub(r"\s+", " ", v).strip()
    while True:
        t = _EDGE_MARKS.sub("", s).strip()
        if t == s:
            return s
        s = t


def _category(v) -> str | None:
    """A value that may be counted or used as a name: at most 40 characters,
    no «@», at most four digits (divar_page's guard)."""
    s = _str(v)
    if not s or len(s) > 40 or "@" in s or sum(c.isdigit() for c in s) > 4:
        return None
    return s


def result_pages(obj, out: list | None = None, depth: int = 0) -> list[dict]:
    """Every object holding a `results` list of cars (objects with a `slug`
    and `car_properties`), wherever it is: the page of the react-query cache,
    or the API's own answer."""
    out = [] if out is None else out
    if depth > 60:
        return out
    if isinstance(obj, dict):
        res = obj.get("results")
        if (isinstance(res, list) and res
                and all(isinstance(r, dict) for r in res)
                and any("slug" in r and "car_properties" in r for r in res)):
            out.append(obj)
        for v in obj.values():
            if isinstance(v, (dict, list)):
                result_pages(v, out, depth + 1)
    elif isinstance(obj, list):
        for v in obj:
            if isinstance(v, (dict, list)):
                result_pages(v, out, depth + 1)
    return out


def _absolute(url: str) -> str:
    if url.startswith("/"):
        return KHODRO45_ORIGIN + url
    return url


# The forms a link's first two segments may take, in the order they are
# tried. The owner's third read (2026-10-30) had «brand-model» and the city's
# English title lower-cased differ on all 24 cards, with the code right, so
# the forms are learned from the cards rather than written down.
FIRST_FORMS = ("brand-model", "model", "brand+model")
CITY_FORMS = ("title_en", "title_en without spaces")
_SEGMENT = re.compile(r"[a-z0-9_-]{1,60}")


def segment_forms(r: dict) -> tuple[dict, dict]:
    """({first form: value}, {city form: value}) for a result, each value
    lower-cased and a path segment, or left out."""
    cp = r.get("car_properties") if isinstance(r.get("car_properties"), dict) else {}
    b = cp.get("brand") if isinstance(cp.get("brand"), dict) else {}
    m = cp.get("model") if isinstance(cp.get("model"), dict) else {}
    c = r.get("city") if isinstance(r.get("city"), dict) else {}
    bs, ms = _str(b.get("seo_slug")).lower(), _str(m.get("seo_slug")).lower()
    first = {"brand-model": f"{bs}-{ms}" if bs and ms else "", "model": ms,
             "brand+model": f"{bs}{ms}" if bs and ms else ""}
    ce = _str(c.get("title_en")).lower()
    city = {"title_en": ce, "title_en without spaces": ce.replace(" ", "")}
    keep = lambda d: {k: v for k, v in d.items() if v and _SEGMENT.fullmatch(v)}   # noqa: E731
    return keep(first), keep(city)


def rule_path(r: dict, prefix: str | None = "", first: str | None = "brand-model",
              city: str | None = "title_en") -> str | None:
    """`/buy-car/<first>/<city>/<prefix><slug>/`, from the result's own
    fields, the slug lower-cased. `prefix` is the part before the slug and
    `first` and `city` the forms of the two segments that the run's cards
    showed (`Khodro45Parser.learned_prefix`, `learned_forms`); None for any of
    them gives no address. The owner's page (2026-10-29) ended its links in
    «cla-» and the slug in lower case. A run checks the rule on every card
    before using it for a result that has none."""
    if prefix is None or first is None or city is None:
        return None
    fs, cs = segment_forms(r)
    slug = _str(r.get("slug"))
    if first not in fs or city not in cs or not _SLUG.match(slug):
        return None
    return f"/buy-car/{fs[first]}/{cs[city]}/{prefix}{slug.lower()}/"


def next_view(url: str | None) -> str:
    """The next page as its path (digits «#») and its parameters, a value
    kept when it is one to three digits or a lowercase word of up to twelve
    letters (`offset=12`), anything else «…»."""
    if not url:
        return "(none)"
    path, _, query = re.sub(r"^https?://[^/]+", "", url).partition("?")
    pairs = []
    for pair in query.split("&"):
        k, _, v = pair.partition("=")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,24}", k):
            keep = re.fullmatch(r"\d{1,3}|[a-z]{1,12}", v)
            pairs.append(f"{k}={v if keep else '…'}")
    return re.sub(r"\d+", "#", path) + ("?" + "&".join(pairs) if pairs else "")


def where_is(url: str | None) -> str:
    """khodro45.com, khodro45.com over http, another origin, or relative."""
    if not url:
        return "none"
    if url.startswith("/"):
        return "relative"
    m = re.match(r"^(https?)://([^/?#]+)", url)
    host = m.group(2).lower() if m else ""
    if host not in ("khodro45.com", "www.khodro45.com"):
        return "another origin"
    return "khodro45.com" if m.group(1).lower() == "https" else "khodro45.com over http"


def ours_over_https(url: str) -> str:
    """A link to khodro45.com given as http:// is the same page over https://:
    the API names its next page `http://khodro45.com/api/…` (the owner's page,
    2026-10-29) while the site is served over https, and the gate reads the
    https origin's robots.txt. The host, the path and the query are kept; any
    other host is left as it is."""
    m = re.match(r"^http://(khodro45\.com)([/?#].*)?$", url, re.I)
    return f"https://{m.group(1).lower()}{m.group(2) or '/'}" if m else url


def _shape_of(s: str) -> str:
    return re.sub(r"[A-Za-z]", "a", re.sub(r"\d", "#", s))


def _relation(slug: str, code: str | None) -> str:
    if not code:
        return "no code"
    if slug == code:
        return "equal"
    if code.endswith(slug):
        return "the code ends with the slug"
    sl, cl = slug.lower(), code.lower()
    if sl == cl:
        return "equal, case aside"
    if cl.endswith(sl):
        return "the code ends with the slug, case aside"
    if slug.endswith(code):
        return "the slug ends with the code"
    if sl in cl or cl in sl:
        return "one holds the other"
    return "neither"


def _code_holds(code: str | None, slug: str) -> bool:
    """The card's code is the slug, or ends in «-» and the slug, case aside."""
    if not code or not slug:
        return False
    cl, sl = code.lower(), slug.lower()
    return cl == sl or cl.endswith("-" + sl)


def _result_key(r: dict) -> tuple | None:
    """(odometer, year) as the data gives them, for the join by content."""
    cp = r.get("car_properties") if isinstance(r.get("car_properties"), dict) else {}
    spec = (r.get("car_specifications")
            if isinstance(r.get("car_specifications"), dict) else {})
    km, y = _num(spec.get("klm")), _num(cp.get("year"))
    return (km, y) if km is not None and y else None


def _card_key(card: Card) -> tuple | None:
    km, y = _figure(card.km_text), _card_year(card)
    return (km, y) if km is not None and y else None


# ---------------------------------------------------------------------------
# The trace
# ---------------------------------------------------------------------------

ODD_KINDS = ("card price is neither field", "price below the floor",
             "odometer differs", "year differs")
_ODD_CAP = 12


@dataclass
class Khodro45Trace:
    """What one page was, in counts. Every field is a count or a category."""
    kind: str = "none"                        # html | api | none
    results: int = 0
    cards: int = 0
    emitted: int = 0
    duplicates: int = 0
    cards_without_result: int = 0
    results_without_card: int = 0
    count: int | None = None                  # what the site says the list holds
    next_shape: str = "(none)"
    skipped: Counter = field(default_factory=Counter)
    price: Counter = field(default_factory=Counter)
    shown: Counter = field(default_factory=Counter)
    mileage: Counter = field(default_factory=Counter)
    year: Counter = field(default_factory=Counter)
    calendar: Counter = field(default_factory=Counter)
    url: Counter = field(default_factory=Counter)
    price_types: Counter = field(default_factory=Counter)
    brands: Counter = field(default_factory=Counter)
    cities: Counter = field(default_factory=Counter)
    tags: Counter = field(default_factory=Counter)
    options: Counter = field(default_factory=Counter)
    trims: Counter = field(default_factory=Counter)
    # How each result found its card, and, for a pair found by what both
    # show, how the result's slug relates to the code at the end of the
    # card's link and the shape of each (letters «a», digits «#»).
    joined: Counter = field(default_factory=Counter)
    slug_relation: Counter = field(default_factory=Counter)
    slug_shapes: Counter = field(default_factory=Counter)
    # Each list of results found: its size, the next page it names (its
    # small numbers kept) and where that page is.
    lists: list = field(default_factory=list)
    next_upgraded: int = 0
    # Which form each segment of a joined card's link took, and, where none
    # fits, the shape of the link's segment against the first form's.
    rule_forms: Counter = field(default_factory=Counter)
    rule_misses: Counter = field(default_factory=Counter)
    refused: Counter = field(default_factory=Counter)
    created: Counter = field(default_factory=Counter)          # date -> listings
    created_missing: Counter = field(default_factory=Counter)  # unreadable, none
    odd: dict = field(default_factory=lambda: {k: [] for k in ODD_KINDS})
    prices: list = field(default_factory=list)    # asking prices taken, toman


def _count(c: Counter, v, trace: Khodro45Trace, key: str) -> None:
    s = _category(v)
    if s is None:
        trace.refused[key] += 1
    elif s in c or len(c) < 20:
        c[s] += 1
    else:
        c["(other)"] += 1


# ---------------------------------------------------------------------------
# One listing
# ---------------------------------------------------------------------------

def _shown_field(r: dict, displayed: int | None) -> str | None:
    """Which field the card's figure is: price, final_price, both, neither."""
    if displayed is None:
        return None
    hits = [f for f in PRICE_FIELDS
            if _num(r.get(f)) is not None
            and abs(_num(r.get(f)) - displayed) <= max(1, displayed // _PRICE_TOL)]
    if len(hits) == 2:
        return "both"
    return hits[0] if hits else "neither"


# A time as the site writes it: a date, a time, a fraction and an offset
# optional. Shape first, then datetime has the last word on the values.
_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|[+-]\d{2}:\d{2})?")


def _created(v, trace: Khodro45Trace) -> str | None:
    """`created_time` as the site wrote it, where it reads as a time; else
    None, counted as unreadable or as none."""
    if v is None:
        trace.created_missing["none"] += 1
        return None
    if isinstance(v, str) and _TIME.fullmatch(v):
        try:
            datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            pass
        else:
            trace.created[v[:10]] += 1
            return v
    trace.created_missing["unreadable"] += 1
    return None


def _price(r: dict, card: Card | None, learned: str | None):
    """(toman, status, provenance, displayed, code, the field used)."""
    displayed = _card_price(card)
    pt = r.get("price_type")
    if _num(pt) not in ACCEPTED_PRICE_TYPES:
        return (None, PriceStatus.AMBIGUOUS, "none", displayed,
                f"price_type {pt}", None)
    shown = _shown_field(r, displayed)
    if shown in ("price", "final_price", "both"):
        f = "price" if shown == "both" else shown
        return (_num(r.get(f)), PriceStatus.DISPLAY_CONFIRMED, "data+card",
                displayed, f"card shows {shown}", f)
    if shown == "neither":
        return (None, PriceStatus.AMBIGUOUS, "none", displayed,
                "card shows neither", None)
    if card is not None:
        # A card with no figure on it: «توافقی», or a price the site does not
        # show. Whatever the data holds, a buyer is shown no number.
        if any("توافقی" in normalize(t) for t in card.texts):
            return None, PriceStatus.NEGOTIABLE, "none", None, "negotiable", None
        return (None, PriceStatus.AMBIGUOUS, "none", None,
                "card shows no figure", None)
    if learned and _num(r.get(learned)) is not None:
        return (_num(r.get(learned)), PriceStatus.STRUCTURED_ONLY, "data",
                None, f"no card: {learned}, as the cards showed", learned)
    return (None, PriceStatus.AMBIGUOUS, "none", None,
            "no card, no field settled", None)


def _odometer(data_km: int | None, card_km: int | None):
    """(km, code). Two readings of one odometer, each as written."""
    if data_km is None and card_km is None:
        return None, "none"
    if card_km is None:
        return data_km, "data_only"
    if data_km is None:
        return card_km, "card_only"
    if abs(data_km - card_km) <= max(_KM_ABS, card_km * _KM_REL):
        return data_km, "agree"
    return None, "disagree"


def _make_model(cp: dict) -> tuple[str | None, str | None]:
    b = cp.get("brand") if isinstance(cp.get("brand"), dict) else {}
    m = cp.get("model") if isinstance(cp.get("model"), dict) else {}
    fa = " ".join(x for x in (_str(b.get("title")), _str(m.get("title"))) if x)
    mk, md = extract_make_model(fa) if fa else (None, None)
    if md:
        return mk, md
    en_b, en_m = _category(b.get("title_en")), _category(m.get("title_en"))
    if en_b and en_m:
        if en_m.lower().startswith(en_b.lower() + " "):
            en_m = en_m[len(en_b):].strip()
        return en_b, en_m
    return None, None


def build(r: dict, card: Card | None, trace: Khodro45Trace,
          learned: str | None, url_rule_ok: bool,
          prefix: str | None = "", forms: tuple = ("brand-model", "title_en")) -> CarListing:
    slug = _str(r.get("slug"))
    cp = r.get("car_properties") if isinstance(r.get("car_properties"), dict) else {}
    b = cp.get("brand") if isinstance(cp.get("brand"), dict) else {}
    m = cp.get("model") if isinstance(cp.get("model"), dict) else {}
    city = r.get("city") if isinstance(r.get("city"), dict) else {}
    spec = (r.get("car_specifications")
            if isinstance(r.get("car_specifications"), dict) else {})
    option, trim_raw = _str(cp.get("option")), _str(cp.get("trim"))
    spec_text = f"{option} {trim_raw}".strip()
    trace.price_types[str(r.get("price_type"))] += 1
    for c, v, key in ((trace.options, option, "option"), (trace.trims, trim_raw, "trim")):
        if v:
            _count(c, v, trace, key)
    _count(trace.brands, b.get("title_en"), trace, "brand")
    _count(trace.cities, city.get("title_en"), trace, "city")

    # the address: the card's, else the rule the cards confirmed
    path = card.href if card else None
    rp = rule_path(r, prefix, *forms)
    if card is not None:
        trace.url["rule agrees" if rp and rp == card.href else "rule differs"] += 1
    elif rp and url_rule_ok:
        path = rp
        trace.url["no card: by the rule"] += 1
    else:
        trace.url["no card: no url"] += 1
    url = KHODRO45_ORIGIN + path if path else ""

    price, p_status, p_prov, displayed, p_code, p_field = _price(r, card, learned)
    trace.price[p_code] += 1
    if p_code == "card shows neither":
        trace.odd["card price is neither field"].append(
            (_num(r.get("price")), _num(r.get("final_price")), displayed))
    if price is not None:
        if not classify_price_value(price).usable:
            trace.odd["price below the floor"].append((price,))
        trace.prices.append(price)

    raw_year = _num(cp.get("year"))
    c_year = _card_year(card)
    if raw_year and c_year and raw_year != c_year:
        trace.year["card differs"] += 1
        trace.odd["year differs"].append((raw_year, c_year))
        year = None
    else:
        y = raw_year or c_year
        trace.year["agree" if raw_year and c_year else "data_only" if raw_year
                   else "card_only" if c_year else "none"] += 1
        year = ld_year_jalali({"vehicleModelDate": y}) if y else None
        if y:
            trace.calendar["gregorian" if 1900 <= y <= 2100 else "jalali"
                           if 1300 <= y <= 1450 else "neither"] += 1

    data_km = _num(spec.get("klm"))
    card_km = _figure(card.km_text) if card else None
    km, m_code = _odometer(data_km, card_km)
    trace.mileage[m_code] += 1
    if m_code == "disagree":
        trace.odd["odometer differs"].append((data_km, card_km))
    if km is None:
        m_status, m_reason = Validity.UNKNOWN, (
            "structured and displayed odometer disagree" if m_code == "disagree"
            else "not stated")
    else:
        j = classify_mileage(km, year)
        m_status, m_reason = j.status, j.reason

    tags = [_str(t.get("title")) for t in (r.get("fmp_tags") or [])
            if isinstance(t, dict)]
    for t in tags:
        _count(trace.tags, t, trace, "tag")
    condition = extract_body_condition(" ".join(tags)) if tags else "unknown"

    make, model = _make_model(cp)
    name = " ".join(x for x in (_str(b.get("title")), _str(m.get("title"))) if x)
    pclass, psource = classify_product(name, from_canonical=True)
    loc = _str(city.get("title")) or None
    province = province_from_city(loc) if loc else None
    if p_status is PriceStatus.NEGOTIABLE:
        kind, kind_src = "negotiable", "rendered_negotiable_marker"
    elif price is not None:
        kind, kind_src = "cash", "no_contrary_evidence"
    else:
        kind, kind_src = "absent", "none"
    return CarListing(
        listing_id=slug, url=url, title=" ".join(x for x in (name, option) if x),
        description="", asking_price_toman=price,
        make=make, model=model,
        trim=extract_trim(f"{option} {trim_raw}") or _category(trim_raw),
        year_jalali=year, mileage_km=km,
        gearbox=extract_gearbox(spec_text), fuel=extract_fuel(spec_text), color=None,
        body_condition=condition,
        condition_source="field" if condition != "unknown" else "none",
        document_issue=None, city=province, seller_raw=None,
        price_raw=(str(r.get(p_field)) if p_field else None),
        price_currency_raw=None, price_displayed_toman=displayed,
        price_status=p_status.value, price_provenance=p_prov,
        mileage_status=m_status.value, mileage_note=m_reason,
        product_class=pclass, product_class_source=psource,
        price_kind=kind, price_kind_source=kind_src,
        seller_type="unknown",
        province_source="city" if province else "none",
        location_raw=loc, source_url=url or None,
        listed_at=_created(r.get("created_time"), trace),
    )


# ---------------------------------------------------------------------------
# One page, and a run of them
# ---------------------------------------------------------------------------

class Khodro45Parser:
    """One instance per run. Remembers the slugs it has returned, which field
    the cards showed and whether the cards' links follow the rule, so that a
    page of the API, which has no card, is read by what the cards of the same
    run said. `next_url` is the next page the last page named."""

    def __init__(self):
        self.seen: set[str] = set()
        self.traces: list[Khodro45Trace] = []
        self.listings: list[CarListing] = []
        self.shown: Counter = Counter()
        self.rule: Counter = Counter()
        self.prefixes: Counter = Counter()
        self.prefix_misses = 0
        self.forms: Counter = Counter()      # (segment, form) -> joined cards it fits
        self.pairs = 0                       # joined cards whose links were read
        self.next_url: str | None = None

    def learned_field(self) -> str | None:
        p, f = self.shown["price"], self.shown["final_price"]
        if p >= LEARN_MIN_CARDS and f == 0:
            return "price"
        if f >= LEARN_MIN_CARDS and p == 0:
            return "final_price"
        return None

    def learned_prefix(self) -> str | None:
        """The part of the cards' codes before the slug, when every joined
        card has the same one and three or more do; else None."""
        if (len(self.prefixes) == 1 and self.prefix_misses == 0
                and sum(self.prefixes.values()) >= LEARN_MIN_CARDS):
            return next(iter(self.prefixes))
        return None

    def learned_forms(self) -> tuple[str | None, str | None]:
        """(the first segment's form, the city's): the first of each that
        every joined card's link took, three or more of them; else None."""
        def one(segment, names):
            if self.pairs < LEARN_MIN_CARDS:
                return None
            return next((n for n in names if self.forms[(segment, n)] == self.pairs), None)
        return one("first", FIRST_FORMS), one("city", CITY_FORMS)

    def url_rule_ok(self) -> bool:
        return (self.rule["rule agrees"] >= LEARN_MIN_CARDS
                and self.rule["rule differs"] == 0)

    def __call__(self, text: str) -> list[CarListing]:
        tr = Khodro45Trace()
        self.traces.append(tr)
        self.next_url = None
        if not text:
            return []
        stripped = text.lstrip()
        cards: list[Card] = []
        if stripped[:1] in ("{", "["):
            try:
                data = json.loads(stripped)
            except ValueError:
                data = None
            tr.kind = "api" if data is not None else "none"
            pages = result_pages(data) if data is not None else []
        else:
            rows = page_rows(text)
            pages = result_pages(rows)
            tr.kind = "html" if pages else "none"
            cards = read_cards(text)
        tr.cards = len(cards)
        unique: list[Card] = []
        hrefs: set[str] = set()
        for c in cards:
            if c.href not in hrefs:
                hrefs.add(c.href)
                unique.append(c)
        by_slug: dict[str, Card] = {}
        for c in unique:
            s = slug_of(c.href)
            if s and s not in by_slug:
                by_slug[s] = c

        results: list[dict] = []
        got: set[str] = set()
        for pg in pages:
            if tr.count is None and _num(pg.get("count")) is not None:
                tr.count = _num(pg.get("count"))
            nxt = pg.get("next")
            nxt = nxt.strip() if isinstance(nxt, str) and nxt.strip() else None
            tr.lists.append((len(pg["results"]), next_view(nxt), where_is(nxt)))
            if nxt:
                https = ours_over_https(nxt)
                tr.next_upgraded += https != nxt
                self.next_url = _absolute(https)
            for r in pg["results"]:
                s = _str(r.get("slug")) if isinstance(r, dict) else ""
                if not _SLUG.match(s):
                    tr.skipped["no slug"] += 1
                    continue
                if s in got:
                    continue
                got.add(s)
                results.append(r)
        tr.next_shape = url_shape(self.next_url)
        tr.results = len(results)

        # Each result's card: by its slug first, and where no card's link ends
        # in it, by what both show. The owner's real page (2026-10-29) joined
        # 0 of 24 by the slug: its `slug` is not the code its card's link ends
        # in. The 24 cards are the 24 results, and an odometer and a year are
        # one car's on a page of 24 when no other result and no other card
        # has the same pair; where two have, neither is joined.
        join: dict[int, Card] = {}
        for i, r in enumerate(results):
            slug = _str(r.get("slug"))
            c = by_slug.get(slug)
            if c is None:
                # the owner's page ends its links in «cla-» and the slug in
                # another case (round K3): the one card whose code holds it
                held = [x for x in unique if _code_holds(slug_of(x.href), slug)]
                c = held[0] if len(held) == 1 else None
            if c is not None and id(c) not in {id(x) for x in join.values()}:
                join[i] = c
                tr.joined["slug"] += 1
        used = {id(c) for c in join.values()}
        by_rkey: dict[tuple, list[int]] = {}
        for i, r in enumerate(results):
            k = _result_key(r) if i not in join else None
            if k:
                by_rkey.setdefault(k, []).append(i)
        by_ckey: dict[tuple, list[Card]] = {}
        for c in unique:
            k = _card_key(c) if id(c) not in used else None
            if k:
                by_ckey.setdefault(k, []).append(c)
        for k, idx in by_rkey.items():
            if len(idx) == 1 and len(by_ckey.get(k, [])) == 1:
                c = by_ckey[k][0]
                join[idx[0]] = c
                used.add(id(c))
                tr.joined["odometer and year"] += 1
        # how each joined result's slug relates to its card's code, and the
        # part of the code before the slug, which is the address rule's
        for i, c in join.items():
            slug = _str(results[i].get("slug"))
            code = slug_of(c.href)
            tr.slug_relation[_relation(slug, code)] += 1
            shape = f"{_shape_of(slug)} / {_shape_of(code or '')}"
            if shape in tr.slug_shapes or len(tr.slug_shapes) < 6:
                tr.slug_shapes[shape] += 1
            if _code_holds(code, slug):
                self.prefixes[code[:len(code) - len(slug)].lower()] += 1
            else:
                self.prefix_misses += 1
            segs = c.href.strip("/").split("/")
            if len(segs) == 4:
                self.pairs += 1
                fs, cs = segment_forms(results[i])
                for segment, forms, seg in (("first", fs, segs[1]), ("city", cs, segs[2])):
                    hit = [n for n, v in forms.items() if v == seg]
                    for n in hit:
                        self.forms[(segment, n)] += 1
                        tr.rule_forms[f"{segment}: {n}"] += 1
                    if not hit:
                        ref = forms.get("brand-model" if segment == "first" else "title_en", "")
                        miss = f"{segment}: {_shape_of(seg)} vs {_shape_of(ref) or '(none)'}"
                        if miss in tr.rule_misses or len(tr.rule_misses) < 6:
                            tr.rule_misses[miss] += 1
        if len(join) < len(results):
            tr.joined["no card"] += len(results) - len(join)
        tr.cards_without_result = sum(1 for c in unique if id(c) not in used)

        # what the cards of this page show, before any result is built, so a
        # result without a card on the same page is read by them as well
        for i, r in enumerate(results):
            card = join.get(i)
            if card is None:
                continue
            shown = _shown_field(r, _card_price(card))
            if shown:
                tr.shown[shown] += 1
                self.shown[shown] += 1
            rp = rule_path(r, self.learned_prefix(), *self.learned_forms())
            self.rule["rule agrees" if rp and rp == card.href else "rule differs"] += 1

        fresh: list[CarListing] = []
        for i, r in enumerate(results):
            if r.get("active") is False:
                tr.skipped["not active"] += 1
                continue
            card = join.get(i)
            if card is None:
                tr.results_without_card += 1
            x = build(r, card, tr, self.learned_field(), self.url_rule_ok(),
                      self.learned_prefix(), self.learned_forms())
            if x.listing_id in self.seen:
                tr.duplicates += 1
                continue
            self.seen.add(x.listing_id)
            fresh.append(x)
        tr.emitted = len(fresh)
        self.listings.extend(fresh)
        return fresh


def parse_khodro45(text: str, trace_into: list | None = None) -> list[CarListing]:
    """The listings of one page (the list page or a page of the API), read
    on their own: a parser of one page, so the cards it holds are all it
    learns from."""
    p = Khodro45Parser()
    out = p(text)
    if trace_into is not None:
        trace_into.extend(p.traces)
    return out


# ---------------------------------------------------------------------------
# The adapter
# ---------------------------------------------------------------------------

@dataclass
class Khodro45Adapter(NextLinkAdapter):
    """Collects Khodro45's public list. No login, no contact, no rotation.

    The first page is `/buy-car/`; each next page is the one the page before
    named (`next`), asked for only if it is on the same origin and robots.txt
    allows it (caro/ingest/paging.py). The site's API serves those pages: what
    its own list loads when a visitor scrolls, asked for at the same pace as a
    page. Anything else ends the run, and the reason is kept in `stopped`.
    """
    origin: str = KHODRO45_ORIGIN
    start_url: str = LIST_URL
    name: str = "khodro45"


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------

def _b(v: int) -> str:
    return f"{v / 1e9:.2f}B"


def report(traces: list[Khodro45Trace]) -> list[str]:
    """Counts and categories only: no slug, no title, no listing's price
    except the smallest, the middle and the largest of those taken."""
    if not traces:
        return []
    L = ["", "KHODRO45 PAGE READ  (what each page was; counts and categories only)",
         "-" * 62]
    counts = [t.count for t in traces if t.count is not None]
    L.append(f"  pages {len(traces)}   listings {sum(t.emitted for t in traces)}"
             f"   results {sum(t.results for t in traces)}"
             f"   cards {sum(t.cards for t in traces)}"
             + (f"   the site's count {counts[0]}" if counts else ""))
    kinds = Counter(t.kind for t in traces)
    L.append("  read from      " + "  ".join(f"{k}:{v}" for k, v in kinds.most_common()))

    def line(label: str, attr: str, top: int = 8) -> None:
        c = Counter()
        for t in traces:
            c.update(getattr(t, attr))
        if c:
            L.append(f"  {label:<15}" + "  ".join(f"{k}:{v}" for k, v in c.most_common(top)))

    line("joined", "joined")
    line("slug vs code", "slug_relation")
    line("their shapes", "slug_shapes")
    line("card shows", "shown")
    line("price", "price")
    line("price type", "price_types")
    line("mileage", "mileage")
    line("year", "year")
    line("calendar", "calendar")
    line("url", "url")
    line("url forms", "rule_forms")
    line("url misses", "rule_misses")
    line("brand", "brands", 12)
    line("city", "cities", 12)
    line("tags", "tags", 12)
    line("option", "options", 12)
    line("trim", "trims", 12)
    created, missing = Counter(), Counter()
    for t in traces:
        created.update(t.created)
        missing.update(t.created_missing)
    if created or missing:
        days = sorted(created.items(), reverse=True)
        L.append(f"  {'created':<15}" + "  ".join(f"{d}:{n}" for d, n in days[:12])
                 + (f"  … {len(days) - 12} older dates" if len(days) > 12 else "")
                 + f"   unreadable {missing['unreadable']}   none {missing['none']}")
    prices = sorted(p for t in traces for p in t.prices)
    if prices:
        L.append(f"  asking price   min {_b(prices[0])}   median "
                 f"{_b(prices[len(prices) // 2])}   max {_b(prices[-1])}   (toman)")
    L.append(f"  next page      {traces[-1].next_shape}")
    for t in traces[-1:]:
        for n, view, where in t.lists:
            L.append(f"  a list of {n:<4} next {view}  ({where})")
        if t.next_upgraded:
            L.append("  the next page is given as http:// on khodro45.com and is asked "
                     "for as https://, the same host, path and query")
    for k, v in (("duplicates", sum(t.duplicates for t in traces)),
                 ("cards without a result", sum(t.cards_without_result for t in traces)),
                 ("results without a card", sum(t.results_without_card for t in traces))):
        if v:
            L.append(f"  {k:<24}{v}")
    sk, refused = Counter(), Counter()
    for t in traces:
        sk.update(t.skipped)
        refused.update(t.refused)
    for k, v in sk.most_common():
        L.append(f"  skipped: {k}: {v}")
    if refused:
        L.append("  not counted: " + "  ".join(f"{k} {v}" for k, v in sorted(refused.items())))
    odd = {k: [x for t in traces for x in t.odd[k]] for k in ODD_KINDS}
    if any(odd.values()):
        L += ["", "  odd cases (numbers only):"]
        for k, rows in odd.items():
            for row in rows[:_ODD_CAP]:
                L.append(f"    {k:<28}" + (f"{row[0]:,}" if len(row) == 1 else str(row)))
            if len(rows) > _ODD_CAP:
                L.append(f"    {k:<28}… and {len(rows) - _ODD_CAP} more")
    shown = Counter()
    for t in traces:
        shown.update(t.shown)
    if shown["price"] and shown["final_price"]:
        L.append("  ⚠ the cards show price on some listings and final_price on "
                 "others: a page of the API, with no card, gets no price.")
    other_types = sum(v for t in traces for k, v in t.price_types.items()
                      if _num(k) not in ACCEPTED_PRICE_TYPES)
    if other_types:
        L.append(f"  ⚠ {other_types} listing(s) of a price type other than 2 carry "
                 "no price: what that type means is not known. Read one such "
                 "card on the site and say.")
    return L
