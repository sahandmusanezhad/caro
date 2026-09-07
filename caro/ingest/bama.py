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
    normalize, parse_mileage_km, parse_price, parse_year_jalali,
)
from caro.tracking import FetchOutcome, FetchStatus, classify_http

SITEMAP_CAR = "https://bama.ir/sitemap/car"
BASE = "https://bama.ir"

_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# The boundary between this listing and the five unrelated cars below it.
RELATED_MARKER = "آگهی های مرتبط"

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


def parse_slug(url: str) -> dict:
    """Identity from the url alone, so it survives a failed page load."""
    m = _SLUG.search(url.split("?")[0].rstrip("/"))
    if not m:
        return {}
    rest = m.group("rest") or ""
    parts = [p for p in rest.split("-") if p]
    raw_model = parts[0] if parts else None
    return {
        "listing_id": m.group("id"),
        "make": SLUG_MAKES.get(m.group("make"), m.group("make").title()),
        "model": SLUG_MODELS.get(raw_model, raw_model),
        "raw_model_slug": raw_model,
        "trim": " ".join(parts[1:]) or None,
        "year_jalali": int(m.group("year")) if m.group("year") else None,
    }


# ---------------------------------------------------------------------------
# Detail page
# ---------------------------------------------------------------------------

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


def parse_detail_page(url: str, html: str) -> CarListing | None:
    """Parse ONE listing, truncated before the related-listings block.

    That truncation is not tidiness. Each detail page carries five other
    cars with their own prices and mileages; without the cut, the first
    price the parser meets after this car's might belong to a different
    vehicle — and nothing downstream could tell.
    """
    lines = _text(html)
    for i, ln in enumerate(lines):
        if RELATED_MARKER in normalize(ln):
            lines = lines[:i]
            break
    if not lines:
        return None

    slug = parse_slug(url)
    blob = " ".join(lines)

    price = None
    for i, ln in enumerate(lines):
        if normalize(ln) in ("تومان", "تومن") and i:
            price = parse_price(lines[i - 1])
            if price:
                break
    if price is None:
        price = parse_price(blob)

    mileage = None
    for ln in lines:
        if "کارکرد" in normalize(ln):
            mileage = parse_mileage_km(ln)
            break

    # Bama publishes body condition structurally. Prefer it; fall back to the
    # description only when the field is absent.
    body_field = _labelled(lines, "وضعیت بدنه")
    desc = _labelled(lines, "توضیحات") or ""
    condition = (extract_body_condition(body_field) if body_field
                 else extract_body_condition(desc))
    if body_field and condition == "unknown":
        # A stated value we do not recognise is not "unknown" in the same
        # sense as silence — record it so the lexicon can be extended.
        condition = "unknown"

    color = _labelled(lines, "رنگ بدنه") or ""
    gearbox_field = _labelled(lines, "گیربکس") or ""

    return CarListing(
        listing_id=slug.get("listing_id") or url.rsplit("-", 1)[-1],
        url=url,
        title=" ".join(lines[:4]),
        description=desc,
        price_irr=price,
        make=slug.get("make"),
        model=slug.get("model"),
        trim=slug.get("trim"),
        year_jalali=slug.get("year_jalali") or parse_year_jalali(blob),
        mileage_km=mileage,
        gearbox=extract_gearbox(gearbox_field) or extract_gearbox(blob),
        fuel=extract_fuel(blob),
        color=extract_color(color) or extract_color(blob),
        body_condition=condition,
        document_issue=has_document_issue(desc),
        city=_labelled(lines, "موقعیت") or None,
        seller_raw=None,          # the masked phone is never read
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
    on_listing: Callable[[CarListing], None] | None = None

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
            raise SourceBlocked(
                f"bama sitemap returned {status}; halting rather than "
                "falling back to crawling search pages")
        cats = [u for u in parse_sitemap(body) if is_category_url(u)]
        if self.only_makes:
            cats = [u for u in cats
                    if any(m in u.lower() for m in self.only_makes)]
        return cats[:self.max_categories]

    def discover_listings(self) -> list[str]:
        urls: list[str] = []
        for cat in self.discover_categories():
            status, html = self._get(cat)
            if classify_http(status) is FetchStatus.OK and html:
                urls.extend(extract_listing_links(html))
            self.sleeper(self.policy.sleep())
            if len(urls) >= self.max_listings:
                break
        seen, out = set(), []
        for u in urls:
            if u not in seen:
                seen.add(u)
                out.append(u)
        return out[:self.max_listings]

    def fetch_all(self, on: date) -> Iterator[FetchOutcome]:
        consecutive = 0
        for url in self.discover_listings():
            status, html = self._get(url)
            fs = classify_http(status)

            if fs is FetchStatus.OK and html:
                consecutive = 0
                listing = self.parse_detail(url, html)
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
