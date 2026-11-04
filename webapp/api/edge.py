"""What the edge may keep of the API's answers (docs/REARCHITECTURE.md,
phase 4).

Three answers depend on nothing but the published runs, the one served
among them, the gate and the code: the models, a model's page, and which
corpus is served. Those three, and no other, say that a shared cache may
keep them -- Cloudflare, by the cache rule PHASE4_SETUP names -- and for how
long, and carry the means to check one:

    Cache-Control   public, max-age=60, s-maxage=<CARO_EDGE_TTL, 300 s>
    ETag            "<the served corpus's digest, 12>-<the answer's, 16>"
    X-Caro-Corpus   the served corpus's sha256, so that a kept answer can be
                    held against /api/health, which no cache keeps

An If-None-Match that names the answer's ETag is answered 304, with nothing
in its body. Only a 200 whose corpus was read and is known by its digest is
kept: a fault about the source -- a corpus that would not load, a run not
found, a catalog that cannot serve it -- is no-store, so an outage is never
kept at the edge after it ends. A fault about the claim (nothing gated) or
the resource is a fact about the corpus read, and is kept like the rest.

When the published runs or the served one change, the deploy purges what
the edge kept (scripts/edge_purge.py); until it is set up, a kept answer
lives at most CARO_EDGE_TTL seconds.
"""

from __future__ import annotations

import hashlib
import json
import os

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

CACHED = ("/api/models", "/api/model", "/api/corpus")
SOURCE_FAULTS = ("CORPUS_INVALID", "RUN_NOT_FOUND", "CATALOG_UNAVAILABLE")
DEFAULT_TTL = 300


def ttl() -> int:
    raw = os.environ.get("CARO_EDGE_TTL", "").strip()
    return int(raw) if raw.isdigit() and 0 < int(raw) <= 86400 else DEFAULT_TTL


def keepable(status: int, body: bytes) -> str | None:
    """The served corpus's sha256 where an answer may be kept, else None."""
    if status != 200:
        return None
    try:
        env = json.loads(body)
    except ValueError:
        return None
    if not isinstance(env, dict):
        return None
    fault = env.get("fault") or {}
    if isinstance(fault, dict) and fault.get("code") in SOURCE_FAULTS:
        return None
    corpus = env.get("corpus")
    ident = corpus.get("identity") if isinstance(corpus, dict) else None
    sha = ident.get("sha256") if isinstance(ident, dict) else None
    return sha if isinstance(sha, str) and len(sha) == 64 else None


def etag(corpus_sha: str, body: bytes) -> str:
    return f'"{corpus_sha[:12]}-{hashlib.sha256(body).hexdigest()[:16]}"'


def _matches(header: str, tag: str) -> bool:
    """If-None-Match: a list of tags, weak or strong, or *."""
    for part in (p.strip() for p in header.split(",")):
        if part == "*" or part.removeprefix("W/") == tag:
            return True
    return False


class EdgeCache(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        if request.method != "GET" or request.url.path not in CACHED:
            return response
        body = b"".join([chunk async for chunk in response.body_iterator])
        headers = dict(response.headers)
        headers.pop("content-length", None)
        sha = keepable(response.status_code, body)
        if sha is None:
            headers["cache-control"] = "no-store"
            return Response(body, status_code=response.status_code, headers=headers,
                            media_type=response.media_type)
        tag = etag(sha, body)
        headers.update({"cache-control": f"public, max-age=60, s-maxage={ttl()}",
                        "etag": tag, "x-caro-corpus": sha})
        if _matches(request.headers.get("if-none-match", ""), tag):
            headers.pop("content-type", None)
            return Response(status_code=304, headers=headers)
        return Response(body, status_code=200, headers=headers, media_type=response.media_type)
