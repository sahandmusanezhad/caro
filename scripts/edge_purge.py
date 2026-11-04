#!/usr/bin/env python3
"""Purges what Cloudflare's edge keeps of the API's answers, when the runs it
answers from have changed (docs/REARCHITECTURE.md, phase 4).

    python -m webapp.role edge-purge

The three answers the edge may keep (webapp/api/edge.py) depend on the
published runs and on the one served. Both are in the image and in its
environment: the files of data/corpora/ and CARO_RUN. Their key is a
digest of the two; when it is not the key last purged, the host's answers
are purged from Cloudflare's cache and the key is kept. deploy/pull.sh
runs this after every change it makes to an environment, so a new corpus
is never answered from the edge with the old one's numbers.

    CARO_CF_API_TOKEN   a Cloudflare token with Zone -> Cache Purge, this zone only
    CARO_CF_ZONE_ID     the zone's id
    CARO_SITE_HOST      the host whose answers are purged: caro.noxioai.com
    CARO_PURGE_STATE    where the last purged key is kept (/var/lib/caro-purge/key)

Without the token and the zone it says purging is off and does nothing,
and a kept answer lives at most CARO_EDGE_TTL. It purges by host; where
Cloudflare refuses that, by the two fixed addresses, /api/models and
/api/corpus, and a model's page then lives out its CARO_EDGE_TTL. Nothing
it prints holds the token.
"""

from __future__ import annotations

import hashlib
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "data" / "corpora"
API = "https://api.cloudflare.com/client/v4/zones/{zone}/purge_cache"
DEFAULT_STATE = "/var/lib/caro-purge/key"


def corpus_key(corpora: Path, run: str) -> str:
    """A digest of every published run's bytes, by name, and of the run served."""
    h = hashlib.sha256()
    for p in sorted(corpora.glob("*.json")):
        h.update(p.name.encode("utf-8") + b"\0" + hashlib.sha256(p.read_bytes()).digest())
    h.update(b"\0run=" + run.strip().encode("utf-8"))
    return h.hexdigest()


def _purge(body: dict, token: str, zone: str, opener: Callable) -> bool:
    req = urllib.request.Request(API.format(zone=zone), data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers={"Authorization": f"Bearer {token}",
                                                         "Content-Type": "application/json"})
    try:
        with opener(req, timeout=20) as r:
            answer = json.loads(r.read().decode("utf-8"))
    except Exception:          # noqa: BLE001 -- a refusal, an error page, no answer: not purged
        return False
    return isinstance(answer, dict) and answer.get("success") is True


def purge(host: str, token: str, zone: str, opener: Callable = urllib.request.urlopen) -> str | None:
    """How the host's answers were purged -- "host" or "addresses" -- or None."""
    if _purge({"hosts": [host]}, token, zone, opener):
        return "host"
    if _purge({"files": [f"https://{host}/api/models", f"https://{host}/api/corpus"]}, token, zone, opener):
        return "addresses"
    return None


def main(argv: list[str] | None = None, env=None, opener: Callable = urllib.request.urlopen,
         corpora: Path = CORPORA, out: Callable[[str], None] = print) -> int:
    env = os.environ if env is None else env
    token = (env.get("CARO_CF_API_TOKEN") or "").strip()
    zone = (env.get("CARO_CF_ZONE_ID") or "").strip()
    host = (env.get("CARO_SITE_HOST") or "").strip()
    if not (token and zone and host):
        out("edge-purge: off -- CARO_CF_API_TOKEN, CARO_CF_ZONE_ID and CARO_SITE_HOST are not all set; "
            "a kept answer lives out its CARO_EDGE_TTL")
        return 0
    state = Path((env.get("CARO_PURGE_STATE") or "").strip() or DEFAULT_STATE)
    key = corpus_key(corpora, env.get("CARO_RUN", "") or "")
    try:
        last = state.read_text(encoding="utf-8").strip()
    except OSError:
        last = ""
    if last == key:
        out(f"edge-purge: the runs are as they were ({key[:12]}); nothing purged")
        return 0
    how = purge(host, token, zone, opener)
    if how is None:
        out(f"edge-purge: Cloudflare did not purge {host}; tried again after the next change")
        return 1
    state.parent.mkdir(parents=True, exist_ok=True)
    state.write_text(key + "\n", encoding="utf-8")
    out(f"edge-purge: {host} purged by {how}, for runs {key[:12]}"
        + ("" if how == "host" else "; a model's page lives out its CARO_EDGE_TTL"))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
