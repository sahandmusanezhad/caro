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
import html as _html
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
# Anywhere in the title, any separator. The first version required a
# hyphen immediately before the date; the browser renders
# «… فروشی - 1405/6/19 | باما», but bidirectional text and a non-ASCII
# dash make "immediately before" a guess. It matched nothing on 19 of
# 19 pages and the run could not tell a missing date from a missed one.
_TITLE_DATE = re.compile(
    r"([۰-۹0-9]{4})\s*/\s*([۰-۹0-9]{1,2})\s*/\s*([۰-۹0-9]{1,2})")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_LD = re.compile(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S)
# NARROW, and narrowed the hard way. The first version matched
# `date|time|publish|modif|creat|updat` anywhere in a key name and
# duly reported "json-ld only: 19" — on `productionDate` and
# `vehicleModelDate` (the CAR'S MODEL YEAR), `publisher`,
# `accelerationTime` and `creator`. Not one of them is a listing date.
# The probe gave a confident wrong answer to the exact question it was
# built to ask, which is worse than returning nothing.
#
# These are the schema.org names that actually denote when an offer or
# a posting was made. Anything else is printed for a human to look at
# rather than counted as a date.
_DATEKEY = re.compile(
    r"^(datePosted|datePublished|dateModified|dateCreated|uploadDate"
    r"|validFrom|validThrough|availabilityStarts)$")
# The relative phrases the cards and the detail page render.
_REL = re.compile(
    r"(لحظاتی پیش|دیروز|امروز"
    r"|[۰-۹0-9]{1,3}\s*(?:دقیقه|ساعت|روز|هفته|ماه|سال)\s*پیش)")
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")


_UNIT_DAYS = {"دقیقه": 0, "ساعت": 0, "روز": 1, "هفته": 7, "ماه": 30,
              "سال": 365}

# Nowruz, per Jalali year, as a Gregorian date. A TABLE, not an algorithm.
#
# A general Jalali converter is twenty lines of leap-year cycle arithmetic
# and is exactly the kind of code that is subtly wrong and confidently
# wrong — which this script has now managed twice by other means. Every
# entry here is checked against a fact established independently: on
# 2026-09-11 listing thhvbl5m rendered «دیروز» beside a title date of
# 1405/6/19, so 1405/6/19 is 2026-09-10, and the first six Jalali months
# are 31 days each, so 1405/1/1 is 173 days earlier.
#
# A year not in this table is refused rather than extrapolated.
NOWRUZ = {1405: date(2026, 3, 21)}
_MONTH_LEN = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]


def jalali_to_gregorian(y: int, m: int, d: int) -> date | None:
    """None when the year is not in the verified table. Never a guess."""
    if y not in NOWRUZ or not (1 <= m <= 12) or not (1 <= d <= 31):
        return None
    from datetime import timedelta
    return NOWRUZ[y] + timedelta(days=sum(_MONTH_LEN[:m - 1]) + d - 1)


def days_ago(phrase: str) -> int | None:
    """How many days back the relative phrase points. None if unreadable.

    This is what answers question two WITHOUT a Jalali calendar. A listing
    that was live on the corpus's collected_on has existed at least that
    long; if its own phrase says less, the date it states moved after the
    listing was already up, and it is not a publication date.

    Hours and minutes collapse to 0 — same day — which is deliberate: the
    comparison is in whole days and pretending to finer resolution would
    invent precision the phrase does not carry.
    """
    p = phrase.strip()
    if not p:
        return None
    if p == "امروز" or p == "لحظاتی پیش":
        return 0
    if p == "دیروز":
        return 1
    m = re.match(r"([۰-۹0-9]{1,3})\s*(دقیقه|ساعت|روز|هفته|ماه|سال)\s*پیش", p)
    if not m:
        return None
    return int(m.group(1).translate(_FA)) * _UNIT_DAYS[m.group(2)]


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
    titles: list[tuple[str, str]] = []         # id, the raw <title>
    no_phrase: list[tuple[str, int, bool]] = []  # id, bytes, had a spec row
    ld_all_keys: Counter = Counter()
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
        # UNESCAPED. The title carries «1405&#x2F;6&#x2F;19» — the slashes
        # are HTML entities, so a regex looking for "/" matched nothing and
        # the run reported "neither: 19" while the date was on every page.
        # Third confident wrong answer from this file; the raw-title print
        # added in the previous fix is what caught it, which is the only
        # reason it is not still being reported as absent.
        title = _html.unescape(t.group(1).strip()) if t else ""
        md = _TITLE_DATE.search(title)
        tdate = ""
        if md:
            y, m, d = (int(g.translate(_FA)) for g in md.groups())
            tdate = f"{y}/{m:02d}/{d:02d}"

        allk, datek = ld_date_keys(html)
        for k in datek:
            ld_date_fields[k] += 1
        # Every key, not just the ones a pattern likes. The narrowed
        # matcher can only find names it was told about, and the whole
        # point is to see what the source actually publishes.
        ld_all_keys.update(k.split(".")[-1] for k in allk)
        titles.append((lid, title))

        rel = _REL.search(html)
        relative = rel.group(1).strip() if rel else ""
        if not relative:
            # A page with no phrase is either a shell or a different
            # template, and which one changes what can be built on this.
            # «گیربکس» is a spec row every full page has.
            no_phrase.append((lid, len(html), "گیربکس" in html))
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
    if ld_all_keys:
        print(f"  every json-ld key name seen ({len(ld_all_keys)} distinct):")
        print("    " + ", ".join(sorted(ld_all_keys))[:600])
        print()
    if ld_date_fields:
        print("  LISTING-date key paths:")
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
        print()
    else:
        since = (date.today() - date.fromisoformat(collected)).days
        print(f"  The corpus was collected {since} day(s) ago, so every")
        print("  listing below has existed at least that long. A phrase")
        print(f"  pointing back FEWER than {since} days is a date that moved")
        print("  after the listing was already up — which a publication date")
        print("  cannot do. No Jalali conversion is involved; this is whole")
        print("  days either way.")
        print()
        anchor = jalali_to_gregorian(1405, 6, 19)
        print(f"  calendar self-check: 1405/6/19 -> {anchor}"
              f"   {'ok' if anchor == date(2026, 9, 10) else 'WRONG — STOP'}")
        print()
        print(f"  {'listing':<20}{'title date':<21}{'phrase':<13}"
              f"{'title':<9}phrase")
        t_moved = t_stable = t_unknown = 0
        p_moved = p_stable = p_unknown = 0
        for lid, td, rel in seen[:30]:
            # The phrase
            d = days_ago(rel)
            if d is None:
                pv, p_unknown = "—", p_unknown + 1
            elif d < since:
                pv, p_moved = "MOVED", p_moved + 1
            else:
                pv, p_stable = "stable", p_stable + 1
            # The title date, through the verified table
            g = None
            if td:
                y, mm, dd = (int(x) for x in td.split("/"))
                g = jalali_to_gregorian(y, mm, dd)
            if g is None:
                tv, t_unknown = "—", t_unknown + 1
            elif (date.today() - g).days < since:
                tv, t_moved = "MOVED", t_moved + 1
            else:
                tv, t_stable = "stable", t_stable + 1
            shown = f"{td} = {g}" if g else (td or "—")
            print(f"  {lid:<20}{shown:<21}{rel or '—':<13}{tv:<9}{pv}")
        print()
        print(f"  TITLE DATE   moved {t_moved} · stable {t_stable} · "
              f"unreadable {t_unknown}")
        print(f"  PHRASE       moved {p_moved} · stable {p_stable} · "
              f"absent {p_unknown}")
        print()
        print("  If these two columns disagree they are two different")
        print("  fields, and only the stable one can be a first_seen_on.")
        moved = p_moved
        print()
        if moved:
            print(f"  {moved} listing(s) state a date later than a day they")
            print("  were demonstrably already live. That is proof, not")
            print("  evidence: this field tracks the start of the CURRENT")
            print("  listing spell — a bump or a renewal — and not first")
            print("  publication.")
        else:
            print("  Nothing moved in this sample. That is evidence of")
            print("  stability and NOT proof of it; a sample that happens to")
            print("  hold no renewed listing looks exactly like this.")
        print()

    if titles:
        print("  the raw <title>, so a missing date can be told from a missed one")
        for lid, t in titles[:6]:
            print(f"    {lid:<22}{t[:70]}")
        print()

    if no_phrase:
        print("  pages with NO relative phrase at all")
        print("  " + "-" * 64)
        for lid, n, full in no_phrase:
            print(f"    {lid:<22}{n:>9,} bytes   "
                  f"{'full page' if full else 'SHELL — no spec rows'}")
        print()
        print("    A full page with no phrase is a second template and the")
        print("    positional rule below does not cover it. A shell is a")
        print("    fetch that did not get the content, which is a different")
        print("    problem and not a fact about the source.")
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
