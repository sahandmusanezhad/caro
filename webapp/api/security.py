"""What the API does so that a caller cannot use it against itself or others.

Four things, each small, each stated with what it is NOT:

**Headers on every response.** The API answers JSON, and nothing it answers
is meant to be rendered, framed or sniffed as something else: `nosniff`, no
framing, no referrer, and a Content-Security-Policy that allows nothing, so a
response opened in a browser tab runs nothing. The admin endpoints add
`no-store`: what the inbox holds is people's names and addresses, and no cache
between here and the operator should keep a copy.

**A rate limit, per process.** The contact form and the admin token are the
two doors a person can knock on repeatedly. `RateLimiter` counts knocks per
address in a sliding window, in memory. It slows one client hammering one
process; it is NOT a wall: a serverless deployment runs many processes, each
with its own count, and a restart forgets. Saying so is the point: a limit
that claims more than it does is how an operator stops looking.

**The address is the socket's.** `X-Forwarded-For` is a header any client can
write, so it is believed only where the operator says a proxy sets it
(`CARO_TRUST_PROXY=1`), and then only its first entry.

**CORS is for development.** The site and the API share an origin in
production (vercel.json's rewrite), so no cross-origin call is needed there.
`CARO_CORS_ORIGINS` names the origins that may call it from elsewhere;
unset, it is the development server's. No cookie is used, so no credentials
are allowed.
"""

from __future__ import annotations

import math
import os
import threading
import time
from collections import deque
from typing import Callable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware

HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}

TOO_MANY_FA = "درخواست‌های این نشانی زیاد بوده است. کمی بعد دوباره امتحان کن."


def private(path: str) -> bool:
    """An answer that is one person's, or holds a seller's number: the
    operator's view, a seller's account and listings, and a reveal. No cache
    keeps it, shared or the browser's own."""
    return (path.startswith(("/api/admin", "/api/account", "/api/listings/mine"))
            or (path.startswith("/api/listings/") and path.endswith("/reveal")))


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        for k, v in HEADERS.items():
            response.headers.setdefault(k, v)
        if private(request.url.path):
            response.headers["Cache-Control"] = "no-store"
        return response


class RateLimiter:
    """At most `limit` events per key in any `window_s` seconds, in memory.

    `hit` records an event and says how long to wait if it is one too many;
    `blocked` only asks. Keys beyond `max_keys` push the oldest out, so a
    flood of addresses cannot grow the table without end."""

    def __init__(self, limit: int, window_s: float, *,
                 clock: Callable[[], float] = time.monotonic,
                 max_keys: int = 10_000):
        self.limit, self.window_s, self.clock = limit, window_s, clock
        self.max_keys = max_keys
        self._events: dict[str, deque] = {}
        self._lock = threading.Lock()

    def _trim(self, key: str, now: float) -> deque:
        q = self._events.get(key)
        if q is None:
            if len(self._events) >= self.max_keys:
                self._events.pop(next(iter(self._events)))
            q = self._events[key] = deque()
        while q and now - q[0] >= self.window_s:
            q.popleft()
        return q

    def blocked(self, key: str) -> float | None:
        """Seconds until the next event is allowed, or None if it is now."""
        with self._lock:
            now = self.clock()
            q = self._trim(key, now)
            if len(q) >= self.limit:
                return max(0.0, self.window_s - (now - q[0]))
            return None

    def hit(self, key: str) -> float | None:
        """Record an event; None if it was allowed, else the seconds to wait
        (and the event is not recorded)."""
        with self._lock:
            now = self.clock()
            q = self._trim(key, now)
            if len(q) >= self.limit:
                return max(0.0, self.window_s - (now - q[0]))
            q.append(now)
            return None

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


def client_address(request: Request) -> str:
    """The socket's address, or the first X-Forwarded-For entry where the
    operator has said a proxy sets it (CARO_TRUST_PROXY=1)."""
    if os.environ.get("CARO_TRUST_PROXY", "").strip() == "1":
        first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def too_many(wait_s: float) -> HTTPException:
    return HTTPException(429, TOO_MANY_FA,
                         headers={"Retry-After": str(max(1, math.ceil(wait_s)))})


def cors_origins() -> list[str]:
    raw = os.environ.get("CARO_CORS_ORIGINS", "")
    got = [o.strip() for o in raw.split(",") if o.strip()]
    return got or ["http://localhost:3000"]
