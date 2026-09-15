"""The site and the demo carry the same palette, and nothing enforces it.

    Run: PYTHONPATH=. python3 tests/test_palette.py

WHY THIS SUITE EXISTS

`webapp/web/app/globals.css` and `demo/index.html` each declare the full
palette as CSS custom properties, in three blocks apiece — the light default,
the `prefers-color-scheme: dark` override, and the explicit
`[data-theme="dark"]` override. The values are identical today and that is
not an accident: a reviewer who watches the demo and then opens the site must
not wonder whether they are looking at two different products.

Nothing checked it. Two hand-maintained copies of sixteen hex values, in two
files that are edited for different reasons, is a drift waiting to happen —
and the failure is SILENT. Both files keep rendering. Both look fine on their
own. Only someone who sees them side by side notices, and by then the video
is recorded.

WHAT THIS DOES NOT ASSUME, AND THE README IS WRONG ABOUT

README says `demo/export_demo.py` regenerates `demo/index.html`. It does not.
That script writes `demo_data.json` and nothing else; the only script that
touches the page is `demo/wire_ranking.py`, which inlines
`ranking_data.json`. `demo/index.html` is hand-maintained HTML with its own
copy of the palette, and it has to stay a single self-contained file because
`docs/DEMO_SCRIPT.md` says it is opened and screen-recorded. So it cannot
`@import` a shared token file, and there is no generator to teach.

That leaves one honest mechanism: compare the two and fail the build when
they disagree. This suite is that comparison. It does not say which palette
is right — only that there is one of them.

WHAT COUNTS AS THE SAME

Values are compared after case-folding and whitespace-collapsing, because
`#F1F3F0` and `#f1f3f0` are the same colour and a font stack does not change
meaning when a space moves. Everything else is compared literally: a token
present in one file and absent from the other is a failure, and so is a value
that differs by one digit.
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "webapp" / "web" / "app" / "globals.css"
DEMO = ROOT / "demo" / "index.html"

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# Reading a palette block out of a file that is not a stylesheet parser's job
# ---------------------------------------------------------------------------

_COMMENT = re.compile(r"/\*.*?\*/", re.S)

# The three blocks, keyed by what they mean rather than by how they are
# spelled. The demo minifies its selectors (`:root{`, `prefers-color-scheme:dark`)
# and globals.css does not, so the patterns tolerate optional whitespace
# rather than matching one file's formatting.
BLOCKS = {
    "light": re.compile(r":root\s*\{"),
    "dark-by-preference": re.compile(
        r":root\s*:not\(\s*\[\s*data-theme\s*=\s*\"light\"\s*\]\s*\)\s*\{"),
    "dark-by-choice": re.compile(
        r":root\s*\[\s*data-theme\s*=\s*\"dark\"\s*\]\s*\{"),
}

_DECL = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;}]+)")


def _body(text: str, start: int) -> str:
    """From the `{` at `start`, the text up to its matching `}`."""
    depth, i = 0, start
    while i < len(text):
        if text[i] == "{":
            depth += 1
        elif text[i] == "}":
            depth -= 1
            if depth == 0:
                return text[start + 1:i]
        i += 1
    raise ValueError("unbalanced braces")


def _norm(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def palette(path: Path) -> dict[str, dict[str, str]]:
    """{block name: {token: value}} for one file.

    `:root` is a prefix of `:root[data-theme="dark"]`, so the bare-light
    pattern would also match the two dark selectors and the first block found
    would win. Each block is therefore located by its OWN pattern first, and
    "light" is whichever `:root {` is none of the others — which is also why
    `:root[data-theme="dark"] .case-btn[...]` in the demo is not mistaken for
    a palette: a descendant selector is not one of the three, and it declares
    no custom properties even if it were.
    """
    text = _COMMENT.sub("", path.read_text(encoding="utf-8"))
    claimed: set[int] = set()
    found: dict[str, dict[str, str]] = {}

    for name in ("dark-by-preference", "dark-by-choice", "light"):
        for m in BLOCKS[name].finditer(text):
            brace = m.end() - 1
            if brace in claimed:
                continue
            decls = dict(_DECL.findall(_body(text, brace)))
            if not decls:
                continue                       # a rule that is not a palette
            claimed.add(brace)
            found[name] = {k: _norm(v) for k, v in decls.items()}
            break

    return found


# ---------------------------------------------------------------------------
print("\nboth files declare all three palette blocks")
# ---------------------------------------------------------------------------

site = palette(SITE)
demo = palette(DEMO)

for label, got in (("globals.css", site), ("demo/index.html", demo)):
    for block in BLOCKS:
        check(f"{label} has the {block} block", block in got,
              f"found {sorted(got)}")

if FAILS:
    print()
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)


# ---------------------------------------------------------------------------
print("\nthe same tokens are declared in both")
# ---------------------------------------------------------------------------

for block in BLOCKS:
    a, b = set(site[block]), set(demo[block])
    check(f"{block}: same token set", a == b,
          f"site-only {sorted(a - b)} · demo-only {sorted(b - a)}")


# ---------------------------------------------------------------------------
print("\nand every token holds the same value")
# ---------------------------------------------------------------------------

for block in BLOCKS:
    shared = sorted(set(site[block]) & set(demo[block]))
    differ = [(t, site[block][t], demo[block][t])
              for t in shared if site[block][t] != demo[block][t]]
    check(f"{block}: {len(shared)} token(s) agree", not differ,
          "; ".join(f"{t}: site={s!r} demo={d!r}" for t, s, d in differ))


# ---------------------------------------------------------------------------
print("\nthe palette is not empty, so agreement means something")
# ---------------------------------------------------------------------------

# Two files that both declare nothing would pass every check above. The point
# of the suite is that a real palette is held in step, so the size is asserted
# rather than assumed — and the accent is named explicitly because it is the
# one token whose drift is most visible and least likely to be noticed in a
# diff full of greys.
for block in BLOCKS:
    check(f"{block}: at least 12 tokens", len(site[block]) >= 12,
          f"got {len(site[block])}")

check("--accent is declared in all three blocks",
      all("--accent" in site[b] for b in BLOCKS),
      str({b: "--accent" in site[b] for b in BLOCKS}))

check("light and dark do not accidentally hold the same accent",
      site["light"]["--accent"] != site["dark-by-choice"]["--accent"],
      site["light"]["--accent"])


# ---------------------------------------------------------------------------
print("\nthe suite can actually fail")
# ---------------------------------------------------------------------------

# A comparison that cannot report a difference is a comparison that proves
# nothing. This runs the real parser over a copy of the demo with one hex
# digit changed, and asserts the difference is seen.
_tampered = DEMO.read_text(encoding="utf-8").replace(
    "--accent:#1a5f59", "--accent:#1a5f5a", 1)
check("a one-digit change to the demo's accent is a change",
      _tampered != DEMO.read_text(encoding="utf-8"),
      "the anchor string is stale — update it with the palette")

import tempfile                                                # noqa: E402

with tempfile.TemporaryDirectory() as d:
    probe = Path(d) / "index.html"
    probe.write_text(_tampered, encoding="utf-8")
    drifted = palette(probe)
    check("and the parser reports it",
          drifted["light"]["--accent"] != site["light"]["--accent"],
          f"{drifted['light'].get('--accent')!r} vs "
          f"{site['light']['--accent']!r}")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
