"""A field the parser fills must reach the corpus, or be named here as lost.

    Run: PYTHONPATH=. python3 tests/test_field_survival.py

WHY THIS SUITE EXISTS

Every other ingest test stops at the parsed object. `parse_detail_page`
returns a `CarListing` with a body condition on it, the assertion passes, and
the run is green — while the thing that actually reaches an estimator is four
transformations further down:

    CarListing            what the parser built
      → FetchOutcome      what a snapshot is made of
      → JSON on disk      what survives the process exiting
      → promote_record    what a published corpus row contains
      → CarListing        what a consumer reads back

Three fields were dropped at the first arrow — `body_condition`,
`document_issue`, `seller_type` — and nothing failed. `first_run.py`'s
inventory reads the live objects, so it printed a healthy condition
distribution; the snapshot it wrote in the same breath contained none of it.
A corpus promoted from that snapshot carries `condition: "unknown"` on every
row, which `ranking.risk_from_condition` prices at 0.35 — a constant, which
cancels out of `value = estimate − asking − risk` and silently removes the
risk term from the product.

The defect is not that a field was forgotten. It is that a boundary existed
which no test crossed, so forgetting was free. This suite crosses it, in
both directions: the fields that must survive are asserted end to end, and
the fields that do NOT survive are enumerated with a reason, so the set is
maintained deliberately instead of discovered on a corpus.

The chain runs through the real serializer and real JSON on disk rather than
passing dataclasses along. A field that survives in memory and is dropped by
`write_snapshot` is the same outage to a reader, and would pass a test built
out of objects.
"""

import json
import os
import tempfile
from dataclasses import fields
from datetime import date
from pathlib import Path

os.environ.setdefault("CARO_SELLER_SALT", "test-salt")

import sys                                                       # noqa: E402
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from caro.corpus_reader import listing_from_record                # noqa: E402
from caro.ingest.divar_car import CarListing, parse_listing       # noqa: E402
from caro.tracking import (                                       # noqa: E402
    FetchOutcome, Snapshot, write_snapshot,
)
from promote_corpus import promote_record                         # noqa: E402

FAILS: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# The chain, run for real
# ---------------------------------------------------------------------------

def through_the_chain(listing: CarListing):
    """(snapshot record, published row, listing read back, refusal).

    Every step is the production one. In particular the snapshot is written
    and re-read as a file: a field that a dataclass carries and the
    serializer drops is exactly the failure this suite is about.
    """
    outcome = listing.to_fetch_outcome("bama", "test-salt")
    snap = Snapshot("survival", date(2026, 9, 8), [outcome])
    with tempfile.TemporaryDirectory() as d:
        p = write_snapshot(Path(d), snap)
        payload = json.loads(p.read_text(encoding="utf-8"))
    rec = payload["outcomes"][0]
    row, why = promote_record(rec)
    back = listing_from_record(row) if row else None
    return rec, row, back, why


def a_listing(**over) -> CarListing:
    """A complete, plausible parse. Overridable field by field."""
    base = dict(
        listing_id="ki4vo2q1", url="https://bama.ir/car/detail-ki4vo2q1",
        title="پراید ۱۳۱", description="",
        asking_price_toman=850_000_000,
        make="پراید", model="131", trim="SE",
        year_jalali=1398, mileage_km=43_000,
        gearbox="دنده‌ای", fuel="بنزینی", color="سفید",
        body_condition="minor_paint", condition_source="field",
        document_issue=False, city="تهران",
        product_class="vehicle", product_class_source="canonical_name",
        price_kind="cash", price_kind_source="no_contrary_evidence",
        seller_raw=None, image_urls=(),
        price_status="usable", price_provenance="jsonld",
        mileage_status="plausible", seller_type="dealer",
    )
    base.update(over)
    return CarListing(**base)


# ---------------------------------------------------------------------------
print("\nthe spine — what an appraisal cannot be computed without")
# ---------------------------------------------------------------------------

rec, row, back, why = through_the_chain(a_listing())
check("the chain completes without a refusal", row is not None, str(why))

SPINE = [("listing_id", "bama:ki4vo2q1"), ("make", "پراید"),
         ("model", "131"), ("trim", "SE"), ("year_jalali", 1398),
         ("mileage_km", 43_000), ("asking_price_toman", 850_000_000)]
for key, want in SPINE:
    check(f"{key} survives to the published row",
          row.get(key) == want, f"got {row.get(key)!r}, wanted {want!r}")

check("province is the renamed city, not a dropped one",
      row.get("province") == "تهران", str(row.get("province")))

# ---------------------------------------------------------------------------
print("\ncondition — the field that was lost, and its provenance with it")
# ---------------------------------------------------------------------------

check("the snapshot record carries the condition at all",
      rec.get("condition_source") == "field"
      and rec.get("body_condition") == "minor_paint",
      f"{rec.get('body_condition')!r} / {rec.get('condition_source')!r}")
check("  it reaches the published row",
      row.get("condition") == "minor_paint", str(row.get("condition")))
check("  it says the source published it, because the source did",
      row.get("condition_source") == "field", str(row.get("condition_source")))
check("  and a consumer reading the corpus back sees the same value",
      back.body_condition == "minor_paint", str(back.body_condition))

desc_row = through_the_chain(
    a_listing(body_condition="replaced_part", condition_source="description"))[1]
check("a condition mined from prose stays labelled as prose",
      desc_row.get("condition_source") == "description",
      "labelling it 'field' would assert the site published a spec row it "
      "never published")
check("  and the value itself is not weakened by that",
      desc_row.get("condition") == "replaced_part")

# The negative. This is the state the whole pipeline used to produce for
# every row, so it must be reachable — and reachable ONLY from real absence.
none_rec, none_row, none_back, _ = through_the_chain(
    a_listing(body_condition="unknown", condition_source="none"))
check("looked for and not found stays unknown, sourced to nothing",
      none_row.get("condition") == "unknown"
      and none_row.get("condition_source") == "none",
      str(none_row))
check("  and unknown is not published as an observed field",
      none_row.get("condition_source") != "field")

# ---------------------------------------------------------------------------
print("\ndocument_issue — where False and absent are different facts")
# ---------------------------------------------------------------------------

check("False survives; it is a finding, not an empty value",
      row.get("document_issue") is False, repr(row.get("document_issue")))
check("  True survives too",
      through_the_chain(a_listing(document_issue=True))[1]
      .get("document_issue") is True)
check("  and a consumer reads False back as False, not as None",
      back.document_issue is False, repr(back.document_issue))

absent = through_the_chain(a_listing(document_issue=None))[1]
check("absent stays absent rather than becoming a clean bill of paperwork",
      "document_issue" not in absent, str(absent.get("document_issue")))

# ---------------------------------------------------------------------------
print("\nseller type — D26 survives promotion, in both directions")
# ---------------------------------------------------------------------------

check("a dealer badge reaches the row", row.get("seller_type") == "dealer")
check("  and dealer_badge agrees with it", row.get("dealer_badge") is True)

priv = through_the_chain(a_listing(seller_type="private"))[1]
check("a private seller reaches the row", priv.get("seller_type") == "private")
check("  and does not raise the badge", priv.get("dealer_badge") is False)

unk_row, unk_back = through_the_chain(a_listing(seller_type="unknown"))[1:3]
check("NO BADGE IS NOT A PRIVATE SELLER (D26)",
      unk_row.get("seller_type") == "unknown",
      "the absence of a business badge is not evidence of its opposite")
check("  and the consumer reads unknown, never private",
      unk_back.seller_type == "unknown", unk_back.seller_type)

# ---------------------------------------------------------------------------
print("\nthe census — every field, crossing or named as lost")
# ---------------------------------------------------------------------------

# What `to_fetch_outcome` is expected to do with each CarListing field.
# `None` means the field deliberately does not cross, and the string beside
# it is why. This table is the point of the suite: a field that starts or
# stops crossing fails here until someone decides which it should be.
CROSSES = {
    "listing_id": "listing_id",
    "asking_price_toman": "asking_price_toman",
    "make": "make", "model": "model", "trim": "trim",
    "year_jalali": "year_jalali", "mileage_km": "mileage_km",
    "color": "color",
    "city": "province",                    # renamed, not dropped
    "seller_raw": "seller_fingerprint",    # salted on the way out (D-privacy)
    "body_condition": "body_condition",
    "condition_source": "condition_source",
    "document_issue": "document_issue",
    "seller_type": "seller_type",
    "product_class": "product_class",
    "product_class_source": "product_class_source",
    "price_kind": "price_kind",
    "price_kind_source": "price_kind_source",
    "source_url": "source_url",
    "url": "source_url",            # the fallback when a source publishes none
}

LOST_ON_PURPOSE = {
    "title": "seller-authored prose — the corpus contract forbids publishing it",
    "description": "the same, and the values derived from it cross instead",
    "image_urls": "addresses again; `image_phashes` is the derived form",
}

LOST_AND_NOT_YET_DECIDED = {
    "gearbox": "parsed on every page; no consumer reads it from a corpus yet",
    "fuel": "as gearbox",
    "price_raw": "price provenance (D20). `promote_record` publishes "
                 "`price_currency_raw`, which means the corpus schema offers "
                 "a field the snapshot path cannot fill — it is populated "
                 "only when promoting a hand-written `listings` fixture",
    "price_currency_raw": "as price_raw — and this one the corpus schema "
                          "does advertise",
    "price_displayed_toman": "as price_raw",
    "price_status": "quality judgement; `corpus_reader` sets it to None and "
                    "`eligibility` fails closed on that, which is the "
                    "intended conservative reading",
    "price_provenance": "as price_status",
    "mileage_status": "as price_status",
    "mileage_note": "as price_status",
}

declared = set(CROSSES) | set(LOST_ON_PURPOSE) | set(LOST_AND_NOT_YET_DECIDED)
actual = {f.name for f in fields(CarListing)}
check("every CarListing field is accounted for in this table",
      declared == actual,
      f"undeclared: {sorted(actual - declared)}  "
      f"stale: {sorted(declared - actual)}")

full = a_listing(seller_raw="نمایشگاه پارس")
out = full.to_fetch_outcome("bama", "test-salt")
for src, dst in CROSSES.items():
    want = getattr(full, src)
    got = getattr(out, dst, "<<missing>>")
    if src == "seller_raw":
        check("seller_raw crosses only as a salted fingerprint",
              got not in (None, "", want) and want not in str(got),
              "the raw value must not appear in a snapshot")
        continue
    if src == "listing_id":
        check("listing_id crosses with its source prefixed",
              got == f"bama:{want}", got)
        continue
    if src in ("source_url", "url"):
        # Two fields, one destination, and which one wins is the point: the
        # source's own canonical address when it publishes one, the address
        # actually requested when it does not. Neither is constructed.
        continue
    check(f"{src} crosses to FetchOutcome.{dst}", got == want,
          f"got {got!r}, wanted {want!r}")

canonical = full.to_fetch_outcome("bama", "test-salt")
check("with no canonical url published, the requested address is carried",
      canonical.source_url == full.url, str(canonical.source_url))
with_canon = a_listing(seller_raw="x",
                       source_url="https://bama.ir/car/detail-ki4vo2q1-pride-131-se-1398"
                       ).to_fetch_outcome("bama", "test-salt")
check("  and the source's own canonical url wins when there is one",
      with_canon.source_url.endswith("-pride-131-se-1398"),
      str(with_canon.source_url))
_canon_row = through_the_chain(
    a_listing(source_url="https://bama.ir/car/detail-ki4vo2q1-pride-131-se-1398"))[1]
check("  it reaches the published row as source_url",
      _canon_row.get("source_url", "").endswith("-pride-131-se-1398"),
      str(_canon_row.get("source_url")))
check("  and no bare `url` key is published, since nothing guarantees one",
      "url" not in _canon_row, str(sorted(_canon_row)))

outcome_fields = {f.name for f in fields(FetchOutcome)}
check("no FetchOutcome field is filled by nothing",
      outcome_fields - set(CROSSES.values())
      == {"status", "http_status", "image_phashes", "payload_sha"},
      str(sorted(outcome_fields - set(CROSSES.values()))))

# ---------------------------------------------------------------------------
print("\nREGRESSION — the shape the defect actually had")
# ---------------------------------------------------------------------------

# A FetchOutcome built the way it was built before this was fixed: the spine
# only. Promotion must still produce a row — the corpus is not broken by an
# adapter that records less — but it must produce an HONEST one.
old_shape = FetchOutcome(
    listing_id="bama:x1", status=next(iter(type(out.status))),
    asking_price_toman=850_000_000, make="پراید", model="131",
    year_jalali=1398, mileage_km=43_000)
old_snap = Snapshot("old", date(2026, 9, 8), [old_shape])
with tempfile.TemporaryDirectory() as d:
    old_rec = json.loads(
        write_snapshot(Path(d), old_snap).read_text(encoding="utf-8")
    )["outcomes"][0]
old_row, _ = promote_record(old_rec)

check("an outcome with no condition still promotes",
      old_row is not None)
check("  and every such row is unknown — the defect, reproduced",
      old_row.get("condition") == "unknown",
      "100% of a corpus promoted from that snapshot, which is a constant "
      "risk term and no ranking signal at all")
check("  sourced to nothing, so the corpus does not claim it was observed",
      old_row.get("condition_source") == "none")
check("  and it carries no seller type, rather than a private one",
      old_row.get("seller_type") is None and old_row.get("dealer_badge") is False)

check("today's snapshot of the same car does NOT produce that",
      row.get("condition") != "unknown",
      "if this ever fails, the boundary has regressed and every downstream "
      "risk number is a redaction artefact again")

# ---------------------------------------------------------------------------
print("\nthe parser's own two paths, end to end")
# ---------------------------------------------------------------------------

divar = parse_listing("d1", "https://divar.ir/v/d1", "پراید ۱۳۱",
                      "گلگیر تعویض شده، سند آزاد",
                      price_text="۸۵۰,۰۰۰,۰۰۰ تومان",
                      mileage_text="۴۳,۰۰۰ کیلومتر")
check("divar's prose parse fills a condition",
      divar.body_condition == "replaced_part", divar.body_condition)
check("  and labels it as prose, since divar publishes no spec row",
      divar.condition_source == "description", divar.condition_source)
d_row = through_the_chain(divar)[1]
check("  and it arrives in the corpus with that label intact",
      d_row.get("condition") == "replaced_part"
      and d_row.get("condition_source") == "description", str(d_row))

quiet = parse_listing("d2", "https://divar.ir/v/d2", "پراید", "خوش‌رنگ")
check("a listing that discloses nothing gets no source",
      quiet.body_condition == "unknown" and quiet.condition_source == "none",
      f"{quiet.body_condition} / {quiet.condition_source}")

# ---------------------------------------------------------------------------
print("\nthe run report — and the false positive it produced on run 6")
# ---------------------------------------------------------------------------
#
# A snapshot holds one record per FETCH. Pages that returned 200 and parsed to
# nothing still yield a FetchOutcome: a listing_id, a status, and no fields.
# The first version of `survival()` divided the parsed column by the number of
# LISTINGS and the snapshot column by the number of RECORDS, so on run 6 —
# 18 parsed, 21 records — every field read as though it had lost a sixth of
# its values. Seven fields were reported as SILENT LOSS and none had lost
# anything: each pair was n/18 against n/21 with the same n.
#
# Manufacturing a finding is the failure this project exists to refuse, so the
# shape that produced it is a fixture now.

from first_run import survival                                   # noqa: E402
from caro.tracking import FetchStatus                            # noqa: E402

_parsed = [a_listing(listing_id=f"p{i}") for i in range(18)]
_outcomes = [x.to_fetch_outcome("bama", "test-salt") for x in _parsed]
# The three that fetched 200 and parsed to nothing.
_outcomes += [FetchOutcome(listing_id=f"bama:dead{i}",
                           status=FetchStatus.UNKNOWN, http_status=200)
              for i in range(3)]

with tempfile.TemporaryDirectory() as _d:
    _p = write_snapshot(Path(_d), Snapshot("run6shape", date(2026, 9, 10),
                                           _outcomes))
    _report = "\n".join(survival(_parsed, _p))

check("18 parsed against 21 records reports NO loss",
      "SILENT LOSS" not in _report,
      "\n" + _report)
check("  and every column reads 100%, because nothing was lost",
      _report.count("100%") >= 8 * 3, "\n" + _report)
check("  the unparsed records are named rather than averaged in",
      "3 snapshot record(s) belong to fetches that parsed to nothing"
      in _report, "\n" + _report)
check("  and the header states one denominator",
      "18 parsed · 18 matched in the snapshot · 18 published" in _report,
      "\n" + _report)

# The positive control, in the same shape: a real loss must still be caught
# with the unparsed records present, or the fix would have bought silence.
with tempfile.TemporaryDirectory() as _d:
    _p = write_snapshot(Path(_d), Snapshot("run6loss", date(2026, 9, 10),
                                           _outcomes))
    _raw = json.loads(_p.read_text(encoding="utf-8"))
    for _o in _raw["outcomes"]:
        _o["body_condition"] = None                # the D51 boundary, restored
    _p.write_text(json.dumps(_raw, ensure_ascii=False), encoding="utf-8")
    _lossy = "\n".join(survival(_parsed, _p))

check("a genuine loss is still caught with unparsed records present",
      "SILENT LOSS" in _lossy and "condition" in _lossy, "\n" + _lossy)
check("  and it is counted per listing, not as a difference of two rates",
      "18 of 18 parsed value(s) do not reach a published row" in _lossy,
      "\n" + _lossy)

# A parsed listing with no record at all is the strongest loss there is, and
# it used to disappear into the same average.
with tempfile.TemporaryDirectory() as _d:
    _p = write_snapshot(Path(_d), Snapshot("missing", date(2026, 9, 10),
                                           _outcomes[:15] + _outcomes[18:]))
    _gap = "\n".join(survival(_parsed, _p))
check("a parsed listing with no snapshot record is reported as such",
      "3 parsed listing(s) have NO snapshot record" in _gap, "\n" + _gap)

print()
if FAILS:
    print(f"{len(FAILS)} FAILED:")
    for f in FAILS:
        print(f"  - {f}")
    raise SystemExit(1)
print("field survival: every declared field crosses every boundary")
