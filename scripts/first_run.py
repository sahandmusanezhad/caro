#!/usr/bin/env python3
"""
First live collection, and the inventory report that decides what comes next.

    python3 scripts/first_run.py --source bama --limit 50
    python3 scripts/first_run.py --source divar --city tehran --pages 2
    python3 scripts/first_run.py --replay data/snapshots/2026-09-07-bama.json

This is deliberately small. The point of a first run is not volume — it is
finding out how much of what the parser expects is actually there. A field
that is populated 40% of the time changes the appraisal design; a field that
is populated 95% of the time does not.

What it prints is the W0 inventory: fill rate and garbage rate per field,
comparable-tier coverage, and the condition distribution. Those numbers
decide whether the corpus can support an estimate at all, and they should be
read before any model is fitted.

Raw responses are written to data/snapshots/ so every later run can be
replayed offline. Re-parsing a saved snapshot costs nothing and asks the site
for nothing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.bama import (                                       # noqa: E402
    BamaAdapter, DiscoveryUnavailable, http_fetcher,
)
from caro.ingest.divar_car import (                                     # noqa: E402
    DivarCarAdapter, SourceBlocked, parse_listing, playwright_fetcher,
)
from caro.tracking import FetchStatus, Snapshot, assess_integrity, write_snapshot  # noqa: E402

SNAPSHOT_DIR = ROOT / "data" / "snapshots"

# Fields whose absence changes the design, in the order they matter.
TRACKED = ["price_irr", "year_jalali", "mileage_km", "make", "model",
           "trim", "gearbox", "fuel", "color", "body_condition"]


def _garbage(field: str, value) -> bool:
    """Values that are present but meaningless.

    A price of 1 and a mileage of 0 are the two classic placeholder values on
    Iranian marketplaces — sellers use them to mean "ask me". Counting them as
    populated would make the corpus look far healthier than it is, which is
    the specific way a field inventory usually lies.
    """
    if value is None:
        return False
    if field == "price_irr":
        return value < 10_000_000          # under 10M toman is not a car
    if field == "mileage_km":
        return value < 0 or value > 1_500_000
    if field == "year_jalali":
        return not (1350 <= value <= 1410)
    if field == "body_condition":
        return value == "unknown"
    return isinstance(value, str) and not value.strip()


def inventory(listings: list) -> str:
    n = len(listings)
    if not n:
        return "no listings parsed — nothing to report"

    L = [f"CORPUS INVENTORY  ({n} listings)", "=" * 62, "",
         f"{'field':<18}{'filled':>9}{'garbage':>9}{'usable':>9}", "-" * 62]
    for f in TRACKED:
        vals = [getattr(x, f, None) for x in listings]
        filled = sum(1 for v in vals if v is not None)
        garbage = sum(1 for v in vals if _garbage(f, v))
        usable = filled - garbage
        flag = "  <-- thin" if usable / n < 0.6 else ""
        L.append(f"{f:<18}{filled / n:>8.0%}{garbage / n:>9.0%}"
                 f"{usable / n:>9.0%}{flag}")

    L += ["", "MODEL COVERAGE  (a tier needs ~30+ to price against)", "-" * 62]
    models = Counter(f"{x.make} {x.model}" for x in listings if x.model)
    for name, c in models.most_common(12):
        bar = "#" * min(30, c)
        L.append(f"  {name:<22}{c:>4}  {bar}")
    thin = sum(1 for _, c in models.items() if c < 30)
    L.append(f"  {len(models)} models, {thin} of them under 30 listings")

    top = models.most_common(1)
    if top and top[0][1] / n > 0.7:
        L.append(f"  ⚠ {top[0][1] / n:.0%} of the corpus is one model "
                 f"({top[0][0]}). Field rates below describe that model, not "
                 "the market.")

    L += ["", "BODY CONDITION  (the field no filter exposes)", "-" * 62]
    cond = Counter(x.body_condition for x in listings)
    for k in ("intact", "minor_paint", "multi_paint", "replaced_part",
              "accident", "unknown"):
        c = cond.get(k, 0)
        L.append(f"  {k:<18}{c:>4}{c / n:>7.0%}  {'#' * min(30, c)}")
    if cond.get("unknown", 0) / n > 0.5:
        L.append("  ⚠ over half the listings disclose no condition. The risk "
                 "layer is mostly blind on this corpus; say so in EVAL.md "
                 "rather than treating silence as 'intact'.")

    prices = sorted(x.price_irr for x in listings
                    if x.price_irr and not _garbage("price_irr", x.price_irr))
    if prices:
        q = lambda p: prices[int(p * (len(prices) - 1))]          # noqa: E731
        L += ["", "PRICE DISTRIBUTION (toman)", "-" * 62,
              f"  min {q(0)/1e9:>6.2f}B   p25 {q(.25)/1e9:>6.2f}B   "
              f"median {q(.5)/1e9:>6.2f}B   p75 {q(.75)/1e9:>6.2f}B   "
              f"max {q(1)/1e9:>6.2f}B"]

    L += ["", "VERDICT", "-" * 62]
    ok_price = sum(1 for x in listings if x.price_irr
                   and not _garbage("price_irr", x.price_irr)) / n
    big_models = sum(1 for _, c in models.items() if c >= 30)
    if ok_price < 0.8:
        L.append("  NOT READY — under 80% usable prices. Fix extraction "
                 "before fitting anything.")
    elif big_models == 0:
        L.append("  NOT READY for appraisal — no model has 30+ listings. "
                 "Collect more, or narrow to fewer models.")
    else:
        L.append(f"  Ready to benchmark on {big_models} model(s) with enough "
                 "support. Run tests/run_all.py, then fit on this corpus.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["bama", "divar"], default="bama")
    ap.add_argument("--city", default="tehran")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--pages", type=int, default=2)
    ap.add_argument("--replay", type=Path,
                    help="parse a saved snapshot instead of fetching")
    args = ap.parse_args()

    if not args.replay and not os.environ.get("CARO_SELLER_SALT"):
        print("CARO_SELLER_SALT is not set.\n"
              "  export CARO_SELLER_SALT=\"$(head -c 24 /dev/urandom | base64)\"\n"
              "An unsalted hash of a phone number is a phone number, so the "
              "hash helper refuses to run without one.", file=sys.stderr)
        return 2

    listings: list = []
    if args.replay:
        raw = json.loads(args.replay.read_text(encoding="utf-8"))
        for r in raw.get("listings", []):
            listings.append(parse_listing(
                r["listing_id"], r["url"], r.get("title", ""),
                r.get("description", ""), price_text=r.get("price_text", ""),
                mileage_text=r.get("mileage_text", ""),
                year_text=r.get("year_text", ""), city=r.get("city")))
        print(f"replayed {len(listings)} listings from {args.replay}\n")
    else:
        print(f"collecting from {args.source} — politely, and stopping if "
              f"asked to.\n")
        try:
            listings = collect(args)
        except DiscoveryUnavailable as e:
            # We could not look. That is emphatically not "there is nothing".
            print(f"\nDISCOVERY UNAVAILABLE: {e}\n"
                  "No corpus was collected, and no conclusion about the "
                  "market follows from that. Try again later.", file=sys.stderr)
            return 1
        except SourceBlocked as e:
            # Not a failure to work around. It is the designed behaviour and
            # it belongs in the run log.
            print(f"\nHALTED: {e}\n"
                  "This is the adapter working as intended. Record it in "
                  "docs/DATA_SOURCES.md and try again later or with a "
                  "smaller limit.", file=sys.stderr)
            if not listings:
                return 1
        except ImportError:
            print("playwright is not installed. In your venv:\n"
                  "  pip install playwright && playwright install chromium",
                  file=sys.stderr)
            return 2

    print(inventory(listings))
    return 0


def collect(args) -> list:
    """Live collection. Kept separate so main() stays readable."""
    out: list = []

    if args.source == "divar":
        def parse_page(_html):
            raise NotImplementedError(
                "Divar's listing-page selectors are not written yet. The "
                "adapter, robots guard and politeness policy are; what is "
                "missing is the DOM extraction, which has to be written "
                "against the live markup. Start with --source bama.")
        ad = DivarCarAdapter(city=args.city, max_pages=args.pages,
                             page_fetcher=playwright_fetcher(),
                             parse_page=parse_page,
                             salt=os.environ["CARO_SELLER_SALT"])
        list(ad.fetch_all(date.today()))
        return out

    # The sitemap and Bama's pages are server-rendered, so plain HTTP is
    # correct here. Driving a browser to download static XML costs seconds and
    # a Chromium process per request for nothing.
    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=args.limit,
                     max_categories=max(1, args.limit // 20 + 1),
                     salt=os.environ["CARO_SELLER_SALT"],
                     on_listing=out.append)

    records = list(ad.fetch_all(date.today()))
    print(ad.stats.report())
    print()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap = assess_integrity(Snapshot(
        f"{args.source}-{date.today().isoformat()}", date.today(), records))
    path = write_snapshot(SNAPSHOT_DIR, snap)
    print(f"{len(out)} listings parsed · snapshot "
          f"{path.relative_to(ROOT)} (integrity: {snap.integrity.value})\n")
    return out


if __name__ == "__main__":
    raise SystemExit(main())
