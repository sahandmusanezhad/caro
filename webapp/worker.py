"""The collection worker: the daily runs, on a schedule, from a queue
(docs/REARCHITECTURE.md, phase 3).

    python -m webapp.role worker

Each day, for each run CARO_COLLECT names, the worker queues one job,
taken at its time of day in Tehran; a job runs `scripts/first_run.py` as
the owner runs it, with the same arguments, under its source's lock, so two
collectors never share a domain's pause. What the run printed is its
transcript; its snapshot is what it wrote. Both go to the private bucket
where one is named (caro/bucket.py), and one record of the run goes to the
server through Cloudflare (CARO_INGEST_URL), which keeps it (caro/runs.py).
A record holds nothing personal: no listing, no seller, no number.

    CARO_COLLECT        the runs, `HH:MM <first_run's arguments>`, `;` between two:
                        `03:30 --source khodro45 --pages 60`
    CARO_QUEUE_URL      the queue (caro/jobs.py): sqlite:///... or postgresql://...
    CARO_SELLER_SALT    first_run's salt, here and on no other machine
    CARO_INGEST_URL     the server the records go to, https://caro.noxioai.com
    CARO_WORKER_TOKEN   what the server knows this worker by
    CARO_BUCKET_*       the bucket (caro/bucket.py); unset, a run stays on this disk

How a run ends decides what follows. A run that collected, or that the
source stopped -- robots.txt, a block, a source that could not be read --
is done: the source's answer is not retried around, and its record says
how it stopped. A run that failed on our side (an exception, a disk) is tried
again after a backoff, three times in all. A day's run not taken by the end
of its day is missed, never run late under the next day's date. A record
that cannot be delivered is kept and sent again on the next turn.
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import os
import shlex
import signal
import socket
import sys
import time
import traceback
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from caro import bucket as bucket_mod
from caro.jobs import Job, Queue, open_queue
from caro.runs import at_tehran, tehran_day

ROOT = Path(__file__).resolve().parent.parent
TRANSCRIPTS = ROOT / "data" / "transcripts"
KIND = "collect"
LOCK_TTL = 6 * 3600        # longer than any run; a dead worker's lock lapses
LEASE = 8 * 3600           # a job running longer than this, its worker is gone
IDLE = 60                  # seconds between two looks at an empty queue
REFUSED = (400, 409, 413, 422)   # what the server will never take, however often sent


class WorkerError(RuntimeError):
    """The worker's settings are wrong. Its message names the setting, never
    a secret."""


@dataclass(frozen=True)
class Entry:
    at: str                 # HH:MM, Tehran
    argv: tuple[str, ...]   # first_run's arguments
    source: str
    pages: int | None


def entries(spec: str, parse: Callable[[list[str]], argparse.Namespace] | None = None) -> list[Entry]:
    """CARO_COLLECT read, each run's arguments read by first_run's own
    parser, so that a run that could not start is refused when the worker
    starts, not at three in the morning. A live run only: no --replay, no
    --page, and one run per source."""
    parse = parse or _first_run_args
    out: list[Entry] = []
    for part in (p.strip() for p in (spec or "").split(";")):
        if not part:
            continue
        at, _, rest = part.partition(" ")
        hh, colon, mm = at.partition(":")
        if not (colon and hh.isdigit() and mm.isdigit() and int(hh) < 24 and int(mm) < 60):
            raise WorkerError(f"CARO_COLLECT: a run starts with its time of day, HH:MM: {part!r}")
        argv = tuple(shlex.split(rest))
        if any(a in ("--replay", "--page") or a.startswith(("--replay=", "--page=")) for a in argv):
            raise WorkerError(f"CARO_COLLECT: a scheduled run reads the source, not a file: {part!r}")
        try:
            args = parse(list(argv))
        except SystemExit:
            raise WorkerError(f"CARO_COLLECT: first_run refuses these arguments: {rest!r}") from None
        if any(e.source == args.source for e in out):
            raise WorkerError(f"CARO_COLLECT: {args.source} is named twice; one run a day per source")
        out.append(Entry(f"{int(hh):02d}:{int(mm):02d}", argv, args.source,
                         getattr(args, "pages", None) if args.source != "bama" else None))
    return out


def _first_run_args(argv: list[str]) -> argparse.Namespace:
    """first_run's own parser, asked without running anything."""
    from scripts import first_run          # noqa: PLC0415 -- the collection, only where it runs
    with contextlib.redirect_stderr(io.StringIO()):
        return first_run.parser().parse_args(argv)


def key_of(source: str, day: str) -> str:
    return f"{KIND}:{source}:{day}"


def schedule(queue: Queue, runs: list[Entry], now: float) -> list[str]:
    """Today's job for each run, queued once; the days before that never
    ran, missed. Gives the keys queued now."""
    today = tehran_day(now)
    made = []
    for e in runs:
        key = key_of(e.source, today)
        queue.expire(KIND, f"{KIND}:{e.source}:", key, now=int(now))
        if queue.enqueue(KIND, key, {"argv": list(e.argv), "source": e.source, "pages": e.pages,
                                      "day": today},
                         run_after=at_tehran(today, e.at), max_attempts=3) is not None:
            made.append(key)
    return made


class _Tee(io.TextIOBase):
    """Writes to all of its streams: the transcript, and the log."""

    def __init__(self, *streams):
        self.streams = streams

    def write(self, s: str) -> int:
        for st in self.streams:
            st.write(s)
        return len(s)

    def flush(self) -> None:
        for st in self.streams:
            st.flush()


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass
class Worker:
    queue: Queue
    runs: list[Entry]
    name: str
    bucket: bucket_mod.Bucket | None = None
    ingest: str = ""
    token: str = ""
    collect: Callable[[list[str], dict], int] | None = None    # first_run.main
    opener: Callable = urllib.request.urlopen
    clock: Callable[[], float] = time.time
    out: Callable[[str], None] = lambda s: print(s, flush=True)
    transcripts: Path = TRANSCRIPTS

    def _collect(self) -> Callable[[list[str], dict], int]:
        if self.collect is None:
            from scripts import first_run      # noqa: PLC0415
            self.collect = lambda argv, report: first_run.main(argv, report=report)
        return self.collect

    # ---- one turn ------------------------------------------------------------
    def turn(self) -> bool:
        """Schedules, takes and runs one job, and reports what is owed.
        True when a job ran."""
        now = int(self.clock())
        for key in schedule(self.queue, self.runs, now):
            self.out(f"worker: queued {key}")
        if self.queue.reap(LEASE, now=now):
            self.out("worker: handed back a job whose worker had stopped")
        job = self.queue.take(self.name, (KIND,), now=now)
        if job is not None:
            self.run(job)
        self.report()
        return job is not None

    def run(self, job: Job) -> None:
        source = job.payload["source"]
        lock = f"source:{source}"
        if not self.queue.acquire(lock, self.name, ttl=LOCK_TTL, now=int(self.clock())):
            self.out(f"worker: {source} is held by another collector; {job.key} waits")
            self.queue.put_back(job, after=300, now=int(self.clock()))
            return
        try:
            self._run(job)
        finally:
            self.queue.release(lock, self.name)

    def _run(self, job: Job) -> None:
        started = int(self.clock())
        report: dict = {}
        buf = io.StringIO()
        self.out(f"worker: {job.key}, attempt {job.attempts} of {job.max_attempts}: "
                 f"first_run {' '.join(job.payload['argv'])}")
        crash = None
        with contextlib.redirect_stdout(_Tee(buf, sys.stdout)), \
                contextlib.redirect_stderr(_Tee(buf, sys.stderr)):
            try:
                rc = self._collect()(list(job.payload["argv"]), report)
            except Exception as e:      # noqa: BLE001 -- ours, kept and retried
                rc, crash = None, e
                traceback.print_exc()
        transcript = buf.getvalue().encode("utf-8")
        stop = report.get("stop")
        if crash is not None:
            outcome, message = "error", f"{type(crash).__name__}: {crash}"
        elif stop in ("robots", "blocked", "unavailable"):
            outcome, message = stop, report.get("message")
        elif stop == "setup" or rc != 0:
            outcome, message = "error", report.get("message") or f"first_run answered {rc}"
        else:
            outcome, message = "collected", None
        rec = self._record(job, started, outcome, message, report, transcript)
        if outcome == "error":
            state = self.queue.fail(job, message or "error", output=rec, retry=stop != "setup",
                                    now=int(self.clock()))
            self.out(f"worker: {job.key} failed ({message}); {state}")
        else:
            self.queue.finish(job, rec, now=int(self.clock()))
            self.out(f"worker: {job.key} {outcome}, {rec.get('listings')} listing(s)")

    def _record(self, job: Job, started: int, outcome: str, message: str | None,
                report: dict, transcript: bytes) -> dict:
        day = job.payload["day"]
        run_id = f"{job.key}#{job.attempts}"
        prefix = f"runs/{job.payload['source']}/{day}/attempt-{job.attempts}"
        robots = report.get("robots") or {}
        rec = {
            "run_id": run_id, "job": job.key, "source": job.payload["source"],
            "pages": job.payload.get("pages"), "argv": list(job.payload["argv"]),
            "collected_on": day, "started_at": started, "finished_at": int(self.clock()),
            "outcome": outcome, "message": (message or None) and str(message)[:2000],
            "listings": report.get("listings"), "stopped": report.get("stopped"),
            "robots": {k: robots.get(k) for k in ("url", "http_status", "sha256", "bytes", "verdict")}
            if robots else None,
            "worker": self.name, "build": os.environ.get("CARO_BUILD") or None,
            "snapshot": None, "transcript": None,
        }
        self.transcripts.mkdir(parents=True, exist_ok=True)
        local = self.transcripts / f"{job.payload['source']}-{day}-attempt-{job.attempts}.txt"
        local.write_bytes(transcript)
        files = [("transcript", local, "text/plain; charset=utf-8")]
        if report.get("snapshot"):
            files.append(("snapshot", Path(report["snapshot"]), "application/json"))
        for what, path, ctype in files:
            data = path.read_bytes()
            kept = {"file": path.name, "sha256": _sha(data), "bytes": len(data), "key": None}
            if self.bucket is not None:
                key = f"{prefix}/{what}{path.suffix}"
                try:
                    self.bucket.put(key, data, ctype)
                    kept["key"] = key
                except bucket_mod.BucketError as e:
                    self.out(f"worker: the bucket did not keep the {what}: {e}")
            rec[what] = kept
        return rec

    # ---- the records owed to the server --------------------------------------
    def report(self) -> int:
        """Sends each record not yet delivered; gives how many were."""
        if not (self.ingest and self.token):
            return 0
        sent = 0
        for out_id, rec in self.queue.unreported():
            body = json.dumps(rec, ensure_ascii=False).encode("utf-8")
            req = urllib.request.Request(
                self.ingest.rstrip("/") + "/api/worker/runs", data=body, method="POST",
                headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}",
                         "User-Agent": "caro-worker"})
            try:
                with self.opener(req, timeout=30) as r:
                    ok = r.status in (200, 201)
            except urllib.error.HTTPError as e:
                # A record the server will never take -- malformed, too large,
                # another under its id -- is not sent again; anything else
                # (the token, a limit, the server down) is, on the next turn.
                final = e.code in REFUSED
                self.out(f"worker: the server did not take {rec['run_id']} (status {e.code})"
                         + ("; not sent again" if final else ""))
                if final:
                    self.queue.reported(out_id, status=e.code, now=int(self.clock()))
                continue
            except Exception as e:     # noqa: BLE001 -- no answer; kept for the next turn
                self.out(f"worker: the server did not answer for {rec['run_id']} ({type(e).__name__})")
                break
            if ok:
                self.queue.reported(out_id, status=200, now=int(self.clock()))
                sent += 1
        return sent


def from_env(env=None, **kw) -> Worker:
    env = os.environ if env is None else env
    if not (env.get("CARO_SELLER_SALT") or "").strip():
        raise WorkerError("CARO_SELLER_SALT is not set; a live run refuses to start without it")
    runs = entries(env.get("CARO_COLLECT", ""))
    if not runs:
        raise WorkerError("CARO_COLLECT names no run")
    ingest, token = (env.get("CARO_INGEST_URL") or "").strip(), (env.get("CARO_WORKER_TOKEN") or "").strip()
    if bool(ingest) != bool(token):
        raise WorkerError("CARO_INGEST_URL and CARO_WORKER_TOKEN go together")
    if ingest and not ingest.startswith("https://"):
        raise WorkerError("CARO_INGEST_URL is not an https address")
    try:
        queue = open_queue(env.get("CARO_QUEUE_URL", ""))
        bucket = bucket_mod.from_env(env)
    except Exception as e:        # noqa: BLE001 -- said by its own message, which names no secret
        raise WorkerError(str(e)) from None
    name = (env.get("CARO_WORKER_NAME") or "").strip() or f"{socket.gethostname()}-{os.getpid()}"
    return Worker(queue, runs, name, bucket, ingest, token, **kw)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="worker", description="the collection worker")
    ap.add_argument("--once", action="store_true", help="one turn, then stop")
    a = ap.parse_args(argv)
    try:
        w = from_env()
    except WorkerError as e:
        print(f"worker: {e}", file=sys.stderr)
        return 2
    stop = {"now": False}

    def _stop(*_):
        stop["now"] = True

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)
    plan = ", ".join(f"{e.source} at {e.at}" for e in w.runs)
    w.out(f"worker {w.name}: {plan} Tehran; bucket {'on' if w.bucket else 'off'}; "
          f"records {'to ' + w.ingest if w.ingest else 'kept here'}")
    while not stop["now"]:
        ran = w.turn()
        if a.once:
            break
        if not ran:
            for _ in range(IDLE):
                if stop["now"]:
                    break
                time.sleep(1)
    return 0


