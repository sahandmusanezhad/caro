"""The publishable corpus artifact — its guards, and the one that was wrong.

`docs/DATA_CONTRACT.md` § *The publishable corpus artifact* is the policy.
`caro/ingest/corpus.py` and `scripts/promote_corpus.py` are the enforcement.
This is what stops the enforcement from quietly stopping.

The suite exists because D46 was a process failure, and the repair for a
process failure that lives only in a document is the same failure waiting
again. Every check here runs offline, needs no corpus, and finishes in under
a second.

Run: PYTHONPATH=. python3 tests/test_corpus.py
"""

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from caro.ingest.corpus import (
    FORBIDDEN_KEYS, SCHEMA, redact, scan_keys, scan_text, validate,
)
from caro.ingest.persian import parse_mileage_km
from caro.ingest.quality import Validity, classify_mileage
from scripts.promote_corpus import canonical_km_line, promote_record

ROOT = Path(__file__).resolve().parent.parent
FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
print("\ncontent guard — an identifier in any value, whatever the key")
# ---------------------------------------------------------------------------

for label, text in [
    ("a mobile in ASCII digits", "call 09123456789"),
    ("the same mobile in Persian digits", "تماس ۰۹۱۲۳۴۵۶۷۸۹"),
    ("the international form", "+989123456789"),
    ("a landline with area code", "دفتر 02188776655"),
    ("a telegram link", "t.me/somedealer"),
    ("an @handle", "بفرستید به @autogallery_tehran"),
]:
    check(f"catches {label}", bool(scan_text(text)), repr(text))

for label, text in [
    ("a rial price", "1234567890"),
    ("an odometer reading", "کارکرد 174538 کیلومتر"),
    ("a payload hash", "payload_sha 9f86d081884c7d659a2feaa0c55ad015"),
    ("a salted seller fingerprint", "a1b2c3d4e5f6a7b8"),
    ("a jalali year", "1393"),
]:
    check(f"does NOT flag {label}", not scan_text(text), repr(text))

check("normalisation happens before matching, not after",
      scan_text("۰۹۱۲۳۴۵۶۷۸۹") and scan_text("09123456789"),
      "Persian digits must be caught exactly as ASCII ones are")

# ---------------------------------------------------------------------------
print("\nschema guard — a forbidden key at any depth")
# ---------------------------------------------------------------------------

check("flags a forbidden key at the top level",
      any(v.guard == "schema" for v in scan_keys({"description": "x"})))
check("  and nested inside a list of records",
      any(v.where.endswith(".desc")
          for v in scan_keys({"listings": [{"id": 1}, {"desc": "x"}]})))
check("  and a key the contract lists but no adapter uses yet",
      bool(scan_keys({"notes": "x"})),
      "the set is a superset of today's fields on purpose")
check("does NOT flag the derived values the contract allows",
      not scan_keys({"seller_fingerprint": "ab", "payload_sha": "cd",
                     "image_phashes": ["e"], "condition": "intact",
                     "condition_source": "description"}),
      "the line is authorship, not identifier shape — a guard that flagged "
      "these would be switched off within a week")
check("  and km_line is in the forbidden set, since it carries page prose",
      "km_line" in FORBIDDEN_KEYS)

# ---------------------------------------------------------------------------
print("\nredact — remove the identifier, keep the value beside it")
# ---------------------------------------------------------------------------

check("removes a phone and leaves the rest",
      "0912" not in redact("کارکرد ۱۲۰٬۰۰۰ — تماس ۰۹۱۲۳۴۵۶۷۸۹")
      and "120" in redact("کارکرد ۱۲۰٬۰۰۰ — تماس ۰۹۱۲۳۴۵۶۷۸۹"))
check("  removes a handle the same way",
      "t.me" not in redact("t.me/autogallery کارکرد ۱۵۰۰۰۰"))
check("  and leaves a clean line untouched in substance",
      parse_mileage_km(redact("کارکرد ۱۷۴٬۵۳۸ کیلومتر")) == 174538)

# ---------------------------------------------------------------------------
print("\nREGRESSION — an identifier must never become a measurement")
# ---------------------------------------------------------------------------
# The first draft of promote_corpus.py published this line as
# "کارکرد 2,188,776,655 کیلومتر" and both guards passed, because by then the
# digits sat in a field called mileage and no longer looked like a phone
# number. Redaction that runs AFTER parsing does not redact, it launders.

LAUNDER = "نمایشگاه اتومبیل — ۰۲۱۸۸۷۷۶۶۵۵"

check("the hazard is still real: the parser does read that phone as a number",
      parse_mileage_km(LAUNDER) == 2188776655,
      "if this ever returns None the regression below stops testing anything")
line, why = canonical_km_line({"km_line": LAUNDER}, 1395)
check("  and promotion refuses it rather than publishing a mileage",
      line is None and why is not None, f"{line!r}")
check("  refusing because nothing survives redaction, not on plausibility",
      "survives" in (why or ""),
      "the order must be redact -> parse -> classify; if plausibility is what "
      "catches this, parsing ran on tainted text first")
check("  and no laundered digits appear in any output",
      "2188776655" not in json.dumps(
          promote_record({"listing_id": "x", "km_line": LAUNDER})[0] or {},
          ensure_ascii=False))

check("a genuine odometer sharing a line with a phone is KEPT, not refused",
      canonical_km_line(
          {"km_line": "کارکرد ۱۲۰٬۰۰۰ — تماس ۰۹۱۲۳۴۵۶۷۸۹"}, 1395)[0]
      == "کارکرد 120,000 کیلومتر",
      "the blanket refusal was over-strict and cost good rows")

check("plausibility remains the backstop under redaction",
      canonical_km_line({"km_line": "هماهنگی با ۰۹۱۲ ۱۲۳ ۴۵۶۷"}, 1395)[0]
      is None)

# The hole the contract admits to, asserted so it cannot close by accident
# and go unnoticed, and cannot widen without a test turning red.
check("KNOWN HOLE: a bare six-digit local number still reads as an odometer",
      canonical_km_line({"km_line": "اتوگالری ۸۸۷۷۶۶"}, 1395)[0]
      == "کارکرد 887,766 کیلومتر",
      "DATA_CONTRACT says these guards raise the cost of an accident and do "
      "not defeat an intent; this is that sentence in practice")

# ---------------------------------------------------------------------------
print("\nderive, then discard — and the derived value cites the right evidence")
# ---------------------------------------------------------------------------

row, _ = promote_record({
    "listing_id": "a1", "mileage_km": 90000, "year_jalali": 1395,
    "description": "گلگیر تعویض شده، سند آزاد"})
check("condition is derived from the description when no spec row exists",
      row.get("condition") not in (None, "", "unknown"), str(row.get("condition")))
check("  and it says so, rather than passing as an observed field",
      row.get("condition_source") == "description", str(row))

row_field, _ = promote_record({
    "listing_id": "a2", "mileage_km": 90000, "year_jalali": 1395,
    "condition": "intact", "description": "گلگیر تعویض شده"})
check("a real spec row outranks the description",
      row_field.get("condition") == "intact"
      and row_field.get("condition_source") == "field")

row_none, _ = promote_record({"listing_id": "a3", "mileage_km": 90000,
                              "year_jalali": 1395})
check("no evidence gives condition unknown with source 'none'",
      row_none.get("condition") == "unknown"
      and row_none.get("condition_source") == "none",
      "dropping prose without deriving first would produce this for every "
      "listing, and CONDITION_RISK would price a redaction artefact at 0.35")

check("document_issue survives the prose it was derived from",
      promote_record({"listing_id": "a4", "mileage_km": 90000,
                      "description": "سند آزاد است"})[0].get("document_issue")
      is False)
check("and the prose itself is gone from the published row",
      not any(k in (row or {}) for k in ("description", "desc", "title")))

# ---------------------------------------------------------------------------
print("\nend to end — four fixtures, and what reaches disk")
# ---------------------------------------------------------------------------

CLEAN = {"taken_on": "2026-09-07", "listings": [
    {"listing_id": "a1", "make": "peugeot", "model": "206",
     "year_jalali": 1393, "mileage_km": 174538,
     "asking_price_toman": 592984063, "price_currency_raw": "IRR",
     "description": "ماشین سالم، سند آزاد", "km_line": "کارکرد ۱۷۴٬۵۳۸ کیلومتر",
     "seller_fingerprint": "a1b2c3d4e5f6a7b8", "payload_sha": "deadbeef"},
]}
LEAK = json.loads(json.dumps(CLEAN))
LEAK["listings"][0]["color"] = "سفید ۰۹۱۲۳۴۵۶۷۸۹"     # an ALLOWED field
PROSE = json.loads(json.dumps(CLEAN))
PROSE["listings"][0]["description"] = "تماس ۰۹۳۶۱۰۴۲۹۸۸ ماشین بدون رنگ"
REFUSE = {"taken_on": "2026-09-07", "listings": [
    {"listing_id": "b1", "year_jalali": 1399, "asking_price_toman": 700000000,
     "km_line": "نمایشگاه اتومبیل — ۰۲۱۸۸۷۷۶۶۵۵"}]}


def promote(fixture):
    """Run the real script. Returns (exit code, whether a file exists, text)."""
    with tempfile.TemporaryDirectory() as d:
        src, dst = Path(d) / "in.json", Path(d) / "out.json"
        src.write_text(json.dumps(fixture, ensure_ascii=False), encoding="utf-8")
        p = subprocess.run(
            [sys.executable, "scripts/promote_corpus.py", "--input", str(src),
             "--run-id", "t", "--output", str(dst)],
            cwd=ROOT, capture_output=True, text=True,
            env={"PYTHONPATH": ".", "PATH": "/usr/bin:/bin"})
        return p.returncode, dst.exists(), (dst.read_text(encoding="utf-8")
                                            if dst.exists() else "")


code, exists, text = promote(CLEAN)
check("clean snapshot promotes", code == 0 and exists)
check("  and the artifact declares the schema", f'"{SCHEMA}"' in text)
check("  and carries provenance for the input it came from",
      '"input_sha256"' in text)
check("  and the guards pass their own output",
      not validate(json.loads(text), text))

code, exists, _ = promote(LEAK)
check("an identifier in an ALLOWED field is refused", code == 1)
check("  and NO artifact is written — a file on disk is a file someone commits",
      not exists)

code, exists, text = promote(PROSE)
check("an identifier confined to the description does not block promotion",
      code == 0 and exists)
check("  and never reaches the artifact", "09361042988" not in text
      and "۰۹۳۶۱۰۴۲۹۸۸" not in text)

code, exists, _ = promote(REFUSE)
check("a row whose only mileage evidence is tainted is refused", code == 1)
check("  and again nothing is written", not exists)

# ---------------------------------------------------------------------------
print("\nmigration property — a corpus may be stricter, never more permissive")
# ---------------------------------------------------------------------------
# NOT equality. The published artifact deliberately holds less than the
# snapshot did: no prose, and no parse-time price provenance. So the property
# that has to hold is one-directional — a corpus can refuse a listing the
# legacy path admitted, and must never admit one the legacy path refused.

from caro.corpus_reader import (                                    # noqa: E402
    CorpusUnavailable, listing_from_record, listings_from_corpus, load_corpus,
)
from caro.ingest.bama import ParseTrace, parse_detail_page          # noqa: E402
from caro.ingest.quality import eligibility as _elig                # noqa: E402
from scripts.replay_run3 import rebuild                             # noqa: E402

# One listing, expressed both ways. Positional order is replay_run3's:
# SLUG ANCHORED DEALER YEAR KM PRICE CUR KM_LINE PRICE_TEXT COND DESC
LEGACY_REC = ["saipa-pride-ex", True, False, 1393, 174538, 592984063, "IRR",
              "کارکرد ۱۷۴٬۵۳۸ کیلومتر", "۵۹۲٬۹۸۴٬۰۶۳", "بدون رنگ",
              "ماشین سالم، سند آزاد"]
SNAP_REC = {"listing_id": "saipa", "make": "Saipa", "model": "Pride",
            "trim": "ex",
            "year_jalali": 1393, "mileage_km": 174538,
            "asking_price_toman": 592984063, "price_currency_raw": "IRR",
            "km_line": "کارکرد ۱۷۴٬۵۳۸ کیلومتر",
            "description": "ماشین سالم، سند آزاد", "condition": "intact"}

url, page = rebuild(LEGACY_REC)
legacy = parse_detail_page(url, page, trace=ParseTrace())
check("the legacy path still parses the shared fixture", legacy is not None)
legacy_ok = _elig(legacy)[0] if legacy else False
check("  and admits it to W1", legacy_ok, str(_elig(legacy)[1]) if legacy else "")

code, exists, text = promote({"taken_on": "2026-09-07", "listings": [SNAP_REC]})
check("the same listing promotes to a corpus artifact", code == 0 and exists)
corpus_listing = listings_from_corpus(json.loads(text))[0]
corpus_ok, corpus_why = _elig(corpus_listing)

check("THE PROPERTY: corpus is not more permissive than legacy",
      not (corpus_ok and not legacy_ok),
      "a corpus admitting what the legacy path refused is the failure this "
      "migration must not have")
check("  here it is strictly stricter — provenance is unavailable",
      legacy_ok and not corpus_ok, f"legacy={legacy_ok} corpus={corpus_ok}")
check("  and it says which provenance, rather than borrowing another reason",
      all("provenance unknown" in w for w in corpus_why), str(corpus_why))

# The other direction, so the property is not satisfied by refusing everything.
bad_rec = dict(SNAP_REC, asking_price_toman=None, mileage_km=None)
bad_legacy = parse_detail_page(*rebuild(
    ["saipa-pride-ex", True, False, 1393, None, None, "IRR", "کارکرد ۱۷۴٬۵۳۸ کیلومتر",
     "توافقی", "بدون رنگ", ""]), trace=ParseTrace())
check("a listing the legacy path REFUSES is refused by the corpus too",
      not _elig(bad_legacy)[0]
      and not _elig(listing_from_record(bad_rec))[0])

check("prose the contract forbids is empty, not reconstructed",
      corpus_listing.title == "" and corpus_listing.description == "",
      "the reader must not invent what the artifact does not carry")
check("  while the values DERIVED from that prose survive",
      corpus_listing.body_condition == "intact",
      str(corpus_listing.body_condition))

for run in ("run3", "run5"):
    try:
        load_corpus(run)
        check(f"{run} raises CorpusUnavailable", False, "it did not raise")
    except CorpusUnavailable as e:
        check(f"{run} has no corpus, and says so as a prerequisite not a bug",
              "D46" in str(e), str(e)[:60])


# ---------------------------------------------------------------------------
# Evidence identity: the digest is of the FILE, and of nothing else.
#
# A `source` path is not an identity. Two deployments can serve different
# files from `data/corpora/run3.json` and both report that string honestly,
# which is how a number gets published with no way back to what produced it —
# D46, in a form nobody would notice because there is no error.
#
# The check that matters is not "a hash is returned". It is that the hash is
# `sha256sum <file>` and not a digest of this process's re-encoding. A
# re-encoding digest looks identical, passes any naive test, and is worthless:
# it varies with key order, separators, `ensure_ascii` and float repr, so two
# machines can publish different digests for one unmodified artifact. So the
# fixture below is written with non-canonical spacing, and the assertion is
# that the two digests DIFFER and that ours is the file's.
print("\nevidence identity — sha256 of the artifact")

import hashlib                                              # noqa: E402
from caro.corpus_reader import CorpusIdentity, sha256_of    # noqa: E402

with tempfile.TemporaryDirectory() as d:
    art = Path(d) / "run9.json"
    obj = {"schema": SCHEMA, "run_id": "run9", "source": "bama.ir",
           "collected_on": "2026-09-09",
           "listings": [{"listing_id": "a1", "asking_price_toman": 500_000_000,
                         "year_jalali": 1393, "mileage_km": 120_000}]}
    # Deliberately not canonical: extra indent, spaces after separators, and
    # Persian text left as escaped ASCII would be a different byte string.
    art.write_text(json.dumps(obj, indent=4, ensure_ascii=True),
                   encoding="utf-8")

    raw = hashlib.sha256(art.read_bytes()).hexdigest()
    check("sha256_of matches sha256sum of the file", sha256_of(art) == raw,
          f"{sha256_of(art)[:12]} vs {raw[:12]}")

    recoded = hashlib.sha256(
        json.dumps(json.loads(art.read_text(encoding="utf-8")),
                   ensure_ascii=False).encode("utf-8")).hexdigest()
    check("  and a re-encoding of the same object hashes DIFFERENTLY",
          recoded != raw,
          "the fixture failed to make the two encodings differ")
    check("  so the digest published is the file's, not the re-encoding's",
          sha256_of(art) != recoded)

    before = sha256_of(art)
    art.write_bytes(art.read_bytes().replace(b"120000", b"120001"))
    check("  one changed digit changes the digest", sha256_of(art) != before,
          "a digest that survives an edit certifies nothing")

_id = CorpusIdentity(run_id="run9", path="data/corpora/run9.json",
                     sha256="8f3a" + "0" * 56 + "", bytes=1234)
check("identity serialises the four fields a reviewer needs",
      set(_id.as_dict()) == {"run_id", "path", "sha256", "bytes"},
      str(sorted(_id.as_dict())))
check("  and shortens to head…tail for a screen, keeping both ends",
      _id.short.startswith("8f3a") and _id.short.endswith("0000")
      and "…" in _id.short, _id.short)

# There is no artifact for these runs, so there is no identity — and asking
# for one raises rather than returning a placeholder. A digest that stands in
# for "we have no evidence file" is worse than no digest, because it renders
# on screen exactly like one that means something.
from caro.corpus_reader import corpus_identity               # noqa: E402
for run in ("run3", "run5"):
    try:
        corpus_identity(run)
        check(f"{run} identity raises", False, "it did not raise")
    except CorpusUnavailable as e:
        check(f"{run} has no identity because it has no artifact",
              "D46" in str(e), str(e)[:60])


# ---------------------------------------------------------------------------
# D49 — absence is a fallback; failure is not.
#
# The whole point is that this failure is INVISIBLE without a test. A broken
# artifact used to produce a working site serving generated data under a
# SYNTHETIC badge that was, in every case, displayed correctly. Nothing lied.
# So the assertion is not "an error was raised" — nothing raised — it is that
# `kind` is not "SYNTHETIC".
print("\nD49 — a real failure never becomes a synthetic success")

import contextlib as _ctx                                    # noqa: E402
import io as _io                                             # noqa: E402
import caro.corpus_reader as _cr                             # noqa: E402
with _ctx.redirect_stdout(_io.StringIO()):
    import webapp.api.corpus as _corpus_mod                   # noqa: E402

_BROKEN = {
    "invalid schema": '{"schema": "not.caro/9", "run_id": "x", '
                      '"source": "s", "collected_on": "d", "listings": []}',
    "forbidden key survives to disk":
        json.dumps({"schema": SCHEMA, "run_id": "x", "source": "bama.ir",
                    "collected_on": "2026-09-09",
                    "listings": [{"listing_id": "a", "description": "تمیز"}]}),
    "truncated write": '{"schema": "caro.corpus/1", "listi',
    "not json at all": "<html>404 Not Found</html>",
    "empty file": "",
}

_real_corpora = _cr.CORPORA
try:
    for label, body in _BROKEN.items():
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "run3.json").write_text(body, encoding="utf-8")
            _cr.CORPORA = Path(d)
            _corpus_mod.active.cache_clear()
            with _ctx.redirect_stdout(_io.StringIO()):
                got = _corpus_mod.active("run3")
            check(f"{label} → not served as SYNTHETIC",
                  got.kind == "UNUSABLE",
                  f"kind={got.kind!r} — a broken artifact became a working "
                  f"site serving generated data")
            check(f"  and the fault travels in the envelope",
                  bool(got.as_dict().get("fault")), str(got.fault))
            check(f"  and nothing is served from it",
                  got.gated is False and not got.rows and not got.listings)

    # The other half of the rule, which must keep working: a corpus that is
    # genuinely ABSENT still falls back, silently and correctly.
    with tempfile.TemporaryDirectory() as d:
        _cr.CORPORA = Path(d)
        _corpus_mod.active.cache_clear()
        with _ctx.redirect_stdout(_io.StringIO()):
            got = _corpus_mod.active("run3")
        check("an ABSENT corpus still falls back to synthetic",
              got.kind == "SYNTHETIC", f"kind={got.kind!r}")
        check("  and that fallback carries no fault",
              got.fault is None, str(got.fault))
finally:
    _cr.CORPORA = _real_corpora
    _corpus_mod.active.cache_clear()

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
