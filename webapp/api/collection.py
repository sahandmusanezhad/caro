"""The collection's records, received from the worker (docs/REARCHITECTURE.md,
phase 3).

    POST /api/worker/runs    one run's record, from the worker, by its token

The worker collects where it runs -- the owner's machine, or a server in
Iran -- and reports each run here, through Cloudflare. The record is kept
in the runs' database (caro/runs.py). It holds nothing personal: the shape
below has no field for a listing, a seller or a number, and anything else
is refused.

Off unless both CARO_WORKER_TOKEN and CARO_OPS_URL are set: 503 RUNS_OFF.
A wrong token is 401, and ten of them from one address in ten minutes are
429 before the token is compared again. The same record twice is kept once
and answered 200 both times, since a worker that was not answered sends
again; another record under a kept run's id is 409.
"""

from __future__ import annotations

import os
import secrets
import threading
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from caro import runs as runs_mod
from webapp.api.security import RateLimiter, client_address, too_many

router = APIRouter()
WORKER_FAILURES = RateLimiter(10, 600)
_HEX64 = r"^[0-9a-f]{64}$"


class _Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Robots(_Shape):
    url: str | None = Field(default=None, max_length=300)
    http_status: int | None = Field(default=None, ge=0, le=999)
    sha256: str | None = Field(default=None, pattern=_HEX64)
    bytes: int | None = Field(default=None, ge=0)
    verdict: str | None = Field(default=None, max_length=40)


class Kept(_Shape):
    file: str = Field(max_length=200)
    sha256: str = Field(pattern=_HEX64)
    bytes: int = Field(ge=0)
    key: str | None = Field(default=None, max_length=300)


class RunRecord(_Shape):
    run_id: str = Field(pattern=r"^collect:[a-z0-9-]{1,40}:\d{4}-\d{2}-\d{2}#\d{1,3}$")
    job: str = Field(pattern=r"^collect:[a-z0-9-]{1,40}:\d{4}-\d{2}-\d{2}$")
    source: str = Field(pattern=r"^[a-z0-9-]{1,40}$")
    pages: int | None = Field(default=None, ge=0, le=10_000)
    argv: list[str] = Field(max_length=40)
    collected_on: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    started_at: int = Field(ge=0)
    finished_at: int = Field(ge=0)
    outcome: Literal["collected", "robots", "blocked", "unavailable", "error"]
    message: str | None = Field(default=None, max_length=2000)
    listings: int | None = Field(default=None, ge=0)
    stopped: str | None = Field(default=None, max_length=500)
    robots: Robots | None = None
    worker: str = Field(max_length=120)
    build: str | None = Field(default=None, max_length=64)
    snapshot: Kept | None = None
    transcript: Kept | None = None


class Received(BaseModel):
    run_id: str
    kept: Literal["kept", "unchanged"]


_migrated: set[str] = set()
_migrated_lock = threading.Lock()


def _open_runs(url: str) -> runs_mod.Runs:
    """The runs' database for one request, migrated by the first request of
    each process, as the seller store is (webapp/api/accounts.py)."""
    with _migrated_lock:
        db = runs_mod.open_runs(url, migrate=url not in _migrated)
        _migrated.add(url)
    return db


def require_worker(request: Request, authorization: str | None = Header(default=None)) -> None:
    """Off, refused or let in, before the body is read: a caller without the
    token learns nothing of the record's shape from the answer."""
    expected = os.environ.get("CARO_WORKER_TOKEN", "").strip()
    if not expected or not os.environ.get(runs_mod.OPS_ENV, "").strip():
        raise HTTPException(503, "RUNS_OFF")
    addr = client_address(request)
    wait = WORKER_FAILURES.blocked(addr)
    if wait is not None:
        raise too_many(wait)
    token = (authorization or "")[len("Bearer "):] if (authorization or "").startswith("Bearer ") else ""
    if not token or not secrets.compare_digest(token.encode("utf-8"), expected.encode("utf-8")):
        WORKER_FAILURES.hit(addr)
        raise HTTPException(401, "the worker's token was not accepted")


@router.post("/api/worker/runs", response_model=Received, dependencies=[Depends(require_worker)])
def receive(rec: RunRecord) -> Received:
    if rec.run_id.rpartition("#")[0] != rec.job or rec.job.split(":")[1] != rec.source \
            or rec.job.split(":")[2] != rec.collected_on:
        raise HTTPException(422, "the run's id, its job, its source and its day disagree")
    try:
        db = _open_runs(os.environ[runs_mod.OPS_ENV].strip())
    except runs_mod.RunsError:
        raise HTTPException(503, "RUNS_UNAVAILABLE") from None
    try:
        kept = db.keep(rec.model_dump())
    except runs_mod.RunsError as e:
        raise HTTPException(409, str(e)) from None
    finally:
        db.close()
    return Received(run_id=rec.run_id, kept=kept)
