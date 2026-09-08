#!/usr/bin/env python3
"""Inline demo/ranking_data.json into demo/index.html.

    python3 demo/export_ranking.py    # produces demo/ranking_data.json
    python3 demo/wire_ranking.py      # puts it inside the page

The page has to open from a file:// URL with no server, so the decision data
cannot be fetched at runtime — it lives inside the page. Doing that by hand is
how a demo ends up showing numbers the pipeline no longer produces, so it is
done here instead: the script replaces exactly the span between two markers and
touches nothing else, and it is idempotent, so re-running the exporter and then
this is the whole refresh.

It refuses rather than guesses. A missing marker, a missing export, or JSON that
does not carry both panels is an error, not a silently half-wired page.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PAGE = ROOT / "demo" / "index.html"
DATA = ROOT / "demo" / "ranking_data.json"

START = "/*W3-DATA-START*/"
END = "/*W3-DATA-END*/"


def main() -> int:
    if not DATA.exists():
        print(f"missing {DATA} — run demo/export_ranking.py first", file=sys.stderr)
        return 1

    payload = json.loads(DATA.read_text(encoding="utf-8"))
    missing = [k for k in ("synthetic", "real") if k not in payload]
    if missing:
        print(f"{DATA.name} is missing panel(s): {', '.join(missing)}", file=sys.stderr)
        return 1

    page = PAGE.read_text(encoding="utf-8")
    i, j = page.find(START), page.find(END)
    if i < 0 or j < 0 or j < i:
        print(f"markers {START}…{END} not found in {PAGE.name}", file=sys.stderr)
        return 1

    # separators=(',',':') keeps the page small; ensure_ascii=False keeps the
    # Persian readable in a diff, which is the point of committing the page.
    blob = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if "</script" in blob:
        print("refusing: payload contains '</script' and would break the page",
              file=sys.stderr)
        return 1

    updated = page[:i + len(START)] + blob + page[j:]
    if updated == page:
        print("already up to date", file=sys.stderr)
        return 0

    PAGE.write_text(updated, encoding="utf-8")
    print(f"wired {len(blob):,} bytes into {PAGE.name} "
          f"({PAGE.stat().st_size:,} bytes total)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
