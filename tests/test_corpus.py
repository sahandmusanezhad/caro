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

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
