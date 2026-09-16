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
#
# The perturbation is DERIVED from whatever the accent currently is rather
# than written here as a literal. The first version of this suite hard-coded
# `--accent:#1a5f59`, and the very next commit — the one that changed the
# palette — made that string absent, so the self-check silently stopped
# perturbing anything and both its assertions failed. It caught itself, which
# is the good outcome, but a guard whose own fixture goes stale with every
# change it guards is a guard that will one day be edited into agreement
# instead of fixed. Now it cannot go stale: there is no colour in this file.
_ACCENT = re.compile(r"(--accent\s*:\s*)(#[0-9a-fA-F]{6})")

_src = DEMO.read_text(encoding="utf-8")
_hit = _ACCENT.search(_src)
check("the demo declares an accent this suite can perturb", _hit is not None,
      "no `--accent: #rrggbb` found in demo/index.html")

if _hit:
    def _nudge(m):
        v = m.group(2)
        return m.group(1) + v[:-1] + ("0" if v[-1].lower() != "0" else "1")

    _tampered = _ACCENT.sub(_nudge, _src, count=1)
    check("perturbing it actually changes the file", _tampered != _src)

    import tempfile                                            # noqa: E402

    with tempfile.TemporaryDirectory() as d:
        probe = Path(d) / "index.html"
        probe.write_text(_tampered, encoding="utf-8")
        drifted = palette(probe)
        check("and the parser reports the difference",
              drifted["light"]["--accent"] != site["light"]["--accent"],
              f"{drifted['light'].get('--accent')!r} vs "
              f"{site['light']['--accent']!r}")


# ---------------------------------------------------------------------------
print("\nno at-rule stands where a selector belongs")
# ---------------------------------------------------------------------------

# The checks above compare two palettes to each other. They say nothing about
# whether either stylesheet PARSES, and that is a different failure with the
# same signature: silent.
#
# `demo/index.html` carried this for as long as the case buttons existed:
#
#     :root[data-theme="dark"] .case-btn[aria-selected="true"],
#     @media (prefers-color-scheme:dark){}
#
# A selector list cannot contain an at-rule. The comma says "another selector
# follows", `@media` is not one, so the prelude fails to parse and the browser
# discards the whole qualified rule. Nothing is reported anywhere — no console
# error a screen recording would show, no visual difference to notice, because
# the rule it dropped had an empty body. It is debris from an edit that
# removed a dark-mode override's declarations and left its selector behind.
#
# The check is STRUCTURAL rather than a search for that text. A guard that
# greps for `@media (prefers-color-scheme:dark){}` catches the instance that
# has already been fixed and nothing else; the defect is the class — an
# at-keyword sitting where a selector is expected — and `@supports`, or the
# same mistake one line lower, is the same bug.

_STYLE = re.compile(r"<style[^>]*>(.*?)</style\s*>", re.S | re.I)
_AT = re.compile(r"@[a-zA-Z][a-zA-Z-]*")


def stylesheet(path: Path) -> str:
    """The CSS in `path`, comments stripped.

    `demo/index.html` is a page, not a stylesheet: two thirds of it is HTML
    and JavaScript, where braces and semicolons mean something else entirely.
    Scanning the whole file would read every JS block as a rule prelude. So
    the CSS is taken from the `<style>` elements when there are any.
    """
    raw = path.read_text(encoding="utf-8")
    if _STYLE.search(raw):
        raw = "\n".join(m.group(1) for m in _STYLE.finditer(raw))
    return _COMMENT.sub("", raw)


def preludes(css: str) -> list[str]:
    """What stands between each statement boundary and the `{` it opens.

    Not a CSS parser — it does not need to be. `{`, `}` and `;` are the only
    boundaries that matter here: whatever precedes a `{` since the last of
    them is that rule's prelude, and a declaration ends at `;` or `}` without
    ever opening a block, so declarations never masquerade as one.
    """
    out, start = [], 0
    for i, ch in enumerate(css):
        if ch in "{};":
            if ch == "{":
                out.append(css[start:i].strip())
            start = i + 1
    return out


def misplaced(css: str) -> list[str]:
    """Preludes holding an at-keyword somewhere other than their start.

    `@media (...) { }` is a statement and its prelude begins with `@` — that
    is fine and common. `sel, @media (...) { }` is not: the at-keyword is
    inside a selector list. Position is the whole distinction.
    """
    out = []
    for pre in preludes(css):
        m = _AT.search(pre)
        if m and m.start() != 0:
            out.append(pre)
    return out


_SHEETS = {"globals.css": stylesheet(SITE), "demo/index.html": stylesheet(DEMO)}

for _label, _css in _SHEETS.items():
    # A scanner that extracted nothing finds nothing wrong with it. Said out
    # loud, so the guard cannot pass by looking at an empty string — which is
    # what a renamed `<style>` tag or a moved file would produce.
    _n = len(preludes(_css))
    check(f"{_label}: {_n} rule prelude(s) to inspect", _n >= 10, f"got {_n}")

for _label, _css in _SHEETS.items():
    _bad = misplaced(_css)
    check(f"{_label}: no at-rule inside a selector list", not _bad,
          " · ".join(re.sub(r"\s+", " ", b) for b in _bad))


# The same reasoning as the accent perturbation above, for the same reason:
# this guard is green on a file that no longer has the defect, which is also
# what it would look like if the scanner had quietly stopped working. So the
# defect is put back into a COPY and the scanner is required to see it.
#
# The injected pattern is built from the demo's own first selector rather
# than written here as a literal, so it cannot go stale the way a hard-coded
# colour did.
#
# What is asserted is that injection adds exactly ONE finding — not that the
# total is one. Those differ precisely when the sheet already has a real
# instance, and that is the case where the difference matters: an absolute
# count would report this self-check as broken when what is actually broken
# is the stylesheet, which the check above already says in the right words. A
# check that fails for a reason other than the one it names gets read as
# noise, and then the check beside it gets read as noise too.
_first = next((p for p in preludes(_SHEETS["demo/index.html"])
               if p and not p.startswith("@")), "")
check("the demo has a selector this suite can graft onto", bool(_first),
      "no plain selector found")

if _first:
    _before = len(misplaced(_SHEETS["demo/index.html"]))
    _broken = _SHEETS["demo/index.html"].replace(
        _first + "{", _first + ",\n@media (prefers-color-scheme:dark){}\n"
        + _first + "{", 1)
    check("injecting an at-rule into a selector list changes the sheet",
          _broken != _SHEETS["demo/index.html"])
    check("and the scanner reports the injected one",
          len(misplaced(_broken)) == _before + 1,
          f"{_before} before, {len(misplaced(_broken))} after")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
