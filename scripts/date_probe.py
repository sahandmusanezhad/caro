#!/usr/bin/env python3
"""Where does bama's date live, what does it mean, and how precise is it?

    python3 scripts/date_probe.py --from-corpus run11 --sample 20

Three questions, one run, on listings whose state YESTERDAY is already
recorded in a published artifact. That last part is what makes question two
answerable at all.

    1. WHERE      json-ld, <title>, both, or neither. The parser reads
                  `ld.get("name")` and never reads the title tag, so today it
                  sees no date at all — but which of the two carries it
                  decides whether this is a one-line change or a new
                  extraction path.

    2. WHAT IT MEANS   publication, or last modification. These differ
                  exactly on the listings that matter most: a renewed or
                  reposted ad almost certainly resets a modification date and
                  does not reset a publication date.

    3. GRANULARITY     hours on a fresh listing, days on an old one, and what
                  a month-old listing actually publishes.

HOW QUESTION TWO IS ANSWERED WITHOUT WAITING A DAY

A single fetch cannot separate publication from modification: whatever date
comes back is consistent with both. What separates them is a listing whose
existence at an EARLIER time is already on record.

Every listing in a published corpus was live on that corpus's
`collected_on`. So if one of them now carries a date LATER than
`collected_on`, that date cannot be its publication date — the listing
demonstrably existed before it. One such row is proof. Zero such rows across
a sample is evidence of stability and NOT proof of it, and this script says
so rather than rounding the distinction away.

WHAT IT PRINTS

Extracted dates, relative-age phrases, and counts. Not titles, not
descriptions, not prices — the date is the subject and everything else on
those pages is seller-authored or beside the point.

POLITENESS

One request per sampled listing, through the same adapter and the same sleep
the collector uses. `--sample` defaults to 20 because twenty is enough to see
a pattern and a hundred is not twenty times more informative.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARO_SELLER_SALT", "date-probe-collects-nothing")

from caro.corpus_reader import CorpusUnavailable, load_corpus     # noqa: E402
from caro.ingest.bama import (                                    # noqa: E402
    BamaAdapter, _text, http_fetcher,
)
from caro.tracking import FetchStatus, classify_http              # noqa: E402

# `… - 1405/6/19 | باما` in the document title.
_TITLE_DATE = re.compile(r"[-–]\s*([۰-۹0-9]{4})/([۰-۹0-9]{1,2})/([۰-۹0-9]{1,2})")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
_DATEKEY = re.compile(r"date|time|publish|modif|creat|updat", re.I)
# The relative phrases the cards and the detail page render.
_REL = re.compile(
    r"(لحظاتی پیش|دیروز|امروز"
    r"|[۰-۹0-9]{1,3}\s*(?:دقیقه|ساعت|روز|هفته|ماه|سال)\s*پیش)")
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


def jalali(y: int, m: int, d: int) -> tuple[int, int, int]:
    return (y, m, d)


def ld_date_keys(html: str) -> tuple[list[str], list[str]]:
    """(every key path in the ld blocks, the date-ish ones)."""
    allk: list[str] = []
    for block in _LD.findall(html):
        try:
            obj = json.loads(block)
        except json.JSONDecodeError:
            continue

        def walk(o, p=""):
            if isinstance(o, dict):
                for k, v in o.items():
                    q = f"{p}.{k}" if p else k
                    allk.append(q)
                    walk(v, q)
            elif isinstance(o, list) and o:
                walk(o[0], f"{p}[0]")
        walk(obj)
    return allk, [k for k in allk if _DATEKEY.search(k.split(".")[-1])]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-corpus", default="run11")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    try:
        art = load_corpus(a.from_corpus)
    except (CorpusUnavailable, ValueError) as e:
        print(f"cannot read corpus {a.from_corpus!r}:\n{e}", file=sys.stderr)
        return 2

    collected = art.get("collected_on")
    rows = [r for r in art.get("listings", []) if r.get("source_url")]
    random.Random(a.seed).shuffle(rows)
    rows = rows[:a.sample]

    print("DATE PROBE")
    print("=" * 66)
    print(f"  corpus               {a.from_corpus}   collected_on {collected}")
    print(f"  sampled              {len(rows)} of "
          f"{len(art.get('listings', []))}   (seed {a.seed})")
    print(f"  today                {date.today().isoformat()}")
    print()
    print("  Every listing below was LIVE on the collected_on above. That is")
    print("  the whole leverage: a date later than it cannot be a publication")
    print("  date.")
    print()

    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=1, max_categories=1)

    where = Counter()
    rel_forms = Counter()
    ld_date_fields = Counter()
    gone = 0
    unreadable = 0
    seen: list[tuple[str, str, str]] = []      # id, title-date, relative
    # (id, line before, the relative line, line after) — the evidence for
    # the positional rule that would replace the missing «موقعیت» label.
    neighbourhood: list[tuple[str, str, str, str]] = []

    for r in rows:
        lid = str(r.get("listing_id", ""))[:24]
        status, html = ad._get(r["source_url"])
        fs = classify_http(status)
        if fs is FetchStatus.ABSENT:
            gone += 1
            continue
        if fs is not FetchStatus.OK or not html:
            unreadable += 1
            continue

        t = _TITLE.search(html)
        title = t.group(1).strip() if t else ""
        md = _TITLE_DATE.search(title)
        tdate = ""
        if md:
            y, m, d = (int(g.translate(_FA)) for g in md.groups())
            tdate = f"{y}/{m:02d}/{d:02d}"

        allk, datek = ld_date_keys(html)
        for k in datek:
            ld_date_fields[k] += 1

        rel = _REL.search(html)
        relative = rel.group(1).strip() if rel else ""
        if relative:
            # Bucket by unit, not by number: "3 روز پیش" and "9 روز پیش" are
            # the same granularity and counting them apart hides the shape.
            unit = re.sub(r"[۰-۹0-9]+\s*", "", relative).strip()
            rel_forms[unit or relative] += 1

        if tdate and datek:
            where["both title and json-ld"] += 1
        elif tdate:
            where["title only"] += 1
        elif datek:
            where["json-ld only"] += 1
        else:
            where["neither"] += 1

        seen.append((lid, tdate, relative))

        # Lines exactly as the parser sees them, so the rule is designed
        # against `_text(html)` and not against a browser's rendering.
        lines = _text(html)
        for i, ln in enumerate(lines):
            if _REL.fullmatch(ln.strip()):
                neighbourhood.append((
                    lid,
                    lines[i - 1].strip() if i else "",
                    ln.strip(),
                    lines[i + 1].strip() if i + 1 < len(lines) else ""))
                break

        ad.sleeper(ad.policy.sleep())

    print("1. WHERE THE DATE LIVES")
    print("-" * 66)
    for k, n in where.most_common():
        print(f"  {k:<28}{n:>4}")
    print()
    if ld_date_fields:
        print("  date-ish json-ld key paths:")
        for k, n in ld_date_fields.most_common(10):
            print(f"    {k:<50}{n:>4}")
    else:
        print("  no date-ish key in any json-ld block.")
        print("  -> the parser cannot reach this by extending the ld read;")
        print("     it needs the title, which nothing currently parses.")
    print()

    print("2. PUBLICATION OR LAST MODIFICATION")
    print("-" * 66)
    print(f"  fetched ok           {len(seen)}")
    print(f"  gone (404/410)       {gone}   ← absence, observed for once")
    print(f"  unreadable           {unreadable}")
    print()
    if not collected:
        print("  corpus states no collected_on; this test cannot run.")
    else:
        print(f"  Listings whose date is LATER than {collected}'s Jalali")
        print("  equivalent were modified after they were already live.")
        print("  Convert by hand if needed — this script does not carry a")
        print("  Jalali calendar, and a wrong conversion here would produce a")
        print("  confident wrong answer about the whole question.")
    print()
    print(f"  {'listing':<26}{'title date':<14}relative")
    for lid, td, rel in seen[:25]:
        print(f"  {lid:<26}{td or '—':<14}{rel or '—'}")
    print()

    print("3b. THE LINE AROUND THE RELATIVE PHRASE  (why province is empty)")
    print("-" * 66)
    print("  `province` is 0 of 76 on run 11 because `parse_detail_page` reads")
    print("  _labelled(lines, \"موقعیت\") and the page renders the location")
    print("  with NO label. What it appears to have instead is a position:")
    print("  between the relative-age line and the price. Confirmed here")
    print("  across the sample, or not — a positional rule that holds on one")
    print("  page is a coincidence.")
    print()
    print(f"  {'listing':<22}{'before':<22}{'REL':<14}after")
    for lid, before, rel, after in neighbourhood[:25]:
        print(f"  {lid:<22}{before[:20]:<22}{rel[:12]:<14}{after[:24]}")
    print()
    print(f"  relative phrase located in {len(neighbourhood)} of {len(seen)} "
          f"pages")
    print()

    print("3. GRANULARITY")
    print("-" * 66)
    if rel_forms:
        for k, n in rel_forms.most_common():
            print(f"  {k:<28}{n:>4}")
    else:
        print("  no relative phrase matched.")
    print()
    print("  A title date is day-granular by construction. The relative")
    print("  phrase is what carries anything finer, and it is the thing that")
    print("  degrades as a listing ages.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
