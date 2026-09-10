#!/usr/bin/env python3
"""Promote an operational snapshot into a publishable corpus artifact.

    python3 scripts/promote_corpus.py \
        --input data/snapshots/2026-09-07-bama.json \
        --run-id run6 \
        --output data/corpora/run6.json

`data/snapshots/` is where a collection run writes; it is ignored by git and
may hold seller-authored prose. `data/corpora/` is what the repository
publishes and what a replay command reads. Nothing moves between them by hand
— this is the only writer of the second, and `docs/DATA_CONTRACT.md`
§ *The publishable corpus artifact* is the contract it enforces.

**On failure it writes nothing and exits non-zero.** Not a partial file, not a
file with a warning banner: an artifact that fails a guard must not exist,
because a file on disk is a file someone can commit.

## Derive, then discard — the part that is easy to get wrong

The naive redaction is to drop the prose fields. That silently changes what
the corpus means, because two parsed values are derived from `توضیحات`:

    condition          `extract_body_condition(desc)` is the FALLBACK when the
                       «وضعیت بدنه» spec row is absent (bama.py:693). Drop the
                       prose and those listings become `unknown`, which is
                       CONDITION_RISK 0.35 — a risk score invented by the
                       redaction step.
    document_issue     `has_document_issue(desc)` (bama.py:732) becomes None
                       for every listing.

And `km_line` is structural, not decorative: `body_from` is the index of the
line containing «کارکرد», and it is the anchor separating site navigation from
the article. Every text-derived value is read below it. Drop it and the text
half of the parse collapses; keep it verbatim and dealer ad copy rides along,
which D45 records as the one place a phone number has actually done so.

So promotion **derives first and discards second**, and canonicalises rather
than deletes where a field carries structure:

    توضیحات   ->  condition (when it was the source) + document_issue, then
                  the text is dropped
    km_line   ->  «کارکرد N کیلومتر» rebuilt from the parsed mileage, so the
                  anchor and the fallback value both survive and the ad copy
                  does not. A row whose mileage is unknown AND whose only
                  mileage evidence was that line is refused, not guessed.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from hashlib import sha256
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.corpus import SCHEMA, redact, validate           # noqa: E402
from caro.ingest.divar_car import (                               # noqa: E402
    extract_body_condition, has_document_issue,
)
from caro.ingest.persian import parse_mileage_km                  # noqa: E402
from caro.ingest.quality import Validity, classify_mileage         # noqa: E402

# Keys a snapshot may use for the prose we derive from and then drop.
_DESC_KEYS = ("description", "desc", "DESC", "توضیحات")
_KMLINE_KEYS = ("km_line", "kmLine", "KM_LINE", "mileage_text")


def _first(rec: dict, keys) -> str:
    for k in keys:
        v = rec.get(k)
        if v:
            return str(v)
    return ""


def canonical_km_line(rec: dict, year: int | None) -> tuple[str | None, str | None]:
    """(line, refusal). Rebuild the anchor from the number, never the prose.

    Two refusals here, and the second was found by a fixture rather than by
    reasoning. `parse_mileage_km` reads «نمایشگاه اتومبیل — ۰۲۱۸۸۷۷۶۶۵۵» as
    2,188,776,655 — a landline turned into an odometer. Dropping the prose
    afterwards then LAUNDERS the number instead of redacting it: the digits
    are in a field called mileage, so the content guard on the finished
    artifact cannot see them.

    So a numeric derivation refuses tainted input before it runs. Deriving
    into a closed vocabulary or a boolean does not need this — a body
    condition and a document flag cannot carry a phone number — but deriving
    into a number or a string can, and that is the whole difference.
    """
    raw = _first(rec, _KMLINE_KEYS)
    km = rec.get("mileage_km")

    if km is None and raw:
        # Redact identifiers, THEN parse the remainder. Refusing the whole
        # line was measured to cost good rows, and parsing first is the
        # laundering path this exists to close.
        cleaned = redact(raw)
        km = parse_mileage_km(cleaned)
        if km is None:
            return None, ("no mileage survives once contact identifiers are "
                          "removed from the only free-text evidence")
        j = classify_mileage(km, year)
        if j.status is not Validity.PLAUSIBLE:
            return None, (f"mileage derived from free text is not plausible "
                          f"({j.reason}); refusing rather than publishing it")

    if km is None:
        if raw:
            return None, ("mileage unknown and the only evidence was a free "
                          "text line, which may not be published verbatim")
        return None, None
    return f"کارکرد {int(km):,} کیلومتر", None


def promote_record(rec: dict) -> tuple[dict | None, str | None]:
    """One snapshot record -> one publishable row, or a refusal reason."""
    desc = _first(rec, _DESC_KEYS)
    year = rec.get("year_jalali") or rec.get("YEAR")
    km_line, refusal = canonical_km_line(rec, year)
    if refusal:
        return None, refusal

    # `"unknown"` is what the parser writes when it looked and found nothing.
    # Treating it as a value would publish `condition_source: "field"` about
    # an absence, and the fallback below would never run.
    # `body_condition` is what a snapshot record is keyed on — `asdict` of a
    # FetchOutcome uses the field's own name — while `condition` is what the
    # published row is keyed on and what hand-written fixtures use. Reading
    # only the second was the last link in the same chain: the value now
    # crossed into the snapshot and was dropped one step later, by a `.get`
    # that named the corpus's spelling instead of the snapshot's.
    condition = (rec.get("condition") or rec.get("body_condition")
                 or rec.get("COND") or "")
    if condition == "unknown":
        condition = ""
    # A record that carries its own provenance is believed. Only a record
    # that carries a condition with no provenance is assumed to have got it
    # from a spec row — that assumption was safe while the only records with
    # a condition were hand-written fixtures, and stops being safe the moment
    # a snapshot carries one.
    recorded_source = rec.get("condition_source") or ""
    if condition:
        condition_source = (recorded_source
                            if recorded_source in ("field", "description")
                            else "field")
    else:
        condition_source = "none"
    if not condition and desc:
        derived = extract_body_condition(desc)
        if derived and derived != "unknown":
            condition, condition_source = derived, "description"

    out = {
        "listing_id": rec.get("listing_id") or rec.get("slug") or rec.get("SLUG"),
        "source": rec.get("source"),
        "year_jalali": year,
        "mileage_km": rec.get("mileage_km"),
        "asking_price_toman": rec.get("asking_price_toman") or rec.get("PRICE"),
        "price_currency_raw": rec.get("price_currency_raw") or rec.get("CUR"),
        "make": rec.get("make"), "model": rec.get("model"),
        "trim": rec.get("trim"), "color": rec.get("color"),
        "province": rec.get("province"),
        "condition": condition or "unknown",
        "condition_source": condition_source,
        # The record's own value wins. Re-deriving from prose was the only
        # option while the prose was the only thing that reached here, and it
        # silently became "no paperwork issue on any car" once it wasn't.
        "document_issue": (rec["document_issue"]
                           if rec.get("document_issue") is not None
                           else (has_document_issue(desc) if desc else None)),
        # D26: a badge is evidence, its absence is not. `dealer_badge` stays
        # a bool because that is what it means — a badge was seen — while
        # `seller_type` keeps the three-way distinction, so a car with no
        # badge is never published as `private`.
        "dealer_badge": bool(rec.get("dealer") or rec.get("DEALER")
                             or rec.get("seller_type") == "dealer"),
        "seller_type": rec.get("seller_type"),
        # What the record IS. Published because a consumer filtering a corpus
        # down to used cars has no other way to do it: a حواله carries a
        # year, a model and a price like any listing, and the estimator would
        # price it as the cheapest car of its model on the market.
        "product_class": rec.get("product_class"),
        "product_class_source": rec.get("product_class_source"),
        "price_kind": rec.get("price_kind"),
        "price_kind_source": rec.get("price_kind_source"),
        # Provenance, not evidence: it lets a person open the page a row came
        # from. It is not prose, carries no contact identifier, and the
        # content guard runs over it like everything else — a url that did
        # read as a phone number would refuse the whole artifact, which is
        # the behaviour we want.
        "source_url": rec.get("source_url"),
        "seller_fingerprint": rec.get("seller_fingerprint"),
        "payload_sha": rec.get("payload_sha"),
        "km_line": None,          # replaced below; the key is forbidden
    }
    del out["km_line"]
    if km_line:
        out["mileage_line_canonical"] = km_line
    if not out["listing_id"]:
        return None, "no listing identifier"
    return {k: v for k, v in out.items() if v is not None}, None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--run-id", required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--source", default="bama")
    ap.add_argument("--collected-on", default=None,
                    help="ISO date the snapshot was taken; read from it if absent")
    a = ap.parse_args()

    if not a.input.exists():
        print(f"no such snapshot: {a.input}", file=sys.stderr)
        return 2

    raw = json.loads(a.input.read_text(encoding="utf-8"))
    records = (raw.get("listings") or raw.get("outcomes")
               if isinstance(raw, dict) else raw) or []

    rows, refused = [], []
    for i, rec in enumerate(records):
        if not isinstance(rec, dict):
            refused.append((i, "record is not an object; positional corpora "
                               "must be converted before promotion"))
            continue
        row, why = promote_record(rec)
        (rows.append(row) if row else refused.append((i, why)))

    artifact = {
        "schema": SCHEMA,
        "run_id": a.run_id,
        "source": a.source,
        "collected_on": (a.collected_on
                         or (raw.get("taken_on") if isinstance(raw, dict) else None)
                         or date.today().isoformat()),
        "promoted_on": datetime.now(timezone.utc).date().isoformat(),
        "provenance": {
            "input_name": a.input.name,
            "input_sha256": sha256(a.input.read_bytes()).hexdigest(),
            "records_in": len(records),
            "records_published": len(rows),
            "records_refused": len(refused),
        },
        "listings": rows,
    }

    serialized = json.dumps(artifact, ensure_ascii=False, indent=1,
                            sort_keys=True)
    violations = validate(artifact, serialized)

    print(f"{len(records)} in · {len(rows)} publishable · {len(refused)} refused")
    for i, why in refused[:10]:
        print(f"  refused #{i}: {why}")
    if len(refused) > 10:
        print(f"  … and {len(refused) - 10} more")

    if violations:
        print(f"\nREFUSING TO WRITE — {len(violations)} guard violation(s):",
              file=sys.stderr)
        for v in violations[:20]:
            print(str(v), file=sys.stderr)
        if len(violations) > 20:
            print(f"  … and {len(violations) - 20} more", file=sys.stderr)
        print("\nNo artifact was written. An artifact that fails a guard must "
              "not exist on disk, because a file on disk is a file someone "
              "can commit.", file=sys.stderr)
        return 1

    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(serialized, encoding="utf-8")
    print(f"\nwrote {a.output} ({len(serialized):,} bytes, both guards clean)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
