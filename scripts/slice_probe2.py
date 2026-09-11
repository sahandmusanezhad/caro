#!/usr/bin/env python3
"""Where do the listings actually come from, and what does robots.txt allow?

    python3 scripts/slice_probe2.py

TWO requests: the category page, and robots.txt.

The first probe found 897,877 bytes of HTML holding ten detail links, no
pagination controls and no result count. That is an application shell: the
list is assembled in the browser, so `extract_listing_links` is reading
whatever the server happened to render into the initial payload, and there
is no second page to follow because there are no page links to follow.

Two questions follow, and both must be answered before step 5 chooses a
collector.

    1. Is the full list reachable at all, and by what?
       A state blob in the page, or an endpoint the page calls. Read out of
       the bytes already fetched, not guessed.

    2. Is it allowed?
       `caro/ingest/base.py` says "respect the source's terms of use and
       robots directives" — in a docstring. Nothing in the fetch path reads
       robots.txt. That was survivable while the collector made a hundred
       requests a day against pages a browser also requests. Step 5 is a
       daily re-fetch of a cohort plus enumeration of a slice, which is a
       different order of load, and the constraint has to become a mechanism
       before the load goes up rather than after.

WHAT IT WILL NOT PRINT

Keys, endpoint paths, and integers. Never a string value out of the state
blob: it holds listing titles and seller prose, the corpus contract forbids
publishing that, and a diagnostic is not an exemption. robots.txt is printed
in full because it is a machine-readable policy file addressed to exactly
this kind of program.

This file reads. It does not call any endpoint it discovers — that is the
next decision, and it is yours.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CARO_SELLER_SALT", "slice-probe-collects-nothing")

from caro.ingest.bama import BamaAdapter, http_fetcher            # noqa: E402
from caro.tracking import FetchStatus, classify_http              # noqa: E402

DEFAULT = "https://bama.ir/car/pride-131"

_BLOB = re.compile(
    r'<script[^>]*id="(__NEXT_DATA__|__NUXT_DATA__)"[^>]*>(.*?)</script>',
    re.S)
_ASSIGN = re.compile(
    r'(window\.__(?:NUXT|INITIAL_STATE|PRELOADED_STATE)__)\s*=\s*', re.I)
# Stops at a quote OR a query string. The first version required the
# closing quote immediately after the path, so "/api/v1/search/car?page=2"
# — an endpoint with parameters, which is most of them — did not match at
# all. A probe that silently misses the interesting case is worse than no
# probe, because its empty output reads as an answer.
_API = re.compile(
    r'["\'](/?(?:api|_next/data)/[A-Za-z0-9/_.\-]{2,80})(?=[?"\'])')
_COUNTISH = re.compile(
    r"total|count|pages?$|pagesize|page_size|perpage|per_page|hits|results",
    re.I)


def walk(node, path="", depth=0, out=None):
    """Collect (path, int) for count-ish keys. Integers only, never strings."""
    out = [] if out is None else out
    if depth > 8:
        return out
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else str(k)
            if isinstance(v, bool):
                continue
            if isinstance(v, int) and _COUNTISH.search(str(k)):
                out.append((p, v))
            walk(v, p, depth + 1, out)
    elif isinstance(node, list):
        # Index 0 only. A list of a thousand listings walked in full would
        # take a while and teach nothing the first element does not.
        if node:
            walk(node[0], f"{path}[0]", depth + 1, out)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--url", default=DEFAULT)
    a = ap.parse_args()

    ad = BamaAdapter(fetcher=http_fetcher(), max_listings=1, max_categories=1)

    print("SLICE PROBE 2 — how the list is served, and what is permitted")
    print("=" * 64)

    status, html = ad._get(a.url)
    print(f"  url                  {a.url}")
    print(f"  http                 {status} -> {classify_http(status).value}")
    if classify_http(status) is not FetchStatus.OK or not html:
        print("\n  Nothing to read.")
        return 1
    print(f"  bytes                {len(html):,}")
    print()

    # ---- 1. state blobs --------------------------------------------------
    print("EMBEDDED STATE")
    print("-" * 64)
    blobs = _BLOB.findall(html)
    assigns = sorted(set(m for m in _ASSIGN.findall(html)))
    if not blobs and not assigns:
        print("  no __NEXT_DATA__ / __NUXT__ / __INITIAL_STATE__ found.")
    for name, body in blobs:
        print(f"  {name}   {len(body):,} bytes")
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            print(f"    does not parse as JSON: {e}")
            continue
        top = sorted(data)[:12] if isinstance(data, dict) else []
        print(f"    top-level keys: {', '.join(top) or '(not an object)'}")
        counts = walk(data)
        if counts:
            print("    count-ish integers (key path -> value):")
            for p, v in counts[:25]:
                print(f"      {p:<52}{v:>10,}")
            if len(counts) > 25:
                print(f"      … and {len(counts) - 25} more")
        else:
            print("    no count-ish integer fields at depth <= 8")
    for name in assigns:
        print(f"  {name} assignment present (not JSON-parsed here)")
    print()

    # ---- 2. endpoints the page names -------------------------------------
    print("ENDPOINT PATHS THE PAGE MENTIONS")
    print("-" * 64)
    paths = sorted(set(_API.findall(html)))
    if paths:
        for p in paths[:30]:
            print(f"    {p}")
        if len(paths) > 30:
            print(f"    … and {len(paths) - 30} more")
    else:
        print("    none matched /api/ or /_next/data/.")
    print()

    # ---- 3. what robots.txt says -----------------------------------------
    host = f"{urlparse(a.url).scheme}://{urlparse(a.url).netloc}"
    rstatus, robots = ad._get(f"{host}/robots.txt")
    print(f"ROBOTS.TXT   {host}/robots.txt   http {rstatus}")
    print("-" * 64)
    if classify_http(rstatus) is not FetchStatus.OK or not robots:
        print("  could not be read. Until it can be, the conservative reading")
        print("  is that nothing new may be requested — an unreadable policy")
        print("  is not an absent one.")
        return 1
    for line in robots.strip().splitlines()[:60]:
        print(f"  {line}")
    print()

    # Disallow rules, matched literally against what we found. Deliberately
    # NOT a robots parser: a half-written one that gets a wildcard wrong
    # gives permission it was never given. This prints the overlap and a
    # person decides.
    dis = [l.split(":", 1)[1].strip()
           for l in robots.splitlines()
           if l.lower().startswith("disallow:") and ":" in l]
    print("DISALLOW RULES vs THE PATHS ABOVE")
    print("-" * 64)
    if not dis:
        print("  no Disallow lines.")
    flagged = [(p, d) for p in paths for d in dis
               if d and (p.startswith(d) or d.rstrip("*") and
                         p.startswith(d.rstrip("*")))]
    if flagged:
        for p, d in flagged[:20]:
            print(f"  ✗ {p}   covered by  Disallow: {d}")
    else:
        print("  no literal prefix match between a discovered path and a")
        print("  Disallow rule.")
    print()
    print("  This is a PREFIX COMPARISON, not a robots evaluation. Wildcards,")
    print("  Allow precedence and user-agent grouping are not implemented")
    print("  here on purpose: a parser that is almost right hands out")
    print("  permission nobody gave. Read the rules above yourself before")
    print("  anything calls anything.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
