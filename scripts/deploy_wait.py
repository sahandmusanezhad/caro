#!/usr/bin/env python3
"""Wait until a deployment runs the commit given, then exit 0.

    python3 scripts/deploy_wait.py --site https://caro-staging.noxioai.com --build <sha>

The server pulls the image its tag names every minute (deploy/pull.sh), so a
merge reaches staging a minute or two after the image is pushed. This asks
`/api/health` until its `build` is the commit, at most --timeout seconds, and
prints what it saw each time it changed. Exit status: 0 when the build
answered; 1 when it did not in time, with the last answer or error.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request


def build_of(site: str, opener=urllib.request.urlopen, timeout: float = 10) -> str:
    req = urllib.request.Request(site.rstrip("/") + "/api/health",
                                 headers={"User-Agent": "caro-deploy-wait"})
    with opener(req, timeout=timeout) as r:
        body = json.loads(r.read().decode("utf-8"))
    return str(body.get("build") or "")


def wait(site: str, build: str, timeout: float, every: float,
         read=build_of, clock=time.monotonic, sleep=time.sleep, out=print) -> int:
    end = clock() + timeout
    last = None
    while True:
        try:
            seen = read(site)
        except (OSError, ValueError) as e:
            seen = f"no answer: {type(e).__name__}"
        if seen != last:
            out(f"deploy-wait: {site} runs {seen or '(no build)'}")
            last = seen
        if seen == build:
            return 0
        if clock() >= end:
            out(f"deploy-wait: {build} did not answer within {timeout:.0f} s")
            return 1
        sleep(every)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", required=True)
    ap.add_argument("--build", required=True)
    ap.add_argument("--timeout", type=float, default=900)
    ap.add_argument("--every", type=float, default=15)
    a = ap.parse_args(argv)
    return wait(a.site, a.build, a.timeout, a.every)


if __name__ == "__main__":
    sys.exit(main())
