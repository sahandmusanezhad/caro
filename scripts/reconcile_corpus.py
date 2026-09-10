#!/usr/bin/env python3
"""Does the published artifact carry the same eligibility the snapshot did?

    python3 scripts/reconcile_corpus.py \
        --snapshot data/snapshots/2026-09-10/bama-....json \
        --run-id run11 \
        --output data/corpora/run11.json

A run report counts parsed OBJECTS. An artifact is what an estimator reads.
Those two disagreed silently for the whole life of this project: every row a
corpus published was ineligible, because `to_fetch_outcome` did not carry
`price_status` or `mileage_status` and `corpus_reader` therefore read None
for both. The run said 54 eligible Prides; the artifact held zero, and the
only reason nobody noticed is that every benchmark so far re-parsed rebuilt
pages instead of reading the artifact.

So the count is not the deliverable here. The RECONCILIATION is:

    for every record in the snapshot
        does the record carry what `eligibility` needs?      (a)
        is the row it promotes to eligible when read back?   (b)

    a and not b   -> a boundary lost it. Named, with the reason.
    b and not a   -> the artifact is MORE permissive than its input, which
                     is the one direction that must never happen.

A difference between the run's number and the artifact's is acceptable only
when every differing row is named. "A new count" is not an explanation.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.corpus_reader import listings_from_corpus                # noqa: E402
from caro.ingest.quality import eligibility                        # noqa: E402


class _FromRecord:
    """The attributes `eligibility` reads, taken straight off a snapshot record.

    Deliberately not a CarListing: constructing one would supply dataclass
    defaults for anything the record omits, and a default is exactly what
    would hide the loss this script exists to find. Missing means missing.
    """

    _FIELDS = ("asking_price_toman", "year_jalali", "mileage_km", "model",
               "price_status", "mileage_status", "product_class", "price_kind")

    def __init__(self, rec: dict):
        for f in self._FIELDS:
            setattr(self, f, rec.get(f))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--snapshot", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--model", default="Pride",
                    help="the model to report a headline count for")
    ap.add_argument("--parse-eligible", type=int, default=None,
                    help="what the collection run reported, so the boundary "
                         "BEFORE this one can be located too")
    a = ap.parse_args()

    if not a.snapshot.exists():
        print(f"no such snapshot: {a.snapshot}", file=sys.stderr)
        return 2

    raw = json.loads(a.snapshot.read_text(encoding="utf-8"))
    records = [r for r in raw.get("outcomes", []) if isinstance(r, dict)]
    ok_records = [r for r in records if r.get("status") == "ok"]

    print(f"snapshot   {a.snapshot}")
    print(f"           {len(records)} records, {len(ok_records)} of them ok\n")

    # ---- promote ---------------------------------------------------------
    a.output.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "promote_corpus.py"),
         "--input", str(a.snapshot), "--run-id", a.run_id,
         "--output", str(a.output)],
        cwd=ROOT, capture_output=True, text=True)
    print("promotion")
    for line in (p.stdout + p.stderr).strip().splitlines():
        print(f"  {line}")
    if p.returncode != 0 or not a.output.exists():
        print("\nNo artifact was written. Nothing to reconcile.")
        return 1
    print()

    artifact = json.loads(a.output.read_text(encoding="utf-8"))
    listings = listings_from_corpus(artifact)
    by_id = {str(x.listing_id): x for x in listings}

    # ---- the reconciliation ---------------------------------------------
    lost, gained = [], []
    for rec in ok_records:
        lid = str(rec.get("listing_id"))
        snap_ok = eligibility(_FromRecord(rec))[0]
        got = by_id.get(lid)
        art_ok, art_why = (eligibility(got) if got is not None
                           else (False, ["not published at all"]))
        if snap_ok and not art_ok:
            lost.append((lid, art_why))
        elif art_ok and not snap_ok:
            gained.append((lid, eligibility(_FromRecord(rec))[1]))

    snap_elig = sum(1 for r in ok_records if eligibility(_FromRecord(r))[0])
    art_elig = sum(1 for x in listings if eligibility(x)[0])

    print("RECONCILIATION")
    print("-" * 62)
    if a.parse_eligible is not None:
        print(f"  eligible at the parse      {a.parse_eligible:>4}"
              f"   (what the run reported)")
    print(f"  eligible in the snapshot   {snap_elig:>4}")
    print(f"  eligible in the artifact   {art_elig:>4}")
    print(f"  lost at a boundary         {len(lost):>4}")
    print(f"  gained (must be zero)      {len(gained):>4}")
    print()

    # Which boundary, not just how many. A drop before the snapshot and a
    # drop after it are different defects in different files, and reporting
    # one number invites fixing the wrong one.
    if a.parse_eligible is not None and a.parse_eligible > snap_elig:
        print(f"  ⚠ {a.parse_eligible - snap_elig} eligible row(s) did not "
              "reach the SNAPSHOT.")
        print("    The boundary is to_fetch_outcome / write_snapshot, not")
        print("    promotion. Nothing below this line can see or fix it.")
        print()

    if lost:
        print("  LOST — the snapshot supported these and the artifact does not:")
        for lid, why in lost[:20]:
            print(f"    {lid:<22}{'; '.join(why)}")
        if len(lost) > 20:
            print(f"    … and {len(lost) - 20} more")
        print()
    if gained:
        print("  ⚠ GAINED — the artifact admits rows its own input did not.")
        print("    This is the one direction that must never happen: the")
        print("    corpus is more permissive than the evidence behind it.")
        for lid, why in gained[:20]:
            print(f"    {lid:<22}{'; '.join(why)}")
        print()
    if not lost and not gained:
        print("  ✓ every eligibility decision survived the artifact\n")

    # ---- what the artifact actually holds --------------------------------
    print("THE ARTIFACT")
    print("-" * 62)
    print(f"  published                  {len(listings):>4}")
    print(f"  appraisal-eligible         {art_elig:>4}")
    for label, vals in (
            ("product_class", [x.product_class for x in listings]),
            ("price_kind", [x.price_kind for x in listings]),
            ("condition", [x.body_condition for x in listings]),
            ("seller_type", [x.seller_type for x in listings])):
        c = Counter(vals).most_common()
        print(f"  {label:<26}" + "  ".join(f"{k}:{v}" for k, v in c))

    want = a.model.lower()
    m_all = [x for x in listings if (x.model or "").lower() == want]
    m_elig = [x for x in m_all if eligibility(x)[0]]
    print()
    print(f"  {a.model:<26}{len(m_all)} published, {len(m_elig)} eligible "
          f"FROM THE ARTIFACT")
    print()

    # ---- refusal reasons, for the rows that are not eligible -------------
    why_counts: Counter = Counter()
    for x in listings:
        ok, why = eligibility(x)
        if not ok:
            why_counts.update(why)
    if why_counts:
        print("  why the rest are not eligible")
        for w, n in why_counts.most_common(8):
            print(f"    {w:<52}{n:>4}")
        print()

    print(f"artifact   {a.output}")
    print(f"           sha256 in the file's provenance block; "
          f"{a.output.stat().st_size:,} bytes")
    print()

    # ---- the invariants, checked rather than eyeballed --------------------
    #
    # The fifth exists because the first four are satisfied by a corpus in
    # which NOTHING is eligible: 0 == 0, nothing lost, nothing gained, and
    # every line reads green while the artifact is useless. A reconciliation
    # that can pass vacuously is not a reconciliation, and this is exactly
    # the failure it was built to catch one level down — fail-closed on both
    # sides agreeing with itself.
    checks = [
        ("snapshot eligible == artifact eligible", snap_elig == art_elig,
         f"{snap_elig} vs {art_elig}"),
        ("nothing lost at a boundary", not lost, f"{len(lost)} lost"),
        ("nothing gained — the artifact is never more permissive",
         not gained, f"{len(gained)} gained"),
        ("the artifact holds eligible rows AT ALL",
         art_elig > 0,
         "0 eligible: the four checks above pass vacuously when both sides "
         "are empty"),
    ]
    if a.parse_eligible is not None:
        checks.insert(0, ("parse eligible == snapshot eligible",
                          a.parse_eligible == snap_elig,
                          f"{a.parse_eligible} vs {snap_elig} — the loss is "
                          "before promotion"))

    print("INVARIANTS")
    print("-" * 62)
    failed = 0
    for name, ok, detail in checks:
        if ok:
            print(f"  ✓ {name}")
        else:
            failed += 1
            print(f"  ✗ {name}   {detail}")
    print()
    if failed:
        print(f"  {failed} invariant(s) failed. The eligibility this corpus "
              "reports is not")
        print("  the eligibility its input supported, and no number from it "
              "may be quoted.")
        return 1
    print(f"  all {len(checks)} hold. {art_elig} eligible rows, and every one "
          "of them is")
    print("  eligible FROM THE ARTIFACT rather than from a parsed object.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
