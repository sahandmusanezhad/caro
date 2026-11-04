"""The queue: a table of jobs, taken by workers, and a lock per source.

The plan's phase 3 and SERVICES.md's design: the queue is a table, a worker
takes a job with `SELECT ... FOR UPDATE SKIP LOCKED` so that two never take
the same one, a job is retried with a backoff and its error kept, and one
collector per source holds that source's lock, so the pause between two
requests to one domain is never shared out between two collectors.

    queue_jobs    a job: its kind, a key that makes it once (a day's run of
                  a source is one job however often it is asked for), its
                  payload, its state, when it may run, its attempts, who
                  holds it, its error, and its last attempt's output
    queue_locks   a name, who holds it, until when
    queue_outbox  each attempt's record, until it is reported, and the
                  status the server answered

A job's states:

    queued   --take-->  running  --finish-->  done
                           |  --fail, attempts left-->  queued, later
                           |  --fail, none left, or not to be retried-->  failed
    queued   --expire-->  missed      (its day passed before it ran)

A worker that dies while a job runs leaves it `running`; `reap` hands it
back after its lease, as an attempt that failed. A lock is a lease too: it
lapses at its time, so a dead holder cannot keep a source locked.

SQLite or Postgres through `caro/sql.py`, as the seller store and the
catalog; names of its own (`queue_...`, migrations in `queue_migrations`),
so it can share a database with either. Times are seconds since the epoch.
"""

from __future__ import annotations

import importlib
import json
import time
from dataclasses import dataclass
from typing import Any, Callable

from caro.sql import Database, connect

QUEUE_ENV = "CARO_QUEUE_URL"

MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        """CREATE TABLE IF NOT EXISTS queue_jobs (
            id {id},
            kind TEXT NOT NULL,
            key TEXT NOT NULL UNIQUE,
            payload TEXT NOT NULL,
            state TEXT NOT NULL DEFAULT 'queued',
            run_after BIGINT NOT NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            max_attempts INTEGER NOT NULL DEFAULT 3,
            locked_by TEXT,
            locked_at BIGINT,
            error TEXT,
            output TEXT,
            created_at BIGINT NOT NULL,
            finished_at BIGINT)""",
        "CREATE INDEX IF NOT EXISTS queue_jobs_take ON queue_jobs(state, run_after)",
        """CREATE TABLE IF NOT EXISTS queue_locks (
            name TEXT PRIMARY KEY,
            holder TEXT NOT NULL,
            expires_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS queue_outbox (
            id {id},
            job_id BIGINT NOT NULL REFERENCES queue_jobs(id) ON DELETE CASCADE,
            record TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            reported_at BIGINT,
            status INTEGER)""",
        "CREATE INDEX IF NOT EXISTS queue_outbox_owed ON queue_outbox(reported_at, id)",
    )),
)

STATES = ("queued", "running", "done", "failed", "missed")


class QueueError(RuntimeError):
    """The queue is named and cannot be used. Its message never holds the
    address, which can carry a password."""


@dataclass(frozen=True)
class Job:
    id: int
    kind: str
    key: str
    payload: dict
    attempts: int           # this one included
    max_attempts: int


def backoff(attempts: int) -> int:
    """Seconds before a failed job is tried again: a minute, then four, then
    sixteen, and never more than six hours."""
    return min(60 * 4 ** max(attempts - 1, 0), 6 * 3600)


class Queue(Database):
    """The queue's database: `caro.sql.Database` with its migrations."""

    def version(self) -> int:
        return self.schema_version("queue_migrations")

    def migrate(self) -> list[int]:
        return self.apply_migrations(MIGRATIONS, table="queue_migrations",
                                     lock=lambda: self.lock("queue-migrations"))

    # ---- jobs --------------------------------------------------------------
    def enqueue(self, kind: str, key: str, payload: dict, *, run_after: int,
                max_attempts: int = 3) -> int | None:
        """A new job, or None where one with this key exists, in any state:
        a key is made once."""
        with self.transaction():
            self.lock("queue-key:" + key)
            if self.row("SELECT id FROM queue_jobs WHERE key = ?", (key,)):
                return None
            return self.insert(
                "INSERT INTO queue_jobs (kind, key, payload, run_after, max_attempts, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (kind, key, json.dumps(payload, sort_keys=True), int(run_after),
                 int(max_attempts), self.now()))

    def take(self, worker: str, kinds: tuple[str, ...], now: int | None = None) -> Job | None:
        """The next queued job of these kinds whose time has come, now this
        worker's; None when there is none. Two workers asking at once get two
        jobs or one, never one job twice."""
        if not kinds:
            return None
        now = self.now() if now is None else int(now)
        marks = ", ".join("?" for _ in kinds)
        with self.transaction():
            r = self.row(
                "SELECT id, kind, key, payload, attempts, max_attempts FROM queue_jobs "
                f"WHERE state = 'queued' AND run_after <= ? AND kind IN ({marks}) "
                "ORDER BY run_after, id LIMIT 1" + self.dialect.skip_locked,
                (now, *kinds))
            if r is None:
                return None
            # The state is asked again: a job is taken from `queued` or not
            # at all, whatever the database's locking did.
            cur = self.execute("UPDATE queue_jobs SET state = 'running', locked_by = ?, locked_at = ?, "
                               "attempts = attempts + 1 WHERE id = ? AND state = 'queued'",
                               (worker, now, r["id"]))
            if cur.rowcount != 1:
                return None
        return Job(int(r["id"]), r["kind"], r["key"], json.loads(r["payload"]),
                   int(r["attempts"]) + 1, int(r["max_attempts"]))

    def _owe(self, job: Job, output: dict, now: int) -> None:
        self.insert("INSERT INTO queue_outbox (job_id, record, created_at) VALUES (?, ?, ?)",
                    (job.id, json.dumps(output, sort_keys=True, ensure_ascii=False), now))

    def finish(self, job: Job, output: dict, now: int | None = None) -> None:
        """The job is done; its output is kept, and owed to whoever the
        records are reported to."""
        now = self.now() if now is None else int(now)
        with self.transaction():
            self.execute("UPDATE queue_jobs SET state = 'done', output = ?, finished_at = ?, "
                         "locked_by = NULL, error = NULL WHERE id = ? AND state = 'running'",
                         (json.dumps(output, sort_keys=True, ensure_ascii=False), now, job.id))
            self._owe(job, output, now)

    def fail(self, job: Job, error: str, *, output: dict | None = None,
             retry: bool = True, now: int | None = None) -> str:
        """Gives the job's next state: `queued` again after its backoff while
        attempts are left and it may be retried, `failed` otherwise. The
        error is kept either way, and so is an attempt's output."""
        now = self.now() if now is None else int(now)
        again = retry and job.attempts < job.max_attempts
        state = "queued" if again else "failed"
        with self.transaction():
            self.execute("UPDATE queue_jobs SET state = ?, run_after = ?, error = ?, output = ?, "
                         "locked_by = NULL, finished_at = ? WHERE id = ? AND state = 'running'",
                         (state, now + backoff(job.attempts) if again else now, error[:2000],
                          None if output is None else json.dumps(output, sort_keys=True, ensure_ascii=False),
                          None if again else now, job.id))
            if output is not None:
                self._owe(job, output, now)
        return state

    def put_back(self, job: Job, *, after: int, now: int | None = None) -> None:
        """Hands a job back untried -- its source's lock was held -- without
        spending an attempt."""
        now = self.now() if now is None else int(now)
        self.execute("UPDATE queue_jobs SET state = 'queued', run_after = ?, locked_by = NULL, "
                     "attempts = attempts - 1 WHERE id = ? AND state = 'running'",
                     (now + int(after), job.id))

    def reap(self, lease: int, now: int | None = None) -> int:
        """Jobs `running` for longer than `lease` seconds, whose worker
        stopped, handed back as an attempt that failed. Gives how many."""
        now = self.now() if now is None else int(now)
        n = 0
        for r in self.rows("SELECT id, kind, key, payload, attempts, max_attempts FROM queue_jobs "
                           "WHERE state = 'running' AND locked_at < ?", (now - int(lease),)):
            job = Job(int(r["id"]), r["kind"], r["key"], json.loads(r["payload"]),
                      int(r["attempts"]), int(r["max_attempts"]))
            self.fail(job, "the worker stopped while it ran", now=now)
            n += 1
        return n

    def expire(self, kind: str, prefix: str, before_key: str, now: int | None = None) -> int:
        """Queued jobs of `kind` whose key starts with `prefix` and sorts
        before `before_key` -- a day's run when the day is over -- become
        `missed`. Gives how many."""
        now = self.now() if now is None else int(now)
        got = self.rows("SELECT id FROM queue_jobs WHERE kind = ? AND state = 'queued' "
                        "AND key LIKE ? AND key < ?", (kind, prefix + "%", before_key))
        for r in got:
            self.execute("UPDATE queue_jobs SET state = 'missed', finished_at = ? "
                         "WHERE id = ? AND state = 'queued'", (now, r["id"]))
        return len(got)

    def job(self, key: str) -> dict | None:
        r = self.row("SELECT * FROM queue_jobs WHERE key = ?", (key,))
        if r is not None:
            r["payload"] = json.loads(r["payload"])
            r["output"] = None if r["output"] is None else json.loads(r["output"])
        return r

    # ---- what is to be reported ---------------------------------------------
    def unreported(self, limit: int = 20) -> list[tuple[int, dict]]:
        """(id, record) of each attempt's record not yet reported, oldest
        first."""
        return [(int(r["id"]), json.loads(r["record"])) for r in self.rows(
            "SELECT id, record FROM queue_outbox WHERE reported_at IS NULL ORDER BY id LIMIT ?",
            (int(limit),))]

    def reported(self, out_id: int, *, status: int, now: int | None = None) -> None:
        now = self.now() if now is None else int(now)
        self.execute("UPDATE queue_outbox SET reported_at = ?, status = ? WHERE id = ?",
                     (now, int(status), out_id))

    # ---- locks -------------------------------------------------------------
    def acquire(self, name: str, holder: str, *, ttl: int, now: int | None = None) -> bool:
        """Takes `name` for `ttl` seconds, or renews it for its holder. False
        while another holds it and its time has not come."""
        now = self.now() if now is None else int(now)
        with self.transaction():
            self.lock("queue-lock:" + name)
            r = self.row("SELECT holder, expires_at FROM queue_locks WHERE name = ?", (name,))
            if r is None:
                self.execute("INSERT INTO queue_locks (name, holder, expires_at) VALUES (?, ?, ?)",
                             (name, holder, now + int(ttl)))
                return True
            if r["holder"] != holder and int(r["expires_at"]) > now:
                return False
            self.execute("UPDATE queue_locks SET holder = ?, expires_at = ? WHERE name = ?",
                         (holder, now + int(ttl), name))
            return True

    def release(self, name: str, holder: str) -> None:
        self.execute("DELETE FROM queue_locks WHERE name = ? AND holder = ?", (name, holder))


def open_queue(url: str, *, clock: Callable[[], float] = time.time,
               importer: Callable[[str], Any] = importlib.import_module,
               migrate: bool = True) -> Queue:
    """The queue `url` names, migrated. One that cannot be used raises
    QueueError."""
    url = (url or "").strip()
    if not url:
        raise QueueError(f"{QUEUE_ENV} is not set")
    conn, dialect = connect(url, setting=QUEUE_ENV, what="the queue", error=QueueError,
                            importer=importer)
    q = Queue(conn, dialect, clock)
    if migrate:
        q.migrate()
    return q
