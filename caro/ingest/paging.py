"""
A list whose every page names the next one, asked for page by page.

Khodro45's list names its next page in the data (`next`, a page of the site's
API) and Sheypoor's in the markup (`rel=next`). The asking is the same for
both, and it is the asking that carries the rules, so it is written once:

    · robots.txt is read before the first page, and a first page it refuses
      raises: nothing is requested (caro/ingest/robots.py).
    · a next page is asked for only if it is on the same origin and robots.txt
      allows it; otherwise the run ends there and `stopped` says why.
    · a page that adds no new listing ends the run: the end of the list, a
      next page the site ignores, or a layout the parser no longer reads, and
      in all three the following page would be requests for no data.
    · a page that does not answer is an unknown outcome, never an absence, and
      the run ends: the next page is known only from it. No retry, no other way
      of asking.
    · the policy's pause follows every request.

The parser is an object called with a page's text, returning the new listings
of that page, with `next_url` set to the next page it named (or None).
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable, Iterator

from caro.ingest.divar_car import PolitenessPolicy
from caro.ingest.robots import RobotsGate
from caro.tracking import FetchOutcome, FetchStatus, classify_http


def url_shape(url: str | None) -> str:
    """A link as its path, digits as «#», and the names of its parameters."""
    if not url:
        return "(none)"
    path, _, query = re.sub(r"^https?://[^/]+", "", url).partition("?")
    names = [p.split("=", 1)[0] for p in query.split("&") if p]
    names = [n for n in names if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,24}", n)]
    return re.sub(r"\d+", "#", path) + ("?" + "&".join(names) if names else "")


@dataclass
class NextLinkAdapter:
    """Collects a public list by following the next page each page names.
    No login, no contact, no rotation."""
    origin: str = ""
    start_url: str = ""
    name: str = ""
    max_pages: int = 2
    policy: PolitenessPolicy = field(default_factory=PolitenessPolicy)
    salt: str | None = None
    page_fetcher: Callable[[str], tuple[int, str]] | None = None
    parser: object | None = None
    sleeper: Callable[[float], None] = time.sleep
    robots_fetcher: Callable[[str], tuple[int, str]] | None = None
    robots: RobotsGate = field(init=False, repr=False, compare=False)
    stopped: str | None = field(default=None, init=False, compare=False)

    def __post_init__(self):
        self.robots = RobotsGate(
            self.origin, self.robots_fetcher, source=self.name,
            pause=lambda: self.sleeper(self.policy.sleep()))

    def fetch_all(self, on: date) -> Iterator[FetchOutcome]:
        if self.page_fetcher is None or self.parser is None:
            raise RuntimeError(
                f"{type(self).__name__} needs a page_fetcher and a parser. Use "
                "http_fetcher() for live collection, or inject fixtures in "
                "tests. Refusing to guess.")
        url = self.start_url
        for page in range(1, self.max_pages + 1):
            if page == 1:
                self.robots.check(url)        # raises: nothing is requested
            elif not self.robots.allows(url):
                self.stopped = (f"the next page ({url_shape(url)}) is not "
                                "requested: robots.txt disallows it, or it is "
                                f"not on {self.origin}")
                return
            try:
                status, body = self.page_fetcher(url)
            except Exception:
                status, body = None, ""
            if classify_http(status) is FetchStatus.OK and body:
                got = self.parser(body)
                for x in got:
                    yield x.to_fetch_outcome(self.name, self.salt)
                if not got:
                    self.stopped = f"page {page} added no new listing"
                    return
                if page == self.max_pages:
                    return
                if not self.parser.next_url:
                    self.stopped = f"page {page} names no next page"
                    return
                url = self.parser.next_url
            else:
                # The next page is known only from this one, so the run ends
                # here. No retry and no other way of asking.
                yield FetchOutcome(
                    listing_id=f"__page__:{self.name}:{page}",
                    status=FetchStatus.UNKNOWN, http_status=status)
                self.stopped = (f"page {page} did not answer (http {status}); "
                                "the next page is known only from it")
                return
            self.sleeper(self.policy.sleep())
