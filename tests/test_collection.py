"""The collection's queue and its bucket (the plan's phase 3) do what they
say.

    python tests/test_collection.py

It needs nothing beyond Python: the queue is SQLite here, in a temporary
directory, and nothing leaves the process -- the bucket is an opener that
keeps what it is handed and answers as R2 would. The queue's rows run
against Postgres as well when CARO_TEST_QUEUE_URL names an empty database
made for them, with psycopg installed, as CI's postgres job does: that is
where two workers racing for one job is FOR UPDATE SKIP LOCKED's to settle.
"""
import contextlib
import io
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

Q.close()
print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
