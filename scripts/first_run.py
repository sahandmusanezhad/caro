#!/usr/bin/env python3
"""
First live collection, and the inventory report that decides what comes next.

    python3 scripts/first_run.py --source bama --limit 50
    python3 scripts/first_run.py --source divar --city tehran --pages 2
    python3 scripts/first_run.py --replay <file with a top-level "listings">

This is deliberately small. The point of a first run is not volume — it is
finding out how much of what the parser expects is actually there. A field
that is populated 40% of the time changes the appraisal design; a field that
is populated 95% of the time does not.

What it prints is the W0 inventory: fill rate and garbage rate per field,
comparable-tier coverage, and the condition distribution. Those numbers
decide whether the corpus can support an estimate at all, and they should be
read before any model is fitted.

Every one of those numbers is computed from the objects the parser returned,
which is the right thing to measure and is NOT what an estimator ever sees.
For a long time those two disagreed completely and this report was the reason
nobody noticed: it showed a healthy condition distribution while the snapshot
written seconds earlier carried no condition at all, and every promoted row
said `unknown` (D51). So the report ends with a FIELD SURVIVAL section that
re-reads the file it just wrote, promotes it, and prints the same fill rate
at all three stages. A field whose rate falls between two columns is a
boundary dropping it, not the source withholding it, and the run says which.

Structured snapshot records are written to data/snapshots/ — one FetchOutcome
per listing, not the raw HTTP response. That directory is operational and
never published; the publishable artifact is produced separately by
scripts/promote_corpus.py into data/corpora/ (docs/DATA_CONTRACT.md).

KNOWN DEFECT, recorded rather than described away: `--replay` reads
`raw["listings"]`, and write_snapshot emits `outcomes`. Replaying a snapshot
this script wrote therefore yields zero listings and says so without failing.
The two formats have never matched. Fixing it is a behaviour change and is not
this docstring's business, but a reader should not be told the loop closes
when it does not.
"""

from __future__ import annotations

import argparse
import hashlib
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
from caro.ingest import coverage as cov_mod                           # noqa: E402
from caro.ingest.quality import (                                     # noqa: E402
    classify_mileage, classify_price_value, eligibility,
)
from caro.tracking import FetchStatus, Snapshot, assess_integrity, write_snapshot  # noqa: E402

SNAPSHOT_DIR = ROOT / "data" / "snapshots"

# Model-level category slugs verified against the live sitemap on 2026-09-07
# and recorded in caro/ingest/bama.py's docstring. NOT manufacturer slugs:
# `/car/saipa` and `/car/ikco` redirect to `/car` and return generic
# inventory, so a run that follows them collects the general feed while
# believing it sampled two manufacturers.
DOMESTIC = ("pride", "peugeot", "dena", "tiba", "samand", "shahin", "tara",
            "runna", "saina", "quik")

# Fields whose absence changes the design, in the order they matter.
TRACKED = ["asking_price_toman", "year_jalali", "mileage_km", "make", "model",
           "trim", "gearbox", "fuel", "color", "body_condition"]


def _garbage(field: str, value, row=None) -> bool:
    """Values that are present but meaningless.

    The two hard cases — odometer plausibility and price magnitude — are
    delegated to `caro.ingest.quality`, which is also what the parser calls,
    so the number in this report and the flag the appraiser filters on can
    never drift apart. A report that computed its own definition of "usable"
    would eventually disagree with the pipeline and be believed anyway.
    """
    if value is None:
        return False
    if field == "asking_price_toman":
        return not classify_price_value(value).usable
    if field == "mileage_km":
        return not classify_mileage(
            value, getattr(row, "year_jalali", None) if row else None).usable
    if field == "year_jalali":
        return not (1350 <= value <= 1410)
    if field == "body_condition":
        return value == "unknown"
    return isinstance(value, str) and not value.strip()


def funnel(fetched: int, listings: list) -> list[str]:
    """Four counts that are routinely collapsed into one, and should not be.

    "300 listings scraped" hides which of these it means:

        fetched             the page came back
        parsed              the page yielded a listing
        usable              the listing's own fields are internally sound
        appraisal-eligible  it can actually inform an estimate

    The gaps between them are the interesting part. A large fetched→parsed
    gap is an extraction problem; a large usable→eligible gap is a *market
    coverage* problem, and the two call for opposite responses. Reporting one
    number invites the reader to assume the best of all four.

    An HTTP 200 is a transport fact, not a semantic one, which is why source
    integrity is reported separately rather than folded in here.
    """
    parsed = len(listings)
    if not parsed:
        return []
    usable, eligible, reasons = 0, 0, Counter()
    for x in listings:
        ok, why = eligibility(x)
        if ok:
            eligible += 1
        else:
            reasons.update(why)
        # "Usable" is the weaker bar: the listing describes a real car
        # coherently, whether or not it can be priced.
        if x.model and x.year_jalali and not _garbage(
                "mileage_km", x.mileage_km, x):
            usable += 1

    L = ["", "COLLECTION FUNNEL", "-" * 62,
         f"  fetched             {fetched:>4}",
         f"  parsed              {parsed:>4}"
         f"{'  (' + str(fetched - parsed) + ' pages yielded nothing)' if fetched > parsed else ''}",
         f"  usable              {usable:>4}   coherent car records",
         f"  appraisal-eligible  {eligible:>4}   can inform an estimate"]
    if reasons:
        L.append("  held back by")
        for why, c in reasons.most_common(6):
            L.append(f"      {why:<34}{c:>4}")
    return L


def provenance(traces: list) -> list[str]:
    """Which extraction path filled each field, and why the rest are empty.

    A fill rate alone cannot distinguish "the site publishes this as
    structured data" from "a text heuristic guessed it". Those two corpora
    look identical in the inventory and are not remotely equally
    trustworthy, so the run reports the split. If the structured share ever
    falls, that is the signal the site changed — visible on the run it
    happens rather than a month later in the estimates.
    """
    if not traces:
        return []
    n = len(traces)
    L = ["", "EXTRACTION PROVENANCE  (how the fields were obtained)", "-" * 62]
    ld = sum(1 for t in traces if t.used_jsonld)
    L.append(f"  pages with a schema.org Car block   {ld:>4}{ld / n:>7.0%}")
    for label, attr in (("price", "price_source"),
                        ("mileage", "mileage_source"),
                        ("condition", "condition_source")):
        c = Counter(getattr(t, attr) for t in traces)
        parts = "  ".join(f"{k}:{v}" for k, v in c.most_common())
        L.append(f"  {label:<12}{parts}")
    why = Counter(t.price_reason for t in traces
                  if t.price_source == "none" and t.price_reason)
    for reason, c in why.most_common(5):
        L.append(f"      no price — {reason}: {c}")

    # The structured price against the one shown to buyers. This is the check
    # that catches a wrong currency *label*, which the currency whitelist
    # cannot: `IRR` on a toman figure is a recognised code, so the guard stays
    # silent while every price comes out a tenth of the truth.
    agree = Counter(t.price_agreement for t in traces)
    L.append(f"  price cross-check  "
             + "  ".join(f"{k}:{v}" for k, v in agree.most_common()))
    mislabelled = sum(v for k, v in agree.items() if k.startswith("label_wrong"))
    if mislabelled:
        L.append(f"  ⚠ {mislabelled} page(s) declare a currency that does not "
                 "match the figure they display. The displayed price was used. "
                 "Record the site's actual convention in DECISIONS.md.")
    if agree.get("unexplained_disagreement"):
        L.append(f"  ⚠ {agree['unexplained_disagreement']} page(s) gave two "
                 "prices that differ by something other than a factor of ten. "
                 "Those rows carry NO price rather than a chosen one — read a "
                 "couple by hand before fitting.")
    if ld < n * 0.9:
        L.append("  ⚠ the structured block is missing on some pages. The text "
                 "fallback is anchored but weaker; treat those rows as lower "
                 "confidence rather than equal evidence.")
    return L


# (label, CarListing attribute, snapshot record key, published row key)
#
# The nine fields an appraisal or a ranking actually consumes. Any one of
# them can be extracted correctly and then lost at a boundary — see D51,
# where four were.
SURVIVAL = [
    ("listing_id",     "listing_id",          "listing_id",     "listing_id"),
    ("make",           "make",                "make",           "make"),
    ("model",          "model",               "model",          "model"),
    ("year_jalali",    "year_jalali",         "year_jalali",    "year_jalali"),
    ("mileage_km",     "mileage_km",          "mileage_km",     "mileage_km"),
    ("price",          "asking_price_toman",  "asking_price_toman",
                                                            "asking_price_toman"),
    ("condition",      "body_condition",      "body_condition", "condition"),
    ("seller_type",    "seller_type",         "seller_type",    "seller_type"),
    ("document_issue", "document_issue",      "document_issue", "document_issue"),
    ("product_class",  "product_class",       "product_class",  "product_class"),
    ("price_kind",     "price_kind",          "price_kind",     "price_kind"),
    # The two the artifact needed most and carried least. Reported here so a
    # future run says whether they crossed, instead of the question being
    # answerable only by promoting and reading the corpus back.
    ("price_status",   "price_status",        "price_status",   "price_status"),
    ("mileage_status", "mileage_status",      "mileage_status", "mileage_status"),
    # ---- everything below was missing, and that is the point ----------------
    #
    # This list was hand-written and covered thirteen fields. Twenty-two are
    # common to CarListing and FetchOutcome, so nine were unaudited — and on
    # the run that printed "✓ every value the parse found reaches the
    # published row", three of those nine were being dropped outright.
    #
    # A check that is honest about what it knows and silent about the rest is
    # worse than no check, because it is quoted as coverage. The report was
    # not lying; it was answering a narrower question than its last line
    # claimed.
    #
    # `tests/test_field_survival.py` now asserts that this list covers every
    # field the two dataclasses share, with any omission declared by name.
    # Adding a field to both types and forgetting this table is a test
    # failure from here on, which is the only form of this guard that lasts.
    ("trim",           "trim",                "trim",           "trim"),
    ("color",          "color",               "color",          "color"),
    ("gearbox",        "gearbox",             "gearbox",        "gearbox"),
    ("fuel",           "fuel",                "fuel",           "fuel"),
    ("source_url",     "source_url",          "source_url",     "source_url"),
    ("condition_src",  "condition_source",    "condition_source",
                                                            "condition_source"),
    ("product_cls_src", "product_class_source", "product_class_source",
                                                        "product_class_source"),
    ("price_kind_src", "price_kind_source",   "price_kind_source",
                                                          "price_kind_source"),
    ("price_cur_raw",  "price_currency_raw",  "price_currency_raw",
                                                         "price_currency_raw"),
]


def _has(v) -> bool:
    """Present as a finding. `False` is one; `unknown` and `None` are not."""
    if v is None:
        return False
    if isinstance(v, str):
        return v.strip() not in ("", "unknown")
    return True


def survival(listings: list, snapshot_path) -> list[str]:
    """Fill rate for the same field, on the same listings, at three stages.

    The inventory above is computed from the live parsed objects. The corpus
    an estimator reads is computed from what was written to disk and then
    promoted. Those were different for the whole life of the project and
    nothing said so: the report showed a healthy condition distribution while
    every published row said `unknown` (D51).

    ON THE SAME LISTINGS is the whole correctness of this function, and the
    first live run it ran on is where that was learned. A snapshot holds one
    record per FETCH — including the pages that returned 200 and parsed to
    nothing, which carry a listing_id and no fields at all. Dividing the
    parsed column by 18 and the snapshot column by 21 made every field look
    like it was losing a sixth of its values, and the run printed SILENT LOSS
    against seven fields that had lost nothing. Every one of those numbers
    was n/18 against n/21 with the same n.

    A report that manufactures a finding is worse than no report: it is the
    exact failure this project exists to refuse, and it was reached by
    comparing two populations while claiming to compare two stages. So the
    records are matched to the parsed listings by id, one denominator is used
    throughout, and a parsed listing with NO record is itself counted — as a
    loss, which is what it would be, rather than being averaged into one.
    """
    if not listings or snapshot_path is None:
        return []
    try:
        from promote_corpus import promote_record
        raw = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
        recs = [r for r in (raw.get("outcomes") or []) if isinstance(r, dict)]
    except Exception as e:                    # noqa: BLE001 — diagnostic only
        return ["", f"FIELD SURVIVAL unavailable: {type(e).__name__}: {e}"]

    parsed = {str(getattr(x, "listing_id", "") or ""): x for x in listings
              if getattr(x, "listing_id", None)}
    n = len(parsed)
    if not n:
        return []

    # `to_fetch_outcome` prefixes the source, so `bama:ki4vo2q1` is the record
    # for the listing parsed as `ki4vo2q1`.
    matched: dict[str, dict] = {}
    for r in recs:
        lid = str(r.get("listing_id") or "")
        key = lid.split(":", 1)[-1] if ":" in lid else lid
        if key in parsed:
            matched[key] = r

    rows: dict[str, dict] = {}
    refused = 0
    for key, r in matched.items():
        row, _why = promote_record(r)
        if row:
            rows[key] = row
        else:
            refused += 1

    L = ["", "FIELD SURVIVAL  (parsed → snapshot → published row)", "-" * 62,
         f"  {n} parsed · {len(matched)} matched in the snapshot · "
         f"{len(rows)} published"
         + (f" · {refused} refused by promotion" if refused else ""),
         f"  {len(recs) - len(matched)} snapshot record(s) belong to fetches "
         f"that parsed to nothing and are not counted below",
         "-" * 62,
         f"{'field':<18}{'parsed':>9}{'snapshot':>10}{'corpus':>9}{'lost':>7}",
         "-" * 62]

    losses = []
    for label, attr, key, rowkey in SURVIVAL:
        a = b = c = lost = 0
        for lid, x in parsed.items():
            here = _has(getattr(x, attr, None))
            in_rec = _has(matched.get(lid, {}).get(key))
            in_row = _has(rows.get(lid, {}).get(rowkey))
            a += here
            b += in_rec
            c += in_row
            # Counted per listing, not as a difference between two rates. A
            # value that appears at one stage and vanishes at the next is the
            # only thing that means anything here.
            lost += here and not in_row
        flag = "  <-- LOST" if lost else ""
        if lost:
            losses.append((label, lost, a))
        L.append(f"{label:<18}{a / n:>8.0%}{b / n:>10.0%}{c / n:>9.0%}"
                 f"{lost:>7}{flag}")

    if len(matched) < n:
        L += ["", f"  ⚠ {n - len(matched)} parsed listing(s) have NO snapshot "
                  "record. Nothing about",
              "    them survives the run at all."]

    if losses:
        L += ["", "  ⚠ SILENT LOSS. The inventory above describes the PARSE. "
                  "A corpus is",
              "    what an estimator reads, and these values do not reach it:"]
        for label, lost, a in losses:
            L.append(f"      {label:<16}{lost} of {a} parsed value(s) do not "
                     "reach a published row")
        L += ["    Do not promote this run. A value lost here is not a fact "
              "about the",
              "    source — it is a boundary, and D51 is the entry about it."]
    else:
        L.append("")
        L.append("  ✓ every value the parse found reaches the published row")
    return L


def inventory(listings: list, traces: list | None = None,
              fetched: int | None = None,
              snapshot_path=None) -> str:
    n = len(listings)
    if not n:
        return "no listings parsed — nothing to report"

    L = [f"CORPUS INVENTORY  ({n} listings)", "=" * 62, "",
         f"{'field':<18}{'filled':>9}{'garbage':>9}{'usable':>9}", "-" * 62]
    for f in TRACKED:
        vals = [getattr(x, f, None) for x in listings]
        filled = sum(1 for v in vals if v is not None)
        garbage = sum(1 for x in listings if _garbage(f, getattr(x, f, None), x))
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

    prices = sorted(x.asking_price_toman for x in listings
                    if x.asking_price_toman and not _garbage("asking_price_toman", x.asking_price_toman))
    if prices:
        q = lambda p: prices[int(p * (len(prices) - 1))]          # noqa: E731
        L += ["", "PRICE DISTRIBUTION (toman)", "-" * 62,
              f"  min {q(0)/1e9:>6.2f}B   p25 {q(.25)/1e9:>6.2f}B   "
              f"median {q(.5)/1e9:>6.2f}B   p75 {q(.75)/1e9:>6.2f}B   "
              f"max {q(1)/1e9:>6.2f}B"]

    L += funnel(fetched if fetched is not None else len(listings), listings)
    L += provenance(traces or [])
    L += survival(listings, snapshot_path)
    covs = cov_mod.assess(listings)
    L += cov_mod.report(covs)

    L += ["", "VERDICT", "-" * 62]
    ok_price = sum(1 for x in listings if x.asking_price_toman
                   and not _garbage("asking_price_toman", x.asking_price_toman)) / n
    # Support is counted in APPRAISAL-ELIGIBLE listings, not parsed ones. A
    # model with 30 rows of which 12 can be priced has 12, and reading the
    # threshold off the parsed count is how a corpus passes a gate it does
    # not meet.
    eligible_models = Counter(f"{x.make} {x.model}" for x in listings
                              if x.model and eligibility(x)[0])
    # Both gates, deliberately. A model that clears the count but fails the
    # variation check is the case this whole section exists to refuse: it
    # would fit, and it would report a NARROWER interval for being
    # homogeneous. See caro.ingest.coverage.
    big_models = [m for m, c in covs.items() if c.sufficient]
    padded = [m for m, c in covs.items()
              if c.n_eligible >= cov_mod.MIN_ELIGIBLE and not c.sufficient]
    if ok_price < 0.8:
        L.append("  NOT READY — under 80% usable prices. Fix extraction "
                 "before fitting anything.")
    elif not big_models:
        best = eligible_models.most_common(1)
        have = f"{best[0][1]} ({best[0][0]})" if best else "0"
        L.append(f"  NOT READY for appraisal — no model reaches 30 "
                 f"appraisal-eligible listings; the best has {have}.")
        L.append("  This is a SAMPLING problem, not an extraction one: go "
                 "deeper on 2-3 models rather than wider across many.")
    elif padded and not big_models:
        L.append(f"  NOT READY for appraisal — {len(padded)} model(s) reach "
                 f"{cov_mod.MIN_ELIGIBLE}+ eligible listings but are too "
                 "homogeneous to price against: "
                 f"{', '.join(sorted(padded))}.")
        L.append("  Count was met and coverage was not. Fetching more of the "
                 "same page makes this WORSE, not better — a homogeneous "
                 "slice yields a narrower interval, so the gate would pass "
                 "on false confidence.")
    else:
        L.append(f"  Ready to benchmark on {len(big_models)} model(s) with "
                 f"30+ eligible listings: {', '.join(sorted(big_models))}.")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["bama", "divar"], default="bama")
    ap.add_argument("--city", default="tehran")
    ap.add_argument("--limit", type=int, default=50)
    ap.add_argument("--pages", type=int, default=2)
    # A POLITENESS ceiling, not a target. Discovery stops as soon as the
    # listing target is met, so a budget larger than needed costs nothing —
    # while a budget smaller than needed silently decides the corpus, which
    # is what `limit // 20 + 1` did on run 6: 50 requested, 3 category pages
    # allowed, 18 listings collected, and every rate in the report describing
    # `audi`, `amg` and `arya`.
    #
    # Defaulting to the limit is the worst case made safe: a category page
    # yielding one listing still lets the run reach its target, and a page
    # yielding ten means the budget is never approached.
    ap.add_argument("--categories", type=int, default=None,
                    help="max category pages to open (default: --limit)")
    ap.add_argument("--makes", default="",
                    help="comma-separated category slugs to pin the sample to; "
                         "'domestic' expands to the model-level slugs verified "
                         "on 2026-09-07")
    ap.add_argument("--seed", type=int, default=0,
                    help="which categories get drawn when --makes is empty. "
                         "Stated in advance and printed, so the sample is "
                         "reproducible rather than incidental")
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
    traces: list = []
    snapshot_path = None
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
              f"asked to.")
        print(sampling_spec(args))
        print()
        try:
            listings, snapshot_path = collect(args, traces)
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

    print(inventory(listings, traces, fetched=len(traces) or None,
                    snapshot_path=snapshot_path))
    return 0


def snapshot_id(args) -> str:
    """A name no other run can collide with, and that never overwrites one.

    The id was `bama-<today>`, so two runs on one day wrote the same file and
    the second silently destroyed the first. That happened here: run 8 was
    executed twice, once pinned to pride/quick/tiba and once to
    mvm-110/chery-tiggo7, and the corpus that cleared the readiness gate —
    55 Prides, 49 eligible — was overwritten by the run after it and had to
    be collected again.

    An overwrite is the same failure as D46 arriving early: the numbers are
    in a transcript and the input they came from is gone. So the id carries
    a digest of the SAMPLE — the thing that makes two runs different.

    Re-running the same sample is handled by `write_snapshot`, which refuses
    to land on a path that exists. That belongs there and not here: only the
    writer knows the directory, and this function's first version probed
    `today`'s while the write went to the snapshot's own date.
    """
    spec = f"{make_list(args)}|{args.seed}|{args.limit}|{args.source}"
    tag = hashlib.sha256(spec.encode()).hexdigest()[:6]
    return f"{args.source}-{date.today().isoformat()}-{tag}"


def make_list(args) -> tuple[str, ...]:
    """The pinned category slugs, or () meaning draw from the whole sitemap."""
    raw = (args.makes or "").strip()
    if not raw:
        return ()
    if raw.lower() == "domestic":
        return DOMESTIC
    return tuple(m.strip().lower() for m in raw.split(",") if m.strip())


def sampling_spec(args) -> str:
    """What this run will sample, printed BEFORE the first request.

    Run 5's most useful finding was that a pre-registration blind to the
    variable that decided the outcome is the only kind worth having. Run 6
    had no registration at all: its sample was whatever the sitemap listed
    first, and nobody chose that or could have defended it. Printing the rule
    before the requests go out is the cheap half of the discipline — it puts
    the choice in the transcript, where a reader can disagree with it.
    """
    makes = make_list(args)
    budget = args.categories or args.limit
    L = ["  SAMPLE, stated before the first request:",
         f"    target            {args.limit} listings",
         f"    category budget   {budget} page(s)"]
    if makes:
        L.append(f"    categories        pinned: {', '.join(makes)}")
        L.append("                      (a deliberate slice, not the market)")
    else:
        L.append(f"    categories        drawn uniformly from the sitemap, "
                 f"seed={args.seed}")
        L.append("                      (same seed, same categories — this "
                 "run is repeatable)")
    return "\n".join(L)


def collect(args, traces: list | None = None) -> tuple[list, object]:
    """Live collection. Returns (listings, snapshot path or None).

    The path comes back because the survival report re-reads what was
    written rather than trusting the objects still in memory. Reading
    the in-memory copy would report that nothing was lost no matter
    what the serialiser did with it."""
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
        return out, None       # divar writes no snapshot yet

    # The sitemap and Bama's pages are server-rendered, so plain HTTP is
    # correct here. Driving a browser to download static XML costs seconds and
    # a Chromium process per request for nothing.
    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=args.limit,
                     max_categories=args.categories or args.limit,
                     only_makes=make_list(args),
                     sample_seed=None if make_list(args) else args.seed,
                     salt=os.environ["CARO_SELLER_SALT"],
                     on_listing=out.append)

    records = list(ad.fetch_all(date.today()))
    if traces is not None:
        traces.extend(ad.traces)
    print(ad.stats.report())
    print()
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    snap = assess_integrity(Snapshot(snapshot_id(args), date.today(), records))
    path = write_snapshot(SNAPSHOT_DIR, snap)
    print(f"{len(out)} listings parsed · snapshot "
          f"{path.relative_to(ROOT)} (integrity: {snap.integrity.value})\n")
    return out, path


if __name__ == "__main__":
    raise SystemExit(main())
