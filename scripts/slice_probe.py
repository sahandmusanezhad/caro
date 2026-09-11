#!/usr/bin/env python3
"""How big is the pinned slice, and how deep does a category page go?

    python3 scripts/slice_probe.py
    python3 scripts/slice_probe.py --url https://bama.ir/car/pride-131

ONE request. It fetches a single category page and reports what the page
says about ITS OWN SIZE — nothing else. No detail pages, no snapshot, no
corpus, no second page. Run it, paste the output, and the collector for
step 5 gets designed from that instead of from an assumption.

WHY THIS QUESTION GATES EVERYTHING ELSE

`discover_listings` fetches each pinned category URL exactly once. Bama
orders those pages by recency, so what we collect is the newest ~10 per
category, and `docs/REPLICATE_2026-09-10.txt` measured the consequence:
13.2% of the sample turned over in under an hour under an identical pin.

That number is why §10 of the temporal contract says the axis cannot open
with this collector. `observed_appearance` is defined as *we watched it
appear*, and a listing that shows up in tomorrow's draw may simply have
been on page 2 today. It is only sound when discovery ENUMERATES THE
SLICE — sees everything in it, every time. Otherwise every row is
left-truncated forever, §3's rule bars left-truncated rows from the test
half, and there is no temporal evaluation to be had at any number of days.

So the design question is not "cohort or deeper discovery". It is:

    how many listings are in the pinned slice, and how many requests does
    enumerating it cost per day?

Three hundred is thirty pages and a rounding error against the politeness
budget. Eight thousand is a different collector, and possibly a different
slice. Guessing which picks the architecture by accident.

WHAT IT PRINTS, AND WHAT IT DELIBERATELY DOES NOT

Structure only: how many detail links the page holds, the pagination
controls it exposes, and any total-count text. No listing prose, no
titles, no descriptions — the corpus contract forbids publishing
seller-authored text and a diagnostic is not an exemption from it.

The pagination parameter is READ, not assumed. This file does not know
whether bama paginates with `?page=`, `?p=`, an offset, or a "load more"
call, and inventing one would produce a confident wrong answer about the
slice size. It reports the hrefs and the numeric hints it can see, and a
person reads them.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARO_SELLER_SALT", "slice-probe-collects-nothing")

from caro.ingest.bama import (                                    # noqa: E402
    BASE, BamaAdapter, extract_listing_links, http_fetcher,
)
from caro.tracking import FetchStatus, classify_http              # noqa: E402

DEFAULT = "https://bama.ir/car/pride-131"

# Anything that looks like it addresses another page of the same list.
_PAGING = re.compile(
    r'href="([^"#]*?(?:page|pagination|offset|skip|from)=[^"&]*)"', re.I)
# A digits-only run next to a Persian noun for results. Deliberately narrow:
# a loose pattern over a listing page matches prices, years and mileages,
# and this must not report one of those as a corpus size.
_COUNT = re.compile(
    r"([۰-۹0-9][۰-۹0-9,٬\s]{0,12})\s*(?:آگهی|خودرو|نتیجه|مورد)")
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT)
    a = ap.parse_args()

    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=1, max_categories=1)
    status, html = ad._get(a.url)

    print("SLICE PROBE — one request, structure only")
    print("=" * 62)
    print(f"  url                  {a.url}")
    print(f"  http                 {status}  -> "
          f"{classify_http(status).value}")
    if classify_http(status) is not FetchStatus.OK or not html:
        print("\n  Nothing to read. This is a fact about the fetch, not about "
              "the slice.")
        return 1
    print(f"  bytes                {len(html):,}")
    print()

    links = extract_listing_links(html)
    print("WHAT ONE PAGE HOLDS")
    print("-" * 62)
    print(f"  detail links         {len(links)}")
    print(f"  distinct             {len(set(links))}")
    print()
    print("  If the whole slice is this and no more, the collector needs no")
    print("  pagination at all — and the 13.2% churn means the slice is")
    print("  turning over, not that we are sampling it.")
    print()

    print("PAGINATION CONTROLS THE PAGE EXPOSES")
    print("-" * 62)
    paging = sorted(set(m if m.startswith("http") else BASE + m
                        for m in _PAGING.findall(html)))
    if paging:
        for u in paging[:20]:
            print(f"    {u}")
        if len(paging) > 20:
            print(f"    … and {len(paging) - 20} more")
    else:
        print("    none found in the HTML.")
        print()
        print("    That does NOT mean there is one page. It means the list is")
        print("    probably extended by a script call rather than by links,")
        print("    and the next thing to look at is the network tab, not this")
        print("    file. Do not infer a slice size from this line.")
    print()

    print("NUMBERS THE PAGE STATES NEXT TO A RESULT NOUN")
    print("-" * 62)
    hits = Counter(m.strip().translate(_FA).replace(",", "").replace("٬", "")
                   for m in _COUNT.findall(html))
    if hits:
        for val, n in hits.most_common(8):
            print(f"    {val:>12}   seen {n}x")
        print()
        print("    One of these may be the slice size. None of them is")
        print("    confirmed to be — they are matches, not a parsed field.")
    else:
        print("    none.")
    print()

    print("WHAT THIS DOES NOT TELL YOU")
    print("-" * 62)
    print("  · whether page 2 exists, and what it costs to reach")
    print("  · whether the order is recency or something else")
    print("  · how long a listing stays inside the observable window")
    print()
    print("  Those need a second request each, and each is a separate")
    print("  decision about how much to ask of the source. This file asks")
    print("  once, on purpose.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
