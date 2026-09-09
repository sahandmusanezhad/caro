#!/usr/bin/env python3
"""Run every suite and print one summary.

    python3 tests/run_all.py            all four layers
    python3 tests/run_all.py ranking    just one

No `make`, no pytest, no arguments needed — the suites are plain scripts and
this is a plain script. That matters more than it sounds: a reviewer who has
to install a build tool before seeing a test pass usually just doesn't.

Two suites need more than numpy, and that used to be a lie by omission. This
file claimed "the project runs anywhere Python does" while `test_appraisal`
imported scipy and `test_api_contract` imported fastapi, so a clean clone
with only numpy — the setup the README describes — got a red build naming a
missing module. A reviewer reads that as "the tests are broken", which is
the same class of failure as D46: the command the documentation gives does
not work for the person told to run it.

A suite whose extra dependency is absent is now SKIPPED, by name, with the
command that would enable it. Skipped is not passed and is never printed as
though it were: the summary says how many ran out of how many exist, and
lists what did not. The skip is allowed ONLY for a declared optional module
that is genuinely absent — any other import error is still a failure, so
this cannot become a way for a broken suite to go quiet.
"""

from __future__ import annotations

import importlib.util
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# (label, path, blurb, extra modules it needs beyond numpy, how to get them)
SUITES = [
    ("W4  ingest", "tests/test_ingest.py",
     "persian parsing, car fields, politeness enforcement", (), ""),
    ("W4  seller", "tests/test_seller_type.py",
     "dealer vs private, the ported primitives, and D26", (), ""),
    ("W0  tracking", "tests/test_tracking.py",
     "observation integrity, repost identity, censoring", (), ""),
    ("W1  appraisal", "tests/test_appraisal.py",
     "leak-free split, baselines, acceptance gate",
     ("scipy",), "pip install scipy"),
    ("W3  ranking", "tests/test_ranking.py",
     "persian intent, relaxation ladder, win-rate vs price sort", (), ""),
    ("W2  agents", "tests/test_agents.py",
     "evidence ledger, adversarial review, judge", (), ""),
    ("W1+ pooling", "tests/test_hierarchical.py",
     "empirical-bayes shrinkage, visible extrapolation, held-out trims",
     (), ""),
    ("--  claims", "tests/test_claims.py",
     "retired overclaims do not return (D36)", (), ""),
    ("--  corpus", "tests/test_corpus.py",
     "publishable artifact guards, and the laundering regression", (), ""),
    ("--  contract", "tests/test_api_contract.py",
     "every endpoint, in every corpus state, against the client's types",
     ("fastapi", "pydantic"), "pip install -r webapp/requirements.txt"),
]


def absent(mods: tuple[str, ...]) -> list[str]:
    """Which of `mods` cannot be imported. Checked WITHOUT importing them."""
    out = []
    for m in mods:
        try:
            if importlib.util.find_spec(m) is None:
                out.append(m)
        except (ImportError, ValueError):
            out.append(m)
    return out

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
    skipped: list[tuple[str, list[str], str]] = []
    headline = ""

    for name, path, blurb, needs, how in suites:
        gone = absent(needs)
        if gone:
            # Declared optional dependency, genuinely absent. Named here and
            # again in the summary — never folded into the pass count.
            skipped.append((name, gone, how))
            print(f"  {DIM}–{OFF} {name:<16}{'skipped':>15}  "
                  f"{DIM}needs {', '.join(gone)}{OFF}")
            continue

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

    if skipped:
        # Said before the verdict, not after it, so it cannot be read past.
        print(f"  {BOLD}{len(skipped)} suite(s) did NOT run — skipped is not "
              f"passed{OFF}")
        for name, gone, how in skipped:
            print(f"    {name:<16}needs {', '.join(gone):<18}{DIM}{how}{OFF}")
        print()

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
    # Only meaningful when everything ran. With a suite skipped the total is
    # legitimately lower, and firing here would tell someone whose only fault
    # is not having scipy that the website is lying to them.
    if not skipped:
        drift = _about_disagrees(total)
        if drift:
            print(f"{RED}{BOLD}the site advertises a stale number{OFF}  "
                  f"{drift}\n")
            return 1

    ran = len(suites) - len(skipped)
    scope = (f"across {ran} of {len(suites)} suite(s)" if skipped
             else f"across {ran} suite(s)")
    print(f"{GREEN}{BOLD}all {total} assertions passed{OFF} {scope}\n")
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
