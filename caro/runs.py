"""What the server knows of the collection: one record per run.

The plan's phase 3: a worker collects, wherever it runs, and reports each
run -- its pin, what it collected, where its snapshot and transcript were
kept, and how it ended -- to the server, through Cloudflare, and the
server keeps the records:

    runs_collection   a run: its id, its source, its day, how it ended, its
                      counts, its robots.txt, and the record as reported

A record holds nothing personal: no listing, no seller, no number. The day
is Tehran's, at +03:30 (the container has no time zone database, and Iran
keeps no daylight saving since 2022).
"""

from __future__ import annotations

import importlib
import json
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from caro.sql import Database, connect

OPS_ENV = "CARO_OPS_URL"
TEHRAN = timezone(timedelta(hours=3, minutes=30))
OUTCOMES = ("collected", "robots", "blocked", "unavailable", "error")

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        """CREATE TABLE IF NOT EXISTS runs_collection (
            run_id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            collected_on TEXT NOT NULL,
            pages INTEGER,
            outcome TEXT NOT NULL,
            listings INTEGER,
            robots_status INTEGER,
            robots_sha256 TEXT,
            finished_at BIGINT NOT NULL,
            received_at BIGINT NOT NULL,
            record TEXT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS runs_collection_source ON runs_collection(source, finished_at)",
    )),
)


class RunsError(RuntimeError):
    """The runs' database is named and cannot be used, or a record cannot be
    kept. Its message never holds the address."""


def tehran_day(t: float) -> str:
    """The day in Tehran at `t`, seconds since the epoch: 2026-11-04."""
    return datetime.fromtimestamp(t, TEHRAN).date().isoformat()


def at_tehran(day: str, hhmm: str) -> int:
    """The moment `hhmm` of `day` in Tehran, as seconds since the epoch."""
    hh, mm = (int(x) for x in hhmm.split(":"))
    return int(datetime.fromisoformat(day).replace(hour=hh, minute=mm, tzinfo=TEHRAN).timestamp())


def _canonical(rec: dict) -> str:
    return json.dumps(rec, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class Runs(Database):
    def version(self) -> int:
        return self.schema_version("runs_migrations")

    def migrate(self) -> list[int]:
        return self.apply_migrations(MIGRATIONS, table="runs_migrations",
                                     lock=lambda: self.lock("runs-migrations"))

    def keep(self, rec: dict, now: int | None = None) -> str:
        """Keeps a reported run: "kept", or "unchanged" for the same record
        again (a worker reports until it is told it was kept). Another record
        under a kept run's id is refused: a run is reported once."""
        now = self.now() if now is None else int(now)
        text = _canonical(rec)
        with self.transaction():
            self.lock("runs:" + rec["run_id"])
            had = self.row("SELECT record FROM runs_collection WHERE run_id = ?", (rec["run_id"],))
            if had is not None:
                if had["record"] == text:
                    return "unchanged"
                raise RunsError(f"run {rec['run_id']} was reported before, with another record")
            robots = rec.get("robots") or {}
            self.execute(
                "INSERT INTO runs_collection (run_id, source, collected_on, pages, outcome, listings, "
                "robots_status, robots_sha256, finished_at, received_at, record) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (rec["run_id"], rec["source"], rec["collected_on"], rec.get("pages"), rec["outcome"],
                 rec.get("listings"), robots.get("http_status"), robots.get("sha256"),
                 int(rec["finished_at"]), now, text))
        return "kept"

    def runs(self, source: str | None = None, limit: int = 200) -> list[dict]:
        """The latest runs, newest first, each as reported."""
        where, params = ("WHERE source = ? ", (source,)) if source else ("", ())
        return [json.loads(r["record"]) for r in self.rows(
            f"SELECT record FROM runs_collection {where}ORDER BY finished_at DESC, run_id DESC LIMIT ?",
            (*params, int(limit)))]


def open_runs(url: str, *, clock: Callable[[], float] = time.time,
              importer: Callable[[str], Any] = importlib.import_module,
              migrate: bool = True) -> Runs:
    url = (url or "").strip()
    if not url:
        raise RunsError(f"{OPS_ENV} is not set")
    conn, dialect = connect(url, setting=OPS_ENV, what="the runs", error=RunsError, importer=importer)
    r = Runs(conn, dialect, clock)
    if migrate:
        r.migrate()
    return r
