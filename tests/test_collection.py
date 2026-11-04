"""The collection's queue, its worker, its bucket and its alerts (the plan's
phase 3) do what they say.

    python tests/test_collection.py

It needs nothing beyond Python: the queue and the runs are SQLite here, in a
temporary directory, and nothing leaves the process -- the bucket, the
server and Telegram are openers that keep what they are handed and answer
as the real ones would, and the run is a stand-in for first_run that
prints and writes as one does. The queue's rows run against Postgres as
well when CARO_TEST_QUEUE_URL names an empty database made for them, with
psycopg installed, as CI's postgres job does: that is where two workers
racing for one job is FOR UPDATE SKIP LOCKED's to settle.
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import threading
import urllib.error
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caro import bucket as bucket_mod  # noqa: E402
from caro import runs as runs_mod  # noqa: E402
from caro.jobs import Job, backoff, open_queue  # noqa: E402
from caro.sql import DIALECTS  # noqa: E402
from webapp import alerts as alerts_mod  # noqa: E402
from webapp import worker as worker_mod  # noqa: E402

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

# ---------------------------------------------------------------------------
# The bucket
# ---------------------------------------------------------------------------
print("\nthe bucket")
_E = bucket_mod.EMPTY_SHA256
_AWS = dict(region="us-east-1", service="s3", key_id="AKIAIOSFODNN7EXAMPLE",
            secret="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", amz_date="20130524T000000Z")
_host = "examplebucket.s3.amazonaws.com"
_put_body_sha = "44ce7dd67c959e0d3524ffac1771dfbba87d2b6b4b4e99e42034a8b803f8b072"
_sigs = (
    bucket_mod.signature(method="GET", path="/test.txt", query={}, payload_sha256=_E,
                         headers={"Host": _host, "Range": "bytes=0-9", "x-amz-content-sha256": _E,
                                  "x-amz-date": "20130524T000000Z"}, **_AWS)[1],
    bucket_mod.signature(method="PUT", path="/test$file.text", query={}, payload_sha256=_put_body_sha,
                         headers={"Host": _host, "Date": "Fri, 24 May 2013 00:00:00 GMT",
                                  "x-amz-content-sha256": _put_body_sha, "x-amz-date": "20130524T000000Z",
                                  "x-amz-storage-class": "REDUCED_REDUNDANCY"}, **_AWS)[1],
    bucket_mod.signature(method="GET", path="/", query={"max-keys": "2", "prefix": "J"}, payload_sha256=_E,
                         headers={"Host": _host, "x-amz-content-sha256": _E,
                                  "x-amz-date": "20130524T000000Z"}, **_AWS)[1],
)
check("B1: AWS's three published Signature Version 4 examples for S3 -- a GET with a range, a PUT whose "
      "key needs encoding, a list with a query -- give the signatures AWS publishes",
      _sigs == ("f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41",
                "98ad721746da40c64f1a55b78f14c238d841ea1380cd77a1b5971af0ece108bd",
                "34b48302e7b5fa45bde8084f4b7868a86f0a534bc59db6670ed5711ef69dc6f7"), str(_sigs))


class _Answer:
    def __init__(self, status=200, body=b""):
        self.status, self.body = status, body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self.body


def _opener(answers, seen):
    """Answers in turn; an exception is raised, an int is that status."""
    def open_(req, timeout):
        seen.append(req)
        a = answers.pop(0) if answers else 200
        if isinstance(a, Exception):
            raise a
        if isinstance(a, int) and a >= 400:
            raise urllib.error.HTTPError(req.full_url, a, "no", {}, None)
        if isinstance(a, tuple):
            return _Answer(*a)
        return _Answer(a)
    return open_


_SECRET = "made-up-r2-secret-0123456789"
_seen_b = []
_bk = bucket_mod.Bucket("https://acc123.r2.cloudflarestorage.com", "caro-runs", "kid123", _SECRET,
                        opener=_opener([200, 403], _seen_b), clock=lambda: 1793750400)
_sha = _bk.put("runs/khodro45/2026-11-04/attempt-1/snapshot.json", b'{"x":1}', "application/json")
_refused = raises(lambda: _bk.put("runs/k/x.json", b"{}"), bucket_mod.BucketError)
_rq0 = _seen_b[0]
_auth = _rq0.get_header("Authorization")
check("B2: a put is one signed PUT to the bucket's path on the account's host, region auto, its body's "
      "sha256 sent and given back; a refusal raises, naming the status and never the secret",
      _rq0.get_method() == "PUT"
      and _rq0.full_url == "https://acc123.r2.cloudflarestorage.com/caro-runs/runs/khodro45/2026-11-04/attempt-1/snapshot.json"
      and _rq0.get_header("X-amz-content-sha256") == bucket_mod.hashlib.sha256(b'{"x":1}').hexdigest() == _sha
      and _auth.startswith("AWS4-HMAC-SHA256 Credential=kid123/20261104/auto/s3/aws4_request, "
                           "SignedHeaders=host;x-amz-content-sha256;x-amz-date, Signature=")
      and _rq0.get_header("Content-type") == "application/json" and _rq0.data == b'{"x":1}'
      and _refused is not None and "status 403" in str(_refused) and _SECRET not in str(_refused),
      str((_rq0.full_url, _auth, _refused)))

_seen_g = []
_bg = bucket_mod.Bucket("https://acc123.r2.cloudflarestorage.com", "caro-runs", "kid123", _SECRET,
                        opener=_opener([(200, b"abc"), (200, b""), 404, 404, TimeoutError("slow")], _seen_g))
_got = (_bg.get("runs/a.json"), _bg.has("runs/a.json"), _bg.has("runs/b.json"))
_miss = raises(lambda: _bg.get("runs/b.json"), bucket_mod.BucketError)
_slow = raises(lambda: _bg.get("runs/c.json"), bucket_mod.BucketError)
check("B3: a get gives the bytes and asks with no body; has is a HEAD, true or false; a get of nothing "
      "and no answer raise, the latter named by its kind alone",
      _got == (b"abc", True, False) and [r.get_method() for r in _seen_g] == ["GET", "HEAD", "HEAD", "GET", "GET"]
      and _seen_g[0].data is None and _miss is not None and "status 404" in str(_miss)
      and _slow is not None and "TimeoutError" in str(_slow) and _SECRET not in str(_slow), str((_got, _miss, _slow)))

_full = {"CARO_BUCKET_ENDPOINT": "https://acc123.r2.cloudflarestorage.com/", "CARO_BUCKET_NAME": "caro-runs",
         "CARO_BUCKET_KEY_ID": "kid123", "CARO_BUCKET_SECRET": _SECRET}
_half = raises(lambda: bucket_mod.from_env({"CARO_BUCKET_NAME": "caro-runs"}), bucket_mod.BucketError)
_b_env = bucket_mod.from_env(_full)
_bad_keys = [raises(lambda k=k: _bk.put(k, b""), bucket_mod.BucketError) for k in ("/abs", "a/../b", "")]
_http = raises(lambda: bucket_mod.Bucket("http://x", "b", "k", "s", opener=_opener([], [])).put("a", b""),
               bucket_mod.BucketError)
check("B4: no bucket is named by nothing; some of the four is refused, naming what is missing; all four "
      "make one; a key that climbs or starts at the root is refused, and so is an endpoint not on https",
      bucket_mod.from_env({}) is None and _half is not None and "CARO_BUCKET_ENDPOINT" in str(_half)
      and "CARO_BUCKET_SECRET" in str(_half) and _b_env.endpoint == "https://acc123.r2.cloudflarestorage.com"
      and _b_env.region == "auto" and all(e is not None for e in _bad_keys)
      and _http is not None and "https" in str(_http),
      str((_half, _bad_keys, _http)))

_seen_c = []
_cli_out = TMP / "fetched.json"
_cli_err = io.StringIO()
_cli_open = _opener([(200, b'{"run":1}'), 404], _seen_c)
with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(_cli_err):
    _cli = (bucket_mod.main(["get", "runs/k/a/snapshot.json", str(_cli_out)], env=_full, opener=_cli_open),
            bucket_mod.main(["get", "runs/k/a/snapshot.json", str(_cli_out)], env=_full, opener=_cli_open),
            bucket_mod.main(["get", "runs/k/b/snapshot.json", str(TMP / "missing.json")], env=_full,
                            opener=_cli_open),
            bucket_mod.main(["get", "runs/k/a/snapshot.json", str(TMP / "none.json")], env={}))
check("B5: `python -m caro.bucket get KEY FILE` writes one object into a new file; over a file that is "
      "there it writes nothing, a key that is not there leaves no file, and without a bucket it says so",
      _cli == (0, 2, 1, 2) and _cli_out.read_bytes() == b'{"run":1}' and not (TMP / "missing.json").exists()
      and not (TMP / "none.json").exists() and len(_seen_c) == 2 and "no bucket is named" in _cli_err.getvalue(),
      str((_cli, _cli_err.getvalue())))

# ---------------------------------------------------------------------------
# The worker
# ---------------------------------------------------------------------------
print("\nthe worker")
_ent = worker_mod.entries("03:30 --source khodro45 --pages 60 ; 6:05 --source divar --pages 3")
_bad = [raises(lambda s=s: worker_mod.entries(s), worker_mod.WorkerError) for s in (
    "3h30 --source khodro45", "03:30 --source khodro45 --replay x.json", "03:30 --source nowhere",
    "03:30 --source khodro45 --pages many", "03:30 --source khodro45; 04:00 --source khodro45 --pages 2",
    "25:00 --source khodro45")]
check("W1: CARO_COLLECT gives each run its time in Tehran and first_run's own arguments, read by "
      "first_run's parser; a time that is not one, a run that reads a file, arguments first_run refuses, "
      "and a source named twice are refused when the worker starts",
      [(e.at, e.source, e.pages, e.argv) for e in _ent]
      == [("03:30", "khodro45", 60, ("--source", "khodro45", "--pages", "60")),
          ("06:05", "divar", 3, ("--source", "divar", "--pages", "3"))]
      and all(b is not None for b in _bad) and worker_mod.entries("") == [], str((_ent, _bad)))

_wq = open_queue(f"sqlite:///{TMP}/worker.sqlite3")
_one = worker_mod.entries("03:30 --source khodro45 --pages 60")
_t_day = runs_mod.at_tehran("2026-11-04", "00:10")
_made1 = worker_mod.schedule(_wq, _one, _t_day)
_made2 = worker_mod.schedule(_wq, _one, _t_day + 60)
_job1 = _wq.job("collect:khodro45:2026-11-04")
_made3 = worker_mod.schedule(_wq, _one, runs_mod.at_tehran("2026-11-05", "00:10"))
check("W2: a day's run is queued once, for its time of day in Tehran (+03:30); the next day's is a job "
      "of its own, and a day that passed without its run is missed, never run under the next day's date",
      _made1 == ["collect:khodro45:2026-11-04"] and _made2 == []
      and _job1["run_after"] == 1793750400 and _job1["payload"]["day"] == "2026-11-04"
      and _job1["payload"]["argv"] == ["--source", "khodro45", "--pages", "60"]
      and _made3 == ["collect:khodro45:2026-11-05"] and _wq.job("collect:khodro45:2026-11-04")["state"] == "missed",
      str((_made1, _made2, _job1 and _job1["run_after"], _made3)))


def _a_run(outcome="collected", listings=492, crash=None):
    """A stand-in for first_run.main: prints, writes a snapshot, and reports as it does."""
    calls = []

    def run(argv, report):
        calls.append(list(argv))
        print("collecting from khodro45 -- politely, and stopping if asked to.")
        robots = {"url": "https://khodro45.com/robots.txt", "http_status": 200, "sha256": "a" * 64,
                  "bytes": 120, "verdict": "rules", "why": "http 200: read", "token": "CARO-research"}
        report["robots"] = robots
        if crash:
            raise crash
        if outcome != "collected":
            report.update(stop=outcome, message=f"HALTED: the source said {outcome}")
            print(f"HALTED: {outcome}", file=sys.stderr)
            return 1 if outcome != "setup" else 2
        snap = TMP / "snapshots" / "khodro45-2026-11-04-abc123.json"
        snap.parent.mkdir(exist_ok=True)
        snap.write_text('{"listings": []}', encoding="utf-8")
        report.update(snapshot=str(snap), listings=listings)
        return 0
    return run, calls


def _worker(run, queue, bucket_answers=(), server_answers=(), with_bucket=True, ingest=True):
    puts, posts = [], []
    clock = [runs_mod.at_tehran("2026-11-04", "03:00")]
    logs = []
    w = worker_mod.Worker(
        queue, _one, "w-test",
        bucket_mod.Bucket("https://acc123.r2.cloudflarestorage.com", "caro-runs", "kid", _SECRET,
                          opener=_opener(list(bucket_answers), puts)) if with_bucket else None,
        "https://caro.example" if ingest else "", "worker-token-123" if ingest else "",
        collect=run, opener=_opener(list(server_answers), posts), clock=lambda: clock[0],
        out=logs.append, transcripts=TMP / "transcripts")
    return w, clock, puts, posts, logs


_run, _calls = _a_run()
_q1 = open_queue(f"sqlite:///{TMP}/w3.sqlite3")
_w, _clock, _puts, _posts, _logs = _worker(_run, _q1, server_answers=[(200, b"{}")])
_before = _w.turn()
_clock[0] = runs_mod.at_tehran("2026-11-04", "03:31")
_buf = io.StringIO()
with contextlib.redirect_stdout(_buf):
    _ran = _w.turn()
_rec = json.loads(_posts[0].data) if _posts else {}
_tfile = TMP / "transcripts" / "khodro45-2026-11-04-attempt-1.txt"
check("W3: before its time the worker runs nothing; at its time it runs first_run with the run's own "
      "arguments, and keeps what the run printed as its transcript",
      _before is False and _ran is True and _calls == [["--source", "khodro45", "--pages", "60"]]
      and _tfile.read_text(encoding="utf-8") == "collecting from khodro45 -- politely, and stopping if asked to.\n"
      and "collecting from khodro45" in _buf.getvalue(), str((_before, _ran, _calls)))
check("W4: the snapshot and the transcript go to the bucket under the run's day and attempt, and the "
      "record goes to the server once, by the worker's token, saying what the run collected and where "
      "its files are, by their digests",
      [p.full_url.rsplit("caro-runs/", 1)[1] for p in _puts]
      == ["runs/khodro45/2026-11-04/attempt-1/transcript.txt", "runs/khodro45/2026-11-04/attempt-1/snapshot.json"]
      and len(_posts) == 1 and _posts[0].full_url == "https://caro.example/api/worker/runs"
      and _posts[0].get_header("Authorization") == "Bearer worker-token-123"
      and _rec["run_id"] == "collect:khodro45:2026-11-04#1" and _rec["outcome"] == "collected"
      and _rec["listings"] == 492 and _rec["pages"] == 60 and _rec["collected_on"] == "2026-11-04"
      and _rec["snapshot"]["key"] == "runs/khodro45/2026-11-04/attempt-1/snapshot.json"
      and _rec["snapshot"]["sha256"] == bucket_mod.hashlib.sha256(b'{"listings": []}').hexdigest()
      and _rec["robots"] == {"url": "https://khodro45.com/robots.txt", "http_status": 200, "sha256": "a" * 64,
                             "bytes": 120, "verdict": "rules"}
      and _q1.job("collect:khodro45:2026-11-04")["state"] == "done" and _q1.unreported() == [],
      str((_rec, [p.full_url for p in _puts])))
check("W5: a record holds the fields the server's shape names and no other",
      set(_rec) == {"run_id", "job", "source", "pages", "argv", "collected_on", "started_at", "finished_at",
                    "outcome", "message", "listings", "stopped", "robots", "worker", "build", "snapshot",
                    "transcript"}, str(sorted(_rec)))

_outs = {}
for _oc in ("robots", "blocked", "unavailable", "setup", "crash"):
    _r, _ = _a_run(_oc, crash=RuntimeError("disk full") if _oc == "crash" else None)
    _qq = open_queue(f"sqlite:///{TMP}/w-{_oc}.sqlite3")
    _ww, _cl, _, _pp, _ = _worker(_r, _qq, server_answers=[(200, b"{}")] * 3, with_bucket=False)
    _cl[0] = runs_mod.at_tehran("2026-11-04", "03:31")
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        _ww.turn()
    _jj = _qq.job("collect:khodro45:2026-11-04")
    _outs[_oc] = (_jj["state"], json.loads(_pp[0].data)["outcome"] if _pp else None,
                  (json.loads(_pp[0].data)["message"] or "")[:40] if _pp else None)
check("W6: a run the source stopped -- robots.txt, a block, a source that could not be read -- is done "
      "and not retried around; a run that could not start fails at once; a failure of ours is tried "
      "again later; each says so in its record",
      _outs["robots"][:2] == ("done", "robots") and _outs["blocked"][:2] == ("done", "blocked")
      and _outs["unavailable"][:2] == ("done", "unavailable") and _outs["setup"][:2] == ("failed", "error")
      and _outs["crash"][:2] == ("queued", "error") and _outs["crash"][2].startswith("RuntimeError: disk full"),
      str(_outs))

_r7, _c7 = _a_run()
_q7 = open_queue(f"sqlite:///{TMP}/w7.sqlite3")
_w7, _cl7, _, _, _l7 = _worker(_r7, _q7, ingest=False, with_bucket=False)
_q7.acquire("source:khodro45", "another-collector", ttl=3600, now=runs_mod.at_tehran("2026-11-04", "03:00"))
_cl7[0] = runs_mod.at_tehran("2026-11-04", "03:31")
_w7.turn()
_j7 = _q7.job("collect:khodro45:2026-11-04")
check("W7: while another collector holds the source, the run waits five minutes and spends no attempt",
      _c7 == [] and _j7["state"] == "queued" and _j7["attempts"] == 0
      and _j7["run_after"] == _cl7[0] + 300 and any("held by another collector" in s for s in _l7), str(_j7))

_r8, _ = _a_run()
_q8 = open_queue(f"sqlite:///{TMP}/w8.sqlite3")
_w8, _cl8, _p8b, _p8, _l8 = _worker(_r8, _q8, bucket_answers=[500, 500],
                                    server_answers=[ConnectionResetError(), 401, 409])
_cl8[0] = runs_mod.at_tehran("2026-11-04", "03:31")
with contextlib.redirect_stdout(io.StringIO()):
    _w8.turn()
_owed1 = len(_q8.unreported())
_w8.report()
_owed2 = len(_q8.unreported())
_w8.report()
_owed3 = len(_q8.unreported())
_r8rec = json.loads(_p8[0].data)
check("W8: a bucket that refuses leaves the run recorded with no key and nothing raised; a server that "
      "does not answer, or refuses the token, is asked again on the next turn; one that will never take "
      "the record is not",
      _r8rec["snapshot"]["key"] is None and _r8rec["transcript"]["key"] is None
      and _r8rec["outcome"] == "collected" and (_owed1, _owed2, _owed3) == (1, 1, 0) and len(_p8) == 3
      and any("the bucket did not keep" in s for s in _l8) and _SECRET not in " ".join(_l8),
      str((_owed1, _owed2, _owed3, _l8)))

_env_ok = {"CARO_SELLER_SALT": "s", "CARO_COLLECT": "03:30 --source khodro45 --pages 60",
           "CARO_QUEUE_URL": f"sqlite:///{TMP}/env.sqlite3"}
_env_bad = [raises(lambda e=e: worker_mod.from_env(e), worker_mod.WorkerError) for e in (
    {**_env_ok, "CARO_SELLER_SALT": ""}, {**_env_ok, "CARO_COLLECT": ""},
    {**_env_ok, "CARO_INGEST_URL": "https://caro.example"},
    {**_env_ok, "CARO_INGEST_URL": "http://caro.example", "CARO_WORKER_TOKEN": "t"},
    {**_env_ok, "CARO_QUEUE_URL": "mysql://x"})]
_wenv = worker_mod.from_env({**_env_ok, "CARO_WORKER_NAME": "laptop"})
check("W9: the worker refuses to start without the salt, without a run, with a server and no token, with "
      "a server not on https, or with a queue it cannot use; with them it starts, its bucket off",
      all(e is not None for e in _env_bad) and _wenv.name == "laptop" and _wenv.bucket is None
      and [e.source for e in _wenv.runs] == ["khodro45"], str(_env_bad))

# ---------------------------------------------------------------------------
# The server's runs, and the alerts
# ---------------------------------------------------------------------------
print("\nthe runs, and the alerts")
_db = runs_mod.open_runs(os.environ.get("CARO_TEST_RUNS_URL") or f"sqlite:///{TMP}/ops.sqlite3")


def _rec_of(day, listings=490, outcome="collected", sha="a" * 64, status=200, msg=None, attempt=1, pages=60,
            source="khodro45"):
    return {"run_id": f"collect:{source}:{day}#{attempt}", "job": f"collect:{source}:{day}", "source": source,
            "pages": pages, "collected_on": day, "finished_at": runs_mod.at_tehran(day, "03:40") + attempt,
            "outcome": outcome, "listings": listings, "message": msg,
            "robots": {"http_status": status, "sha256": sha}}


_k1 = (_db.keep(_rec_of("2026-11-01", 480)), _db.keep(_rec_of("2026-11-01", 480)))
_conflict = raises(lambda: _db.keep(_rec_of("2026-11-01", 481)), runs_mod.RunsError)
check("R1: a run is kept once; the same record again is unchanged; another under its id is refused",
      _k1 == ("kept", "unchanged") and _conflict is not None and len(_db.runs()) == 1, str((_k1, _conflict)))

for _d, _n in (("2026-11-02", 500), ("2026-11-03", 492), ("2026-11-04", 510)):
    _db.keep(_rec_of(_d, _n))
_db.keep(_rec_of("2026-11-05", 120))
_db.keep(_rec_of("2026-11-06", None, outcome="robots", sha=None, status=503, msg="robots.txt: deny_all"))
_db.keep(_rec_of("2026-11-07", 495, sha="b" * 64))
_db.keep(_rec_of("2026-11-07", 30, pages=2, source="divar"))
_db.keep(_rec_of("2026-11-07", None, outcome="blocked", source="sheypoor", sha=None, msg="HALTED: 403"))
_expect = runs_mod.expected("khodro45@05:00, divar@06:30")
_at = runs_mod.at_tehran("2026-11-08", "05:01")
_al = runs_mod.alerts(_db.runs(), _expect, _at)
_keys = [a.key for a in _al]
check("R2: the runs raise each alert once by its key: a count far below the runs before it as deep, a "
      "run stopped on robots.txt that answered 503, robots.txt changed, a run stopped on a block, and "
      "today's run not arrived after its time and not before",
      _keys == ["count:collect:khodro45:2026-11-05#1", "stopped:collect:khodro45:2026-11-06#1",
                "robots:collect:khodro45:2026-11-07#1", "stopped:collect:sheypoor:2026-11-07#1",
                "missing:khodro45:2026-11-08"]
      and "robots.txt answered 503" in _al[1].text and "a middle of 496" in _al[0].text
      and [a.key for a in runs_mod.alerts(_db.runs(), _expect, runs_mod.at_tehran("2026-11-08", "04:59"))
           if a.key.startswith("missing")] == [], str(_keys))
check("R3: a count is judged against at least three runs before it read as deeply, and within half to "
      "one and a half times their middle it raises nothing",
      not any(k.startswith("count:") and "divar" in k for k in _keys)
      and not any(k == "count:collect:khodro45:2026-11-07#1" for k in _keys)
      and runs_mod.alerts([_rec_of("2026-11-0" + str(i), 100) for i in (1, 2)] + [_rec_of("2026-11-03", 10)],
                          [], _at) == [])
_ex_bad = [raises(lambda s=s: runs_mod.expected(s), ValueError) for s in ("khodro45", "khodro45@5", "@05:00",
                                                                           "khodro45@24:00")]
check("R4: the expected runs are source@HH:MM, comma between two; anything else is refused",
      [(e.source, e.by) for e in _expect] == [("khodro45", "05:00"), ("divar", "06:30")]
      and runs_mod.expected("") == [] and all(e is not None for e in _ex_bad), str(_ex_bad))


class _Bot:
    def __init__(self, answers):
        self.answers, self.sent = list(answers), []

    def send(self, text):
        self.sent.append(text)
        return self.answers.pop(0) if self.answers else True


_bot = _Bot([True, False, True, True, True])
_out = []
_said1 = alerts_mod.look(_db, _expect, _bot, _at, out=_out.append)
_said2 = alerts_mod.look(_db, _expect, _bot, _at, out=_out.append)
_said3 = alerts_mod.look(_db, _expect, _bot, _at, out=_out.append)
check("R5: each alert is sent once; one the bot did not take is sent again on the next look, and kept as "
      "said once it is; each message says it is CARO's",
      len(_said1) == 4 and _said2 == [_keys[1]] and _said3 == [] and len(_bot.sent) == 6
      and all(t.startswith("CARO: ") for t in _bot.sent), str((_said1, _said2, _said3)))

_tg_seen = []
_tg = alerts_mod.Telegram("123:made-up-bot-token", "-1009", opener=_opener([200, TimeoutError("x")], _tg_seen))
_errb = io.StringIO()
with contextlib.redirect_stderr(_errb):
    _tg_ok = (_tg.send("CARO: one"), _tg.send("CARO: two"))
check("R6: Telegram is sent a POST to the bot's sendMessage with the chat and the text; a message not "
      "taken is said by its kind, never by the address, which holds the token",
      _tg_ok == (True, False) and _tg_seen[0].full_url == "https://api.telegram.org/bot123:made-up-bot-token/sendMessage"
      and _tg_seen[0].get_method() == "POST" and b"chat_id=-1009" in _tg_seen[0].data
      and "TimeoutError" in _errb.getvalue() and "made-up-bot-token" not in _errb.getvalue(),
      _errb.getvalue())

_q8.close()
Q.close()
print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
