"""
A Next.js page's data stream, read offline: the rows of its React Server
Components payload.

A page served by the App Router carries its data in scripts of the form
`self.__next_f.push([1,"<a JS string>"])`. Joined in order, the strings are
lines of `id:payload`; a payload that starts with `[` or `{` is JSON, and the
props the server rendered the page from are in it. Khodro45's `/buy-car/` page
holds its listings there (the owner's survey, 2026-10-29): a react-query
cache, `state.queries[].state.data.pages[].results`, and nothing in the markup
says the same in numbers a parser can trust.

This was `scripts/page_probe.py`'s reader, written to SEE such a page. It is
here so that an adapter reads a page with the same function the probe used to
look at it; the probe imports it from here.
"""

from __future__ import annotations

import json
import re
from html.parser import HTMLParser

RSC_PUSH = re.compile(
    r'^\s*self\.__next_f\.push\(\s*\[\s*\d+\s*,\s*(".*")\s*\]\s*\)\s*;?\s*$', re.S)
RSC_ROW = re.compile(r"^[0-9A-Za-z]+:([\[{].*)$")


def rsc_rows(script_texts: list[str]) -> tuple[list, int, int]:
    """(parsed JSON rows, scripts that were pushes, characters in them).

    The pushes are joined BEFORE the rows are split: a row may be cut between
    two pushes, and is whole only once they are one string. A row that is not
    JSON (a module reference, `I[...]`, `HL[...]`) is skipped."""
    chunks, n, size = [], 0, 0
    for t in script_texts:
        m = RSC_PUSH.match(t)
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
        m = RSC_ROW.match(line)
        if m:
            try:
                rows.append(json.loads(m.group(1)))
            except ValueError:
                pass
    return rows, n, size


class _Scripts(HTMLParser):
    """The text of every inline script, in page order."""

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.texts: list[str] = []
        self._in: list[str] | None = None

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._in = None if dict(attrs).get("src") else []

    def handle_data(self, data):
        if self._in is not None:
            self._in.append(data)

    def handle_endtag(self, tag):
        if tag == "script" and self._in is not None:
            self.texts.append("".join(self._in))
            self._in = None


def inline_scripts(html: str) -> list[str]:
    if not html:
        return []
    p = _Scripts()
    try:
        p.feed(html)
        p.close()
    except Exception:             # a page that cannot be read has no scripts
        pass
    return p.texts


def page_rows(html: str) -> list:
    """The JSON rows of a page's data stream; [] for a page without one."""
    return rsc_rows(inline_scripts(html))[0]
