#!/usr/bin/env python3
"""
Replay Run 3 through the shipped parser and the frozen gates.

    python3 scripts/replay_run3.py

Collected live 2026-09-07 from bama.ir. The gate definitions in
`caro/ingest/quality.py` and `caro/ingest/coverage.py` were frozen BEFORE
collection (docs/DATA_CONTRACT.md) and are untouched by this script — it
varies the sampling and reads the verdict, which is the whole design.

Snapshot shape, one row per listing, positional:

    0  slug            full detail slug, so make/model/year parse as in production
    1  anchored        the page carried a «کارکرد» line
    2  dealer          a trade badge was present (D26)
    3  ld_year         JSON-LD vehicleModelDate / productionDate
    4  ld_km           JSON-LD mileageFromOdometer.value
    5  ld_price        JSON-LD offers.price, verbatim
    6  ld_currency     JSON-LD offers.priceCurrency, verbatim
    7  km_line         the «کارکرد …» line as rendered
    8  price_text      the price rendered to buyers, or «توافقی»
    9  condition       the «وضعیت بدنه» value as rendered
   10  desc            first line after «توضیحات», truncated to 70 chars

Every judgement — currency reconciliation, mileage plausibility, the
condition lexicon, slug → make/model, eligibility, degeneracy — is made by
the Python code under test. The snapshot carries only what the site printed.

One transfer-side reduction is recorded rather than hidden: the description
is truncated to 70 characters, so `document_issue` (which scans the seller's
prose for «سند در گرو») is under-detected on listings whose disclosure runs
past that. It is not part of any gate in this run.
"""

from __future__ import annotations

import html as html_lib
import json
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.bama import ParseTrace, parse_detail_page          # noqa: E402
from caro.ingest import stratification                            # noqa: E402
from scripts.run3_matrix import compare                              # noqa: E402

SNAP = ROOT / "data" / "snapshots" / "run3"

SLUG, ANCHORED, DEALER, YEAR, KM, PRICE, CUR, KM_LINE, PRICE_TEXT, COND, DESC \
    = range(11)


def rebuild(rec: list) -> tuple[str, str]:
    """A page the shipped parser reads exactly as it would a live one."""
    url = "https://bama.ir/car/detail-" + rec[SLUG]
    node: dict = {"@context": "https://schema.org", "@type": ["Product", "Car"]}
    node["identifier"] = rec[SLUG].split("-")[0]
    if rec[YEAR]:
        node["productionDate"] = node["vehicleModelDate"] = rec[YEAR]
    if rec[KM] is not None:
        node["mileageFromOdometer"] = {"@type": "QuantitativeValue",
                                       "value": rec[KM], "unitCode": "KMT"}
    if rec[PRICE] is not None:
        node["offers"] = {"@type": "Offer", "price": rec[PRICE],
                          "priceCurrency": rec[CUR]}

    lines: list[str] = []
    if rec[KM_LINE]:
        lines.append(rec[KM_LINE])
    if rec[PRICE_TEXT] == "توافقی":
        lines.append("قیمت توافقی")
    elif rec[PRICE_TEXT]:
        lines += [rec[PRICE_TEXT], "تومان"]
    if rec[COND]:
        lines += ["وضعیت بدنه", rec[COND]]
    if rec[DESC]:
        lines += ["توضیحات", rec[DESC]]
    if rec[DEALER]:
        lines.append("3 سال فعالیت مداوم در باما")

    body = "".join(f"<p>{html_lib.escape(str(x))}</p>" for x in lines)
    return url, ('<html><head><script type="application/ld+json">'
                 + json.dumps(node, ensure_ascii=False)
                 + '</script></head><body>'
                 # navigation, with a real price in it, as the live page has
                 '<nav><p>خودرو</p><p>قیمت روز خودرو</p>'
                 '<p>1,234,567,890</p><p>تومان</p></nav>'
                 f'<article>{body}</article></body></html>')


def main() -> int:
    rows = json.loads((SNAP / "listings.json").read_text(encoding="utf-8"))
    flags = (SNAP / "arms.txt").read_text(encoding="utf-8").strip()
    if len(flags) != len(rows):
        print(f"arm flags ({len(flags)}) do not match rows ({len(rows)})",
              file=sys.stderr)
        return 1

    arms: dict[str, list] = {"depth": [], "variation": []}
    traces = []
    parsed = []
    for rec, flag in zip(rows, flags):
        url, page = rebuild(rec)
        tr = ParseTrace()
        got = parse_detail_page(url, page, trace=tr)
        traces.append(tr)
        if got is None:
            continue
        parsed.append(got)
        if flag in ("d", "b"):
            arms["depth"].append(got)
        if flag in ("v", "b"):
            arms["variation"].append(got)

    print("RUN 3 — bama.ir, collected 2026-09-07")
    print("=" * 78)
    print("Design frozen before collection. The gates are inputs, not outputs.\n")
    print(f"  detail pages fetched   {len(rows)}")
    print(f"  parsed                 {len(parsed)}")
    print(f"  depth arm              {len(arms['depth'])}")
    print(f"  variation arm          {len(arms['variation'])}")
    print()

    # The depth arm's ceiling was measured in the pre-flight and is a fact
    # about the access route, so it is declared here rather than inferred
    # from the counts — inferring it would let a route limit masquerade as a
    # statement about the market.
    acquisition = {
        "depth": (False,
                  "the /car/<slug>-page-N route saturates at ~20 distinct "
                  "listings per model (pride: 10,10,3,1,0,0 new per page). "
                  "This arm CANNOT reach 30 by construction — a ceiling of "
                  "the route, not of the market."),
        "variation": (True, ""),
    }
    print(compare(arms, fetched={"depth": len(arms["depth"]),
                                 "variation": len(arms["variation"])},
                  acquisition=acquisition))

    print("\n".join(stratification.report(parsed)))

    print("\n\nWHAT THE SAMPLE IS MADE OF")
    print("-" * 62)
    src = Counter("dealer" if x.seller_type == "dealer" else "unknown"
                  for x in parsed)
    print(f"  seller signal        {dict(src)}   (diagnostic only — D27)")
    off_target = [x for x in parsed
                  if x.make not in ("Saipa", "IKCO", "Peugeot")]
    print(f"  off-target listings  {len(off_target)}  "
          f"{sorted({f'{x.make} {x.model}' for x in off_target})[:6]}")
    print("    Category pages carry promoted cars from other models. They are")
    print("    parsed correctly and grouped under their own make, so they")
    print("    dilute nothing — but they inflate raw discovery counts, which")
    print("    is why the per-model ladder is the number that matters.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
