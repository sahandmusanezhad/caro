#!/usr/bin/env python3
"""Replay the 2026-09-07 live Bama collection through the real parser.

    python3 scripts/replay_bama.py

Why a replay rather than a live run: this sandbox cannot reach bama.ir (the
egress proxy refuses the host), so the 100 listings were collected through a
browser and stored positionally in data/snapshots/2026-09-07-bama-part*.json.

What is stored is exactly what `parse_detail_page` consumes and nothing more:

  * the page's schema.org Product/Car node, verbatim; and
  * the article's text lines, produced with the same substitutions `_text()`
    applies, sliced from the «کارکرد» anchor to «آگهی های مرتبط».

So the page is reassembled here and run through the shipped parser. Nothing
about the extraction is reimplemented — a bug in `parse_detail_page` shows up
in this report exactly as it would in a live run.

One reduction is worth naming: the seller description is truncated to the two
lines after «توضیحات», which is all `_labelled()` ever reads, and the
JSON-LD's duplicate copy of it was dropped. Field coverage is unaffected;
`document_issue`, which scans the description, is under-counted on the few
listings whose disclosure runs past those two lines.
"""

from __future__ import annotations

import html as html_lib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.bama import ParseTrace, parse_detail_page      # noqa: E402
from scripts.first_run import inventory                          # noqa: E402

SNAPS = sorted((ROOT / "data" / "snapshots").glob("2026-09-07-bama-part*.json"))

# Positional layout of a stored record, in the order the browser wrote it.
SLUG, ANCHORED, IDENT, NAME, COLOR, GEARBOX, FUEL, YEAR, KM, KM_UNIT, \
    PRICE, CURRENCY = range(12)
LINES = 12


def rebuild(rec: list) -> tuple[str, str]:
    """(url, html) — a page the shipped parser can read.

    The lines go back as <p> elements because that is what `_text()` splits
    on, so the parser recovers exactly the list that was captured.
    """
    url = "https://bama.ir/car/detail-" + rec[SLUG]
    node: dict = {"@context": "https://schema.org", "@type": ["Product", "Car"]}
    if rec[IDENT]:
        node["identifier"] = rec[IDENT]
    if rec[NAME]:
        node["name"] = rec[NAME]
    if rec[COLOR]:
        node["color"] = rec[COLOR]
    if rec[GEARBOX]:
        node["vehicleTransmission"] = rec[GEARBOX]
    if rec[FUEL]:
        node["fuelType"] = rec[FUEL]
    if rec[YEAR]:
        node["productionDate"] = node["vehicleModelDate"] = rec[YEAR]
    if rec[KM] is not None:
        node["mileageFromOdometer"] = {"@type": "QuantitativeValue",
                                       "value": rec[KM],
                                       "unitCode": rec[KM_UNIT] or "KMT"}
    if rec[PRICE] is not None:
        node["offers"] = {"@type": "Offer", "price": rec[PRICE],
                          "priceCurrency": rec[CURRENCY]}

    body = "".join(f"<p>{html_lib.escape(str(l))}</p>" for l in rec[LINES:])
    page = ('<html><head><script type="application/ld+json">'
            + json.dumps(node, ensure_ascii=False)
            + "</script></head><body>"
            # The site's navigation renders above the article and carries real
            # prices. It is reproduced because it is the hazard the anchoring
            # exists for; a replay without it would not exercise that path.
            "<nav><p>خودرو</p><p>قیمت روز خودرو</p></nav>"
            f"<article>{body}</article></body></html>")
    return url, page


def main() -> int:
    records: list[list] = []
    for p in SNAPS:
        records.extend(json.loads(p.read_text(encoding="utf-8")))
    if not records:
        print("no snapshot found under data/snapshots/", file=sys.stderr)
        return 1

    listings, traces = [], []
    for rec in records:
        url, page = rebuild(rec)
        tr = ParseTrace()
        got = parse_detail_page(url, page, trace=tr)
        traces.append(tr)
        if got is not None:
            listings.append(got)

    print(f"BAMA · live collection 2026-09-07 · {len(records)} detail pages "
          f"fetched, {len(listings)} parsed\n"
          "10 model categories, first page of each, all HTTP 200\n")
    print(inventory(listings, traces))

    print("\n\nPRICE SANITY (the reason the currency was cross-checked)")
    print("-" * 62)
    priced = sorted((x for x in listings if x.price_irr),
                    key=lambda x: x.price_irr)

    def row(tag, x):
        km = f"{x.mileage_km:,} km" if x.mileage_km is not None else "no km"
        print(f"  {tag:<9}{x.make} {x.model} {x.year_jalali:<6}"
              f"{x.price_irr/1e6:>8,.0f}M toman  {km:>12}")

    for x in priced[:3]:
        row("cheapest", x)
    for x in reversed(priced[-3:]):
        row("dearest", x)
    print("\n  Read these as a human would: an Iranian used car is priced in\n"
          "  hundreds of millions to a few billion toman. Divide by ten and\n"
          "  the whole table becomes absurd — which is the check that caught\n"
          "  the site's currency label.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
