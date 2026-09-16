"""Where bama states the location, and what label — if any — precedes it.

    Run: python3 scripts/location_probe.py [--sample 3]

WHY THIS EXISTS AND WHY IT IS NOT A FIX

`province` is empty on all 76 records of run 11. The cause was established on
2026-09-11 and written into `docs/NETWORK_OBSERVATION_2026-09-11.md` §6:
`parse_detail_page` reads `_labelled(lines, "موقعیت")` and the page renders
the location with no such label. A parser miss, not a boundary loss and not a
source limitation — the value is on the page.

It is not a cosmetic gap. `province` is a blocking key in
`tracking.blocking_keys` and a scoring term in `repost_match_score`, so
repost matching has been running with one signal permanently absent. A
listing that is taken down and re-posted is the case W0 exists for, and it is
being matched with less than it was designed to use.

What has never been captured is WHAT the page actually renders. Nothing in
this repository holds a bama detail page, so the label cannot be read here,
and a fix written without reading it would be a guess wearing a regex. The
last three confident wrong answers in `date_probe.py` were all of that shape
— a pattern that matched nothing while the value sat on the page — and each
was caught only because a probe printed the raw material instead of a verdict.

So this prints the raw material. It decides nothing, writes nothing, and
changes no behaviour. Read its output, then the fix can be written from
observation.

WHAT IT PRINTS

  1. whether «موقعیت» appears at all, and if so what follows it
  2. every line that looks like an Iranian province or major city, with the
     two lines on either side — the positional evidence a label-free rule
     would need
  3. for the first page only, the complete line list around the specification
     block, because the name list in (2) is itself an assumption and a page
     may state the location in a form it does not contain

POLITENESS. One request per sampled listing, through the same adapter, the
same robots check and the same sleep as a collection run. Default sample is
three: one page shows the shape, three show whether the shape is the page's
or that listing's.

NO PHONE NUMBER LEAVES THIS SCRIPT — AND THE FIRST DRAFT SAID SO WRONGLY

That draft claimed «no phone number is read, printed or stored — nothing
here looks for one». The second half was true and the first half did not
follow from it. Sections 2 and 3 print raw page lines, and bama renders the
seller's number as a line of its own: run against `bama:oniy1maq`, this
script printed «۰۹۳۰۸۹۰۸۱XX» — nine digits of an eleven-digit number, the
site's own masking being the only thing between it and the terminal.

Not looking for something is not the same as not finding it, and a claim
about an outcome has to be checked against the outcome. This is D57 in the
smallest possible form: the one sentence in the file about the constraint
that matters most was the one sentence nobody had run.

So no line reaches stdout raw. `redact_phone_like` is applied once, where
the page is read, so every section downstream is safe by construction rather
than by three remembered call sites. What it catches and what it does not is
stated below its own definition instead of being implied here. The
production adapter is unaffected and always was — `parse_detail_page` sets
`seller_raw=None` and never reads this line — and this script still writes
nothing anywhere.
"""
import argparse
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARO_SELLER_SALT", "location-probe-collects-nothing")

from caro.corpus_reader import CorpusUnavailable, load_corpus     # noqa: E402
from caro.ingest.bama import (                                    # noqa: E402
    BamaAdapter, _labelled, _text, http_fetcher,
)
from caro.ingest.persian import normalize                         # noqa: E402
from caro.tracking import FetchStatus, classify_http              # noqa: E402

# Iran's provinces plus the larger cities a listing is likely to name. This
# is a NET, not a vocabulary: it exists to find candidate lines worth looking
# at, and section 3 prints the surrounding block precisely because a page may
# state a place this list does not contain. Nothing downstream should ever
# import it as a canonical set.
PLACES = [
    "تهران", "البرز", "کرج", "اصفهان", "فارس", "شیراز", "خراسان رضوی",
    "مشهد", "آذربایجان شرقی", "تبریز", "آذربایجان غربی", "ارومیه",
    "خوزستان", "اهواز", "مازندران", "ساری", "گیلان", "رشت", "کرمان",
    "قم", "قزوین", "مرکزی", "اراک", "همدان", "کرمانشاه", "یزد", "اردبیل",
    "زنجان", "سمنان", "گلستان", "گرگان", "لرستان", "خرم‌آباد", "بوشهر",
    "هرمزگان", "بندرعباس", "کردستان", "سنندج", "سیستان و بلوچستان",
    "زاهدان", "چهارمحال و بختیاری", "شهرکرد", "کهگیلویه و بویراحمد",
    "یاسوج", "ایلام", "خراسان شمالی", "بجنورد", "خراسان جنوبی", "بیرجند",
    "اسلامشهر", "شهریار", "ورامین", "پرند", "پردیس",
]
_PLACES_N = {normalize(p) for p in PLACES}

LABELS = ["موقعیت", "شهر", "استان", "محل", "منطقه", "آدرس", "مکان"]

# Latin, Persian and Arabic-Indic digits are all live on this page: the specs
# arrive Latin («500,000»), the seller's own text Persian («۱۶۰تا»).
_DIGITS = "0123456789۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩"
# What bama puts where the last two digits belong. `*` and `#` are here
# because other boards use them and this cost nothing to include.
_MASK = "Xx×*#"
_SEP = " ‌._-"
_SPAN = re.compile(
    f"[{_DIGITS}][{_DIGITS}{_MASK}]*(?:[{_SEP}]+[{_DIGITS}{_MASK}]+)*")


def redact_phone_like(text: str) -> str:
    """Replace phone-shaped spans with their length, leaving figures alone.

    A span is redacted when it carries eight or more digit-or-mask characters
    AND at least one of: a mask character, a leading zero, an internal
    separator. The second clause is what keeps the probe useful — «350,000,000»
    and «500,000» are what section 3 exists to show sitting around the
    location, and a plain length rule would blank them out. A comma is not a
    separator here for exactly that reason: it is how a price is written and
    not how a number is.

    WHAT THIS DOES NOT CATCH, stated rather than left to be discovered:

      · a number written the way a price is — «09123456789» is caught by the
        leading zero, but a landline typed as «021,8877,6655» is not
      · a number spelled in words, or split by Persian letters between groups
      · a number that reaches eight digits only after the page's own masking
        removes some — this counts mask characters toward the length for that
        reason, but a heavier mask still shrinks the span

    It is a probe-side guard on what is printed, not a redaction library, and
    nothing downstream should import it as one. The real guarantee lives in
    the adapter, which does not read the line at all.
    """
    def one(m: re.Match[str]) -> str:
        span = m.group(0)
        digits = sum(ch in _DIGITS for ch in span)
        masks = sum(ch in _MASK for ch in span)
        if digits + masks < 8:
            return span
        if not (masks
                or span[0] in "0۰٠"
                or any(ch in _SEP for ch in span)):
            return span
        return f"[{digits + masks} digits redacted]"
    return _SPAN.sub(one, text)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-corpus", default="run11")
    ap.add_argument("--sample", type=int, default=3)
    a = ap.parse_args()

    try:
        art = load_corpus(a.from_corpus)
    except (CorpusUnavailable, ValueError) as e:
        print(f"cannot read corpus {a.from_corpus!r}:\n{e}", file=sys.stderr)
        return 2

    rows = [r for r in art.get("listings", []) if r.get("source_url")]
    rows = rows[:a.sample]
    if not rows:
        print("no listing in that corpus carries a source_url.", file=sys.stderr)
        return 2

    print("LOCATION PROBE")
    print("=" * 70)
    print(f"  corpus     {a.from_corpus}")
    print(f"  sampled    {len(rows)} of {len(art.get('listings', []))}")
    print()
    print("  This prints what the page says. It does not decide anything and")
    print("  it writes nothing. `province` is empty on every record; the fix")
    print("  is written after reading this, not before.")
    print()

    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=1, max_categories=1)

    label_hits: Counter = Counter()
    pages: list[tuple[str, list[str]]] = []
    gone = unreadable = 0

    for r in rows:
        lid = str(r.get("listing_id", ""))[:24]
        status, html = ad._get(r["source_url"])
        fs = classify_http(status)
        if fs is FetchStatus.ABSENT:
            gone += 1
            print(f"  {lid}  gone ({status})")
            continue
        if fs is not FetchStatus.OK or not html:
            unreadable += 1
            print(f"  {lid}  unreadable ({status})")
            continue
        # Redacted HERE, at the one place the page becomes lines, so that
        # sections 1, 2 and 3 are safe because they cannot be otherwise —
        # not because three separate print sites each remembered to be.
        pages.append((lid, [redact_phone_like(ln) for ln in _text(html)]))
        ad.sleeper(ad.policy.sleep())

    print(f"  fetched {len(pages)} · gone {gone} · unreadable {unreadable}")
    if not pages:
        print("\nnothing to read.")
        return 1

    # -----------------------------------------------------------------
    print()
    print("1. LABELS — does any of these precede a value?")
    print("-" * 70)
    for lid, lines in pages:
        found = [(lb, _labelled(lines, lb)) for lb in LABELS]
        found = [(lb, v) for lb, v in found if v]
        if found:
            for lb, v in found:
                label_hits[lb] += 1
                print(f"  {lid:<24}«{lb}» → {v[:40]!r}")
        else:
            print(f"  {lid:<24}none of {len(LABELS)} labels is present")
    print()
    print(f"  «موقعیت» — the label the parser reads — hit on "
          f"{label_hits.get('موقعیت', 0)} of {len(pages)} page(s).")

    # -----------------------------------------------------------------
    print()
    print("2. PLACE NAMES — every line matching the net, with its neighbours")
    print("-" * 70)
    any_place = False
    for lid, lines in pages:
        hits = [i for i, ln in enumerate(lines)
                if normalize(ln) in _PLACES_N]
        if not hits:
            print(f"  {lid:<24}no line is exactly a known place name")
            continue
        any_place = True
        for i in hits[:6]:
            before2 = lines[i - 2][:26] if i >= 2 else ""
            before1 = lines[i - 1][:26] if i >= 1 else ""
            after1 = lines[i + 1][:26] if i + 1 < len(lines) else ""
            print(f"  {lid}  [{i}]")
            print(f"      −2  {before2!r}")
            print(f"      −1  {before1!r}")
            print(f"       →  {lines[i][:40]!r}")
            print(f"      +1  {after1!r}")
    if not any_place:
        print()
        print("  The net caught nothing. That is informative rather than a")
        print("  failure: the page may name a place this list omits, or may")
        print("  render it joined to other text. Section 3 is the fallback.")

    # -----------------------------------------------------------------
    print()
    print("3. THE FIRST PAGE, AROUND THE SPECIFICATION BLOCK")
    print("-" * 70)
    print("  Printed because the name list above is itself an assumption.")
    print("  Anchored on «کارکرد», which every one of these pages states.")
    print()
    lid, lines = pages[0]
    anchor = next((i for i, ln in enumerate(lines)
                   if "کارکرد" in normalize(ln)), None)
    if anchor is None:
        print("  «کارکرد» not found — printing the first 60 lines instead.")
        lo, hi = 0, min(60, len(lines))
    else:
        lo, hi = max(0, anchor - 25), min(len(lines), anchor + 35)
    print(f"  {lid}   lines {lo}–{hi - 1} of {len(lines)}")
    for i in range(lo, hi):
        print(f"    [{i:>4}]  {lines[i][:64]}")

    print()
    print("Read section 1 first. If a label is there under another name, the")
    print("fix is one string. If section 2 shows the place always sits at a")
    print("fixed offset from something stable, the fix is positional and has")
    print("to be validated against the value before it is accepted — a rule")
    print("that takes whatever line follows an anchor will happily record a")
    print("price as a province the day the block is reordered.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
