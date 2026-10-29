#!/usr/bin/env python3
"""
A few public pages of one source, fetched politely and kept on this machine.

    python3 scripts/page_probe.py --source divar --origin https://divar.ir \\
        --url https://divar.ir/s/tehran/car
    python3 scripts/page_probe.py --skeleton ~/caro-probes/<run>/01-3f9a1c2e.html
    python3 scripts/page_probe.py --rows     ~/caro-probes/<run>/01-3f9a1c2e.html
    python3 scripts/page_probe.py --scripts  ~/caro-probes/<run>/01-3f9a1c2e.html
    python3 scripts/page_probe.py --survey   ~/caro-probes/<run>/01-3f9a1c2e.html
    python3 scripts/page_probe.py --around /v/ ~/caro-probes/<run>/01-3f9a1c2e.html

For a page the browser fills in after it loads (a table of rows that is only
skeletons in the HTML), `--render browser --wait 8` gives it eight seconds
rather than one and a half. A Next.js page keeps its data in
`self.__next_f.push(...)` scripts; the survey reads them (its "data lists").

`--survey` is the one to send: the links, how the page paginates, the repeated
groups, the shape of the JSON and the categories in it (a currency, a unit, a
brand, a city, with counts), in one answer. The other three were what Divar
took, one round trip each, and a fourth to learn what the short strings said.
A number is printed as a category if it is a boolean or under 100, and as a
summary (how many, how many different, the smallest, the middle, the largest,
how many zeros) if its name says it is a quantity of a car: price, mileage,
year, views. That is how a price's unit is read (Khodro45 gave `price: int`).
Nothing under a person's name (phone, mobile, seller, owner, user, contact,
mail, address) is printed, whatever it holds.

A page whose cards differ one from another, so that `--rows` finds none
(Sheypoor), is read with `--around /v/ FILE`: the markup around the links
whose path starts with that, `--up N` levels above (3), the first two printed
in full, with the count of links and of different shapes. A page whose menu
has such links too (Khodro45's) needs `--show 6` to reach the cards.

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

TWO VIEWS THAT GO TO THE POINT

The first real page (Divar's car category, 816,689 bytes) showed what the
skeleton is bad at: its first 400 lines were the menu and the filters, and the
listings, if they were in the page at all, were past them. So:

  `--rows FILE` finds the groups of three or more siblings of one shape (the
  cards of a list are the largest of them), ranks them by how much page they
  take, and prints ONE instance of each in full, with where it sits. A group
  inside one already shown is not shown again.

  `--scripts FILE` is for a page that carries its data in a script instead of
  in the markup: for each script of any size that holds JSON (bare, after an
  assignment, or inside JSON.parse("...")) it prints the SHAPE of the JSON:
  the names of the keys, the length of each list, and the kind of each value
  (int, str, url, digits(n), fa-text ...). A value is never printed.
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


def _is_token(run: str, *, strict: bool = False) -> bool:
    """A run of eight or more Latin letters, digits and dashes that holds a
    digit is an id and not a word: post-card and buy-apartment are words.
    `strict`, for the path of a link, also takes a run that holds both an upper
    and a lower case letter (AbCdEfGh: about one listing token in four has no
    digit at all). Elsewhere that is a camelCase name, itemListElement, and
    it is structure."""
    return bool(re.search(r"\d", run)
                or (strict and re.search(r"[a-z]", run)
                    and re.search(r"[A-Z]", run)))


def _mask_token(s: str, *, strict: bool = False) -> str:
    """An id-like run (see `_is_token`) becomes «<tok>», and then every digit
    left becomes «#». The runs are found first: masking the digits first cuts
    a token into pieces too short to be found."""
    return _mask_digits(re.sub(
        r"[A-Za-z0-9_-]{8,}",
        lambda m: "<tok>" if _is_token(m.group(0), strict=strict)
        else m.group(0), s))


def _mask_key(k: str) -> str:
    """A JSON key: a camelCase or snake_case name is the schema and stays; a
    run of digits or a long hex id is data used as a key and does not."""
    if re.fullmatch(r"[0-9a-fA-F-]{8,}|\d+", k) or re.search(r"\d{4,}", k):
        return "<tok>" if len(k) >= 8 else "#"
    return _mask_digits(k)


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
    return _mask_token(h, strict=True) or "/"


def _path_of(h: str) -> str:
    """The path of an http(s) or relative link, no host, no query, no fragment.
    A tel: or mailto: link has no path that starts with «/»."""
    return re.sub(r"^https?://[^/]+", "", h.strip().split("#", 1)[0].split("?", 1)[0])


def _url_shape(u: str) -> str:
    """A link as its masked path and the NAMES of its query parameters, each
    with its value if that is one to three digits (a page number) or a
    lowercase word of up to twelve letters, and `…` if it is anything else."""
    scheme = re.match(r"^([A-Za-z][A-Za-z0-9+.-]*):", u.strip())
    if scheme and scheme.group(1).lower() not in ("http", "https"):
        return scheme.group(1).lower() + ":…"
    query = u.strip().split("#", 1)[0].partition("?")[2]
    pairs = []
    for pair in query.split("&"):
        k, _, val = pair.partition("=")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\[\]-]{0,24}", k):
            keep = re.fullmatch(r"\d{1,3}|[a-z]{1,12}", val)
            pairs.append(f"{k}={val if keep else '…'}")
    return (_mask_token(_path_of(u), strict=True) or "/") \
        + ("?" + "&".join(pairs) if pairs else "")


def _href_kind(h: str) -> str:
    """/v for /v/<slug>/<token>, / for the home page, tel:… for a phone link."""
    masked = _mask_href(h)
    return "/" + masked[1:].split("/")[0] if masked.startswith("/") else masked


class _Node:
    __slots__ = ("tag", "attrs", "kids", "parent", "text")

    def __init__(self, tag: str, attrs: dict[str, str | None], parent=None):
        self.tag, self.attrs, self.kids = tag, attrs, []
        self.parent, self.text = parent, ""


class _Tree(html.parser.HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.stack = [self.root]
        self._quiet = 0

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.stack[-1])
        self.stack[-1].kids.append(node)
        if tag not in _VOID:
            self.stack.append(node)
            if tag in _SKIPPED_TEXT:
                self._quiet += 1

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].kids.append(_Node(tag, dict(attrs), self.stack[-1]))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                for gone in self.stack[i:]:
                    if gone.tag in _SKIPPED_TEXT:
                        self._quiet -= 1
                del self.stack[i:]
                return

    def handle_data(self, data):
        if self._quiet:
            if self.stack[-1].tag == "script":      # kept for --scripts only
                self.stack[-1].text += data
            return
        if data.strip():
            self.stack[-1].kids.append(data)


def _classes(n: _Node) -> list[str]:
    return sorted((n.attrs.get("class") or "").split())


def _shape(n) -> str:
    """What makes two siblings 'the same row': tag, classes and, recursively,
    the shape of what they hold. Text counts as present, never as itself."""
    if isinstance(n, str):
        return "t"
    # a digit in a class (c-1, c-2) does not make two cards different rows,
    # and the kind of a link (/v, tel:, mailto:) does. The kind is the scheme
    # or the first segment of the path and no more: the rest of a listing's
    # path is its own, and a card whose token happened to hold a letter in
    # place of a digit would be a row of its own.
    href = _href_kind(n.attrs["href"]) if n.attrs.get("href") else ""
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


def _walk(n, depth: int, lines: list[str], with_text: bool,
          max_depth: int = _MAX_DEPTH) -> None:
    """The children of `n`, one line each, a run of siblings of one shape as
    its first with the count."""
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
        if depth + 1 < max_depth:
            _walk(k, depth + 1, lines, with_text, max_depth)
        elif k.kids:
            lines.append("  " * (depth + 1) + "…")
        i = j


def _parse(page: str) -> _Tree:
    tree = _Tree()
    tree.feed(page)
    tree.close()
    return tree


def _link_table(paths: Counter) -> list[str]:
    """Link paths by count. A first segment that holds more than five distinct
    paths (/v/<slug>/<token>: one per listing) is one row, `/v/<…>`, with the
    total, so that a list of listings is not lost behind twelve rows of
    categories that occur once each."""
    by_first: dict[str, set] = {}
    for p in paths:
        by_first.setdefault(p.split("/")[1] if p.startswith("/") else p, set()).add(p)
    wide = {f for f, ps in by_first.items() if len(ps) > 5}
    folded: Counter = Counter()
    for p, c in paths.items():
        first = p.split("/")[1] if p.startswith("/") else p
        folded[f"/{first}/<…>" if first in wide else p] += c
    return [f"#   {p}  ({c})" for p, c in folded.most_common(12)]


def skeleton(page: str, *, name: str = "", with_text: bool = True) -> str:
    """The shape of `page`: see the module docstring. Deterministic."""
    tree = _parse(page)
    lines: list[str] = []
    links: Counter = Counter()
    _walk(tree.root, 0, lines, with_text)

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
    head += _link_table(links)
    body = lines[:_MAX_LINES]
    if len(lines) > _MAX_LINES:
        body.append(f"… {len(lines) - _MAX_LINES} more lines")
    return "\n".join(head + ["# tree:"] + body) + "\n"


# ---------------------------------------------------------------------------
# Rows: the cards of a list, found rather than scrolled to
# ---------------------------------------------------------------------------

_ROW_MIN = 3
_ROW_LINES = 150


def _where(n: _Node) -> str:
    """Where a node sits: its last six ancestors as tag#id.first-class."""
    parts = []
    while n is not None and n.tag != "#root":
        c = _classes(n)
        parts.append(n.tag + ("#" + _mask_token(n.attrs["id"])
                              if n.attrs.get("id") else "")
                     + ("." + c[0] if c else ""))
        n = n.parent
    return " > ".join(reversed(parts[:6])) or "(top)"


def rows(page: str, *, name: str = "", with_text: bool = True,
         top: int = 4) -> str:
    """The `top` largest groups of three or more siblings of one shape, each
    as one instance printed in full. Largest is count times elements in one."""
    tree = _parse(page)
    sizes: dict[int, int] = {}

    def size(n) -> int:
        if id(n) not in sizes:
            sizes[id(n)] = 1 + sum(size(k) for k in n.kids
                                   if not isinstance(k, str))
        return sizes[id(n)]

    found: list[tuple] = []

    def visit(n):
        kids, i = n.kids, 0
        while i < len(kids):
            if isinstance(kids[i], str):
                i += 1
                continue
            sig, j = _shape(kids[i]), i + 1
            while (j < len(kids) and not isinstance(kids[j], str)
                   and _shape(kids[j]) == sig):
                j += 1
            if j - i >= _ROW_MIN and size(kids[i]) >= 2:
                found.append(((j - i) * size(kids[i]), j - i, size(kids[i]),
                              n, kids[i:j]))
            i = j
        for k in kids:
            if not isinstance(k, str):
                visit(k)

    visit(tree.root)
    found.sort(key=lambda f: (-f[0], -f[1]))
    shown: list[tuple] = []
    inside: set[int] = set()
    for score, count, one, parent, run in found:
        a, nested = parent, False
        while a is not None:
            if id(a) in inside:
                nested = True
                break
            a = a.parent
        if nested:
            continue
        shown.append((count, one, parent, run))
        for r in run:
            stack = [r]
            while stack:
                x = stack.pop()
                inside.add(id(x))
                stack.extend(k for k in x.kids if not isinstance(k, str))
        if len(shown) == top:
            break
    out = [f"# rows of {name or 'a page'}: groups of {_ROW_MIN} or more "
           f"siblings of one shape, largest first, one instance of each"]
    if not shown:
        out.append("# none found")
    for count, one, parent, run in shown:
        out.append(f"# ×{count}, about {one} elements each, under: "
                   f"{_where(parent)}")
        lines: list[str] = []
        lines.append(_label(run[0], with_text))
        _walk(run[0], 1, lines, with_text)
        out.extend(lines[:_ROW_LINES])
        if len(lines) > _ROW_LINES:
            out.append(f"… {len(lines) - _ROW_LINES} more lines")
        out.append("")
    return "\n".join(out) + "\n"


_AROUND_SHOWN = 2
_AROUND_SHOW_MAX = 6
_AROUND_UP_MAX = 8


def around(page: str, prefix: str, *, up: int = 3, name: str = "",
           with_text: bool = True, show: int = _AROUND_SHOWN) -> str:
    """The markup around the links whose path starts with `prefix`: how many
    there are, how many different parents they have `up` levels above, and the
    first two parents printed as `rows` prints a row. For a page whose cards
    differ one from another, so that no three siblings are of one shape and
    `rows` says "none found" (Sheypoor's, 2026-10-29). `show` parents are
    printed: the first ones, which on a page with a menu full of such links
    (Khodro45's) may be the menu's and not a card."""
    tree = _parse(page)
    anchors: list[_Node] = []

    def find(n):
        for k in n.kids:
            if isinstance(k, str):
                continue
            if (k.tag == "a" and k.attrs.get("href")
                    and _path_of(k.attrs["href"]).startswith(prefix)):
                anchors.append(k)
            find(k)

    find(tree.root)
    parents: list[_Node] = []
    seen: set[int] = set()
    for a in anchors:
        n = a
        for _ in range(up):
            if n.parent is not None and n.parent.tag != "#root":
                n = n.parent
        if id(n) not in seen:
            seen.add(id(n))
            parents.append(n)
    shapes = len({_shape(n) for n in parents})
    out = [f"# around links starting with {prefix!r} in {name or 'a page'}: "
           f"{len(anchors)} link(s), {len(parents)} different parent(s) {up} "
           f"level(s) up, {shapes} different shape(s) among them"]
    if not anchors:
        out.append("# none found")
    for i, n in enumerate(parents[:show], 1):
        out.append(f"# parent {i}, under: {_where(n.parent) if n.parent else '(top)'}")
        lines = [_label(n, with_text)]
        _walk(n, 1, lines, with_text)
        out.extend(lines[:_ROW_LINES])
        if len(lines) > _ROW_LINES:
            out.append(f"… {len(lines) - _ROW_LINES} more lines")
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Scripts: the shape of the JSON a page carries, and never a value
# ---------------------------------------------------------------------------

_SCRIPT_MIN = 300
_JSON_LINES = 120


def _json_of(text: str):
    """The JSON in a script, or None: bare, after `window.X =`, or inside
    JSON.parse("...")."""
    t = text.strip()
    try:
        return json.loads(t)
    except ValueError:
        pass
    m = re.match(r"^[\w.$\[\]\"'-]+\s*=\s*(.*?);?\s*$", t, re.S)
    if not m:
        return None
    body = m.group(1)
    try:
        return json.loads(body)
    except ValueError:
        pass
    q = re.fullmatch(r"JSON\.parse\((\".*\")\)", body, re.S)
    if q:
        try:
            return json.loads(json.loads(q.group(1)))
        except ValueError:
            return None
    return None


def _jkind(v) -> str:
    """What a value is, and nothing of what it says."""
    if isinstance(v, dict):
        return "object"
    if isinstance(v, list):
        return "list"
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "int"
    if isinstance(v, float):
        return "float"
    if v is None:
        return "null"
    if isinstance(v, str):
        if re.fullmatch(r"https?://\S+", v):
            return "url"
        if re.fullmatch(r"\d+", v):
            return f"digits({len(v)})"
        if re.search(r"[\u0600-\u06ff]", v):
            return "fa-text"
        return "str"
    return type(v).__name__


def _jlines(v, name: str, depth: int, out: list[str]) -> None:
    pad = "  " * depth
    if depth > 9:
        out.append(f"{pad}{name}: …")
    elif isinstance(v, dict):
        out.append(f"{pad}{name}: object ({len(v)} keys)")
        items = list(v.items())
        if len(items) > 30 and len({_jkind(x) for _, x in items[:30]}) == 1:
            out.append(f"{pad}  <{len(items)} keys such as "
                       f"{_mask_key(str(items[0][0]))!r}>:")
            _jlines(items[0][1], "value", depth + 2, out)
            return
        for k, x in items[:40]:
            _jlines(x, _mask_key(str(k)), depth + 1, out)
        if len(items) > 40:
            out.append(f"{pad}  … {len(items) - 40} more keys")
    elif isinstance(v, list):
        out.append(f"{pad}{name}: list of {len(v)}")
        if v:
            _jlines(v[0], "[0]", depth + 1, out)
    else:
        out.append(f"{pad}{name}: {_jkind(v)}")


def scripts_report(page: str, *, name: str = "") -> str:
    tree = _parse(page)
    scripts: list[_Node] = []

    def find(n):
        for k in n.kids:
            if isinstance(k, str):
                continue
            if k.tag == "script":
                scripts.append(k)
            find(k)

    find(tree.root)
    out = [f"# scripts of {name or 'a page'}: {len(scripts)} script tag(s), "
           f"{sum(1 for s in scripts if s.attrs.get('src'))} external; the "
           f"shape of the JSON in each inline one of {_SCRIPT_MIN} characters "
           "or more, and no value"]
    pushes = [sc.text for sc in scripts if not sc.attrs.get("src")]
    rows_, n_push, size_push = rsc_rows(pushes)
    if n_push:
        out.append(f"# Next.js data stream (self.__next_f.push): {n_push} script(s), "
                   f"{size_push} characters, {len(rows_)} JSON row(s); its lists of "
                   "objects are in the survey's data lists")
    for i, sc in enumerate(scripts, 1):
        if sc.attrs.get("src") or len(sc.text) < _SCRIPT_MIN:
            continue
        if _RSC_PUSH.match(sc.text):
            continue
        tags = " ".join(f"[{k}={_mask_text(v)}]" if v else f"[{k}]"
                        for k, v in sorted(sc.attrs.items()))
        data = _json_of(sc.text)
        if data is None:
            out.append(f"# script {i} {tags} {len(sc.text)} characters: not "
                       f"JSON; begins {_mask_text(sc.text.strip()[:60])!r}")
            continue
        out.append(f"# script {i} {tags} {len(sc.text)} characters: JSON")
        lines: list[str] = []
        _jlines(data, "(root)", 0, lines)
        out.extend(lines[:_JSON_LINES])
        if len(lines) > _JSON_LINES:
            out.append(f"… {len(lines) - _JSON_LINES} more lines")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# Survey: the three views and the two that were missing, in one answer
# ---------------------------------------------------------------------------
#
# Divar took three round trips -- the skeleton, the rows, the scripts -- and a
# fourth to learn what the short strings in the JSON said (`IRR`, `KMT`, the
# damage slugs, the brands). A survey is one command that prints all of it, so
# a page of a source nobody has read yet (Sheypoor, Khodro45, Divar's page 2)
# costs one probe and one survey.

_VALUE_DISTINCT = 12
_VALUE_MIN = 3
_VALUE_PATHS = 60
_VALUE_MAX_LEN = 40
_VALUE_MAX_DIGITS = 4
# A path with one of these in it never has a value printed: a person's field.
_PRIVATE = re.compile(r"phone|tel\b|mobile|mail|address|seller|owner|user|"
                      r"contact|person|author|(?<![a-z])name$", re.I)
# Persian text is printed only under a key that names a kind of thing.
_KIND = re.compile(r"city|district|neighbo|province|state|category|brand|model|"
                   r"color|colour|gear|fuel|body|type|condition|status|unit|"
                   r"currency|availability|damage|transmission", re.I)


def _short_value(v) -> str | None:
    """A string that may be printed as a category, or None. At most 40
    characters, no «@», and at most four digits in all."""
    if not isinstance(v, str):
        return None
    v = v.strip()
    if (not v or len(v) > _VALUE_MAX_LEN or "@" in v
            or sum(c.isdigit() for c in v) > _VALUE_MAX_DIGITS):
        return None
    return v


# A boolean and an integer under 100 are categories as a short string is
# (`price_type: 1`, `active: true`); a bigger number is a quantity, and a
# quantity prints as a summary (min, median, max), and only under a name that
# says it is a quantity of a car. The first survey of Khodro45 could not tell
# a price's unit from `price: int` (2026-10-29).
_SMALL_INT = 100
# The name is split into words (final_price, finalPrice) and a word has to be
# one of these: `image`, `page`, `message` and `generate` hold «age» and
# «rate» and are not quantities.
_QUANTITY_WORD = re.compile(
    r"(?:price|amount|deposit|installment|discount|mileage|odometer|kilomet|"
    r"views|total|count|capacity)\w*|(?:cost|fee|km|klm|year|age|power|size|"
    r"rate|view)s?", re.I)


def _is_quantity_name(name: str) -> bool:
    words = re.split(r"[^a-z]+", re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower())
    return any(_QUANTITY_WORD.fullmatch(w) for w in words if w)
_DIGIT_STRING_MAX = 15


def _category_of(v) -> str | None:
    """The text a value is counted under, or None: a short string, a boolean
    (`true`), a small integer, or null."""
    if v is None:
        return "null"
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v) if abs(v) < _SMALL_INT else None
    return _short_value(v)


def _quantity_of(v) -> float | None:
    """A number, or a string of up to 15 digits, as a number; else None."""
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if isinstance(v, str) and re.fullmatch(r"\d{1,%d}" % _DIGIT_STRING_MAX, v.strip()):
        return float(v.strip())
    return None


def _collect(v, path: str, out: dict, budget: list, nums: dict | None = None) -> None:
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(v, dict):
        for k, x in v.items():
            _collect(x, f"{path}.{_mask_key(str(k))}" if path else _mask_key(str(k)),
                     out, budget, nums)
    elif isinstance(v, list):
        for x in v:
            _collect(x, f"{path}[]", out, budget, nums)
    else:
        sv = _category_of(v)
        if sv is not None:
            out.setdefault(path, Counter())[sv] += 1
        else:
            out.setdefault(path, Counter())      # seen, not a category
        if nums is not None:
            q = _quantity_of(v)
            if q is not None:
                nums.setdefault(path, []).append(q)


# A Next.js page (the App Router) carries its data in scripts of the form
# `self.__next_f.push([1,"<a JS string>"])`: React Server Component rows, one
# `id:json` per line once the strings are joined. That is where the listings of
# a server-rendered Next.js list are, and `_json_of` sees "not JSON" in it.
_RSC_PUSH = re.compile(
    r'^\s*self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*(".*")\s*\]\s*\)\s*;?\s*$', re.S)
_RSC_ROW = re.compile(r"^[0-9A-Za-z]+:([\[{].*)$")


def rsc_rows(script_texts: list[str]) -> tuple[list, int, int]:
    """(parsed JSON rows, scripts that were pushes, characters in them)."""
    chunks, n, size = [], 0, 0
    for t in script_texts:
        m = _RSC_PUSH.match(t)
        if not m:
            continue
        n += 1
        size += len(t)
        try:
            chunks.append(json.loads(m.group(1)))
        except ValueError:
            continue
    rows = []
    for line in "".join(c for c in chunks if isinstance(c, str)).split("\n"):
        m = _RSC_ROW.match(line)
        if m:
            try:
                rows.append(json.loads(m.group(1)))
            except ValueError:
                pass
    return rows, n, size


def _inline_scripts(page: str) -> list:
    tree = _parse(page)
    scripts: list = []

    def find(n):
        for k in n.kids:
            if isinstance(k, str):
                continue
            if k.tag == "script":
                scripts.append(k)
            find(k)

    find(tree.root)
    return scripts


_LIST_TOP = 5
_LIST_ITEM_LINES = 60


def _row_lists(v, path: str, out: list, depth: int = 0, beside: dict | None = None) -> None:
    """Lists of three or more objects that share at least three keys, each
    with the other keys of the object that holds it (`beside`: a page's
    count, the link to the next page)."""
    if depth > 40:
        return
    if isinstance(v, list):
        dicts = [x for x in v if isinstance(x, dict)]
        if len(dicts) >= 3 and len(dicts) >= 0.8 * len(v):
            common = frozenset.intersection(*(frozenset(d) for d in dicts))
            if len(common) >= 3:
                out.append((path or "(root)", dicts, len(common), beside or {}))
        for x in v[:300]:
            if isinstance(x, (list, dict)):
                _row_lists(x, f"{path}[]", out, depth + 1)
    elif isinstance(v, dict):
        for k, x in v.items():
            if isinstance(x, (list, dict)):
                _row_lists(x, f"{path}.{_mask_key(str(k))}" if path else _mask_key(str(k)),
                           out, depth + 1,
                           {a: b for a, b in v.items() if b is not x})


def _shown_numbers(nums: dict) -> list:
    """The (path, n, distinct, min, median, max, zero) that may be printed: a
    path whose last name is a quantity of a car, that is not a person's path,
    with three numbers or more. `id`, `token` and `number` are not in the
    names, and a private path prints none whatever its name."""
    shown = []
    for path, xs in nums.items():
        last = re.sub(r"(\[\])+$", "", path).rsplit(".", 1)[-1]
        if (len(xs) < _VALUE_MIN or _PRIVATE.search(path)
                or not _is_quantity_name(last)):
            continue
        xs = sorted(xs)
        shown.append((path, len(xs), len(set(xs)), xs[0], xs[len(xs) // 2],
                      xs[-1], sum(1 for x in xs if x == 0)))
    shown.sort(key=lambda t: (-t[1], t[0]))
    return shown


def _number_line(t: tuple) -> str:
    path, n, distinct, lo, mid, hi, zero = t
    return (f"{path}: n={n} distinct={distinct} min={lo:.15g} "
            f"median={mid:.15g} max={hi:.15g} zero={zero}")


def _shown_values(paths: dict) -> list:
    """The (total, path, [(value, count)]) that may be printed. See values_report."""
    shown = []
    for path, c in paths.items():
        total = sum(c.values())
        if re.fullmatch(r"rsc(\[\])*", path):        # the tag names of React elements
            continue
        # A category repeats: a path whose values are each used about once is
        # an id, a title or a slug, one per item, and prints none. The first
        # version counted uses in all, and a list of five cars printed its
        # five ids (found by a row of the tests, 2026-10-29).
        if (not c or len(c) > _VALUE_DISTINCT or total < _VALUE_MIN
                or total < 2 * len(c)
                or (_PRIVATE.search(path) and not path.endswith("brand.name"))):
            continue
        vals = [(v, n) for v, n in c.most_common()
                if re.search(r"[\u0600-\u06ff]", v) is None
                or _KIND.search(path.rsplit(".", 1)[-1])]
        if vals:
            shown.append((total, path, vals))
    shown.sort(key=lambda t: (-t[0], t[1]))
    return shown


_BESIDE_KEYS = 12
_BESIDE_INT = 1_000_000
_LINK_KEY = re.compile(r"^(next|prev|previous)(_?page|_?url|_?link)?$", re.I)


def _beside_lines(d: dict, path: str, depth: int = 0) -> list[str]:
    """The keys beside a list, as a shape. A boolean, a null and an integer
    under a million show their value (a total, a page number); the link to the
    next or the previous page shows as its path and the names of its
    parameters; no other string shows more than its kind."""
    out: list[str] = []
    pad = "  " * depth
    for k, x in list(d.items())[:_BESIDE_KEYS]:
        key = _mask_key(str(k))
        here = f"{path}.{key}"
        if isinstance(x, dict):
            out.append(f"{pad}{key}: object ({len(x)} keys)")
            if depth < 1:
                out.extend(_beside_lines(x, here, depth + 1))
        elif isinstance(x, list):
            out.append(f"{pad}{key}: list of {len(x)}")
            if x and depth < 1 and isinstance(x[0], dict):
                out.extend(_beside_lines(x[0], here + "[]", depth + 1))
            elif x and depth < 1 and not isinstance(x[0], list):
                out.append(f"{pad}  [0]: " + _beside_scalar(x[0], here + "[]", key))
        else:
            out.append(f"{pad}{key}: " + _beside_scalar(x, here, key))
    if len(d) > _BESIDE_KEYS:
        out.append(f"{pad}… {len(d) - _BESIDE_KEYS} more keys")
    return out


def _beside_scalar(x, path: str, key: str) -> str:
    if _PRIVATE.search(path):
        return _jkind(x)
    if x is None or isinstance(x, bool):
        return _jkind(x) + " = " + json.dumps(x)
    if isinstance(x, int) and abs(x) < _BESIDE_INT:
        return f"int = {x}"
    if isinstance(x, str) and _LINK_KEY.match(key) and re.match(r"(https?://|/)", x):
        return "url = " + _url_shape(x)
    return _jkind(x)


def data_lists_report(page: str, *, name: str = "") -> str:
    """The lists of row-like objects in a page's JSON and RSC stream: where the
    listings are. Path, count, shared keys, the shape of the first object and
    the categories among them; no other value."""
    scripts = [s for s in _inline_scripts(page)
               if not s.attrs.get("src") and len(s.text) >= _SCRIPT_MIN]
    docs = []
    for sc in scripts:
        data = _json_of(sc.text)
        if data is not None:
            docs.append(("json", data))
    rows, _, _ = rsc_rows([s.text for s in scripts])
    docs += [("rsc", r) for r in rows]
    found: list = []
    for kind, d in docs:
        _row_lists(d, kind, found)
    # a list inside the items of a bigger one is the same data twice
    found.sort(key=lambda t: -(len(t[1]) * t[2]))   # (path, objects, shared, beside)
    out = [f"# data lists of {name or 'a page'}: lists of 3 or more objects that share "
           f"3 or more keys, in its JSON and its Next.js data stream (rsc); the "
           f"{_LIST_TOP} largest, with the shape of the first and its categories"]
    seen = set()
    for path, items, common, beside in found:
        sig = (len(items), common)
        if sig in seen:
            continue
        seen.add(sig)
        if len(seen) > _LIST_TOP:
            break
        out.append(f"## {path}: {len(items)} objects, {common} keys in common")
        if beside:
            out.append("  beside the list, in the object that holds it:")
            out.extend("    " + ln for ln in _beside_lines(beside, path))
        lines: list[str] = []
        _jlines(items[0], "[0]", 0, lines)
        out.extend("  " + ln for ln in lines[:_LIST_ITEM_LINES])
        if len(lines) > _LIST_ITEM_LINES:
            out.append(f"  … {len(lines) - _LIST_ITEM_LINES} more lines")
        paths: dict = {}
        nums: dict = {}
        budget = [50_000]
        for it in items:
            _collect(it, "", paths, budget, nums)
        vs = _shown_values(paths)
        if vs:
            out.append("  categories:")
            for _, p, vals in vs[:_VALUE_PATHS]:
                out.append(f"    {p}: " + "  ".join(f"{v}:{n}" for v, n in vals))
        ns = _shown_numbers(nums)
        if ns:
            out.append("  quantities (count, distinct, smallest, middle, largest, zeros):")
            for t in ns[:_VALUE_PATHS]:
                out.append("    " + _number_line(t))
    if len(out) == 1:
        out.append("  (none)")
    return "\n".join(out) + "\n"


def values_report(page: str, *, name: str = "") -> str:
    """The values of the JSON strings that can be categories, with counts.

    A path is printed only if it has at most 12 distinct values, each short,
    and each used twice on average (and 3 uses in all): a currency, a unit, a
    brand, a city. A value used once in a path of values used once is an id.
    Ids, titles, prices and addresses have many values and print none. A path
    named for a person (phone, mail, seller, owner, user, contact, name) never
    prints one, and a Persian text only under a key that names a kind of thing.
    """
    scripts = [s for s in _inline_scripts(page)
               if not s.attrs.get("src") and len(s.text) >= _SCRIPT_MIN]
    paths: dict = {}
    nums: dict = {}
    budget = [200_000]
    for sc in scripts:
        data = _json_of(sc.text)
        if data is not None:
            _collect(data, "", paths, budget, nums)
    for r in rsc_rows([sc.text for sc in scripts])[0]:
        _collect(r, "rsc", paths, budget, nums)
    shown = _shown_values(paths)
    out = [f"# values of {name or 'a page'}: JSON strings that are categories "
           f"(at most {_VALUE_DISTINCT} distinct, {_VALUE_MIN} or more uses; "
           "short, at most 4 digits, no person's field), with counts"]
    for total, path, vals in shown[:_VALUE_PATHS]:
        out.append(f"  {path}: " + "  ".join(f"{v}:{n}" for v, n in vals))
    if len(shown) > _VALUE_PATHS:
        out.append(f"… {len(shown) - _VALUE_PATHS} more paths")
    if not shown:
        out.append("  (none)")
    ns = _shown_numbers(nums)
    if ns:
        out.append("# quantities: numbers under a name that says it is a quantity "
                   "of a car (count, distinct, smallest, middle, largest, zeros)")
        for t in ns[:_VALUE_PATHS]:
            out.append("  " + _number_line(t))
    return "\n".join(out) + "\n"


def pagination_hints(page: str) -> str:
    """How a list says there is more of it: the names of the query parameters
    on its links (names only), and any rel=next or rel=prev."""
    names: Counter = Counter()
    rels: Counter = Counter()
    for href in re.findall(r"""href\s*=\s*["']([^"']*\?[^"']*)["']""", page):
        q = href.split("?", 1)[1].split("#", 1)[0]
        for pair in q.split("&"):
            k = pair.split("=", 1)[0]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_\[\]-]{0,24}", k):
                names[k] += 1
    for m in re.finditer(r"""rel\s*=\s*["']?(next|prev|previous)\b""", page, re.I):
        rels[m.group(1).lower()] += 1
    targets: list[str] = []
    for tag in re.finditer(r"<(?:link|a)\b[^>]*>", page, re.I):
        t = tag.group(0)
        rel = re.search(r"""rel\s*=\s*["']?(next|prev|previous)\b""", t, re.I)
        ref = re.search(r"""href\s*=\s*["']([^"']*)["']""", t, re.I)
        if rel and ref:
            line = f"{rel.group(1).lower()} -> {_url_shape(html.unescape(ref.group(1)))}"
            if line not in targets:
                targets.append(line)
    out = ["# pagination hints: query parameter names on links (count), and rel=next/prev"]
    out.append("  params: " + ("  ".join(f"{k}:{n}" for k, n in names.most_common(12))
                              if names else "(none)"))
    out.append("  rel: " + ("  ".join(f"{k}:{n}" for k, n in rels.most_common())
                            if rels else "(none)"))
    if targets:
        out.append("  rel targets (path, parameter names, a page number kept): "
                   + "  ".join(targets[:4]))
    return "\n".join(out) + "\n"


def survey(page: str, *, name: str = "") -> str:
    """Everything a parser needs to be written, with no text in it and no digit
    that is not masked, except a number under a name that says it is a quantity
    of a car (a price, a mileage, a year: the smallest, the middle and the
    largest of them) and the value of a boolean, a null or a small integer:
    the page's size and links, how it paginates, its repeated groups, the
    shape of its JSON, the categories in that JSON and its quantities."""
    sk = skeleton(page, name=name, with_text=False).split("# tree:")[0].rstrip("\n")
    return "\n".join([sk, pagination_hints(page).rstrip("\n"),
                       rows(page, name=name, with_text=False).rstrip("\n"),
                       scripts_report(page, name=name).rstrip("\n"),
                       data_lists_report(page, name=name).rstrip("\n"),
                       values_report(page, name=name).rstrip("\n")]) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--skeleton", nargs="+", type=Path, metavar="FILE",
                    help="print the shape of saved pages and exit; no network")
    ap.add_argument("--rows", nargs="+", type=Path, metavar="FILE",
                    help="print the largest repeated groups of saved pages, "
                         "one instance of each, and exit; no network")
    ap.add_argument("--scripts", nargs="+", type=Path, metavar="FILE",
                    help="print the shape of the JSON in the scripts of saved "
                         "pages, no value, and exit; no network")
    ap.add_argument("--survey", nargs="+", type=Path, metavar="FILE",
                    help="print the links, the pagination hints, the rows, the "
                         "shape of the JSON and the categories in it, in one "
                         "answer, and exit; no network, no text")
    ap.add_argument("--around", nargs=2, metavar=("PREFIX", "FILE"),
                    help="print the markup around the links of a saved page whose "
                         "path starts with PREFIX (e.g. /v/), for a page whose cards "
                         "differ so that --rows finds none; no network")
    ap.add_argument("--show", type=int, default=_AROUND_SHOWN, metavar="N",
                    help=f"with --around: how many of the parents to print, the "
                         f"first ones (1 to {_AROUND_SHOW_MAX}, default {_AROUND_SHOWN})")
    ap.add_argument("--up", type=int, default=3, metavar="N",
                    help=f"with --around: how many levels above the link to print "
                         f"(0 to {_AROUND_UP_MAX}, default 3)")
    ap.add_argument("--source", help="a short name, e.g. divar, sheypoor")
    ap.add_argument("--origin", help="e.g. https://divar.ir")
    ap.add_argument("--url", action="append", default=[],
                    help=f"a page to request, at most {MAX_URLS}, repeatable")
    ap.add_argument("--render", choices=["http", "browser"], default="http",
                    help="http for a server-rendered page, browser for one "
                         "rendered client-side (default: http)")
    ap.add_argument("--wait", type=float, default=1.5, metavar="SECONDS",
                    help="with --render browser: seconds to wait after the "
                         "page is ready for it to fill itself in, 0.5 to 30 "
                         "(default 1.5; a page that fetches its rows needs more)")
    ap.add_argument("--no-text", action="store_true",
                    help="with --skeleton, --rows or --around: leave every text out")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT,
                    help=f"where runs are kept (default: {DEFAULT_OUT})")
    args = ap.parse_args(argv)

    if args.around:
        prefix, path = args.around
        if not prefix.startswith("/"):
            ap.error("--around PREFIX is the start of a link's path, e.g. /v/")
        if not 0 <= args.up <= _AROUND_UP_MAX:
            ap.error(f"--up must be between 0 and {_AROUND_UP_MAX}")
        if not 1 <= args.show <= _AROUND_SHOW_MAX:
            ap.error(f"--show must be between 1 and {_AROUND_SHOW_MAX}")
        f = Path(path)
        print(around(f.read_text(encoding="utf-8", errors="replace"), prefix,
                     up=args.up, name=f.name, with_text=not args.no_text,
                     show=args.show))
        return 0
    if args.skeleton:
        for f in args.skeleton:
            print(skeleton(f.read_text(encoding="utf-8", errors="replace"),
                           name=f.name, with_text=not args.no_text))
        return 0
    for flag, view in ((args.rows, lambda t, f: rows(
            t, name=f.name, with_text=not args.no_text)),
                       (args.scripts, lambda t, f: scripts_report(
                           t, name=f.name)),
                       (args.survey, lambda t, f: survey(t, name=f.name))):
        if flag:
            for f in flag:
                print(view(f.read_text(encoding="utf-8", errors="replace"), f))
            return 0
    if not (args.source and args.origin and args.url):
        ap.error("--source, --origin and at least one --url are needed "
                 "(or --skeleton, --rows, --scripts, --survey or --around)")

    policy = PolitenessPolicy()
    if args.render == "browser":
        try:
            import playwright.sync_api                      # noqa: F401, PLC0415
        except ImportError:
            print("playwright is not installed. In your venv:\n"
                  "  pip install playwright && playwright install chromium",
                  file=sys.stderr)
            return 2
        if not 0.5 <= args.wait <= 30:
            ap.error("--wait must be between 0.5 and 30 seconds")
        fetch = playwright_fetcher(policy, wait_ms=int(args.wait * 1000))
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
              "add --no-text to leave the text out):")
        for view in ("survey",):
            print(f"  python3 scripts/page_probe.py --{view} "
                  f"{res.out_dir / first}")
    return res.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
