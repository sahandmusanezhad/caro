#!/usr/bin/env python3
"""The site, read from the outside, after a merge.

    python3 scripts/site_check.py                               the site on Vercel
    python3 scripts/site_check.py --site https://caro.noxioai.com

The working agreement asks for the site to be read from the outside after
every merge, and the decision entry to say what was read. A session's
sandbox cannot reach the site, so the owner runs this and sends back what
it prints. Every line is one fact a merge can change:

    about     the counts /about publishes: decisions, assertions, suites
    corpus    which run the API serves, its kind, and its digest
    model     a model's page: its listings, and its history, run by run
    search    one question, the model it read and how many listings it shows
    home      whether the seller pages are linked from the home page
    edge      what the edge kept of /api/models -- Cloudflare's cache status,
              for how long -- and whether its corpus is the one health
              names, which no cache keeps (phase 4)
    headers   who answered: Cloudflare or Vercel

Standard library only; a dozen requests to our own site, nothing else.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.parse
import urllib.request

UA = "caro-site-check"


def get(base: str, path: str, timeout: float = 30) -> tuple[int, dict, str]:
    req = urllib.request.Request(base.rstrip("/") + path, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read().decode("utf-8")


def about_counts(html: str) -> list[str]:
    """The «number word» pairs /about publishes, as `number=word`."""
    text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    # once each, in the order the page gives them: the page names a count
    # in more than one place
    return list(dict.fromkeys(f"{n}={w}" for n, w in re.findall(r"([۰-۹]+) (تصمیم|گزاره|مجموعه)", text)))


def edge_line(base: str) -> str:
    """The models' answer as the edge gives it, held against health's digest."""
    _, _, body = get(base, "/api/health")
    served = json.loads(body).get("corpus")
    _, h, _ = get(base, "/api/models")
    kept = h.get("x-caro-corpus")
    if served is None and kept is None:
        return "edge     no corpus digest on health or the models: an API from before phase 4"
    same = "the same" if kept == served else "NOT the same"
    return (f"edge     models {h.get('cf-cache-status', '-')}, {h.get('cache-control', '-')}; "
            f"its corpus {(kept or '-')[:12]}, health's {(served or '-')[:12]}: {same}")


def report(base: str, model: tuple[str, str], question: str) -> list[str]:
    out = []
    s, h, html = get(base, "/about")
    out.append(f"about    {s} " + " ".join(about_counts(html)))
    s, h, body = get(base, "/api/corpus")
    c = json.loads(body)
    ident = c["corpus"].get("identity") or {}
    out.append(f"corpus   {s} {c['status']['kind']} {ident.get('run_id', '-')} "
               f"{(ident.get('sha256') or '-')[:12]} {c['corpus']['rows']} rows")
    q = urllib.parse.urlencode({"make": model[0], "model": model[1]})
    s, h, body = get(base, f"/api/model?{q}")
    m = json.loads(body)
    out.append(f"model    {s} {model[0]} {model[1]}: {(m.get('summary') or {}).get('listings')} listings")
    for p in m.get("history", []):
        out.append(f"history  {p.get('run_id')} {p.get('collected_on')} {p.get('source')} "
                   f"{p.get('priced')} {p.get('price_median')}")
    s, h, body = get(base, "/api/search?" + urllib.parse.urlencode({"q": question, "k": 3}))
    r = json.loads(body)
    out.append(f"search   {s} «{question}»: models {r['intent']['models']}, "
               f"{r.get('evidence_total')} shown, {r.get('evidence_unchecked_total')} apart")
    s, h, html = get(base, "/")
    listings, sell = 'href="/listings"' in html, 'href="/sell"' in html
    out.append(f"home     {s} seller links: {listings} {sell}")
    out.append(edge_line(base))
    out.append(f"headers  server: {h.get('server', '-')}  cf-ray: {'yes' if 'cf-ray' in h else 'no'}")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--site", default="https://caro-rho.vercel.app")
    ap.add_argument("--model", default="IKCO/Samand", help="MAKE/MODEL for the model line")
    ap.add_argument("--question", default="سمند زیر ۲ میلیارد")
    a = ap.parse_args(argv)
    make, _, model = a.model.partition("/")
    try:
        for line in report(a.site, (make, model), a.question):
            print(line)
    except Exception as e:                       # noqa: BLE001 — say what failed, and where
        print(f"the site check stopped: {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
