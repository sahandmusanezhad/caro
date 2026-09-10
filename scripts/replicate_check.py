#!/usr/bin/env python3
"""Two snapshots, same pin, same day. What moved that the market cannot have?

    python3 scripts/replicate_check.py \
        data/snapshots/2026-09-10/bama-2026-09-10-a07d10-3.json \
        data/snapshots/2026-09-10/bama-2026-09-10-a07d10-4.json

Every run of `first_run.py` prints counts, and two runs printing different
counts looks like the market moving. It is not. Between two runs an hour
apart with an identical `--makes/--seed/--limit`, ANY difference is the
source's ordering, the source's churn, and our own sampler — and none of
those is a market fact (D36).

That difference is a NOISE FLOOR, and without it a day-to-day change has no
scale to be read against. "Eligible went 71 → 69" means nothing until you
know whether 2 is large.

Two independent things get measured, because they fail independently and
only one of them is alarming:

    SAMPLE STABILITY   do the two runs even draw the same listings?
                       Churn here is the sampler and the source's page
                       ordering. It bounds what a day-to-day delta can mean.

    FIELD STABILITY    for the listings BOTH runs drew, does the parser
                       produce the same values? Churn here is a parser
                       defect or a source edit, and on a one-hour interval
                       it should be zero. If it is not, no corpus from this
                       collector is reproducible and nothing else in this
                       report matters.

Deliberately NOT a pass/fail gate. It reports a floor; what counts as
tolerable is a claim about the collector, and this file does not make one.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# The salt never reaches a comparison here — nothing in this file reads a
# fingerprint. It is set because importing the ingest package refuses to
# emit an unsalted one, and a diagnostic must not be the thing that teaches
# someone to unset that guard.
os.environ.setdefault("CARO_SELLER_SALT", "replicate-check-not-a-corpus")

from caro.ingest.quality import eligibility                         # noqa: E402


class _FromRecord:
    """The attributes `eligibility` reads, straight off a snapshot record.

    Not a CarListing, for the same reason `reconcile_corpus` refuses one: a
    dataclass would supply defaults for whatever the record omits, and a
    default is precisely what hides the difference this file looks for.
    """

    _FIELDS = ("asking_price_toman", "year_jalali", "mileage_km", "model",
               "price_status", "mileage_status", "product_class", "price_kind")

    def __init__(self, rec: dict):
        for f in self._FIELDS:
            setattr(self, f, rec.get(f))


# Fields that describe the CAR. Between two runs an hour apart these cannot
# legitimately move: a seller editing an ad is possible but rare, and a
# nonzero count here is a finding either way.
STABLE_FIELDS = ("year_jalali", "mileage_km", "make", "model", "trim",
                 "body_condition", "product_class", "price_kind",
                 "price_status", "mileage_status", "seller_type")


def index(snap: dict) -> dict[str, dict]:
    return {str(o["listing_id"]): o for o in snap.get("outcomes", [])
            if isinstance(o, dict) and o.get("status") == "ok"}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("first", type=Path)
    ap.add_argument("second", type=Path)
    a = ap.parse_args()

    for p in (a.first, a.second):
        if not p.exists():
            print(f"no such snapshot: {p}", file=sys.stderr)
            return 2

    A = json.loads(a.first.read_text(encoding="utf-8"))
    B = json.loads(a.second.read_text(encoding="utf-8"))

    if A.get("snapshot_id") != B.get("snapshot_id"):
        print("NOTE: different snapshot_id, so these are not the same pin.")
        print(f"  {A.get('snapshot_id')}  vs  {B.get('snapshot_id')}")
        print("  The numbers below then mix sampler churn with a changed "
              "sample specification,\n  and the floor they report is not a "
              "floor for anything.\n")

    x, y = index(A), index(B)
    kx, ky = set(x), set(y)
    both, only_x, only_y = kx & ky, kx - ky, ky - kx

    ex = {k for k in kx if eligibility(_FromRecord(x[k]))[0]}
    ey = {k for k in ky if eligibility(_FromRecord(y[k]))[0]}

    # THE INTERVAL IS NOT KNOWN, and this file says so rather than printing a
    # number that looks like one.
    #
    # `Snapshot.taken_on` is a `date`. Two runs an hour apart carry the same
    # value, so a snapshot cannot order itself against another from the same
    # day — the identical defect as a flat `first_seen_ordinal`, one level
    # down. The only clock left is the file's mtime, and mtime is not
    # evidence: `cp`, a fresh checkout, and rsync all rewrite it. The first
    # version of this file printed an mtime interval as fact and reported
    # "0.0 h apart" for two runs an hour apart, because a copy had flattened
    # both to the same second.
    ta = datetime.fromtimestamp(a.first.stat().st_mtime)
    tb = datetime.fromtimestamp(a.second.stat().st_mtime)
    gap = abs((tb - ta).total_seconds())
    same_day = A.get("taken_on") == B.get("taken_on")

    print("SAME-PIN REPLICATE")
    print("=" * 66)
    print(f"  {a.first.name}")
    print(f"  {a.second.name}")
    print(f"  snapshot_id          {A.get('snapshot_id')}")
    print(f"  taken_on             {A.get('taken_on')}  and  {B.get('taken_on')}"
          f"   {'(the same day)' if same_day else ''}")
    print(f"  interval             UNKNOWN — a snapshot records a DATE, not a "
          f"time")
    print(f"    file mtime says    {ta:%Y-%m-%d %H:%M:%S} → {tb:%H:%M:%S}, "
          f"{gap / 3600:.1f} h")
    print(f"    which is not evidence: a copy or a checkout rewrites it")
    print()

    print("SAMPLE STABILITY   (the market cannot move this; only we can)")
    print("-" * 66)
    print(f"  ok records           {len(x):>4}  and {len(y):>4}")
    print(f"  drawn by both        {len(both):>4}   "
          f"{len(both) / max(1, len(kx)):.0%} of the first")
    print(f"  only in the first    {len(only_x):>4}")
    print(f"  only in the second   {len(only_y):>4}")
    churn = (len(only_x) + len(only_y)) / max(1, len(kx) + len(ky))
    print(f"  churn                {churn:>5.1%}   symmetric difference")
    print()

    print("ELIGIBILITY")
    print("-" * 66)
    print(f"  eligible, first      {len(ex):>4}")
    print(f"  eligible, second     {len(ey):>4}")
    out = sorted((ex & both) - ey)
    into = sorted((ey & both) - ex)
    print(f"  flipped out (shared) {len(out):>4}")
    print(f"  flipped in  (shared) {len(into):>4}")
    for k in out[:10]:
        print(f"      {k:<22}now: {'; '.join(eligibility(_FromRecord(y[k]))[1])}")
    for k in into[:10]:
        print(f"      {k:<22}was: {'; '.join(eligibility(_FromRecord(x[k]))[1])}")
    print()

    print("FIELD STABILITY   (on the listings both runs drew)")
    print("-" * 66)
    moved, identical, absent = [], 0, 0
    for k in sorted(both):
        pa, pb = x[k].get("asking_price_toman"), y[k].get("asking_price_toman")
        if pa is None or pb is None:
            absent += 1
        elif pa == pb:
            identical += 1
        else:
            moved.append((k, pa, pb))
    print(f"  price identical      {identical:>4}")
    print(f"  price changed        {len(moved):>4}")
    print(f"  price absent in one  {absent:>4}")
    for k, pa, pb in moved[:12]:
        print(f"      {k:<22}{pa:>13,} → {pb:>13,}   {(pb / pa - 1):+.1%}")
    print()
    dirty = 0
    for f in STABLE_FIELDS:
        diff = sorted(k for k in both if x[k].get(f) != y[k].get(f))
        dirty += len(diff)
        tail = "" if not diff else f"   ← {', '.join(diff[:4])}"
        print(f"  {f:<22}{len(diff):>4} changed{tail}")
    print()

    print("WHAT THIS BOUNDS")
    print("-" * 66)
    if dirty == 0 and not moved:
        print("  The parser is reproducible: every field the two runs both saw")
        print("  came out identical. A difference between runs is therefore")
        print("  the SAMPLE, not the extraction.")
    else:
        print(f"  {dirty + len(moved)} field value(s) moved on listings both "
              "runs drew. On this")
        print("  interval that is a parser defect or a source edit — find out "
              "which\n  before any corpus from this collector is used.")
    print()
    print(f"  Sample churn of {churn:.0%} with an identical pin is the floor. "
          "Over what\n  interval is not recorded anywhere (see the header), so "
          "the floor is a\n  RATE PER RUN and not a rate per hour.")
    print(f"  A later delta of {abs(len(ex) - len(ey))} eligible rows or fewer "
          "is inside it, and is")
    print("  not evidence about the market.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
