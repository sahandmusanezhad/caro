#!/usr/bin/env python3
"""Load the published corpora into the catalog, and check what it holds.

    CARO_CATALOG_URL=sqlite:///data/catalog.sqlite3 python3 scripts/catalog_load.py
    python3 scripts/catalog_load.py --replace run17      a run whose file changed
    python3 scripts/catalog_load.py --verify             every run's bytes, again

The catalog is the database `CARO_CATALOG_URL` names (caro/catalog.py),
`sqlite:///<path>` or `postgresql://...`; for Postgres, psycopg is needed.
Loading is idempotent: a run already there with the same digest is left as
it is, and one whose file changed is refused unless --replace names it.

A run already loaded is known by its digest and not checked again: its
bytes passed the guards when they were loaded. `--verify` writes nothing.
For every run it gives back the published text from the catalog's rows,
checks its sha256 and size against the ones the run was loaded with -- the
digest the site shows, recomputed -- and runs today's guards over it, which
can have changed since.

Exit status: 0 when every corpus is in the catalog as published (and, with
--verify, every run gives its bytes back); 1 when one was refused or did
not verify; 2 when no catalog is named or it cannot be opened.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from caro.catalog import CATALOG_ENV, CatalogError, open_catalog  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--corpora", type=Path,
                    default=Path(os.environ.get("CARO_CORPORA") or ROOT / "data" / "corpora"),
                    help="the directory of published corpora (default: data/corpora)")
    ap.add_argument("--replace", action="append", default=[], metavar="RUN",
                    help="replace this run if its file changed; may be given more than once")
    ap.add_argument("--verify", action="store_true",
                    help="load nothing; give back every run's bytes and check their digest")
    a = ap.parse_args(argv)

    if not os.environ.get(CATALOG_ENV, "").strip():
        print(f"{CATALOG_ENV} is not set: it names the catalog, "
              "sqlite:///<path> or postgresql://...", file=sys.stderr)
        return 2
    try:
        cat = open_catalog(migrate=not a.verify)
    except CatalogError as e:
        print(f"the catalog cannot be opened: {e}", file=sys.stderr)
        return 2
    assert cat is not None
    try:
        if a.verify:
            return _verify(cat)
        return _load(cat, a.corpora, frozenset(a.replace))
    finally:
        cat.close()


def _load(cat, corpora: Path, replace: frozenset[str]) -> int:
    if not corpora.is_dir():
        print(f"{corpora} is not a directory of corpora", file=sys.stderr)
        return 1
    done, refused = cat.load_corpora(corpora, replace=replace)
    for d in done:
        print(f"  {d.run_id:<10} {d.did:<9} {d.listings:>7,} listings  sha256 {d.sha256[:12]}…")
    for name, why in refused:
        print(f"  {name:<10} REFUSED   {why}")
    if any("is not changed" in why for _name, why in refused):
        print("  a run whose file changed on purpose is replaced with --replace RUN")
    on_disk = {p.stem for p in corpora.glob("*.json")}
    only_there = [r["run_id"] for r in cat.runs() if r["run_id"] not in on_disk]
    if only_there:
        # Kept: a published run is not taken out of the catalog because its
        # file is not in this directory. Said, because a model's history in
        # the catalog then has runs that the files do not.
        print(f"  in the catalog and not in {corpora}: {', '.join(only_there)}")
    print(f"{len(done)} in the catalog as published, {len(refused)} refused")
    return 1 if refused else 0


def _verify(cat) -> int:
    runs = cat.runs()
    bad = [r["run_id"] for r in runs if not cat.verify(r["run_id"])]
    refused = {r["run_id"]: cat.recheck(r["run_id"]) for r in runs}
    for r in runs:
        mark = "DIFFERS" if r["run_id"] in bad else "same bytes"
        guards = (f"today's guards refuse it: {len(refused[r['run_id']])}, the first: "
                  f"{str(refused[r['run_id']][0]).strip()}" if refused[r["run_id"]] else "today's guards take it")
        print(f"  {r['run_id']:<10} {mark:<10} sha256 {r['sha256'][:12]}…  {int(r['bytes']):,} bytes  {guards}")
    n_refused = sum(1 for v in refused.values() if v)
    print(f"{len(runs) - len(bad)} of {len(runs)} runs give back the bytes they were loaded from; "
          f"today's guards refuse {n_refused}")
    return 1 if bad or n_refused else 0


if __name__ == "__main__":
    raise SystemExit(main())
