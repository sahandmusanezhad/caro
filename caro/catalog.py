"""The catalog: every published run and its listings, in SQLite or Postgres.

docs/SERVICES.md, step 1. A model's page reads the asking prices of every
published run, and with the runs in files that meant every corpus loaded
into memory and validated on a process's first request: 20.5 s and 508 MB
for ten daily runs of 10,000 listings, measured on 2026-11-02. In a
database a run is read where it is -- the served run's rows once, a model's
rows across the runs by an index.

    data/corpora/<run>.json   the published artifact, caro.corpus/1
          |  load_run         the guards, once; the digest; one transaction
          v
    catalog_runs              a run: what the artifact says of itself, and
                              the digest and size of its bytes
    catalog_listings          a listing: its record as published, and the
                              values a model's history is narrowed by
          |  records, model_rows, artifact_text
          v
    webapp/api/corpus.py and webapp/api/market.py; anyone checking the bytes

Four properties, and each of them is a decision.

**The published bytes come back.** Every corpus is promotion's
`serialize(artifact)`, and `artifact_text` writes the same text from the
rows, so the digest the site shows can be recomputed from the catalog
(`verify`), not only copied into it, and a run the catalog holds can be
published again without its file. A file not written as promotion writes one
is refused: the catalog could not give its bytes back.

**Nothing derived is stored.** No middle, no «priced», no count of what a
rule admits. Beside the record, a row holds the make and the model as a
model's page matches them, and four values as published; everything a rule
decides is decided when it is read, by the same Python that reads a file.
A rule changed in code applies to every run at once, and no stored figure
is left over from the rule before.

**A published run is not changed.** Loading a run the catalog holds with the
same digest writes nothing. With another digest it is refused and nothing
is written: replacing a published run is asked for by its name.

**Names of its own.** The seller store may share one database with this
one, and it has a table called `listings` and records its migrations in
`schema_migrations`. The catalog's tables are `catalog_...` and its
migrations are recorded in `catalog_migrations`, so neither reads the
other's. Migrations only add, as the seller store's do.
"""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from caro.ingest.corpus import serialize, validate
from caro.sql import Database, connect

CATALOG_ENV = "CARO_CATALOG_URL"


class CatalogError(RuntimeError):
    """The catalog is named and cannot be used, or a run cannot go into it.
    Its message never holds the address, which can carry a password."""


# {id} is not used: every key here is a published one.
MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        # `head` is the artifact without its listings, as JSON: with the
        # records it is the whole artifact again.
        """CREATE TABLE IF NOT EXISTS catalog_runs (
            run_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            collected_on TEXT NOT NULL,
            path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            bytes BIGINT NOT NULL,
            listings INTEGER NOT NULL,
            head TEXT NOT NULL,
            loaded_at BIGINT NOT NULL)""",
        # `position` is the record's place in the artifact, which is the
        # order every reader of a file sees. `record` is the published
        # record; the columns before it are read out of it by `_row`.
        """CREATE TABLE IF NOT EXISTS catalog_listings (
            run_id TEXT NOT NULL REFERENCES catalog_runs(run_id) ON DELETE CASCADE,
            position INTEGER NOT NULL,
            listing_id TEXT NOT NULL,
            make_key TEXT NOT NULL,
            model_key TEXT NOT NULL,
            product_class TEXT,
            asking_price_toman BIGINT,
            price_status TEXT,
            price_kind TEXT,
            record TEXT NOT NULL,
            PRIMARY KEY (run_id, position),
            UNIQUE (run_id, listing_id))""",
        "CREATE INDEX IF NOT EXISTS catalog_listings_model ON catalog_listings(model_key, make_key)",
    )),
)

TABLES = ("catalog_runs", "catalog_listings")
HEAD = MIGRATIONS[-1][0]

# What a model's history reads of a listing, as the record has it.
AS_PUBLISHED = ("product_class", "asking_price_toman", "price_status", "price_kind")
_TEXT = ("make", "model", "product_class", "price_status", "price_kind")


def match_key(value: object) -> str:
    """A make or a model as a model's page matches it: stripped, and '' for
    none. webapp/api/market.py matches with this, so the index and the page
    cannot disagree about which listings are a model's."""
    return (value or "").strip()            # type: ignore[union-attr]


@dataclass(frozen=True)
class Loaded:
    run_id: str
    did: str            # "loaded", "unchanged" or "replaced"
    listings: int
    sha256: str


def _row(run_id: str, position: int, rec: object, where: str) -> tuple:
    """A record as a row of catalog_listings. A value the columns cannot hold
    as it is published is refused, never coerced."""
    if not isinstance(rec, dict) or not isinstance(rec.get("listing_id"), str) or not rec["listing_id"]:
        raise CatalogError(f"{where}: record {position} has no listing_id")
    for k in _TEXT:
        if rec.get(k) is not None and not isinstance(rec[k], str):
            raise CatalogError(f"{where}: record {position}'s {k} is a {type(rec[k]).__name__}, not text")
    price = rec.get("asking_price_toman")
    if price is not None and (isinstance(price, bool) or not isinstance(price, int)):
        raise CatalogError(f"{where}: record {position}'s asking_price_toman is a "
                           f"{type(price).__name__}, not a whole number of toman")
    return (run_id, position, rec["listing_id"], match_key(rec.get("make")),
            match_key(rec.get("model")), rec.get("product_class"), price,
            rec.get("price_status"), rec.get("price_kind"),
            json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


class Catalog(Database):
    """The catalog's database: `caro.sql.Database` with its migrations, its
    loader and its reads."""

    # ---- the schema --------------------------------------------------------
    def version(self) -> int:
        return self.schema_version("catalog_migrations")

    def migrate(self) -> list[int]:
        return self.apply_migrations(MIGRATIONS, table="catalog_migrations",
                                     lock=lambda: self.lock("catalog-migrations"))

    # ---- writing -----------------------------------------------------------
    def load_run(self, path: Path, *, replace: bool = False) -> Loaded:
        """One published corpus into the catalog, in one transaction: all of
        it, or none of it. See the module's docstring for when it writes."""
        from caro.corpus_reader import display_path        # noqa: PLC0415
        where = display_path(path)
        try:
            data = path.read_bytes()
            text = data.decode("utf-8")
            artifact = json.loads(text)
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise CatalogError(f"{where}: not a corpus that can be read ({type(e).__name__})") from None
        problems = validate(artifact, text)
        if problems:
            raise CatalogError(f"{where}: {len(problems)} guard violation(s); the first: {problems[0]}")
        run_id = artifact["run_id"]
        if run_id != path.stem:
            raise CatalogError(f"{where} says it is run {run_id!r}: a corpus's file is named after its run")
        if serialize(artifact) != text:
            raise CatalogError(f"{where} is not written as promotion writes a corpus, "
                               "so the catalog could not give its bytes back")
        rows = [_row(run_id, i, rec, where) for i, rec in enumerate(artifact["listings"])]
        seen: set[str] = set()
        for r in rows:
            if r[2] in seen:
                raise CatalogError(f"{where}: listing {r[2]} is in it twice")
            seen.add(r[2])
        head = {k: v for k, v in artifact.items() if k != "listings"}
        sha = hashlib.sha256(data).hexdigest()
        try:
            return self._write(run_id, artifact, head, rows, data, sha, where, replace)
        except CatalogError:
            raise
        except Exception as e:
            # The transaction is rolled back; what the database said is kept,
            # and it cannot hold the address: the connection is already open.
            raise CatalogError(f"{where}: the database refused the run "
                               f"({type(e).__name__}: {e})") from e

    def _write(self, run_id: str, artifact: dict, head: dict, rows: list[tuple],
               data: bytes, sha: str, where: str, replace: bool) -> Loaded:
        with self.transaction():
            self.lock(f"catalog-run:{run_id}")
            had = self.row("SELECT sha256 FROM catalog_runs WHERE run_id = ?", (run_id,))
            if had is not None and had["sha256"] == sha:
                return Loaded(run_id, "unchanged", len(rows), sha)
            if had is not None and not replace:
                raise CatalogError(
                    f"run {run_id} is in the catalog with sha256 {had['sha256'][:12]}… and {where} "
                    f"is {sha[:12]}…: a published run is not changed. If this file is meant to "
                    f"replace it, load it again asking for {run_id} to be replaced")
            if had is not None:
                self.execute("DELETE FROM catalog_runs WHERE run_id = ?", (run_id,))
            self.execute(
                "INSERT INTO catalog_runs (run_id, source, collected_on, path, sha256, bytes, "
                "listings, head, loaded_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, str(artifact["source"]), str(artifact.get("collected_on") or ""),
                 where, sha, len(data), len(rows),
                 json.dumps(head, ensure_ascii=False, sort_keys=True), self.now()))
            self.execute_many(
                "INSERT INTO catalog_listings (run_id, position, listing_id, make_key, model_key, "
                "product_class, asking_price_toman, price_status, price_kind, record) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
        return Loaded(run_id, "replaced" if had is not None else "loaded", len(rows), sha)

    def load_corpora(self, directory: Path, *,
                     replace: frozenset[str] = frozenset()) -> tuple[list[Loaded], list[tuple[str, str]]]:
        """Every corpus in `directory`, each on its own: one that is refused
        does not stop the others. (what was loaded, [(file, why refused)])."""
        done, refused = [], []
        for p in sorted(Path(directory).glob("*.json")):
            try:
                done.append(self.load_run(p, replace=p.stem in replace))
            except CatalogError as e:
                refused.append((p.name, str(e)))
        return done, refused

    # ---- reading -----------------------------------------------------------
    _RUN = "run_id, source, collected_on, path, sha256, bytes, listings"

    def runs(self) -> list[dict]:
        """Every run, by collection date and then name, as a model's history
        orders them. Sorted here rather than by ORDER BY, because Postgres
        orders text by its collation and Python by code point."""
        got = self.rows(f"SELECT {self._RUN} FROM catalog_runs")
        return sorted(got, key=lambda r: (r["collected_on"], r["run_id"]))

    def run(self, run_id: str) -> dict | None:
        return self.row(f"SELECT {self._RUN} FROM catalog_runs WHERE run_id = ?", (run_id,))

    def records(self, run_id: str) -> list[dict]:
        """A run's records, as published, in the artifact's order."""
        return [json.loads(r["record"]) for r in self.rows(
            "SELECT record FROM catalog_listings WHERE run_id = ? ORDER BY position", (run_id,))]

    def model_rows(self, make: str, model: str) -> list[dict]:
        """Every run's listings of a model, as a model's page matches them --
        the make and the model, or the model under any make where the make
        is '' -- with what its history reads of them."""
        sql = ("SELECT run_id, listing_id, make_key, model_key, product_class, asking_price_toman, "
               "price_status, price_kind FROM catalog_listings WHERE model_key = ?")
        params: tuple = (match_key(model),)
        if match_key(make):
            sql += " AND make_key = ?"
            params += (match_key(make),)
        return self.rows(sql, params)

    def artifact_text(self, run_id: str) -> str | None:
        """The run's published text, from the rows; None for a run the
        catalog does not hold."""
        got = self.row("SELECT head FROM catalog_runs WHERE run_id = ?", (run_id,))
        if got is None:
            return None
        artifact = json.loads(got["head"])
        artifact["listings"] = self.records(run_id)
        return serialize(artifact)

    def verify(self, run_id: str) -> bool:
        """The run's bytes, given back from the rows, have the digest and the
        size it was loaded with."""
        run, text = self.run(run_id), self.artifact_text(run_id)
        if run is None or text is None:
            return False
        data = text.encode("utf-8")
        return hashlib.sha256(data).hexdigest() == run["sha256"] and len(data) == int(run["bytes"])


def open_catalog(url: str | None = None, *, migrate: bool = False,
                 clock: Callable[[], float] = time.time,
                 importer: Callable[[str], Any] = importlib.import_module) -> Catalog | None:
    """The catalog `CARO_CATALOG_URL` names, or None when it names none. One
    that is named and cannot be opened raises CatalogError.

    `migrate` is for the loader. The API reads and never writes, so it opens
    the catalog as it is and asks `version()` whether it can read it."""
    url = (url if url is not None else os.environ.get(CATALOG_ENV, "")).strip()
    if not url:
        return None
    conn, dialect = connect(url, setting=CATALOG_ENV, what="the catalog",
                            error=CatalogError, importer=importer)
    cat = Catalog(conn, dialect, clock)
    if migrate:
        cat.migrate()
    return cat
