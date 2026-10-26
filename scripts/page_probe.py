#!/usr/bin/env python3
"""
A few public pages of one source, fetched politely and kept on this machine.

    python3 scripts/page_probe.py --source divar --origin https://divar.ir \\
        --render browser --url https://divar.ir/s/tehran/light
    python3 scripts/page_probe.py --skeleton ~/caro-probes/<run>/01-3f9a1c2e.html

WHY THIS EXISTS

`DivarCarAdapter` has a robots gate, a politeness policy and a rule to stop
when the source stops answering. It has no extraction of the listing page:
`first_run.py --source divar` raises NotImplementedError after its first page,
and nothing in this repository holds a page Divar serves. Sheypoor and
Khodro45 have no adapter at all. The extraction has to be written against the
markup a source really serves, and a selector written without reading that
markup is a guess wearing a regex (`location_probe.py` says the same of
bama). The roadmap names the method (the product gaps, item 1): the owner
probes first, the probe's pages stay on his machine, and the adapter is
built and tested offline against what the probe kept.

WHAT IT DOES

  1. Reads the origin's robots.txt through the gate a collection run uses
     (`caro/ingest/robots.py`) and prints what it read.
  2. Asks that gate about each url before requesting it. A url the file
     disallows is not requested; if the file gives no policy, nothing is. For
     Divar the 2026-09-07 transcription beside the adapter is asked as well.
  3. Requests at most MAX_URLS pages, one after another, with the adapters'
     pause between them, under the adapters' User-Agent, which says who we
     are and how to write to us.
  4. Keeps each page that returned, byte for byte, in a folder OUTSIDE the
     repository (a folder inside it is refused), beside `probe.json`: the
     url, the status, the size, the sha256 of the page and the robots record.
  5. Stops at the first page that does not return: a status other than 2xx,
     an empty body, an error. It does not retry, wait it out or change how it
     asks. A block is a finding and is recorded as one (caro/ingest/base.py,
     obligation 1).

WHAT IT DOES NOT DO

No login, no cookie, no click, no form, nothing that reveals a contact. No
proxy and no change to how the browser presents itself: where a browser is
needed (`--render browser`, for a page rendered client-side) it is stock
Playwright Chromium with our User-Agent and nothing injected. It does not
follow a link: the urls are the ones it is given.

THE SKELETON

A saved page is the owner's to read and not to publish: a listing page may
carry a seller's name or a number. `--skeleton FILE` prints the shape of one,
with no network: the tags and the classes (kept as written: a class with a
digit in it, col-6, is structure and not content), the names of the data
attributes with their values masked, the path of each link with its tokens
masked (a tel: or mailto: link is shown as its scheme alone), and each text
as its first 40 characters. Every digit taken from the page's text, its
attribute values or its links is replaced by «#», so a phone number cannot
appear in it. That sentence is checked by a test, not believed.

What it does NOT hide is a name: if a page prints a seller's or a showroom's
name in a text, its first 40 characters are in the skeleton. `--no-text` keeps
the text out altogether, and shows only that a text is there; the shape and
the classes are usually enough to write the selectors, and the formats of a
price and a mileage are already known to the parsers. Read what is printed
before it is sent anywhere.
"""

from __future__ import annotations

import argparse
import hashlib
import html.parser
import json
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from caro.ingest.bama import http_fetcher                              # noqa: E402
from caro.ingest.divar_car import (                                      # noqa: E402
    PolitenessPolicy, assert_allowed, playwright_fetcher,
)
from caro.ingest.robots import RobotsGate, RobotsViolation, describe     # noqa: E402

# A probe looks; it does not crawl. Five pages is a category page, a few
# listings, and one to compare them with.
MAX_URLS = 5
DEFAULT_OUT = Path.home() / "caro-probes"
_SOURCE = re.compile(r"[a-z0-9][a-z0-9_-]{0,31}")


class ProbeRefused(ValueError):
    """The probe was asked for something it does not do."""


@dataclass
class ProbeResult:
    manifest: dict
    exit_code: int
    out_dir: Path


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def probe(origin: str, urls: list[str], *, source: str,
          fetch: Callable[[str], tuple[int, str]],
          robots_fetch: Callable[[str], tuple[int, str]],
          out_dir: Path, policy: PolitenessPolicy | None = None,
          sleeper: Callable[[float], None] = time.sleep,
          repo_root: Path = ROOT) -> ProbeResult:
    """Fetch `urls` of one origin as the docstring says, and keep them.

    `fetch` and `robots_fetch` are injected, as the adapters' are, so the
    behaviour is tested without a network."""
    policy = policy or PolitenessPolicy()
    if not _SOURCE.fullmatch(source):
        raise ProbeRefused(f"--source must look like divar or khodro45, "
                           f"not {source!r}")
    if not urls:
        raise ProbeRefused("no url was given")
    if len(urls) > MAX_URLS:
        raise ProbeRefused(f"{len(urls)} urls: a probe asks for at most "
                           f"{MAX_URLS}")
    out = Path(out_dir).expanduser().resolve()
    root = Path(repo_root).resolve()
    if out == root or root in out.parents:
        raise ProbeRefused(f"{out} is inside the repository. What a probe "
                           "keeps stays on this machine and is never "
                           "committed: choose a folder outside it")

    if (out / "probe.json").exists():
        raise ProbeRefused(f"{out} already holds a probe; a run is never "
                           "overwritten")
    gate = RobotsGate(origin, robots_fetch, source=source,
                      pause=lambda: sleeper(policy.sleep()))
    pages: list[dict] = []
    halted: str | None = None
    requested = 0
    started = _utc()
    for url in urls:
        try:
            if source == "divar":
                assert_allowed(url)
            gate.check(url)
        except RobotsViolation as e:
            pages.append({"url": url, "requested": False, "refused": str(e)})
            if e.everything:
                halted = str(e)
                break
            continue
        if requested:
            sleeper(policy.sleep())
        requested += 1
        try:
            status, body = fetch(url)
        except Exception as e:                    # an error is not a page
            status, body = None, ""
            error = f"{type(e).__name__}: {e}"
        else:
            error = None
        body = body if isinstance(body, str) else ""
        entry = {"url": url, "requested": True, "http_status": status,
                 "fetched_at": _utc()}
        if status is not None and 200 <= status < 300 and body:
            raw = body.encode("utf-8")
            name = (f"{requested:02d}-"
                    f"{hashlib.sha256(url.encode('utf-8')).hexdigest()[:8]}"
                    ".html")
            out.mkdir(parents=True, exist_ok=True)
            (out / name).write_bytes(raw)
            entry.update(saved_as=name, bytes=len(raw),
                         sha256=hashlib.sha256(raw).hexdigest())
            pages.append(entry)
            continue
        entry["not_returned"] = (error or
                                 ("empty body" if status and 200 <= status < 300
                                  else f"http {status}"))
        pages.append(entry)
        halted = (f"{url} did not return ({entry['not_returned']}); stopped. "
                  "Nothing was retried and nothing about how we ask was "
                  "changed: this is the source's answer, recorded as such.")
        break

    saved = sum(1 for p in pages if p.get("saved_as"))
    manifest = {
        "tool": "scripts/page_probe.py", "source": source,
        "origin": origin, "user_agent": policy.user_agent,
        "started_at": started, "finished_at": _utc(),
        "robots": gate.record, "robots_line": describe(gate.record),
        "pages": pages, "halted": halted,
    }
    out.mkdir(parents=True, exist_ok=True)
    (out / "probe.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return ProbeResult(manifest, 0 if (saved and not halted) else 1, out)


# ---------------------------------------------------------------------------
# The skeleton: the shape of a page, with nothing in it that is a person's
# ---------------------------------------------------------------------------

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input",
                   "link", "meta", "param", "source", "track", "wbr"})
_SKIPPED_TEXT = frozenset({"script", "style"})
_TEXT_CAP = 40
_MAX_LINES = 400
_MAX_DEPTH = 16


def _mask_digits(s: str) -> str:
    """Every digit of any script becomes «#», and a run of them one «#»."""
    s = re.sub(r"\d", "#", s)
    return re.sub(r"#(?:[\s,٬.٫،/:-]*#)+", "#", s)


def _mask_token(s: str) -> str:
    """A long run of Latin letters, digits and dashes that holds a digit (a
    listing token, an id, a hash) becomes «<tok>», and then every digit left
    becomes «#». The runs are found first: masking the digits first cuts a
    token into pieces too short to be found. A word with a dash and no digit
    (a data-testid like post-card) is structure and stays."""
    return _mask_digits(re.sub(
        r"[A-Za-z0-9_-]{8,}",
        lambda m: "<tok>" if re.search(r"\d", m.group(0)) else m.group(0), s))


def _mask_text(s: str) -> str:
    s = _mask_token(re.sub(r"\s+", " ", s).strip())
    return s if len(s) <= _TEXT_CAP else s[:_TEXT_CAP] + "…"


def _show_text(s: str, with_text: bool) -> str:
    return _mask_text(s) if with_text else "…"


def _mask_href(h: str) -> str:
    """The path of a link, tokens masked, and no query. A link that is not
    http(s) (tel:, mailto:, sms:, javascript:) is its scheme and nothing
    after it."""
    scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", h.strip())
    if scheme and scheme.group(1).lower() not in ("http", "https"):
        return scheme.group(1).lower() + ":…"
    h = re.sub(r"^https?://[^/]+", "", h.split("#", 1)[0].split("?", 1)[0])
    return _mask_token(h) or "/"


class _Node:
    __slots__ = ("tag", "attrs", "kids")

    def __init__(self, tag: str, attrs: dict[str, str | None]):
        self.tag, self.attrs, self.kids = tag, attrs, []


class _Tree(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]
        self._quiet = 0

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs))
        self.stack[-1].kids.append(node)
        if tag not in _VOID:
            self.stack.append(node)
            if tag in _SKIPPED_TEXT:
                self._quiet += 1

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(_Node(tag, dict(attrs)))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                for gone in self.stack[i:]:
                    if gone.tag in _SKIPPED_TEXT:
                        self._quiet -= 1
                del self.stack[i:]
                return

    def handle_data(self, data):
        if not self._quiet and data.strip():
            self.stack[-1].kids.append(data)


def _classes(n: _Node) -> list[str]:
    return sorted((n.attrs.get("class") or "").split())


def _shape(n) -> str:
    """What makes two siblings 'the same row': tag, classes and, recursively,
    the shape of what they hold. Text counts as present, never as itself."""
    if isinstance(n, str):
        return "t"
    # a digit in a class (c-1, c-2) does not make two cards different rows,
    # and the kind of a link (/v/<tok>, tel:, mailto:) does
    href = _mask_href(n.attrs["href"]) if n.attrs.get("href") else ""
    return (n.tag + "." + re.sub(r"\d+", "#", ".".join(_classes(n)))
            + "@" + href + "("
            + ",".join(_shape(k) for k in n.kids) + ")")


def _label(n: _Node, with_text: bool = True) -> str:
    out = [n.tag]
    if n.attrs.get("id"):
        out.append("#" + _mask_token(n.attrs["id"]))
    out.extend("." + c for c in _classes(n))
    for k in sorted(n.attrs):
        v = n.attrs[k]
        if k in ("id", "class", "style"):
            continue
        if k == "href" and v:
            out.append(f"[href={_mask_href(v)}]")
        elif k in ("src", "srcset", "data-src"):
            out.append(f"[{k}=…{Path(re.sub(r'[?#].*', '', v or '')).suffix}]")
        elif k.startswith("data-") or k.startswith("aria-") or k in (
                "role", "type", "rel", "name", "itemprop", "itemtype"):
            out.append(f"[{k}={_show_text(v, with_text)}]" if v else f"[{k}]")
        else:
            out.append(f"[{k}]")
    return " ".join(out)


def skeleton(page: str, *, name: str = "", with_text: bool = True) -> str:
    """The shape of `page`: see the module docstring. Deterministic."""
    tree = _Tree()
    tree.feed(page)
    tree.close()
    lines: list[str] = []
    links: Counter = Counter()

    def walk(n, depth: int):
        kids, i = n.kids, 0
        while i < len(kids):
            k = kids[i]
            j = i + 1
            if isinstance(k, str):
                lines.append("  " * depth + '"' + _show_text(k, with_text) + '"')
                i = j
                continue
            sig = _shape(k)
            while (j < len(kids) and not isinstance(kids[j], str)
                   and _shape(kids[j]) == sig):
                j += 1
            reps = f"  ×{j - i}" if j - i > 1 else ""
            lines.append("  " * depth + _label(k, with_text) + reps)
            if depth + 1 < _MAX_DEPTH:
                walk(k, depth + 1)
            elif k.kids:
                lines.append("  " * (depth + 1) + "…")
            i = j

    walk(tree.root, 0)

    # links inside collapsed rows are shown once, so the table counts the
    # whole page
    def count_links(n):
        for k in n.kids:
            if isinstance(k, str):
                continue
            if k.tag == "a" and k.attrs.get("href"):
                links[_mask_href(k.attrs["href"])] += 1
            count_links(k)

    count_links(tree.root)
    head = [f"# skeleton of {name or 'a page'}: {len(page.encode('utf-8'))} "
            f"bytes, sha256 {hashlib.sha256(page.encode('utf-8')).hexdigest()}",
            "# links by masked path (count):"]
    head += [f"#   {p}  ({c})" for p, c in links.most_common(12)]
    body = lines[:_MAX_LINES]
    if len(lines) > _MAX_LINES:
        body.append(f"… {len(lines) - _MAX_LINES} more lines")
    return "\n".join(head + ["# tree:"] + body) + "\n"


# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--skeleton", nargs="+", type=Path, metavar="FILE",
                    help="print the shape of saved pages and exit; no network")
    ap.add_argument("--source", help="a short name, e.g. divar, sheypoor")
    ap.add_argument("--origin", help="e.g. https://divar.ir")
    ap.add_argument("--url", action="append", default=[],
                    help=f"a page to request, at most {MAX_URLS}, repeatable")
    ap.add_argument("--render", choices=["http", "browser"], default="http",
                    help="http for a server-rendered page, browser for one "
                         "rendered client-side (default: http)")
    ap.add_argument("--no-text", action="store_true",
                    help="with --skeleton: leave every text out of it")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"where runs are kept (default: {DEFAULT_OUT})")
    args = ap.parse_args(argv)

    if args.skeleton:
        for f in args.skeleton:
            print(skeleton(f.read_text(encoding="utf-8", errors="replace"),
                           name=f.name, with_text=not args.no_text))
        return 0
    if not (args.source and args.origin and args.url):
        ap.error("--source, --origin and at least one --url are needed "
                 "(or --skeleton FILE)")

    policy = PolitenessPolicy()
    if args.render == "browser":
        try:
            import playwright.sync_api                      # noqa: F401, PLC0415
        except ImportError:
            print("playwright is not installed. In your venv:\n"
                  "  pip install playwright && playwright install chromium",
                  file=sys.stderr)
            return 2
        fetch = playwright_fetcher(policy)
    else:
        fetch = http_fetcher(policy)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    try:
        res = probe(args.origin, args.url, source=args.source, fetch=fetch,
                    robots_fetch=http_fetcher(policy),
                    out_dir=args.out / f"{stamp}-{args.source}", policy=policy)
    except ProbeRefused as e:
        print(f"refused: {e}", file=sys.stderr)
        return 2

    m = res.manifest
    print(f"robots.txt  {m['robots_line']}")
    for p in m["pages"]:
        if not p["requested"]:
            print(f"  not requested  {p['url']}\n    {p['refused']}")
        elif p.get("saved_as"):
            print(f"  http {p['http_status']}  {p['bytes']:>8} bytes  "
                  f"{p['saved_as']}  {p['url']}")
        else:
            print(f"  http {p['http_status']}  NOT RETURNED  {p['url']}")
    if m["halted"]:
        print(f"\nHALTED: {m['halted']}", file=sys.stderr)
    print(f"\nkept in {res.out_dir}  (outside the repository; not to be "
          "committed or published)")
    if any(p.get("saved_as") for p in m["pages"]):
        first = next(p["saved_as"] for p in m["pages"] if p.get("saved_as"))
        print("what can be sent to have a parser written (read it first; "
              "add --no-text to leave the text out):\n"
              f"  python3 scripts/page_probe.py --skeleton "
              f"{res.out_dir / first}")
    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
