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
# A third reason joined the two provenance ones when `product_class` was
# added: a corpus artifact written before that field existed does not state
# whether its rows are cars or حواله, and an undetermined class fails closed
# exactly like an unrecorded provenance. That is the same property, not a new
# one — but the count is pinned so a FOURTH reason has to be looked at rather
# than absorbed by a substring match.
check("  and every refusal names something the artifact does not carry",
      all("provenance unknown" in w or w.startswith("product class is")
          or w.startswith("price is a") for w in corpus_why),
      str(corpus_why))
check("    price provenance, mileage provenance, class and kind — no more",
      len(corpus_why) == 4, str(corpus_why))

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
import os as _os                                             # noqa: E402
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
_real_run = _os.environ.get(_corpus_mod.RUN_ENV)


def _serving(dir_: Path, run_env: str | None):
    """What `active()` returns with this corpora directory and this CARO_RUN.

    The environment is set here rather than in the test body because the run
    is no longer a parameter: it is read inside `active()`, so a suite that
    does not control the variable is testing whatever the shell had.
    """
    _cr.CORPORA = dir_
    if run_env is None:
        _os.environ.pop(_corpus_mod.RUN_ENV, None)
    else:
        _os.environ[_corpus_mod.RUN_ENV] = run_env
    _corpus_mod.active.cache_clear()
    with _ctx.redirect_stdout(_io.StringIO()):
        return _corpus_mod.active()


try:
    # The artifact is named after the DEFAULT, read from the module. Hardcoding
    # "run3" here is how this suite kept passing while `active()` defaulted to
    # a run that had not existed since D46 and the site served SYNTHETIC on
    # every request: the test wrote the file the default named, so the default
    # was never wrong from in here.
    _default = _corpus_mod.DEFAULT_RUN
    for label, body in _BROKEN.items():
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / f"{_default}.json").write_text(body, encoding="utf-8")
            got = _serving(Path(d), None)
            check(f"{label} → not served as SYNTHETIC",
                  got.kind == "UNUSABLE",
                  f"kind={got.kind!r} — a broken artifact became a working "
                  f"site serving generated data")
            check(f"  and the fault travels in the envelope",
                  bool(got.as_dict().get("fault")), str(got.fault))
            check(f"  and it is reported as the FILE being broken",
                  got.fault_code == "CORPUS_INVALID", str(got.fault_code))
            check(f"  and nothing is served from it",
                  got.gated is False and not got.rows and not got.listings)

    # The other half of the rule, which must keep working: a corpus that is
    # genuinely ABSENT still falls back. Not silently any more — see below.
    with tempfile.TemporaryDirectory() as d:
        got = _serving(Path(d), None)
        check("an ABSENT default corpus still falls back to synthetic",
              got.kind == "SYNTHETIC", f"kind={got.kind!r}")
        check("  and that fallback carries no fault — absence is not failure",
              got.fault is None, str(got.fault))
        # The half that was missing. The fallback was correct and mute: it
        # never said which artifact it had looked for, so a deployment with a
        # corpus sitting in the wrong place looked exactly like one with no
        # corpus at all.
        check("  but it NAMES the artifact it looked for and did not find",
              f"{_default}.json" in got.note_fa, got.note_fa[-90:])

    # And the case that used to be indistinguishable from absence: somebody
    # said which run to serve, and it is not there.
    with tempfile.TemporaryDirectory() as d:
        got = _serving(Path(d), "run_that_does_not_exist")
        check("a run that was ASKED FOR and is missing is not a fallback",
              got.kind == "UNUSABLE", f"kind={got.kind!r}")
        check("  and it is NOT reported as a corrupt file",
              got.fault_code == "RUN_NOT_FOUND", str(got.fault_code))
        check("  and nothing is served from it",
              got.gated is False and not got.rows and not got.listings)
        check("  and the message names the run that was asked for",
              "run_that_does_not_exist" in (got.fault or ""), str(got.fault))

    # Same directory, same emptiness, two different answers — which is the
    # whole point of `configured()` returning the flag.
    with tempfile.TemporaryDirectory() as d:
        check("an empty directory is SYNTHETIC or UNUSABLE depending only on "
              "whether a run was named",
              _serving(Path(d), None).kind == "SYNTHETIC"
              and _serving(Path(d), "runX").kind == "UNUSABLE")
finally:
    _cr.CORPORA = _real_corpora
    if _real_run is None:
        _os.environ.pop(_corpus_mod.RUN_ENV, None)
    else:
        _os.environ[_corpus_mod.RUN_ENV] = _real_run
    _corpus_mod.active.cache_clear()

# ---------------------------------------------------------------------------
print("\nthe date-watch summary carries D58's numbers, and only four fields")
# ---------------------------------------------------------------------------
#
# `data/observations/` is operational and stays out of the repository: its
# records hold truncated page text. D58 draws four cells, a population and a
# maximum out of it, and until this artifact existed nobody could add them up
# — the condition D57 refuses in the case of a digest.
#
# The arithmetic below is written out again rather than imported from
# `scripts/date_watch.py`. That is deliberate and it is the whole value of the
# check: importing `summarise()` would compare the generator with itself and
# agree with any bug it has. Two implementations of one definition, the way
# test_claims.py verifies its glob against an independent os.walk.
#
# The definition, in full, so that neither implementation is the authority:
#
#     age            = observed_date − title_date_iso, where a title date exists
#     table A bins   by that age
#     table B bins   by phrase_days where it exists, by the age where it does not
#     both cover     the observations with an age defined, and nothing else
#
# D58's first draft printed B's figure under A's label and mis-added a column,
# so both tables are checked under their own names, and both are required to
# sum to the population — a cross-total catches a transposition that no single
# cell can.

_SUM = ROOT / "data" / "derived" / "date_watch_summary.json"
check("data/derived/date_watch_summary.json is in the repository",
      _SUM.exists(), "run `python3 scripts/date_watch.py --export`")

if _SUM.exists():
    _doc = json.loads(_SUM.read_text(encoding="utf-8"))
    _obs = _doc["observations"]
    _ALLOWED = {"listing_id", "observed_at", "phrase_days", "title_date_iso"}

    check(f"every one of its {len(_obs)} rows carries exactly the four "
          f"permitted fields",
          all(set(r) == _ALLOWED for r in _obs),
          str(sorted({k for r in _obs for k in r} - _ALLOWED)))

    # Named individually rather than as "anything not permitted", because the
    # risk is a specific set of fields that exist in the observation record
    # and must never cross into a published one. A reader should be able to
    # see which.
    _NEVER = ("title_raw", "title_decoded", "line_after_1", "line_after_2",
              "mileage_line", "matched_substring", "url")
    _blob = _SUM.read_text(encoding="utf-8")
    for _k in _NEVER:
        check(f"  «{_k}» appears nowhere in the artifact",
              f'"{_k}"' not in _blob)

    from datetime import date as _date, datetime as _dt      # noqa: E402

    def _age(r):
        return (_dt.fromisoformat(r["observed_at"]).date()
                - _date.fromisoformat(r["title_date_iso"])).days

    _aged = [r for r in _obs if r["title_date_iso"]]
    _A = {"0-6": [0, 0], "7+": [0, 0]}
    _B = {"0-6": [0, 0], "7+": [0, 0]}
    for _r in _aged:
        _shown = _r["phrase_days"] is not None
        _a = _age(_r)
        _d = _r["phrase_days"] if _shown else _a
        _A["0-6" if _a <= 6 else "7+"][0 if _shown else 1] += 1
        _B["0-6" if _d <= 6 else "7+"][0 if _shown else 1] += 1
    _bearing = [r for r in _obs if r["phrase_days"] is not None]
    _mx = max((r["phrase_days"] for r in _bearing), default=None)

    _ag = _doc["aggregates"]
    check(f"the artifact's own count of age-defined rows is {len(_aged)}",
          _ag["age_defined"] == len(_aged), f"it says {_ag['age_defined']}")
    check(f"by title age: 0–6 {_A['0-6']}, 7+ {_A['7+']}",
          {k: list(v) for k, v in _A.items()} == _ag["by_title_age"],
          f"the artifact says {_ag['by_title_age']}")
    check(f"by phrase value: 0–6 {_B['0-6']}, 7+ {_B['7+']}",
          {k: list(v) for k, v in _B.items()} == _ag["by_phrase_value"],
          f"the artifact says {_ag['by_phrase_value']}")
    check(f"max_phrase_days is {_mx} over {len(_bearing)} phrase-bearing row(s)",
          (_ag["max_phrase_days"], _ag["phrase_bearing"])
          == (_mx, len(_bearing)),
          f"the artifact says {_ag['max_phrase_days']} over "
          f"{_ag['phrase_bearing']}")
    for _name, _t in (("by_title_age", _A), ("by_phrase_value", _B)):
        check(f"  {_name}: the four cells sum to {len(_aged)}",
              sum(sum(v) for v in _t.values()) == len(_aged))

    # --- and now the document -------------------------------------------
    #
    # The oracle is the artifact. D58 is the claim being tested, so its
    # numbers are READ rather than trusted, and nothing here is a literal
    # copied from it — a check that took its expected values from the entry
    # would agree with whatever the entry happened to say, which is how the
    # first draft passed a review.
    #
    # Only the tabular cells, the population and the maximum are checked.
    # D58's sentence about the one listing still inside the horizon is prose,
    # and a regex over prose is a guard that breaks when someone improves a
    # sentence rather than when a number goes wrong.
    import re as _re                                          # noqa: E402

    _d58 = _re.search(r"^## D58\b.*?(?=^## D|\Z)",
                      (ROOT / "docs" / "DECISIONS.md").read_text(
                          encoding="utf-8"), _re.S | _re.M)
    check("docs/DECISIONS.md contains D58", _d58 is not None)
    if _d58:
        _body = _d58.group(0)
        _says = {"age": {}, "d": {}}
        for _kind, _lo, _hi, _p, _ab in _re.findall(
                r"^\s*(age|d)\s*(\d+)\s*[–-]\s*(\d+)"
                r"[^\n]*?present\s+(\d+)\s+absent\s+(\d+)", _body, _re.M):
            _says[_kind]["0-6" if int(_lo) == 0 else "7+"] = [int(_p), int(_ab)]
        for _label, _table, _key in (("title-derived age", _A, "age"),
                                     ("the phrase's own value", _B, "d")):
            for _bin in ("0-6", "7+"):
                check(f"D58 states bin {_bin} of the table by {_label} as "
                      f"{_table[_bin]}",
                      _says[_key].get(_bin) == _table[_bin],
                      f"it states {_says[_key].get(_bin)}")
        _n = _re.search(r"(\d+)\s+observations? where an age is defined", _body)
        check(f"D58 states the population its tables cover ({len(_aged)})",
              bool(_n) and int(_n[1]) == len(_aged),
              f"it states {_n[1]}" if _n else "it does not state it at all")
        _m = _re.search(
            r"over\s+all\s+(\d+)\s+phrase-bearing observations is (\d+)", _body)
        check(f"D58 states max_phrase_days {_mx} over {len(_bearing)}",
              bool(_m) and (int(_m[2]), int(_m[1])) == (_mx, len(_bearing)),
              f"it states {_m[2]} over {_m[1]}" if _m else "it states neither")


# ---------------------------------------------------------------------------
print("\nthe eligibility table and the document say the same thing")
# ---------------------------------------------------------------------------
#
# `docs/FIELD_PROVENANCE.md` is where the judgement lives, measured against
# run11. `webapp/api/eligibility.py` is where a renderer will read it. Two
# declarations, compared here — parsing the document into the module instead
# would give one declaration and a test that compares it with itself.
#
# The document is also checked against the artifact, so the chain is:
#
#     data/corpora/run11.json  →  FIELD_PROVENANCE.md  →  eligibility.FIELDS
#
# and a break anywhere in it fails, naming the link.

from webapp.api.eligibility import (                              # noqa: E402
    FIELDS as _ELIG, RENDERER_CONSUMES as _CONSUMES, STATUSES as _STATUSES)

_DOC = (ROOT / "docs" / "FIELD_PROVENANCE.md").read_text(encoding="utf-8")
_TABLE = _re.compile(
    r"^\| `(\w+)` \| `(\w+)` \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| (\S+) \| "
    r"(\S+) \|", _re.M)
_doc_rows = _TABLE.findall(_DOC)

check(f"FIELD_PROVENANCE.md has a readable table ({len(_doc_rows)} rows)",
      len(_doc_rows) >= 20, f"parsed {len(_doc_rows)}")

if _doc_rows:
    _BOOL = {"yes": True, "no": False}
    _doc = {}
    for _f, _st, _filled, _dist, *_flags in _doc_rows:
        check(f"  {_f}: card/detail/gate/facet are yes or no",
              all(v in _BOOL for v in _flags), str(_flags))
        check(f"  {_f}: «{_st}» is one of the five statuses",
              _st in _STATUSES)
        if all(v in _BOOL for v in _flags):
            _doc[_f] = (_st, *(_BOOL[v] for v in _flags), _filled, _dist)

    # ---- the document against the artifact ------------------------------
    _EMPTY = {None, "", "unknown", "none"}
    _art = json.loads((ROOT / "data" / "corpora" / "run11.json")
                      .read_text(encoding="utf-8"))["listings"]
    _keys = {k for r in _art for k in r}
    for _f, (_st, _c, _d, _g, _fa, _filled, _dist) in sorted(_doc.items()):
        if _filled == "—":
            check(f"  {_f}: dashed in the document, and not a key in run11",
                  _f not in _keys)
            continue
        _nn = [r.get(_f) for r in _art if r.get(_f) not in _EMPTY]
        _got = f"{len(_nn)}/{len(_art)}"
        _n_dist = len({json.dumps(x, ensure_ascii=False) for x in _nn})
        check(f"  {_f}: run11 says {_got}, {_n_dist} distinct",
              (_filled, _dist) == (_got, str(_n_dist)),
              f"the document says {_filled}, {_dist}")

    # ---- the document against the module --------------------------------
    check(f"every field in the document is in eligibility.FIELDS "
          f"({len(_doc)})",
          set(_doc) == set(_ELIG),
          f"doc-only {sorted(set(_doc) - set(_ELIG))} · "
          f"code-only {sorted(set(_ELIG) - set(_doc))}")

    for _f in sorted(set(_doc) & set(_ELIG)):
        _st, _c, _d, _g, _fa, *_ = _doc[_f]
        _e = _ELIG[_f]
        check(f"  {_f}: {_st} card={_c} detail={_d} gate={_g} facet={_fa}",
              (_e.status, _e.card, _e.detail, _e.gate, _e.facet)
              == (_st, _c, _d, _g, _fa),
              f"the module says {_e.status} card={_e.card} "
              f"detail={_e.detail} gate={_e.gate} facet={_e.facet}")

    # ---- the invariant that does not depend on either file ---------------
    _pending = sorted(f for f, e in _ELIG.items()
                      if e.status == "PENDING_LIVE_VALIDATION")
    check(f"nothing PENDING_LIVE_VALIDATION is drawn or chosen "
          f"({', '.join(_pending)})",
          all(not (_ELIG[f].card or _ELIG[f].gate or _ELIG[f].facet)
              for f in _pending))

    # ---- and the one with nothing to check yet, said out loud ------------
    #
    # No renderer exists, so RENDERER_CONSUMES is empty and this check has no
    # input. Printing the zero is the difference between a guard that is green
    # because it passed and one that is green because it looked at nothing.
    for _surface, _fields in sorted(_CONSUMES.items()):
        _illegal = sorted(f for f in _fields
                          if not getattr(_ELIG.get(f, _ELIG["image"]),
                                         _surface))
        check(f"  renderer/{_surface}: {len(_fields)} field(s) declared, "
              f"none ineligible",
              not _illegal, f"ineligible: {_illegal}")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
