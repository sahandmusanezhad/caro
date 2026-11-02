#!/usr/bin/env python3
"""Can this machine reach the hosts the platform plan would use, and how fast?

    python3 scripts/reach_probe.py                       the default targets, five rounds
    python3 scripts/reach_probe.py --rounds 10 --json reach.json
    python3 scripts/reach_probe.py --postgres ep-name-123456.eu-central-1.aws.neon.tech
    python3 scripts/reach_probe.py --target "my VPS=203.0.113.7:443"

Phase 0 of the plan (docs/REARCHITECTURE.md) asks for it to be run from
inside Iran: it decides where the API and Postgres live -- Hetzner in Europe,
Neon, or Postgres beside the API -- and D64 raised the question without
anyone measuring it. Run it on an ordinary connection in Iran, and once more
on the network the collection worker would use; send back what it prints,
or the --json file, which is the record.

What it measures, per target and round, each step only if the one before it
worked:

    dns     the name resolved, its first address, how long it took
    tcp     a connection to the port (443 unless given), how long
    tls     a handshake that sends the target's name (SNI), its certificate
            checked, how long
    http    an HTTPS HEAD of "/", its status and the time to its first byte

A failure is named by its kind -- dns, dns-private, refused, reset, timeout,
tls, cert, http, other -- because filtering shows as a reset or a timeout at
the handshake for some names and not others, or as a DNS answer that points
at a private address, and one count of "failed" would hide which.
`dns-private` is that last one: a public name answered with an address no
server on the internet has.

If a name fails DNS from everywhere, the name is wrong, not filtered; the
probe cannot tell those apart, so Cloudflare and GitHub are among the
targets as controls, and --target adds any other.

Never less than --pause seconds (2) between two connections to one host,
and nothing is downloaded but a status line. No listing is read and no
source is touched: the targets are infrastructure. Standard library only.
"""

from __future__ import annotations

import argparse
import ipaddress
import json
import socket
import ssl
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCHEMA = "caro.reach/1"
USER_AGENT = "caro-reach-probe"


@dataclass(frozen=True)
class Target:
    name: str
    host: str
    port: int = 443
    tls: bool = True        # handshake after the connection
    http: bool = True       # HEAD / after the handshake


DEFAULT_TARGETS = (
    Target("Hetzner, Falkenstein", "fsn1-speed.hetzner.com"),
    Target("Hetzner, Nuremberg", "nbg1-speed.hetzner.com"),
    Target("Hetzner, Helsinki", "hel1-speed.hetzner.com"),
    Target("Neon's console", "console.neon.tech"),
    Target("Cloudflare (a control)", "www.cloudflare.com"),
    Target("the site on Vercel", "caro-rho.vercel.app"),
    Target("GitHub (a control)", "github.com"),
    Target("GitHub's container registry", "ghcr.io"),
)


@dataclass
class Attempt:
    target: str
    host: str
    port: int
    round: int
    ok: bool = False
    failed_at: str | None = None    # dns, tcp, tls or http
    kind: str | None = None         # see the module's docstring
    detail: str | None = None
    address: str | None = None
    dns_ms: float | None = None
    tcp_ms: float | None = None
    tls_ms: float | None = None
    http_ms: float | None = None
    status: int | None = None


def kind_of(e: BaseException) -> str:
    """The kind of a failure, from its exception alone."""
    if isinstance(e, socket.gaierror):
        return "dns"
    if isinstance(e, ssl.SSLCertVerificationError):
        return "cert"
    if isinstance(e, (socket.timeout, TimeoutError)):
        return "timeout"
    if isinstance(e, ConnectionRefusedError):
        return "refused"
    if isinstance(e, (ConnectionResetError, BrokenPipeError, ssl.SSLEOFError, ssl.SSLZeroReturnError)):
        return "reset"
    if isinstance(e, ssl.SSLError):
        return "tls"
    return "other"


def is_private(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address)
    except ValueError:
        return False
    return ip.is_private or ip.is_loopback or ip.is_reserved or ip.is_link_local or ip.is_unspecified


@dataclass
class Probe:
    """One run. Every step that touches the network is a field, so a suite
    can run the probe on 127.0.0.1 with no other address reachable."""
    timeout: float = 5.0
    pause: float = 2.0
    allow_private: bool = False      # the suites' targets are on 127.0.0.1
    resolve: Callable[..., Any] = socket.getaddrinfo
    connect: Callable[..., Any] = socket.create_connection
    context: ssl.SSLContext = field(default_factory=ssl.create_default_context)
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last: dict[str, float] = field(default_factory=dict)

    def _wait_for(self, host: str) -> None:
        """No two connections to one host closer than `pause`."""
        last = self._last.get(host)
        if last is not None:
            gap = self.pause - (self.clock() - last)
            if gap > 0:
                self.sleep(gap)
        self._last[host] = self.clock()

    def attempt(self, t: Target, rnd: int) -> Attempt:
        a = Attempt(target=t.name, host=t.host, port=t.port, round=rnd)
        step = "dns"
        sock = None
        try:
            t0 = self.clock()
            infos = self.resolve(t.host, t.port, type=socket.SOCK_STREAM)
            a.dns_ms = (self.clock() - t0) * 1000
            # IPv4 first: it is what a connection from Iran mostly has, and
            # one address family keeps the rounds comparable.
            v4 = [i for i in infos if i[0] == socket.AF_INET]
            a.address = str((v4 or infos)[0][4][0])
            if not self.allow_private and is_private(a.address):
                a.failed_at, a.kind = "dns", "dns-private"
                a.detail = f"{t.host} answered with {a.address}, a private address"
                return a
            step = "tcp"
            self._wait_for(t.host)
            t0 = self.clock()
            sock = self.connect((a.address, t.port), timeout=self.timeout)
            a.tcp_ms = (self.clock() - t0) * 1000
            if t.tls:
                step = "tls"
                t0 = self.clock()
                sock = self.context.wrap_socket(sock, server_hostname=t.host)
                a.tls_ms = (self.clock() - t0) * 1000
            if t.tls and t.http:
                step = "http"
                sock.settimeout(self.timeout)
                t0 = self.clock()
                sock.sendall((f"HEAD / HTTP/1.1\r\nHost: {t.host}\r\nUser-Agent: {USER_AGENT}\r\n"
                              "Connection: close\r\n\r\n").encode("ascii"))
                first = sock.recv(64)
                a.http_ms = (self.clock() - t0) * 1000
                line = first.split(b"\r\n", 1)[0].decode("latin-1")
                parts = line.split()
                if len(parts) < 2 or not parts[0].startswith("HTTP/") or not parts[1].isdigit():
                    a.failed_at, a.kind = "http", "http"
                    a.detail = f"not an HTTP status line: {line[:40]!r}"
                    return a
                a.status = int(parts[1])
            a.ok = True
        except Exception as e:                  # noqa: BLE001 — every failure is named, none raised
            a.failed_at, a.kind = step, kind_of(e)
            a.detail = f"{type(e).__name__}: {e}"[:160]
        finally:
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
        return a

    def run(self, targets: tuple[Target, ...] | list[Target], rounds: int,
            progress: Callable[[Attempt], None] | None = None) -> list[Attempt]:
        """Round by round, every target once in each, so that the rounds of
        one host are spread over the run rather than bunched together."""
        out = []
        for rnd in range(1, rounds + 1):
            for t in targets:
                a = self.attempt(t, rnd)
                out.append(a)
                if progress:
                    progress(a)
        return out


def _median(xs: list[float]) -> str:
    return f"{statistics.median(xs):.0f} ms" if xs else "—"


def table(attempts: list[Attempt]) -> str:
    by: dict[tuple[str, str, int], list[Attempt]] = {}
    for a in attempts:
        by.setdefault((a.target, a.host, a.port), []).append(a)
    rows = [("target", "host", "dns", "tcp", "tls", "http", "reached", "failed")]
    for (name, host, port), xs in by.items():
        ok = [a for a in xs if a.ok]
        kinds: dict[str, int] = {}
        for a in xs:
            if not a.ok:
                kinds[f"{a.kind} at {a.failed_at}"] = kinds.get(f"{a.kind} at {a.failed_at}", 0) + 1
        statuses = sorted({a.status for a in ok if a.status is not None})
        http = _median([a.http_ms for a in ok if a.http_ms is not None])
        if statuses:
            http += " · " + "/".join(str(s) for s in statuses)
        rows.append((name, f"{host}:{port}",
                     _median([a.dns_ms for a in xs if a.dns_ms is not None]),
                     _median([a.tcp_ms for a in xs if a.tcp_ms is not None]),
                     _median([a.tls_ms for a in xs if a.tls_ms is not None]),
                     http, f"{len(ok)}/{len(xs)}",
                     ", ".join(f"{k} ×{n}" for k, n in sorted(kinds.items())) or "—"))
    widths = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    return "\n".join("  ".join(c.ljust(w) for c, w in zip(r, widths)).rstrip() for r in rows)


def record(attempts: list[Attempt], *, rounds: int, timeout: float, pause: float,
           ran_at: str) -> dict:
    """What --json writes. Nothing about the machine it ran on: no name, no
    address of its own."""
    return {"schema": SCHEMA, "ran_at": ran_at, "rounds": rounds, "timeout_s": timeout,
            "pause_s": pause, "attempts": [asdict(a) for a in attempts]}


def parse_target(spec: str) -> Target:
    """`NAME=HOST[:PORT]`, or `HOST[:PORT]`."""
    name, _, where = spec.rpartition("=")
    host, colon, port = where.rpartition(":")
    if not colon or not port.isdigit():
        host, port = where, "443"
    return Target(name or host, host, int(port))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rounds", type=int, default=5)
    ap.add_argument("--timeout", type=float, default=5.0, help="seconds for each step")
    ap.add_argument("--pause", type=float, default=2.0,
                    help="the least seconds between two connections to one host")
    ap.add_argument("--target", action="append", default=[], metavar="NAME=HOST[:PORT]",
                    help="one more target; may be given more than once")
    ap.add_argument("--postgres", action="append", default=[], metavar="HOST[:PORT]",
                    help="a Postgres endpoint (5432 unless given): connection only")
    ap.add_argument("--only", action="store_true", help="only the targets given, not the defaults")
    ap.add_argument("--json", type=Path, help="write every attempt here")
    a = ap.parse_args(argv)
    if a.rounds < 1 or a.timeout <= 0 or a.pause < 0:
        ap.error("--rounds is at least 1, --timeout more than 0, --pause not negative")

    targets = [] if a.only else list(DEFAULT_TARGETS)
    targets += [parse_target(s) for s in a.target]
    for spec in a.postgres:
        host, colon, port = spec.rpartition(":")
        if not colon or not port.isdigit():
            host, port = spec, "5432"
        targets.append(Target(f"Postgres {host}", host, int(port), tls=False, http=False))
    if not targets:
        ap.error("no target: --only needs --target or --postgres")

    ran_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"reach probe, {len(targets)} targets, {a.rounds} rounds, {ran_at}", file=sys.stderr)
    probe = Probe(timeout=a.timeout, pause=a.pause)
    attempts = probe.run(targets, a.rounds,
                         progress=lambda x: print(f"  round {x.round}  {x.host:<32} "
                                                  f"{'ok' if x.ok else x.kind}", file=sys.stderr))
    print(table(attempts))
    if a.json:
        a.json.write_text(json.dumps(record(attempts, rounds=a.rounds, timeout=a.timeout,
                                            pause=a.pause, ran_at=ran_at),
                                     ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nwrote {a.json}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
