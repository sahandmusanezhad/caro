"""The API's own numbers, read by the server's collector
(docs/REARCHITECTURE.md, phase 7; docs/SLO.md).

    GET /metrics     Prometheus's text format, 0.0.4

Since this process started:

    caro_requests_total{route,method,code}   every answer, by the route that
                                             gave it -- the route's template,
                                             never the path a client wrote,
                                             and «unmatched» for a path no
                                             route has
    caro_request_seconds{route}              how long each took, a histogram
                                             with a bucket at 300 ms, the
                                             search's target (docs/PERF.md)
    caro_process_start_time_seconds          when it started

and, read when asked:

    caro_corpus_info{run_id,kind,sha256}     the corpus served, 1
    caro_collection_up                       1 where the runs' database
                                             (CARO_OPS_URL) was read, 0 where
                                             it is named and was not
    caro_collection_last_run_timestamp_seconds{source}
                                             when each source's last collected
                                             run finished
    caro_collection_last_listings{source}    what that run collected

Nothing in it is a person's: no address, no question, no listing, no
number, so there is nothing to scrub. A label holds only what the code
names: a route's template, a method, a status, a source, a run.

Only the collector reads it. nginx sends /api/ to the API and every other
path to the site (deploy/nginx/caro.conf), so the edge never reaches
/metrics; a request that came through nginx all the same carries the
X-Forwarded-For nginx always sets, or Cloudflare's own header, and is
answered 404. The collector reads it on the environment's own network
(deploy/alloy/config.alloy).
"""

from __future__ import annotations

import os
import threading
import time

from fastapi import APIRouter, HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

# Seconds. 0.3 is the search's target, so that the share of searches within
# it is read from a bucket and not interpolated between two.
BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.2, 0.3, 0.5, 1.0, 2.5, 5.0, 10.0)
METHODS = ("GET", "POST", "HEAD", "OPTIONS", "PUT", "PATCH", "DELETE")
THROUGH_EDGE = ("x-forwarded-for", "cf-connecting-ip")
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"


def _label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _labels(**kw: object) -> str:
    return "{" + ",".join(f'{k}="{_label(v)}"' for k, v in kw.items()) + "}"


def _num(x: float) -> str:
    return repr(float(x)) if x != int(x) else str(int(x))


class Registry:
    def __init__(self, clock=time.time) -> None:
        self._lock = threading.Lock()
        self.started = clock()
        self.requests: dict[tuple[str, str, int], int] = {}
        # route -> ([count at or under each bucket], sum, count)
        self.seconds: dict[str, tuple[list[int], float, int]] = {}

    def observe(self, route: str, method: str, code: int, seconds: float) -> None:
        method = method if method in METHODS else "other"
        with self._lock:
            key = (route, method, int(code))
            self.requests[key] = self.requests.get(key, 0) + 1
            buckets, total, n = self.seconds.get(route, ([0] * len(BUCKETS), 0.0, 0))
            for i, le in enumerate(BUCKETS):
                if seconds <= le:
                    buckets[i] += 1
            self.seconds[route] = (buckets, total + seconds, n + 1)

    def lines(self) -> list[str]:
        with self._lock:
            requests = sorted(self.requests.items())
            seconds = sorted((r, (list(b), s, n)) for r, (b, s, n) in self.seconds.items())
        out = ["# HELP caro_requests_total Answers, by the route that gave them.",
               "# TYPE caro_requests_total counter"]
        out += [f"caro_requests_total{_labels(route=r, method=m, code=c)} {n}" for (r, m, c), n in requests]
        out += ["# HELP caro_request_seconds How long an answer took, by route.",
                "# TYPE caro_request_seconds histogram"]
        for route, (buckets, total, n) in seconds:
            for le, count in zip(BUCKETS, buckets):
                out.append(f"caro_request_seconds_bucket{_labels(route=route, le=_num(le))} {count}")
            out.append(f"caro_request_seconds_bucket{_labels(route=route, le='+Inf')} {n}")
            out.append(f"caro_request_seconds_sum{_labels(route=route)} {total!r}")
            out.append(f"caro_request_seconds_count{_labels(route=route)} {n}")
        out += ["# HELP caro_process_start_time_seconds When this process started.",
                "# TYPE caro_process_start_time_seconds gauge",
                f"caro_process_start_time_seconds {self.started!r}"]
        return out


REGISTRY = Registry()


class Measure(BaseHTTPMiddleware):
    """Counts and times every answer, by its route's template."""

    async def dispatch(self, request: Request, call_next):
        t0 = time.perf_counter()
        code = 500
        try:
            response = await call_next(request)
            code = response.status_code
            return response
        finally:
            route = getattr(request.scope.get("route"), "path", None) or "unmatched"
            REGISTRY.observe(route, request.method, code, time.perf_counter() - t0)


def corpus_lines() -> list[str]:
    from webapp.api import corpus as corpus_mod
    try:
        c = corpus_mod.active()
    except Exception:              # noqa: BLE001 -- no corpus is a line of its own, not a failed scrape
        return []
    ident = c.identity
    if ident is None:
        return []
    return ["# HELP caro_corpus_info The corpus served.", "# TYPE caro_corpus_info gauge",
            f"caro_corpus_info{_labels(run_id=ident.run_id, kind=c.kind, sha256=ident.sha256)} 1"]


def collection_lines(url: str | None = None) -> list[str]:
    """The last collected run of each source, from the runs' database; where
    it is named and cannot be read, caro_collection_up is 0 and nothing else
    is said. Its address is never printed."""
    from caro import runs as runs_mod
    url = (os.environ.get(runs_mod.OPS_ENV, "") if url is None else url).strip()
    if not url:
        return []
    out = ["# HELP caro_collection_up Whether the runs' database was read.",
           "# TYPE caro_collection_up gauge"]
    try:
        db = runs_mod.open_runs(url, migrate=False)
        try:
            records = db.runs(limit=500)
        finally:
            db.close()
    except Exception:              # noqa: BLE001 -- named and not read: say so, and nothing of why
        return out + ["caro_collection_up 0"]
    last: dict[str, dict] = {}
    for rec in records:            # newest first
        if rec.get("outcome") == "collected" and rec.get("source") not in last:
            last[rec["source"]] = rec
    out.append("caro_collection_up 1")
    out += ["# HELP caro_collection_last_run_timestamp_seconds When each source's last collected run finished.",
            "# TYPE caro_collection_last_run_timestamp_seconds gauge"]
    out += [f"caro_collection_last_run_timestamp_seconds{_labels(source=s)} {int(r['finished_at'])}"
            for s, r in sorted(last.items())]
    out += ["# HELP caro_collection_last_listings What each source's last collected run collected.",
            "# TYPE caro_collection_last_listings gauge"]
    out += [f"caro_collection_last_listings{_labels(source=s)} {int(r.get('listings') or 0)}"
            for s, r in sorted(last.items())]
    return out


router = APIRouter()


@router.get("/metrics", include_in_schema=False)
def metrics(request: Request) -> Response:
    if any(h in request.headers for h in THROUGH_EDGE):
        raise HTTPException(404)
    lines = REGISTRY.lines() + corpus_lines() + collection_lines()
    return Response("\n".join(lines) + "\n", media_type=CONTENT_TYPE)
