"""The catalog keeps every published run as it was published, and only adds.

    Run: PYTHONPATH=. python3 tests/test_catalog.py

WHY THIS SUITE EXISTS

`caro/catalog.py` holds the published runs in a database, so that a model's
history is read by an index instead of every corpus in memory
(docs/SERVICES.md, step 1). Four of its promises fail silently if they
fail: that the bytes a run was published as come back from its rows, so the
digest the site shows is still the artifact's; that a published run is not
changed by loading a different file under its name; that a run is written
whole or not at all; and that the catalog shares a database with the seller
store without either reading the other's tables. Each has rows here.

It needs nothing beyond Python and numpy: the catalog is SQLite here, in a
temporary file, loaded from data/corpora. The same rows run against Postgres
when CARO_TEST_CATALOG_URL names an empty database made for them, with
psycopg installed -- CI does that -- and the suite refuses a database that
already holds anything.
"""
import hashlib
import json
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caro.catalog import (  # noqa: E402
    AS_PUBLISHED, CATALOG_ENV, HEAD, MIGRATIONS, TABLES, CatalogError, match_key, open_catalog)
from caro.corpus_reader import corpus_identity  # noqa: E402
from caro.ingest.corpus import serialize  # noqa: E402
from webapp.api.store import MIGRATIONS as STORE_MIGRATIONS, open_store  # noqa: E402

FAILS = []
CORPORA = ROOT / "data" / "corpora"
FILES = sorted(CORPORA.glob("*.json"))
ARTIFACTS = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in FILES}


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def raises(fn, kind=Exception):
    """The exception `fn` raised, or None."""
    try:
        fn()
    except kind as e:          # noqa: BLE001
        return e
    return None


_tmp = tempfile.TemporaryDirectory()
TMP = Path(_tmp.name)
URL = os.environ.get("CARO_TEST_CATALOG_URL") or f"sqlite:///{TMP}/catalog.sqlite3"
CAT = open_catalog(URL)
if raises(lambda: CAT.row("SELECT 1 AS one FROM catalog_runs")) is None:
    print("CARO_TEST_CATALOG_URL names a database that already has a catalog_runs table; "
          "give it an empty one made for this suite")
    raise SystemExit(2)
print(f"\nthe catalog, on {CAT.dialect.name}")


def count(table, where="", params=()):
    return CAT.row(f"SELECT COUNT(*) AS n FROM {table} {where}", params)["n"]


def corpus_dir(name, change=None):
    """A copy of data/corpora in a directory of its own, with `change`
    applied to it (a function of the directory)."""
    d = TMP / name
    d.mkdir()
    for p in FILES:
        (d / p.name).write_bytes(p.read_bytes())
    if change:
        change(d)
    return d


def rewrite(d, run, edit, text=serialize):
    """A run's file in `d`, with `edit` applied to its artifact and written
    by `text` (as promotion writes it, unless told otherwise)."""
    a = json.loads((d / f"{run}.json").read_text(encoding="utf-8"))
    edit(a)
    (d / f"{run}.json").write_text(text(a), encoding="utf-8")


# ---------------------------------------------------------------------------
# What opens, and what refuses
# ---------------------------------------------------------------------------
_was = os.environ.pop(CATALOG_ENV, None)
check("CT1: no CARO_CATALOG_URL, no catalog: the API reads the files",
      open_catalog() is None and open_catalog("  ") is None)
if _was is not None:
    os.environ[CATALOG_ENV] = _was


class _Refusing:
    @staticmethod
    def connect(url, **kw):
        raise RuntimeError(f"could not connect to {url}")


def _no_driver(name):
    raise ImportError(f"No module named {name!r}")


_PW = "hunter2-catalog-pw"
_e2 = [raises(lambda u=u, i=i: open_catalog(u, importer=i), CatalogError) for u, i in (
    (f"mysql://u:{_PW}@db.example/x", None), (_PW, None),
    (f"postgresql://u:{_PW}@db.example/x", _no_driver),
    (f"postgresql://u:{_PW}@db.example/x", lambda name: _Refusing))]
check("CT2: an address the catalog cannot use is refused, naming CARO_CATALOG_URL or what failed and never "
      "the password: another scheme, no scheme, no driver, a server that refuses",
      all(e is not None for e in _e2) and not any(_PW in str(e) for e in _e2)
      and "«mysql»" in str(_e2[0]) and "scheme: none" in str(_e2[1]) and "psycopg" in str(_e2[2])
      and "refused" in str(_e2[3]) and all(CATALOG_ENV in str(e) for e in _e2[:3]),
      str([str(e) for e in _e2]))

# ---------------------------------------------------------------------------
# Migrations, and a database shared with the seller store
# ---------------------------------------------------------------------------
_v0 = CAT.version()
_applied = CAT.migrate()
_again = CAT.migrate()
check("CT3: migrating an empty database applies every migration in order, makes the catalog's tables and "
      "catalog_migrations, and a second migration applies nothing",
      _v0 == 0 and _applied == [n for n, _ in MIGRATIONS] and _again == [] and CAT.version() == HEAD
      and all(raises(lambda t=t: count(t)) is None for t in TABLES + ("catalog_migrations",)),
      str((_v0, _applied, _again)))

_ADDS = re.compile(r"\s*(CREATE TABLE IF NOT EXISTS|CREATE (UNIQUE )?INDEX IF NOT EXISTS"
                   r"|ALTER TABLE \w+ ADD COLUMN)\s", re.I)
_TAKES = re.compile(r"\b(DROP|RENAME|ALTER\s+COLUMN|TRUNCATE)\b", re.I)
_bad = [s.split("(")[0].strip()[:60] for _, stmts in MIGRATIONS for s in stmts
        if not _ADDS.match(s) or _TAKES.search(s)]
_named = [re.match(r"\s*CREATE (?:TABLE|(?:UNIQUE )?INDEX) IF NOT EXISTS (\w+)", s, re.I)
          for _, stmts in MIGRATIONS for s in stmts]
check("CT4: every statement of every migration only adds, the migrations are numbered 1, 2, … in order, "
      "and everything they make is named catalog_…",
      not _bad and [n for n, _ in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))
      and all(m and m.group(1).startswith("catalog_") for m in _named),
      str((_bad, [m.group(1) if m else None for m in _named])))

# One database for both stores, as SERVICES.md allows: the seller store has
# a table called `listings` and records its migrations in schema_migrations.
_both = f"sqlite:///{TMP}/both.sqlite3"
_st = open_store(_both, "made-up-for-the-suites-0123456789abcdef")
_cb = open_catalog(_both, migrate=True)
_seller_head = STORE_MIGRATIONS[-1][0]
check("CT5: in a database the seller store already uses, the catalog makes all its tables and records its "
      "own migrations apart; the store keeps its own, and `listings` stays the store's",
      _cb.version() == HEAD and _st.version() == _seller_head
      and _cb.row("SELECT COUNT(*) AS n FROM schema_migrations")["n"] == len(STORE_MIGRATIONS)
      and _cb.row("SELECT COUNT(*) AS n FROM catalog_migrations")["n"] == len(MIGRATIONS)
      and raises(lambda: _cb.row("SELECT account_id FROM listings")) is None
      and raises(lambda: _cb.row("SELECT record FROM catalog_listings")) is None,
      str((_cb.version(), _st.version())))
_cb.close()
_st.close()

# ---------------------------------------------------------------------------
# Loading the published corpora
# ---------------------------------------------------------------------------
_done, _refused = CAT.load_corpora(CORPORA)
_n = {r: len(a["listings"]) for r, a in ARTIFACTS.items()}
check(f"CT6: data/corpora loads whole: {len(FILES)} runs, {sum(_n.values())} listings, every run loaded and "
      f"none refused, each with as many rows as its artifact has listings",
      not _refused and [d.did for d in _done] == ["loaded"] * len(FILES)
      and {d.run_id: d.listings for d in _done} == _n
      and all(count("catalog_listings", "WHERE run_id = ?", (r,)) == n for r, n in _n.items())
      and {r["run_id"]: int(r["listings"]) for r in CAT.runs()} == _n,
      str((_refused, [(d.run_id, d.did) for d in _done])))

_stamp = {r["run_id"]: CAT.row("SELECT loaded_at FROM catalog_runs WHERE run_id = ?",
                               (r["run_id"],))["loaded_at"] for r in CAT.runs()}
_rows_before = count("catalog_listings")
_done2, _refused2 = CAT.load_corpora(CORPORA)
check("CT7: loading again writes nothing: every run unchanged, its rows and the time it was loaded as they were",
      not _refused2 and [d.did for d in _done2] == ["unchanged"] * len(FILES)
      and count("catalog_listings") == _rows_before
      and all(CAT.row("SELECT loaded_at FROM catalog_runs WHERE run_id = ?", (r,))["loaded_at"] == t
              for r, t in _stamp.items()),
      str([(d.run_id, d.did) for d in _done2]))

_same = {}
for p in FILES:
    _id = corpus_identity(p.stem)
    _txt = CAT.artifact_text(p.stem)
    _same[p.stem] = (_txt == p.read_text(encoding="utf-8") and CAT.verify(p.stem)
                     and CAT.run(p.stem)["sha256"] == _id.sha256 == hashlib.sha256(_txt.encode()).hexdigest()
                     and int(CAT.run(p.stem)["bytes"]) == _id.bytes and CAT.run(p.stem)["path"] == _id.path)
check("CT8: every run's published text comes back from its rows byte for byte; its sha256, size and path are "
      "the ones the files give the site",
      all(_same.values()) and len(_same) == len(FILES), str(_same))

_cols = []
for run, a in ARTIFACTS.items():
    got = CAT.rows("SELECT * FROM catalog_listings WHERE run_id = ? ORDER BY position", (run,))
    if CAT.records(run) != a["listings"] or len(got) != len(a["listings"]):
        _cols.append((run, "records"))
        continue
    for i, (row, rec) in enumerate(zip(got, a["listings"], strict=True)):
        want = {"position": i, "listing_id": rec["listing_id"], "make_key": match_key(rec.get("make")),
                "model_key": match_key(rec.get("model")), **{k: rec.get(k) for k in AS_PUBLISHED}}
        if {k: row[k] for k in want} != want or json.loads(row["record"]) != rec:
            _cols.append((run, i))
check("CT9: every run's records come back in the artifact's order and equal to it, and every row's columns "
      "are its record's values as published, the make and model as a model's page matches them",
      not _cols, str(_cols[:5]))

_wanted = [("Peugeot", "206"), ("", "206"), ("IKCO", "Dena"), ("Saipa", "Pride"), ("", "Pride"),
           (" Saipa ", " Pride "), ("Peugeot", "Pride"), ("", "no such model")]
_hist = []
for mk, md in _wanted:
    want = sorted((run, rec["listing_id"]) for run, a in ARTIFACTS.items() for rec in a["listings"]
                  if match_key(rec.get("model")) == match_key(md)
                  and (not match_key(mk) or match_key(rec.get("make")) == match_key(mk)))
    got = sorted((r["run_id"], r["listing_id"]) for r in CAT.model_rows(mk, md))
    _hist.append((mk, md, len(want), want == got))
check("CT10: a model's rows across the runs are the listings a model's page matches: the make and the model, "
      "the model under any make when the make is left out, spaces ignored, nothing for a pair no run has",
      all(ok for *_, ok in _hist) and _hist[0][2] > 0 and _hist[1][2] >= _hist[0][2] and _hist[-1][2] == 0,
      str(_hist))

_order = [r["run_id"] for r in CAT.runs()]
check("CT11: the runs come in collection date, then name, as a model's history draws them",
      _order == [r for _on, r in sorted((a["collected_on"], r) for r, a in ARTIFACTS.items())], str(_order))

# ---------------------------------------------------------------------------
# A published run is not changed, and a run is written whole or not at all
# ---------------------------------------------------------------------------
_d12 = corpus_dir("changed", lambda d: rewrite(d, "run16", lambda a: a["listings"][0].update(
    mileage_km=(a["listings"][0].get("mileage_km") or 0) + 1)))
_sha16 = CAT.run("run16")["sha256"]
_e12 = raises(lambda: CAT.load_run(_d12 / "run16.json"), CatalogError)
_kept = CAT.run("run16")["sha256"] == _sha16 and CAT.verify("run16")
_r12 = CAT.load_run(_d12 / "run16.json", replace=True)
check("CT12: a changed file under a published run's name is refused, naming both digests, and nothing is "
      "written; asked to replace it, the catalog holds the new file whole and none of the old",
      _e12 is not None and _sha16[:12] in str(_e12) and _kept and _r12.did == "replaced"
      and CAT.run("run16")["sha256"] == hashlib.sha256((_d12 / "run16.json").read_bytes()).hexdigest()
      and CAT.artifact_text("run16") == (_d12 / "run16.json").read_text(encoding="utf-8")
      and count("catalog_listings", "WHERE run_id = ?", ("run16",)) == _n["run16"],
      str((_e12, _r12)))
CAT.load_run(CORPORA / "run16.json", replace=True)


def _phone_in_seller(a):
    a["listings"][0]["seller_type"] = "0912-345-6789"


_bad_files = {
    "named after another run": lambda d: (d / "run13.json").rename(d / "run99.json"),
    "not written as promotion writes it": lambda d: rewrite(
        d, "run13", lambda a: None, text=lambda a: json.dumps(a, ensure_ascii=False, indent=2, sort_keys=True)),
    "a guard violation": lambda d: rewrite(d, "run13", _phone_in_seller),
    "a price that is not whole toman": lambda d: rewrite(
        d, "run13", lambda a: a["listings"][3].update(asking_price_toman=1.5e9)),
    "a listing twice": lambda d: rewrite(d, "run13", lambda a: a["listings"].append(dict(a["listings"][0]))),
    "not JSON": lambda d: (d / "run13.json").write_text('{"schema": "caro.corpus/1", ', encoding="utf-8"),
}
_out13 = {}
_fresh = open_catalog(f"sqlite:///{TMP}/fresh.sqlite3", migrate=True)
for i, (why, change) in enumerate(_bad_files.items()):
    d = corpus_dir(f"bad{i}", change)
    done, refused = _fresh.load_corpora(d)
    named = [n for n, _ in refused]
    _out13[why] = (len(refused) == 1 and named[0] in ("run13.json", "run99.json")
                   and sorted(x.run_id for x in done) == sorted(r for r in ARTIFACTS if r != "run13"))
    _fresh.execute("DELETE FROM catalog_runs")
check("CT13: a file named after another run, one not written as promotion writes, one with a guard violation, "
      "a price that is not whole toman, a listing twice, or not JSON is refused by name, nothing of it is "
      "written, and the other runs load",
      all(_out13.values()) and len(_out13) == len(_bad_files)
      and _fresh.row("SELECT COUNT(*) AS n FROM catalog_listings")["n"] == 0, str(_out13))

_real_many = _fresh.execute_many


def _dies_halfway(sql, params):
    _real_many(sql, list(params)[:10])
    raise RuntimeError("the connection went away halfway")


_fresh.execute_many = _dies_halfway
_e14 = raises(lambda: _fresh.load_run(CORPORA / "run17.json"), CatalogError)
_fresh.execute_many = _real_many
check("CT14: a load that fails halfway leaves nothing: no run row, no listing, and the error says the "
      "database refused the run",
      _e14 is not None and "refused the run" in str(_e14)
      and _fresh.row("SELECT COUNT(*) AS n FROM catalog_runs")["n"] == 0
      and _fresh.row("SELECT COUNT(*) AS n FROM catalog_listings")["n"] == 0, str(_e14))
_fresh.close()

CAT.close()
print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
