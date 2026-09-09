#!/usr/bin/env python3
"""Run every suite and print one summary.

    python3 tests/run_all.py            all four layers
    python3 tests/run_all.py ranking    just one

No `make`, no pytest, no arguments needed — the suites are plain scripts and
this is a plain script, so the project runs anywhere Python does. That
matters more than it sounds: a reviewer who has to install a build tool
before seeing a test pass usually just doesn't.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SUITES = [
    ("W4  ingest", "tests/test_ingest.py",
     "persian parsing, car fields, politeness enforcement"),
    ("W4  seller", "tests/test_seller_type.py",
     "dealer vs private, the ported primitives, and D26"),
    ("W0  tracking", "tests/test_tracking.py",
     "observation integrity, repost identity, censoring"),
    ("W1  appraisal", "tests/test_appraisal.py",
     "leak-free split, baselines, acceptance gate"),
    ("W3  ranking", "tests/test_ranking.py",
     "persian intent, relaxation ladder, win-rate vs price sort"),
    ("W2  agents", "tests/test_agents.py",
     "evidence ledger, adversarial review, judge"),
    ("W1+ pooling", "tests/test_hierarchical.py",
     "empirical-bayes shrinkage, visible extrapolation, held-out trims"),
    ("--  claims", "tests/test_claims.py",
     "retired overclaims do not return (D36)"),
    ("--  corpus", "tests/test_corpus.py",
     "publishable artifact guards, and the laundering regression"),
    ("--  contract", "tests/test_api_contract.py",
     "every endpoint, in every corpus state, against the client's types"),
]

TTY = sys.stdout.isatty() and not os.environ.get("NO_COLOR")
GREEN, RED, DIM, BOLD, OFF = (
    ("\033[32m", "\033[31m", "\033[2m", "\033[1m", "\033[0m") if TTY
    else ("", "", "", "", ""))


def provenance() -> str:
    """Which commit this output came from, printed in the header.

    Added after three consecutive reviews were carried out against an export
    that was one or two commits behind, each concluding the implementation
    was missing work that had already landed. Nothing was wrong with the
    code and a lot of attention was spent finding that out.

    A pasted transcript should be able to answer "which version is this?" on
    its own. `+dirty` marks uncommitted changes, so a run against a working
    tree is never mistaken for a run against a commit. Outside a git
    checkout this returns nothing rather than failing — the suite must stay
    runnable from a tarball.
    """
    try:
        p = subprocess.run(["git", "log", "-1", "--format=%h %cs"],
                           cwd=ROOT, capture_output=True, text=True,
                           timeout=5)
        if p.returncode != 0:
            return ""
        d = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT,
                           capture_output=True, text=True, timeout=5)
        return p.stdout.strip() + ("+dirty" if d.stdout.strip() else "")
    except Exception:
        return ""


def run(path: str) -> tuple[bool, int, float, str]:
    env = {**os.environ, "PYTHONPATH": str(ROOT), "NO_COLOR": "1"}
    t0 = time.time()
    p = subprocess.run([sys.executable, path], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    out = p.stdout + p.stderr
    return p.returncode == 0, out.count("✓"), time.time() - t0, out


def main(argv: list[str]) -> int:
    wanted = argv[1].lower() if len(argv) > 1 else None
    suites = [s for s in SUITES
              if not wanted or wanted in s[0].lower() or wanted in s[1]]
    if not suites:
        print(f"no suite matching {wanted!r}. "
              f"try: {', '.join(s[0].split()[-1] for s in SUITES)}")
        return 2

    print(f"\n{BOLD}CARO test suite{OFF}  {DIM}python "
          f"{sys.version.split()[0]}  {provenance()}{OFF}\n")
    total = failed = 0
    outputs: list[tuple[str, str]] = []
    headline = ""

    for name, path, blurb in suites:
        # The in-progress line is overwritten with \r, which only works on a
        # terminal — piped or redirected it would print every suite twice.
        if TTY:
            print(f"  {name:<16}{DIM}{blurb}{OFF}", end="", flush=True)
        ok, n, secs, out = run(path)
        total += n
        mark = f"{GREEN}✓{OFF}" if ok else f"{RED}✗{OFF}"
        print(f"{chr(13) if TTY else ''}  {mark} {name:<16}{n:>4} assertions  {DIM}{secs:5.1f}s{OFF}"
              f"  {DIM}{blurb}{OFF}")
        if not ok:
            failed += 1
            outputs.append((name, out))
        # The number the whole product rests on belongs in the summary, not
        # buried in scrollback.
        m = re.search(r"(queries=\d+\s+win-rate=[\d.]+%.*)", out)
        if m:
            headline = m.group(1).strip()

    print()
    if headline:
        print(f"  {BOLD}ranking vs price-sort{OFF}  {headline}\n")
    if failed:
        for name, out in outputs:
            print(f"{RED}--- {name} ---{OFF}\n{out}")
        print(f"{RED}{BOLD}{failed} suite(s) failed{OFF}  ({total} assertions ran)\n")
        return 1

    # The website advertises this total, and only this file knows it. A count
    # maintained by hand beside a suite that grows is a count that goes stale —
    # `/about` said 47 decisions for as long as there were 48, and nobody saw
    # it. The check lives here rather than inside a suite because a suite that
    # asserts on the total assertion count changes the number it is asserting.
    #
    # When this fires the fix is to edit the page, not to delete the check.
    drift = _about_disagrees(total)
    if drift:
        print(f"{RED}{BOLD}the site advertises a stale number{OFF}  {drift}\n")
        return 1

    print(f"{GREEN}{BOLD}all {total} assertions passed{OFF} "
          f"across {len(suites)} suite(s)\n")
    return 0


_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def _about_disagrees(total: int) -> str:
    """'' if the about page states `total`, else what it says instead."""
    page = ROOT / "webapp" / "web" / "app" / "about" / "page.tsx"
    if not page.exists():
        return ""                       # no site in this checkout; not a fault
    body = page.read_text(encoding="utf-8")
    m = re.search(r"\['([۰-۹]+)', 'گزاره‌ی آزمون'", body)
    if not m:
        return (f"{page.relative_to(ROOT)} no longer states an assertion "
                f"count — restore it or drop this check deliberately")
    want = str(total).translate(_FA)
    if m.group(1) == want:
        return ""
    return (f"{page.relative_to(ROOT)} says «{m.group(1)}», the suites ran "
            f"{total} → change it to «{want}»")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
