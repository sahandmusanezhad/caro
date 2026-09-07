"""
Bama adapter — sitemap-first, because Bama asks to be crawled that way.

Verified from https://bama.ir/robots.txt on 2026-09-07:

    User-agent: *
    Sitemap: https://bama.ir/sitemap/car
    Sitemap: https://bama.ir/sitemap/car-filters
    Sitemap: https://bama.ir/sitemap/dealer
    Sitemap: https://bama.ir/sitemap/price
    ...
    Disallow: /uploads/Bamalmages/CampaignBanner/
    Disallow: temp.bama.ir/robots.txt

Nothing relevant to car listings is disallowed, and the site publishes a
**car sitemap**. That is a published discovery mechanism, and it changes the
design rather than merely permitting the old one:

  · No scroll-and-guess pagination. The sitemap enumerates listing urls, so
    coverage is knowable instead of estimated.
  · Far fewer requests for the same coverage — one index fetch replaces
    dozens of search-page loads.
  · No browser needed for discovery. Playwright is only required where a
    detail page turns out to be client-rendered.

Using a search-result crawler here when the site hands you an index would be
both ruder and worse. The politest path is also the more complete one, which
is not always true and is worth taking when it is.

Role in CARO: `primary_offers`. Bama is car-specialist, so its structured
fields are the richest available and its schema is the one the others are
mapped onto.
"""

from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterator, Sequence

from caro.ingest.divar_car import (
    CarListing, PolitenessPolicy, SourceBlocked, parse_listing,
)
from caro.tracking import FetchOutcome, FetchStatus, classify_http

SITEMAP_CAR = "https://bama.ir/sitemap/car"
SITEMAP_PRICE = "https://bama.ir/sitemap/price"

# Sitemaps are XML; the namespace is boilerplate but omitting it silently
# returns zero urls, which looks exactly like an empty site.
_SM_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}


def parse_sitemap(xml_text: str) -> list[str]:
    """Extract urls from a sitemap or a sitemap index.

    Handles both shapes, and falls back to a regex when the document is
    malformed — a partial url list beats an exception, provided the caller
    knows the count may be short.
    """
    try:
        root = ET.fromstring(xml_text.strip())
    except ET.ParseError:
        return re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml_text)
    locs = [e.text.strip() for e in root.findall(".//sm:loc", _SM_NS)
            if e.text and e.text.strip()]
    if not locs:                      # namespace-less document
        locs = [e.text.strip() for e in root.iter()
                if e.tag.endswith("loc") and e.text and e.text.strip()]
    return locs


def is_listing_url(url: str) -> bool:
    """A car detail page, not a filter, dealer or price-guide page.

    The car sitemap mixes them, and a price-guide page is emphatically not an
    offer — letting one into the corpus teaches the appraiser from a number
    nobody is actually asking.
    """
    return bool(re.search(r"/car/detail-", url))


@dataclass
class BamaAdapter:
    """Sitemap discovery, then detail fetches, with the same stop-on-block rule.

    `fetcher` returns (status_code, text) and is injected, so every path here
    is testable without the network.
    """
    name: str = "bama"
    max_listings: int = 200
    policy: PolitenessPolicy = field(default_factory=PolitenessPolicy)
    salt: str | None = None
    fetcher: Callable[[str], tuple[int, str]] | None = None
    parse_detail: Callable[[str, str], CarListing | None] | None = None
    sleeper: Callable[[float], None] = time.sleep
    sitemap_url: str = SITEMAP_CAR

    def discover(self) -> list[str]:
        """Listing urls from the published sitemap."""
        if self.fetcher is None:
            raise RuntimeError("BamaAdapter needs a fetcher. Refusing to guess.")
        status, body = self.fetcher(self.sitemap_url)
        if classify_http(status) is not FetchStatus.OK:
            raise SourceBlocked(
                f"bama sitemap returned {status}; halting rather than "
                "falling back to crawling search pages")
        urls = [u for u in parse_sitemap(body) if is_listing_url(u)]
        return urls[:self.max_listings]

    def fetch_all(self, on: date) -> Iterator[FetchOutcome]:
        if self.fetcher is None or self.parse_detail is None:
            raise RuntimeError(
                "BamaAdapter needs a fetcher and parse_detail. Refusing to guess.")

        consecutive = 0
        for i, url in enumerate(self.discover()):
            try:
                status, html = self.fetcher(url)
            except Exception:
                status, html = None, ""

            fs = classify_http(status)
            if fs is FetchStatus.OK and html:
                consecutive = 0
                listing = self.parse_detail(url, html)
                if listing is not None:
                    yield listing.to_fetch_outcome(self.name, self.salt)
            elif fs is FetchStatus.ABSENT:
                # A 404 on a url the sitemap advertised is a real absence: the
                # listing was there when the index was built and is gone now.
                # This is the one place an ABSENT is genuinely earned.
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
                        f"consecutive failures; halting")

            self.sleeper(self.policy.sleep())


def listing_id_from_url(url: str) -> str:
    m = re.search(r"/car/detail-([\w-]+)", url)
    return m.group(1) if m else url.rsplit("/", 1)[-1]
