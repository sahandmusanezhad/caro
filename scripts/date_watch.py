#!/usr/bin/env python3
"""The same listings, every day, recorded — so the date's behaviour is measured.

    python3 scripts/date_watch.py                 # one observation round
    python3 scripts/date_watch.py --report        # read the file, fetch nothing

One question is open and only repetition closes it:

    Does the source-declared date ever move BACKWARDS?

`docs/DATE_SEMANTICS_2026-09-12.md` records one listing whose title date
moved forward. That refutes "publication date". It does NOT establish
monotonicity — a field seen to move forward once is a field that has moved,
not a field that only moves forward — and until monotonicity holds the date
cannot serve as an upper bound on anything, which is the only role the
temporal contract could have given it.

So: the same ids, the same fetcher, the same extraction, appended to one
file, day after day. Nothing is concluded here. The file accumulates and the
verdict comes from the file.

WHAT IS RECORDED PER LISTING PER ROUND

    listing_id  observed_at  http_status
    title_raw  title_decoded  title_date_raw  title_date_iso
    phrase_raw  phrase_days
    extraction_status            the vocabulary below, never inferred
    matched_substring            what the pattern actually matched
    extractor_version            so a rule change is visible in the series
    line_before / line_after     the province neighbourhood, EVERY page

EXTRACTION STATUS IS A VOCABULARY, NOT A BOOLEAN

This script has produced three confident wrong answers by treating "the
pattern did not match" as "the value is not there". Once the key regex was
too loose, once too strict, once blind to HTML entities. Each time a
no-match was printed as an absence.

    PRESENT              matched, and parsed
    PRESENT_BUT_UNPARSED found something date-shaped, could not read it
    MALFORMED            matched, and the value is impossible
    ABSENT_IN_SOURCE     the raw text is there and contains no date
    UNREADABLE           no usable response; says nothing about the source

`ABSENT_IN_SOURCE` is only ever claimed against a raw string that was
actually retrieved and is recorded beside the claim. Nothing else may be
called absent.

THE FILE

`data/observations/date_watch.jsonl`, append-only, one JSON object per
listing per round. Operational, like `data/snapshots/` — never published,
and it holds a truncated neighbouring line per page which may be arbitrary
page text. The corpus contract governs what is PUBLISHED; this is not that.
"""

from __future__ import annotations

import argparse
import html as _html
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARO_SELLER_SALT", "date-watch-collects-nothing")

from caro.corpus_reader import CorpusUnavailable, load_corpus     # noqa: E402
from caro.ingest.bama import (                                    # noqa: E402
    BamaAdapter, _text, http_fetcher,
)
from caro.tracking import FetchStatus, classify_http              # noqa: E402

OUT = ROOT / "data" / "observations" / "date_watch.jsonl"

# Bumped whenever an extraction rule changes, so a shift in the series can be
# told from a shift in the source. Three silent rule changes is how this file
# came to exist.
EXTRACTOR_VERSION = 2   # v2: month-name titles, rounds by observation

# One value for every record a single pass writes, so a round is identifiable
# without guessing from timestamps. Twenty polite requests span minutes.
ROUND_ID = datetime.now(timezone.utc).isoformat(timespec="seconds")

PRESENT = "PRESENT"
PRESENT_BUT_UNPARSED = "PRESENT_BUT_UNPARSED"
MALFORMED = "MALFORMED"
ABSENT_IN_SOURCE = "ABSENT_IN_SOURCE"
UNREADABLE = "UNREADABLE"

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.S)
_JDATE = re.compile(r"([۰-۹0-9]{4})\s*/\s*([۰-۹0-9]{1,2})\s*/\s*([۰-۹0-9]{1,2})")
# Anything date-shaped at all, used ONLY to tell "no date here" from "a date
# I could not read". It must know every form the source uses, because
# ABSENT_IN_SOURCE is the strongest claim this vocabulary makes.
#
# It was too narrow on its first outing and made that claim wrongly.
# Listing l39y2bdi's title changed mid-day from
#     «… فروشی - 1405/6/20 | باما»
# to
#     «… فروشی امروز شنبه 21 شهریور | باما»
# and, seeing no slash, the script recorded ABSENT_IN_SOURCE for a title
# that states its date in words. The raw title is stored beside the claim,
# which is the only reason this was caught rather than believed.
_MONTHS = ("فروردین|اردیبهشت|خرداد|تیر|مرداد|شهریور"
           "|مهر|آبان|آذر|دی|بهمن|اسفند")
_DATEISH = re.compile(
    r"[۰-۹0-9]{2,4}\s*[/\-.]\s*[۰-۹0-9]{1,2}"
    rf"|[۰-۹0-9]{{1,2}}\s*(?:{_MONTHS})"
    r"|امروز|دیروز")
_REL = re.compile(
    r"(لحظاتی پیش|دیروز|امروز"
    r"|[۰-۹0-9]{1,3}\s*(?:دقیقه|ساعت|روز|هفته|ماه|سال)\s*پیش)")
_MILEAGE = re.compile(r"^(کارکرد\s|صفر کیلومتر)")
_FA = str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789")

_UNIT_DAYS = {"دقیقه": 0, "ساعت": 0, "روز": 1, "هفته": 7, "ماه": 30, "سال": 365}
NOWRUZ = {1405: date(2026, 3, 21)}
_MONTH_LEN = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]


def jalali_to_iso(y: int, m: int, d: int) -> str | None:
    """Verified table only. A year outside it is refused, never extrapolated."""
    if y not in NOWRUZ or not (1 <= m <= 12) or not (1 <= d <= 31):
        return None
    from datetime import timedelta
    return (NOWRUZ[y] + timedelta(
        days=sum(_MONTH_LEN[:m - 1]) + d - 1)).isoformat()


def phrase_days(p: str) -> int | None:
    p = (p or "").strip()
    if p in ("امروز", "لحظاتی پیش"):
        return 0
    if p == "دیروز":
        return 1
    m = re.match(r"([۰-۹0-9]{1,3})\s*(دقیقه|ساعت|روز|هفته|ماه|سال)\s*پیش", p)
    return int(m.group(1).translate(_FA)) * _UNIT_DAYS[m.group(2)] if m else None


def observe(ad, url: str, lid: str) -> dict:
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    rec: dict = {"listing_id": lid, "observed_at": now, "url": url,
                 "round_id": ROUND_ID,
                 "extractor_version": EXTRACTOR_VERSION}
    status, raw = ad._get(url)
    rec["http_status"] = status
    fs = classify_http(status)
    rec["fetch"] = fs.value
    if fs is not FetchStatus.OK or not raw:
        rec["extraction_status"] = UNREADABLE
        return rec

    t = _TITLE.search(raw)
    title_raw = t.group(1).strip() if t else ""
    title = _html.unescape(title_raw)
    rec["title_raw"] = title_raw[:160]
    rec["title_decoded"] = title[:160]

    m = _JDATE.search(title)
    if m:
        rec["matched_substring"] = m.group(0)
        y, mo, d = (int(g.translate(_FA)) for g in m.groups())
        rec["title_date_raw"] = f"{y}/{mo}/{d}"
        iso = jalali_to_iso(y, mo, d)
        if iso:
            rec["title_date_iso"] = iso
            rec["extraction_status"] = PRESENT
        else:
            rec["extraction_status"] = MALFORMED
    elif _DATEISH.search(title):
        # Something date-shaped that the rule could not read. NOT absence.
        rec["extraction_status"] = PRESENT_BUT_UNPARSED
        rec["matched_substring"] = _DATEISH.search(title).group(0)
    else:
        # Claimed only against a title that was actually retrieved, and the
        # title is recorded above so the claim is checkable.
        rec["extraction_status"] = ABSENT_IN_SOURCE

    lines = _text(raw)
    rp = _REL.search(raw)
    rec["phrase_raw"] = rp.group(1).strip() if rp else None
    rec["phrase_days"] = phrase_days(rec["phrase_raw"] or "")

    # The province neighbourhood, anchored on the MILEAGE line so it is
    # recorded for every page and not only the ones carrying a phrase — which
    # is the 26% gap that makes the phrase unusable as an anchor.
    for i, ln in enumerate(lines):
        if _MILEAGE.match(ln.strip()):
            rec["mileage_line"] = ln.strip()[:40]
            rec["line_after_1"] = (lines[i + 1].strip()[:40]
                                   if i + 1 < len(lines) else None)
            rec["line_after_2"] = (lines[i + 2].strip()[:40]
                                   if i + 2 < len(lines) else None)
            break
    return rec


def load_rounds() -> dict[str, list[dict]]:
    by_id: dict[str, list[dict]] = defaultdict(list)
    if OUT.exists():
        for line in OUT.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                by_id[r["listing_id"]].append(r)
    return by_id


def report(by_id: dict[str, list[dict]]) -> int:
    # A ROUND is an observation, not a calendar day. Keying on the date
    # threw away a real second round taken six hours later and reported
    # "1 round — nothing can be said", which was false: two observations
    # are two observations whatever the clock says.
    #
    # The INTERVAL is printed with them, because it decides what the
    # comparison is worth. Eighteen unchanged dates over six hours is much
    # weaker evidence than the same over six days, and a reader must not
    # have to work that out.
    stamps = sorted({r["observed_at"] for rs in by_id.values() for r in rs})
    # A ROUND is one pass over the sample, not one minute and not one day.
    # Keying on the minute reported "6 rounds" for two passes, because
    # twenty polite requests take several minutes to make. The exact count
    # is how many times the most-observed listing was seen; no clustering
    # heuristic can be wrong about that.
    n_rounds = max(len(v) for v in by_id.values()) if by_id else 0
    rounds = list(range(n_rounds))
    print("DATE WATCH")
    print("=" * 66)
    print(f"  file        {OUT}")
    print(f"  listings    {len(by_id)}")
    print(f"  observations{sum(len(v) for v in by_id.values()):>5}")
    print(f"  rounds      {n_rounds}   first {stamps[0]}")
    if len(stamps) > 1:
        span = (datetime.fromisoformat(stamps[-1])
                - datetime.fromisoformat(stamps[0])).total_seconds()
        print(f"              {' ' * 8}last  {stamps[-1]}")
        print(f"  span        {span / 3600:.1f} hours "
              f"({span / 86400:.2f} days)")
    print()
    if len(rounds) < 2:
        print("  One round. Nothing can be said about movement yet — that is")
        print("  the point of the file, not a fault in it. Run it again.")
        return 0

    back = fwd = same = nodata = 0
    backwards: list[tuple[str, str, str]] = []
    rendering: list[str] = []
    for lid, rs in sorted(by_id.items()):
        ordered = sorted(rs, key=lambda r: r["observed_at"])
        # A listing whose title CHANGED FORMAT has no iso on one side and
        # would otherwise vanish into "no data" — which is what happened to
        # the only listing that actually moved. Named separately.
        if (len(ordered) >= 2
                and bool(ordered[0].get("title_date_iso"))
                != bool(ordered[-1].get("title_date_iso"))):
            rendering.append(
                f"{lid}: {ordered[0].get('extraction_status')} -> "
                f"{ordered[-1].get('extraction_status')}")
        seq = [r for r in ordered if r.get("title_date_iso")]
        if len(seq) < 2:
            nodata += 1
            continue
        for a, b in zip(seq, seq[1:]):
            if b["title_date_iso"] < a["title_date_iso"]:
                back += 1
                backwards.append((lid, a["title_date_iso"], b["title_date_iso"]))
            elif b["title_date_iso"] > a["title_date_iso"]:
                fwd += 1
            else:
                same += 1

    print("MONOTONICITY — the open question")
    print("-" * 66)
    print(f"  transitions forward    {fwd}")
    print(f"  transitions unchanged  {same}")
    print(f"  transitions BACKWARD   {back}")
    print(f"  listings with <2 dates {nodata}")
    if rendering:
        print()
        print("  TITLE CHANGED RENDERING — not comparable as dates, and not")
        print("  'no data'. Look at these by hand:")
        for line in rendering[:10]:
            print(f"    {line}")
    print()
    if back:
        print("  NOT MONOTONIC. Proved by:")
        for lid, a, b in backwards[:10]:
            print(f"    {lid:<24}{a} -> {b}")
        print()
        print("  The date cannot be an upper bound on anything, and the")
        print("  temporal contract gets nothing from it.")
    else:
        print("  No backward transition observed across "
              f"{fwd + same} transition(s).")
        print("  That is consistent with monotonicity and does not prove it.")
        print("  It is the same shape of evidence as 'no shift detected' on a")
        print("  sample too small to detect one.")
    print()

    st = Counter(r.get("extraction_status") for rs in by_id.values() for r in rs)
    print("EXTRACTION STATUS across every observation")
    print("-" * 66)
    for k, n in st.most_common():
        print(f"  {k:<24}{n:>5}")
    print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-corpus", default="run11")
    ap.add_argument("--sample", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--report", action="store_true",
                    help="read the file and say what it shows; fetch nothing")
    a = ap.parse_args()

    if a.report:
        return report(load_rounds())

    try:
        art = load_corpus(a.from_corpus)
    except (CorpusUnavailable, ValueError) as e:
        print(f"cannot read corpus {a.from_corpus!r}:\n{e}", file=sys.stderr)
        return 2

    rows = [r for r in art.get("listings", []) if r.get("source_url")]
    random.Random(a.seed).shuffle(rows)
    rows = rows[:a.sample]

    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=1, max_categories=1)
    OUT.parent.mkdir(parents=True, exist_ok=True)

    print(f"observing {len(rows)} listing(s) from {a.from_corpus}, seed "
          f"{a.seed} — the same set every round")
    written = 0
    with OUT.open("a", encoding="utf-8") as fh:
        for r in rows:
            rec = observe(ad, r["source_url"], str(r.get("listing_id", "")))
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            written += 1
            ad.sleeper(ad.policy.sleep())
    print(f"appended {written} observation(s) to {OUT}")
    print()
    return report(load_rounds())


if __name__ == "__main__":
    raise SystemExit(main())
