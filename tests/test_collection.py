"""The collection's queue (the plan's phase 3) takes each job once, tries it
again after a backoff, and locks a source.

    python tests/test_collection.py

It needs nothing beyond Python: the queue is SQLite here, in a temporary
directory. Its rows run against Postgres as well when CARO_TEST_QUEUE_URL
names an empty database made for them, with psycopg installed, as CI's
postgres job does: that is where two workers racing for one job is FOR
UPDATE SKIP LOCKED's to settle.
"""
import os
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caro.jobs import Job, backoff, open_queue  # noqa: E402
from caro.sql import DIALECTS  # noqa: E402

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def raises(fn, kind=Exception):
    try:
        fn()
    except kind as e:          # noqa: BLE001
        return e
    return None


_tmp = tempfile.TemporaryDirectory()
TMP = Path(_tmp.name)
URL = os.environ.get("CARO_TEST_QUEUE_URL") or f"sqlite:///{TMP}/queue.sqlite3"
Q = open_queue(URL, migrate=False)
if raises(lambda: Q.row("SELECT 1 AS one FROM queue_jobs")) is None:
    print("CARO_TEST_QUEUE_URL names a database that already has a queue; give it an empty one")
    raise SystemExit(2)
Q.migrate()
print(f"\nthe queue, on {Q.dialect.name}")

# ---------------------------------------------------------------------------
# A job: made once, taken once, failed with a backoff, done
# ---------------------------------------------------------------------------
_k = "collect:khodro45:2026-11-04"
_made = (Q.enqueue("collect", _k, {"n": 1}, run_after=100), Q.enqueue("collect", _k, {"n": 2}, run_after=0))
check("Q1: a key makes one job; asked again, in any state, it makes none",
      isinstance(_made[0], int) and _made[1] is None and Q.job(_k)["payload"] == {"n": 1}, str(_made))

_early = Q.take("w1", ("collect",), now=99)
_j = Q.take("w1", ("collect",), now=100)
_second = Q.take("w2", ("collect",), now=100)
_other_kind = Q.take("w2", ("promote",), now=100)
check("Q2: a job is not taken before its time; at its time one worker takes it, its attempt counted, "
      "and nobody else does, nor a worker asking for another kind",
      _early is None and isinstance(_j, Job) and _j.attempts == 1 and _j.key == _k
      and _second is None and _other_kind is None and Q.job(_k)["state"] == "running"
      and Q.job(_k)["locked_by"] == "w1", str((_early, _j, _second)))

_s1 = Q.fail(_j, "boom one", output={"run_id": f"{_k}#1"}, now=200)
_r1 = Q.job(_k)
_j2 = Q.take("w1", ("collect",), now=200 + backoff(1))
_s2 = Q.fail(_j2, "boom two", now=300)
_j3 = Q.take("w1", ("collect",), now=300 + backoff(2))
_s3 = Q.fail(_j3, "boom three", now=2000)
_r3 = Q.job(_k)
check("Q3: a failed attempt goes back after its backoff, its error kept, until the attempts are spent; "
      "then it fails -- a minute, four, sixteen, and never more than six hours",
      (_s1, _s2, _s3) == ("queued", "queued", "failed") and _r1["run_after"] == 260
      and _r1["error"] == "boom one" and _j2.attempts == 2 and _j3.attempts == 3
      and _r3["state"] == "failed" and _r3["error"] == "boom three"
      and [backoff(n) for n in (1, 2, 3, 6, 20)] == [60, 240, 960, 21600, 21600], str((_s1, _s2, _s3, _r1)))

Q.enqueue("collect", "collect:divar:2026-11-04", {}, run_after=0)
_jd = Q.take("w1", ("collect",), now=10)
_sd = Q.fail(_jd, "the source's answer", retry=False, now=11)
Q.enqueue("collect", "collect:bama:2026-11-04", {}, run_after=0)
_jb = Q.take("w1", ("collect",), now=10)
Q.finish(_jb, {"run_id": "collect:bama:2026-11-04#1", "outcome": "collected"}, now=12)
_rb = Q.job("collect:bama:2026-11-04")
check("Q4: a failure not to be retried fails at once; a job finished is done, its output kept",
      _sd == "failed" and Q.job("collect:divar:2026-11-04")["attempts"] == 1
      and _rb["state"] == "done" and _rb["output"]["outcome"] == "collected" and _rb["finished_at"] == 12)

_owed = Q.unreported()
for _oid, _rec in _owed[:1]:
    Q.reported(_oid, status=200, now=13)
_left = Q.unreported()
check("Q5: every attempt that has a record owes it -- a failed one as well as the one that finished -- "
      "oldest first, until it is reported",
      [r["run_id"] for _, r in _owed] == [f"{_k}#1", "collect:bama:2026-11-04#1"]
      and [r["run_id"] for _, r in _left] == ["collect:bama:2026-11-04#1"], str(_owed))

Q.enqueue("collect", "collect:sheypoor:2026-11-04", {}, run_after=0)
_js = Q.take("w1", ("collect",), now=10)
Q.put_back(_js, after=300, now=10)
_rs = Q.job("collect:sheypoor:2026-11-04")
_js2 = Q.take("w1", ("collect",), now=310)
check("Q6: a job handed back untried waits, and spends no attempt",
      _rs["state"] == "queued" and _rs["attempts"] == 0 and _rs["run_after"] == 310
      and _js2 is not None and _js2.attempts == 1, str(_rs))

Q.enqueue("collect", "collect:fresh:2026-11-04", {}, run_after=0)
_jf = Q.take("w9", ("collect",), now=1000)
_reaped = Q.reap(600, now=1500)
_fresh_then = Q.job("collect:fresh:2026-11-04")["state"]
_reaped2 = Q.reap(600, now=1601)
check("Q7: a job running past its lease is handed back as an attempt that failed; one within it is not",
      _reaped == 1 and _fresh_then == "running" and _reaped2 == 1
      and Q.job("collect:sheypoor:2026-11-04")["state"] == "queued"
      and Q.job("collect:sheypoor:2026-11-04")["error"] == "the worker stopped while it ran"
      and Q.job("collect:fresh:2026-11-04")["state"] == "queued", str((_reaped, _fresh_then, _reaped2)))

for _d in ("2026-11-01", "2026-11-02", "2026-11-03"):
    Q.enqueue("collect", f"collect:khodro99:{_d}", {}, run_after=0)
Q.enqueue("collect", "collect:other:2026-11-01", {}, run_after=0)
_jr = None
_n_exp = Q.expire("collect", "collect:khodro99:", "collect:khodro99:2026-11-03", now=50)
check("Q8: a source's days before today that never ran are missed; today's, and another source's, wait",
      _n_exp == 2 and [Q.job(f"collect:khodro99:{d}")["state"] for d in ("2026-11-01", "2026-11-02", "2026-11-03")]
      == ["missed", "missed", "queued"] and Q.job("collect:other:2026-11-01")["state"] == "queued", str(_n_exp))

_l = (Q.acquire("source:k", "w1", ttl=10, now=0), Q.acquire("source:k", "w2", ttl=10, now=5),
      Q.acquire("source:k", "w1", ttl=10, now=6), Q.acquire("source:k", "w2", ttl=10, now=15),
      Q.acquire("source:k", "w2", ttl=10, now=17))
Q.release("source:k", "w1")
_still = Q.acquire("source:k", "w1", ttl=10, now=18)
Q.release("source:k", "w2")
_free = Q.acquire("source:k", "w1", ttl=10, now=19)
check("Q9: a source's lock is one holder's until it lapses; its holder renews it, and only its holder "
      "releases it",
      _l == (True, False, True, False, True) and _still is False and _free is True, str((_l, _still, _free)))

_race_url = os.environ.get("CARO_TEST_QUEUE_URL") or f"sqlite:///{TMP}/race.sqlite3"
_rq = Q if os.environ.get("CARO_TEST_QUEUE_URL") else open_queue(_race_url)
for _i in range(50):
    _rq.enqueue("race", f"race:{_i}", {"i": _i}, run_after=0)
_taken, _errors = Counter(), []


def _racer(n):
    q = open_queue(_race_url, migrate=False)
    try:
        while True:
            j = q.take(f"r{n}", ("race",), now=10)
            if j is None:
                break
            _taken[j.key] += 1
            q.finish(j, {"by": n}, now=11)
    except Exception as e:       # noqa: BLE001
        _errors.append(repr(e))
    finally:
        q.close()


_ts = [threading.Thread(target=_racer, args=(n,)) for n in range(6)]
for _t in _ts:
    _t.start()
for _t in _ts:
    _t.join()
check("Q10: six workers, each on its own connection, over fifty jobs: every job taken, none twice",
      len(_taken) == 50 and max(_taken.values()) == 1 and not _errors
      and _rq.row("SELECT COUNT(*) AS n FROM queue_jobs WHERE kind = 'race' AND state = 'done'")["n"] == 50,
      str((len(_taken), _taken.most_common(2), _errors[:2])))
check("Q11: Postgres takes a job FOR UPDATE SKIP LOCKED and SQLite under BEGIN IMMEDIATE, and either "
      "takes it only from queued",
      DIALECTS["postgres"].skip_locked == " FOR UPDATE SKIP LOCKED" and DIALECTS["sqlite"].skip_locked == ""
      and DIALECTS["sqlite"].begin == "BEGIN IMMEDIATE"
      and "AND state = 'queued'" in Path(ROOT / "caro/jobs.py").read_text(encoding="utf-8").split("def take")[1]
      .split("def finish")[0])

Q.close()
print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
