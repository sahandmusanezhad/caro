#!/usr/bin/env python3
"""What must a stored signal projection carry? Ask the consumers, not us.

    python3 scripts/derive_projection.py

`TrackedListing` stores `FetchOutcome` objects — `last_signals` today, and
the temporal contract proposes `first_signals` beside it. `FetchOutcome` is
an ACQUISITION type: it is what a fetcher hands to tracking, and this session
alone added eleven fields to it. Every one of those is now persisted in W0
state whether tracking needs it or not.

The question is whether a slot should hold the whole type or a narrower
projection of it, and the only honest way to answer is to read what the
consumers actually touch. So nothing here is a proposed field list. Every
name below is pulled out of the AST of a function that reads it:

    eligibility()            what W1 refuses a row for
    features_from_listing()  what reaches the design matrix
    rows_from_corpus()       what a Row is built from
    listing_from_record()    what the corpus→domain mapping reads
    blocking_keys()          \\
    hard_contradictions()     }  what repost matching needs
    repost_match_score()     /

Two results this produces that a hand-written list would not:

  · the CORPUS chain and the REPOST chain want different sets with a small
    overlap, so one stored type serving both hides two different contracts;

  · a consumer reading a key that NO FetchOutcome field can supply is a
    read that returns None forever. That is not visible from either side
    alone — the reader looks correct and the writer looks complete.

A hand-maintained list of fields to audit is exactly what went blind
before: `first_run.py`'s FIELD SURVIVAL table checks thirteen named fields
and printed "every value the parse found reaches the published row" while
three fields parsed at 100% were being dropped at this very boundary. A
list derived from source cannot go blind that way, which is the point of
running this as a script rather than writing the answer down once.

Exit status is 1 if any consumer reads a name that nothing can supply.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def parse(rel: str) -> ast.Module:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def find(mod: ast.Module, name: str, cls=(ast.FunctionDef,)):
    for n in ast.walk(mod):
        if isinstance(n, cls) and getattr(n, "name", None) == name:
            return n
    raise SystemExit(f"derive_projection: {name} not found — did it move?")


def fields_of(cls_node: ast.ClassDef) -> list[str]:
    return [s.target.id for s in cls_node.body if isinstance(s, ast.AnnAssign)]


def attrs_on(fn, roots: set[str]) -> set[str]:
    """Attribute names READ off any name in `roots`, incl. getattr(x, 'y')."""
    out: set[str] = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id in roots and isinstance(n.ctx, ast.Load)):
            out.add(n.attr)
        # `getattr(listing, "product_class", None)` — the fail-closed reads
        # in `eligibility` are written this way precisely so a missing
        # attribute is a value and not an AttributeError, and a scan that
        # only looked at ast.Attribute would miss every one of them.
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "getattr" and len(n.args) >= 2
                and isinstance(n.args[0], ast.Name) and n.args[0].id in roots
                and isinstance(n.args[1], ast.Constant)):
            out.add(n.args[1].value)
    return out


def get_keys(fn, roots: set[str]) -> set[str]:
    """Literal keys in `root.get("x")`."""
    out: set[str] = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in roots and n.args
                and isinstance(n.args[0], ast.Constant)):
            out.add(n.args[0].value)
    return out


def _promotion_reads(mod: ast.Module) -> dict[str, set[str]]:
    """corpus key -> the snapshot keys promotion may fill it from.

    Two shapes appear in `promote_corpus`, and both are read here:

        "condition": condition or "unknown"        a local, assigned above
        "price_kind": rec.get("price_kind")        read inline

    For the first, the local's own `rec.get(...)` reads are followed one
    level. That is deliberately shallow — deeper would be a dataflow
    analysis, and a tool that is hard to trust about its own answer is worse
    than one that reports a small, checkable set.
    """
    locals_: dict[str, set[str]] = {}
    for n in ast.walk(mod):
        if isinstance(n, ast.Assign) and len(n.targets) == 1 \
                and isinstance(n.targets[0], ast.Name):
            got = get_keys(n, {"rec"})
            if got:
                locals_[n.targets[0].id] = got

    out: dict[str, set[str]] = {}
    for n in ast.walk(mod):
        if not isinstance(n, ast.Dict):
            continue
        for k, v in zip(n.keys, n.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            srcs = get_keys(v, {"rec"})
            for sub in ast.walk(v):
                if isinstance(sub, ast.Name) and sub.id in locals_:
                    srcs |= locals_[sub.id]
            if srcs:
                out.setdefault(k.value, set()).update(srcs)
    return out


def show(title: str, names, note: str = "") -> None:
    names = sorted(names)
    print(f"\n{title}  ({len(names)}){'   ' + note if note else ''}")
    print("-" * 70)
    for x in names:
        print(f"    {x}")
    if not names:
        print("    (none)")


def main() -> int:
    q, rk, cr, tr = (parse("caro/ingest/quality.py"), parse("caro/ranking.py"),
                     parse("caro/corpus_reader.py"), parse("caro/tracking.py"))

    fetch_fields = set(fields_of(find(tr, "FetchOutcome", (ast.ClassDef,))))
    car_fields = set(fields_of(
        find(parse("caro/ingest/divar_car.py"), "CarListing", (ast.ClassDef,))))

    elig = attrs_on(find(q, "eligibility"), {"listing"})
    feats = attrs_on(find(rk, "features_from_listing"), {"listing"})
    rows = attrs_on(find(cr, "rows_from_corpus"), {"got"})
    mapped = get_keys(find(cr, "listing_from_record"), {"rec"})

    repost = set()
    for fn, roots in (("blocking_keys", {"o"}),
                      ("hard_contradictions", {"old", "new"}),
                      ("repost_match_score", {"old", "new"})):
        repost |= attrs_on(find(tr, fn), roots)
    repost &= fetch_fields

    # Promotion RENAMES some fields, and a scan that ignored that would cry
    # wolf on every one. `corpus_reader` reads the corpus key `condition`;
    # the snapshot carries `body_condition`; `promote_corpus` bridges them.
    # A rename is not a loss, and a tool that reports it as one gets
    # switched off — after which the real losses go unreported too.
    #
    # Read from promote_corpus's own source rather than hardcoded here, so
    # that a mapping changed there cannot silently disagree with this.
    promoted = _promotion_reads(parse("scripts/promote_corpus.py"))

    corpus_wants = (elig | feats | rows | mapped)
    corpus = corpus_wants & fetch_fields
    # A key is supplied if a FetchOutcome field carries it directly, OR if
    # promotion fills it from one that does.
    supplied = fetch_fields | {k for k, srcs in promoted.items()
                               if srcs & fetch_fields}
    corpus |= {f for k, srcs in promoted.items() if k in corpus_wants
               for f in srcs & fetch_fields}
    phantom = corpus_wants - supplied

    print("=" * 70)
    print("WHAT EACH CONSUMER READS   (from its own source, not from a list)")
    print("=" * 70)
    show("eligibility(listing)", elig)
    show("features_from_listing(listing)", feats)
    show("rows_from_corpus -> Row(...)", rows)
    show("listing_from_record(rec) — corpus keys", mapped)

    print("\n" + "=" * 70)
    print(f"AGAINST FetchOutcome ({len(fetch_fields)} fields)")
    print("=" * 70)
    show("A  the CORPUS chain needs", corpus)
    show("B  REPOST matching needs", repost,
         "← this is what last_signals is for")
    show("C  needed by neither", fetch_fields - corpus - repost)

    print(f"\n  A ∩ B  {len(corpus & repost):>3}   both")
    print(f"  A \\ B  {len(corpus - repost):>3}   corpus only")
    print(f"  B \\ A  {len(repost - corpus):>3}   repost only")
    print(f"  A ∪ B  {len(corpus | repost):>3}   of {len(fetch_fields)} — a "
          f"projection would drop {len(fetch_fields - corpus - repost)}")
    print()
    print("  The two slots do not want the same fields. One stored type")
    print("  serving both is one contract standing in for two.")

    print("\n" + "=" * 70)
    print("READS NOTHING CAN SUPPLY")
    print("=" * 70)
    if not phantom:
        print("\n  none — every key a consumer reads is backed by a "
              "FetchOutcome field.")
        return 0
    print("\n  A consumer reads these; no FetchOutcome field carries them, so")
    print("  they are None on every row and always will be:")
    print()
    for name in sorted(phantom):
        where = "PARSED, then dropped at this boundary" if name in car_fields \
            else "never parsed either"
        print(f"    {name:<24}{where}")
    print()
    print("  For the ones marked PARSED: the parser produces a value, the")
    print("  corpus reader asks for it, and FetchOutcome has nowhere to put")
    print("  it in between. That is D51 — a value is not collected until it")
    print("  survives to where it is read.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
