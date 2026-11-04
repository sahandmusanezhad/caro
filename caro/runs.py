"""What the server knows of the collection: one record per run, and the
alerts the records raise.

The plan's phase 3: a worker collects, wherever it runs, and reports each
run -- its pin, what it collected, where its snapshot and transcript were
kept, and how it ended -- to the server, through Cloudflare. The server
keeps the records, and from them, on a clock of its own, says what went
wrong, because a worker that stopped cannot say that it stopped:

    missing    a run expected by a time of day did not arrive
    stopped    a run stopped on robots.txt, on a block, on a source that
               could not be read, or on an error of ours
    robots     robots.txt is not the file the run before read
    count      a run collected far fewer or far more listings than the
               runs before it, read as deeply

    runs_collection   a run: its id, its source, its day, how it ended, its
                      counts, its robots.txt, and the record as reported
    runs_alerts       an alert said, by a key that makes it once

A record holds nothing personal: no listing, no seller, no number. The day
is Tehran's, at +03:30 (the container has no time zone database, and Iran
keeps no daylight saving since 2022).
"""

from __future__ import annotations

import importlib
import json
import statistics
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable

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
    # The alerts said, each once (webapp/alerts.py).
    (2, (
        """CREATE TABLE IF NOT EXISTS runs_alerts (
            key TEXT PRIMARY KEY,
            text TEXT NOT NULL,
            sent_at BIGINT NOT NULL)""",
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

    def said(self, key: str) -> bool:
        return self.row("SELECT key FROM runs_alerts WHERE key = ?", (key,)) is not None

    def say(self, key: str, text: str, now: int | None = None) -> bool:
        """Records an alert as said; False where it was said before."""
        now = self.now() if now is None else int(now)
        with self.transaction():
            self.lock("runs-alert:" + key)
            if self.said(key):
                return False
            self.execute("INSERT INTO runs_alerts (key, text, sent_at) VALUES (?, ?, ?)",
                         (key, text, now))
        return True


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


# ---------------------------------------------------------------------------
# What the records say
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Expected:
    source: str
    by: str             # HH:MM, Tehran


@dataclass(frozen=True)
class Alert:
    key: str
    text: str


def expected(spec: str) -> list[Expected]:
    """`khodro45@05:00, divar@06:30`: each source whose run is expected
    every day, and the time of day in Tehran by which it should have
    arrived. Anything else is refused, by what it is."""
    out = []
    for part in (p.strip() for p in (spec or "").split(",")):
        if not part:
            continue
        source, at, by = part.partition("@")
        hh, colon, mm = by.partition(":")
        if (not at or not source.strip() or not colon or not (hh.isdigit() and mm.isdigit())
                or not (0 <= int(hh) < 24 and 0 <= int(mm) < 60)):
            raise ValueError(f"not a source and a time of day, source@HH:MM: {part!r}")
        out.append(Expected(source.strip(), f"{int(hh):02d}:{int(mm):02d}"))
    return out


COUNT_LOW, COUNT_HIGH, COUNT_RUNS, COUNT_AT_LEAST = 0.5, 1.5, 7, 3


def alerts(runs: Iterable[dict], expect: list[Expected], now: float) -> list[Alert]:
    """Every alert the runs raise at `now`, oldest run first; the caller
    says each once, by its key. `runs` are records as reported, any order."""
    by_source: dict[str, list[dict]] = {}
    for r in sorted(runs, key=lambda r: (r["finished_at"], r["run_id"])):
        by_source.setdefault(r["source"], []).append(r)
    out: list[Alert] = []
    for source, rs in by_source.items():
        for i, r in enumerate(rs):
            before = rs[:i]
            out += _of_run(r, before)
    today = tehran_day(now)
    clock = datetime.fromtimestamp(now, TEHRAN).strftime("%H:%M")
    for e in expect:
        arrived = any(r["collected_on"] == today for r in by_source.get(e.source, []))
        if clock >= e.by and not arrived:
            out.append(Alert(f"missing:{e.source}:{today}",
                             f"no {e.source} run has arrived for {today}, expected by {e.by} Tehran"))
    return out


def _of_run(r: dict, before: list[dict]) -> list[Alert]:
    out = []
    rid, src = r["run_id"], r["source"]
    robots = r.get("robots") or {}
    if r["outcome"] != "collected":
        why = {"robots": "on robots.txt", "blocked": "on a block", "unavailable":
               "on a source it could not read", "error": "on an error of ours"}.get(r["outcome"], r["outcome"])
        status = robots.get("http_status")
        tail = f" (robots.txt answered {status})" if r["outcome"] == "robots" and status else ""
        msg = (r.get("message") or "").strip().splitlines()
        out.append(Alert(f"stopped:{rid}", f"{src} run {rid} stopped {why}{tail}"
                         + (f": {msg[0][:300]}" if msg else "")))
    sha = robots.get("sha256")
    if sha:
        last = next((b for b in reversed(before) if (b.get("robots") or {}).get("sha256")), None)
        if last is not None and last["robots"]["sha256"] != sha:
            out.append(Alert(f"robots:{rid}", f"{src}'s robots.txt changed before run {rid}: "
                             f"{last['robots']['sha256'][:12]} -> {sha[:12]}; read it before the next run"))
    if r["outcome"] == "collected" and isinstance(r.get("listings"), int):
        alike = [b["listings"] for b in before if b["outcome"] == "collected"
                 and b.get("pages") == r.get("pages") and isinstance(b.get("listings"), int)][-COUNT_RUNS:]
        if len(alike) >= COUNT_AT_LEAST:
            mid = statistics.median(alike)
            if not (COUNT_LOW * mid <= r["listings"] <= COUNT_HIGH * mid):
                out.append(Alert(f"count:{rid}", f"{src} run {rid} collected {r['listings']} listings; "
                                 f"the {len(alike)} runs before it as deep, a middle of {mid:g}"))
    return out
