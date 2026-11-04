"""The private bucket: a run's snapshot and transcript, kept off the machine
that collected them.

The plan's phase 3 writes what a collection read to a private bucket, so a
run is kept where neither the owner's disk nor the worker's can lose it,
and `scripts/replicate_check.py` can compare two runs from it. The bucket is
Cloudflare R2, reached through Cloudflare like everything the worker writes
from Iran (phase 0's probe), and R2 speaks the S3 protocol. This is the
part of it CARO uses -- put an object, get one, ask whether one is there --
signed with AWS Signature Version 4, in the standard library, so that the
worker's image needs no SDK for three requests.

    CARO_BUCKET_ENDPOINT   https://<account id>.r2.cloudflarestorage.com
    CARO_BUCKET_NAME       the bucket
    CARO_BUCKET_KEY_ID     an R2 API token's access key id, for this bucket only
    CARO_BUCKET_SECRET     its secret

Unset, there is no bucket: a run is kept on the worker's disk alone, and its
record says so. A run's files are at `runs/<source>/<day>/attempt-<n>/`,
`snapshot.json` and `transcript.txt`, and one is fetched to compare two runs:

    python -m caro.bucket get runs/khodro45/2026-11-05/attempt-1/snapshot.json a.json An object is addressed by path, `/<bucket>/<key>`, and the
region is R2's `auto`. Nothing here prints or raises the secret, a
signature, or an address with a key in it.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Callable

ENV = ("CARO_BUCKET_ENDPOINT", "CARO_BUCKET_NAME", "CARO_BUCKET_KEY_ID", "CARO_BUCKET_SECRET")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class BucketError(RuntimeError):
    """A request the bucket did not answer as asked. Its message names the
    request and the status, never the secret or a signature."""


def _quote(s: str, safe: str) -> str:
    # SigV4's URI encoding: every byte but the unreserved ones, upper-case hex
    return urllib.parse.quote(s, safe=safe)


def canonical_query(query: dict[str, str]) -> str:
    return "&".join(f"{_quote(k, '-_.~')}={_quote(v, '-_.~')}" for k, v in sorted(query.items()))


def signature(*, method: str, path: str, query: dict[str, str], headers: dict[str, str],
              payload_sha256: str, amz_date: str, region: str, service: str,
              key_id: str, secret: str) -> tuple[str, str]:
    """(the Authorization header, the signature) for one request, by AWS
    Signature Version 4. `headers` are the ones signed, `host` and
    `x-amz-date` among them; `path` is the object's path, not yet encoded."""
    names = sorted(k.lower() for k in headers)
    lowered = {k.lower(): " ".join(str(v).strip().split()) for k, v in headers.items()}
    canonical = "\n".join([
        method,
        _quote(path, "/-_.~"),
        canonical_query(query),
        "".join(f"{n}:{lowered[n]}\n" for n in names),
        ";".join(names),
        payload_sha256,
    ])
    day = amz_date[:8]
    scope = f"{day}/{region}/{service}/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope,
                         hashlib.sha256(canonical.encode("utf-8")).hexdigest()])
    k = ("AWS4" + secret).encode("utf-8")
    for part in (day, region, service, "aws4_request"):
        k = hmac.new(k, part.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(k, to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    auth = (f"AWS4-HMAC-SHA256 Credential={key_id}/{scope}, "
            f"SignedHeaders={';'.join(names)}, Signature={sig}")
    return auth, sig


@dataclass
class Bucket:
    endpoint: str           # https://<account id>.r2.cloudflarestorage.com
    name: str
    key_id: str
    secret: str
    region: str = "auto"
    opener: Callable = urllib.request.urlopen
    clock: Callable[[], float] = time.time
    timeout: float = 60

    def _request(self, method: str, key: str, body: bytes = b"",
                 content_type: str | None = None) -> tuple[int, bytes]:
        if not key or key.startswith("/") or ".." in key.split("/"):
            raise BucketError(f"not an object's key: {key!r}")
        parts = urllib.parse.urlsplit(self.endpoint)
        if parts.scheme != "https" or not parts.netloc:
            raise BucketError("CARO_BUCKET_ENDPOINT is not an https address")
        path = f"/{self.name}/{key}"
        amz_date = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(self.clock()))
        payload = hashlib.sha256(body).hexdigest()
        signed = {"host": parts.netloc, "x-amz-content-sha256": payload, "x-amz-date": amz_date}
        auth, _ = signature(method=method, path=path, query={}, headers=signed,
                            payload_sha256=payload, amz_date=amz_date, region=self.region,
                            service="s3", key_id=self.key_id, secret=self.secret)
        headers = {**signed, "Authorization": auth}
        if content_type:
            headers["Content-Type"] = content_type
        req = urllib.request.Request(f"https://{parts.netloc}{_quote(path, '/-_.~')}",
                                     data=body if method == "PUT" else None,
                                     method=method, headers=headers)
        try:
            with self.opener(req, timeout=self.timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, b""
        except Exception as e:      # noqa: BLE001 -- no answer, said by its kind alone
            raise BucketError(f"{method} {key}: no answer ({type(e).__name__})") from None

    def put(self, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        """Writes one object and gives the sha256 of its bytes."""
        status, _ = self._request("PUT", key, data, content_type)
        if status != 200:
            raise BucketError(f"PUT {key}: status {status}")
        return hashlib.sha256(data).hexdigest()

    def get(self, key: str) -> bytes:
        status, data = self._request("GET", key)
        if status != 200:
            raise BucketError(f"GET {key}: status {status}")
        return data

    def has(self, key: str) -> bool:
        status, _ = self._request("HEAD", key)
        if status in (200, 404):
            return status == 200
        raise BucketError(f"HEAD {key}: status {status}")


def from_env(env: dict | None = None, **kw) -> Bucket | None:
    """The bucket the environment names, or None where it names none. Some
    of the four set and not all is a mistake, said by name."""
    env = os.environ if env is None else env
    got = {k: (env.get(k) or "").strip() for k in ENV}
    if not any(got.values()):
        return None
    missing = [k for k, v in got.items() if not v]
    if missing:
        raise BucketError("the bucket is half named: " + ", ".join(missing) + " not set")
    return Bucket(got["CARO_BUCKET_ENDPOINT"].rstrip("/"), got["CARO_BUCKET_NAME"],
                  got["CARO_BUCKET_KEY_ID"], got["CARO_BUCKET_SECRET"], **kw)


def main(argv: list[str] | None = None, env: dict | None = None, **kw) -> int:
    """`get KEY FILE`: one object of the bucket the environment names, into
    a file that does not exist yet. `kw` goes to the Bucket, for the suites."""
    ap = argparse.ArgumentParser(prog="python -m caro.bucket")
    sub = ap.add_subparsers(dest="cmd", required=True)
    g = sub.add_parser("get", help="one object into a new file")
    g.add_argument("key")
    g.add_argument("file")
    a = ap.parse_args(argv)
    try:
        b = from_env(env, **kw)
        if b is None:
            print("no bucket is named: CARO_BUCKET_ENDPOINT, _NAME, _KEY_ID and _SECRET", file=sys.stderr)
            return 2
        out = open(a.file, "xb")          # never over a file that is there
    except (BucketError, OSError) as e:
        print(f"bucket: {e}", file=sys.stderr)
        return 2
    try:
        data = b.get(a.key)
    except BucketError as e:
        out.close()
        os.unlink(a.file)
        print(f"bucket: {e}", file=sys.stderr)
        return 1
    with out:
        out.write(data)
    print(f"{a.key}: {len(data):,} bytes, sha256 {hashlib.sha256(data).hexdigest()}, into {a.file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
