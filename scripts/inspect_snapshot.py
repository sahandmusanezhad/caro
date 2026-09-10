#!/usr/bin/env python3
"""Pull the listings worth reading by hand out of a snapshot.

    python3 scripts/inspect_snapshot.py data/snapshots/<date>/<file>.json

A run report gives rates. Deciding whether a rate is a fact about the source
or a defect in the parser needs the PAGE, and until now nothing pointed from
a snapshot back at one.

It reconstructs the address from the listing id, which is the only handle a
FetchOutcome carries: `url` is not on the record, so `promote_corpus`
publishes no url and `corpus_reader` reads a key nothing writes. That is the
same shape as `price_currency_raw` in the field-survival census — a field the
schema offers and the live path cannot fill — and it is why this script
rebuilds the address instead of reading it. If bama does not resolve a
detail url without its slug tail, the id is still what you search for.

Deliberately three lists and no verdicts: the cheapest rows, because an
implausible price is the first thing to open; the rows with no price, which
are the `no offers block` pages; and the seller-type split, which decides
whether `seller_type: unknown` is the source's limit or ours.
"""
import json, sys
from pathlib import Path

p = Path(sys.argv[1] if len(sys.argv) > 1 else "")
if not p.exists():
    print("usage: inspect_snapshot.py <snapshot.json>"); raise SystemExit(2)
recs = json.loads(p.read_text(encoding="utf-8")).get("outcomes", [])
ok = [r for r in recs if r.get("status") == "ok"]

def url(r):
    lid = str(r.get("listing_id") or "")
    return "https://bama.ir/car/detail-" + lid.split(":", 1)[-1]

priced = sorted((r for r in ok if r.get("asking_price_toman")),
                key=lambda r: r["asking_price_toman"])
print(f"{len(recs)} records · {len(ok)} ok · {len(priced)} priced\n")

print("CHEAPEST FIVE  (an implausible price is the one to open first)")
for r in priced[:5]:
    print(f"  {r['asking_price_toman']/1e9:>7.3f}B  {r.get('make')} "
          f"{r.get('model')} {r.get('year_jalali')}  {url(r)}")

noprice = [r for r in ok if not r.get("asking_price_toman")]
print(f"\nNO PRICE  ({len(noprice)}) — the `no offers block` pages")
for r in noprice[:5]:
    print(f"           {r.get('make')} {r.get('model')} "
          f"{r.get('year_jalali')}  {url(r)}")

dealers = [r for r in ok if r.get("seller_type") == "dealer"]
print(f"\nSELLER TYPE  dealer:{len(dealers)}  "
      f"other:{len(ok) - len(dealers)}  — open any row above and look for a")
print("  dealership block: a Bama tenure badge, a showroom address, union")
print("  membership. If none of them is on the page, seller_type=unknown is")
print("  the SOURCE's limit, not the parser's.")
