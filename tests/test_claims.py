"""D36 — a retired overclaim does not come back.

Run: PYTHONPATH=. python3 tests/test_claims.py

Repeatedly now, a mechanism the design supports has been restated as an
observed fact about the Iranian used-car market. D36 catalogues every
occurrence. This suite is the mechanical half of that decision.

**Patterns and instances are different counts, and both are printed.** D36
numbers *instances* — one claim in one place at one time. This file holds
*patterns*, and a pattern can cover more than one instance: the README and
`caro/ranking.py` carried the same sentence about damaged cars, and D18 and
the README carried the same sentence about differing prices. So there are
fewer regexes here than numbered entries in D36, permanently and by
construction.

Neither number is written down twice. The header prints both from the
catalogue below, and `d36_instance_numbers()` reads the instance numbers
straight out of `docs/DECISIONS.md` so the two files can be asserted to
agree in both directions — because a hand-copied count going stale is how
several of the instances got written in the first place.

**Two things are retired, and they mean different things.** A `claim` entry
approximates one sentence, so a hit is that sentence returning. A
`vocabulary` entry retires a TERM from own-voice copy in every sentence it
could appear in, including a denial. A vocabulary hit is a policy violation,
not a finding that the surrounding sentence is an overclaim — the regex does
not read sentences and this file does not pretend otherwise.

**What it is.** A regression test over the surfaces in its scan set —
`README.md`, `docs/*.md`, `caro/**/*.py`, `scripts/*.py`, `tests/*.py`, and
`demo/*.{py,html,json,md}`. It knows the claims already caught and asserts
none of them returns.

That list is the scope, not a synonym for "everywhere a reader looks". A
`CHANGELOG.txt` or a `docs/*.rst` added tomorrow is outside it and this
guard would say nothing — which is worth stating plainly in a file whose
subject is claims that outrun what is actually checked. Widening it is a
one-line change when a new surface appears; pretending it is already
general is the mistake.

**What it is not.** A lint for overclaiming in general. It cannot recognise
the next claim phrased in new words; that judgement is semantic and belongs
to whoever writes the sentence, using D36's five-tier vocabulary — which
this file records the existence of and does not validate, because
classifying a sentence into a tier is exactly the semantic judgement it
disclaims. Instance (9) is the standing proof: a reader found it, and no
catalogue could have. Saying this plainly matters more here than anywhere
else in the project — a test that claimed to prevent overclaiming would
itself be an overclaim.

**The rule it enforces.** A retired claim may appear only *in quotation
marks*. Every one of these sentences has to stay quotable — D18 and D36 both
cite them at length, and a project that cannot record its own errors will
repeat them. What is forbidden is the phrase asserted in the project's own
voice. Cite the mistake; do not commit it.

That distinction is the whole test, and it is the reason this can be
mechanical at all. "Is this an overclaim?" is semantic. "Is this sentence
inside quotation marks?" is not.
"""

from __future__ import annotations

import io
import os
import re
import tokenize
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FAILS = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# The catalogue
# ---------------------------------------------------------------------------
#
# `pattern` is matched against whitespace-normalised text, so a claim broken
# across two lines is still caught. Keep the phrasing long enough to be
# unambiguous: a short pattern would fire on innocent prose and get muted,
# which is how a regression suite quietly stops testing anything.
#
# `where` is the instance from D36's catalogue, so a failure points at the
# history rather than at a regex.
#
# `instances` is the machine-readable version of `where`: the D36 entry
# numbers this pattern covers. It is what lets the two files be checked
# against each other instead of trusted to match.
#
# `kind` says what a match MEANS, because two different things are being
# retired here and they need different reactions:
#
#   claim       a specific sentence came back. The regex approximates one
#               claim, and a hit is almost certainly that claim returning.
#
#   vocabulary  a TERM is retired from own-voice copy, whatever sentence it
#               sits in. A hit is a policy violation, not proof that the
#               surrounding sentence is an overclaim — the regex does not
#               read sentences and is not pretending to. "CARO does not
#               infer a negotiation floor" would match, and should: the
#               phrase belongs in quotation marks or not at all, because a
#               reader skimming past the "not" sees the term either way.

CLAIM, VOCABULARY = "claim", "vocabulary"

RETIRED = [
    dict(
        id="accepted",
        kind=CLAIM,
        instances=(1, 3),
        pattern=r"the seller has already accepted",
        where="D36 #1 — price_gap_fa(), and again #3 in the README",
        why="a published price is not a transaction. It may be stale, "
            "channel-specific, or since raised. CARO observes asks and has "
            "no settlement data at all, so this sentence sits in D36's "
            "bottom tier, which is empty by construction.",
        instead="a price the seller has publicly quoted — actionable price "
                "evidence, not transaction evidence",
    ),
    dict(
        id="refuse",
        kind=CLAIM,
        instances=(2,),
        pattern=r"cannot credibly refuse it elsewhere",
        where="D36 #2 — D18",
        why="asserts what the seller would do, from one number they "
            "published somewhere.",
        instead="report the spread; let the buyer draw the inference",
    ),
    dict(
        id="cheapest",
        kind=CLAIM,
        instances=(3, 8),
        pattern=r"cheapest listing is (usually|typically|often) the most "
                r"damaged",
        where="D36 #3 — README",
        why="a property of the synthetic generating process, restated as a "
            "property of the Iranian market. The benchmark builds this in; "
            "it cannot also be evidence for it.",
        instead="price-sorting CAN systematically favour damaged cars",
    ),
    dict(
        id="floor",
        kind=VOCABULARY,
        instances=(4,),
        pattern=r"negotiation floor",
        where="D36 #4 — a label in tests/test_ingest.py",
        why="RETIRED VOCABULARY, not a retired sentence. min(prices) is the "
            "lowest price the seller has published; every use of 'floor' "
            "for it asserts they will not go below, and CARO has no "
            "transaction evidence that could support that. The regex does "
            "not judge the sentence it lands in — it does not read "
            "sentences. The rule is that the term stays in quotation marks "
            "or stays out.",
        instead="the lowest PUBLISHED price",
    ),
    dict(
        id="usually-differ",
        kind=CLAIM,
        instances=(5, 6),
        pattern=r"prices differ, which they usually do",
        where="D36 #5 — D18, and #6 — the same sentence copied into the "
              "README",
        why="how often cross-site prices differ is a market frequency this "
            "project has never measured. The cross-source path has only "
            "ever run on fixtures.",
        instead="when the prices differ",
    ),
    dict(
        id="oracle-ceiling",
        kind=VOCABULARY,
        instances=(9,),
        pattern=r"(the )?upper bound on performance",
        where="D36 #9 — the Oracle's docstring in tests/test_appraisal.py",
        why="RETIRED VOCABULARY. The Oracle reads quantiles out of the "
            "fixture's own generating formula, so it is a ceiling for that "
            "formula and those three features. The phrase is retired in "
            "every sentence, including a denial, because unscoped it "
            "invites putting D34's real MAE beside a synthetic number and "
            "calling the gap headroom — a comparison with no meaning.",
        instead="a reference ceiling for THIS synthetic benchmark",
    ),
    dict(
        id="fa-negotiate-above",
        kind=CLAIM,
        instances=(7,),
        pattern=r"جای چانه‌?زنی دارد|فروشنده خودش این خودرو",
        where="D36 #7 — the retired Persian copy, still printed in the "
              "README as a sample of what CARO says",
        why="the Persian original of #1. It survived the English fix "
            "because it sits in a fenced code block four lines below the "
            "sentence that was corrected — the prose was fixed and the "
            "quoted OUTPUT underneath it was not.",
        instead="paste what price_gap_fa() actually returns today",
    ),
]

# Every reader-facing surface currently declared in this scan set — which is
# not the same as everything a reader could encounter, and the difference is
# the kind of thing this file exists to keep honest. Scanning
# widely is not thoroughness theatre: of the instances in D36, one was a test
# label, two were in the design record, one was a module docstring in the
# shipped package and one was in a test fixture. A scan limited to the README
# would have found three of nine.
#
# This file is the single exclusion, for one narrow reason: the catalogue
# must contain the retired strings themselves, so scanning it would be
# scanning the definition. The quotation exemption would mostly cover that
# on its own, but a file that is largely quoted strings is a poor place to
# lean on a quote heuristic, and an explicit exclusion says what is
# happening.
SELF = "tests/test_claims.py"
SURFACES = [
    s for s in (["README.md"]
                + sorted(str(p.relative_to(ROOT)) for p in
                         ROOT.glob("docs/*.md"))
                + sorted(str(p.relative_to(ROOT)) for p in
                         ROOT.glob("caro/**/*.py"))
                + sorted(str(p.relative_to(ROOT)) for p in
                         ROOT.glob("scripts/*.py"))
                + sorted(str(p.relative_to(ROOT)) for p in
                         ROOT.glob("tests/*.py"))
                # The demo is the surface most people will actually look at,
                # and index.html / demo_data.json are GENERATED — so a guard
                # that only inspects a live response cannot see them. A
                # regenerated artefact carries whatever the code said on the
                # day it ran, which is precisely how a retired string ships.
                + sorted(str(p.relative_to(ROOT)) for p in
                         ROOT.glob("demo/*")
                         if p.suffix in {".py", ".html", ".json", ".md"}))
    if s != SELF]

# Straight double quotes and Persian guillemets. Nothing else.
#
# An earlier version also exempted single-quoted runs of twelve characters or
# more, on the theory that some citation somewhere would need it. That is the
# wrong shape for an exemption: `'a long ordinary python string'` would have
# counted as a citation, and the whole guard rests on the exemption staying
# small. Removing it was checked rather than argued — across all 40 surfaces
# and every pattern, the narrow and wide versions return identical verdicts,
# so the rule bought nothing and could only ever have hidden something.
#
# If a real citation someday needs single quotes, quote it with double ones.
_QUOTED = re.compile(r'"[^"]*"' r"|«[^»]*»")


def normalise(text: str) -> str:
    """Flatten to one line so a claim wrapped across two is still found.

    Markdown blockquote markers go first. D18 quotes its own retired sentence
    inside a `>` block, and leaving the markers in place would split the
    phrase — the test would pass by failing to look, which is the worst way
    for a regression suite to be green.

    Python triple-quotes go next, and for the opposite reason. `\"\"\"` is
    three quote characters, so left-to-right pairing desynchronises for the
    rest of the file and genuine citations inside docstrings stop counting as
    quoted. That direction produces false alarms rather than silence, which
    is the safer failure — but it is still wrong, and it fired on
    `cross_source.py` the first time this suite ran.
    """
    text = re.sub(r"(?m)^\s*>\s?", "", text)
    text = text.replace('"""', " ").replace("'''", " ")
    return re.sub(r"\s+", " ", text)


def quoted_spans(text: str) -> list[tuple[int, int]]:
    """Character ranges that are inside quotation marks.

    Pairing is non-greedy and left-to-right, which is what a reader does.

    This is a heuristic, not a parser, and it is meant to stay one. It does
    not understand escaping or nesting. The safe direction for a heuristic
    here is *under*-exempting: a missed exemption is a false alarm someone
    fixes in a minute, while an over-broad exemption silently retires the
    whole guard. So when in doubt, this matches less.
    """
    return [(m.start(), m.end()) for m in _QUOTED.finditer(text)]


def unquoted_hits(text: str, pattern: str) -> list[str]:
    """Occurrences outside the narrow quotation forms this guard permits.

    Deliberately not called "not a citation". Quotation marks are a
    SYNTACTIC exemption, not evidence that the quoted text is historically
    cited: "the seller has already accepted this price" is exempt in any
    prose sentence, including one that is asserting it and merely happens to
    quote. That gap is the price of a mechanical rule, and `code_and_prose`
    narrows it where it mattered most.

    The exemption exists at all because D36 and D18 have to be able to
    catalogue the claims they retire. Without it the fix would be to stop
    writing our mistakes down.
    """
    flat = normalise(text)
    spans = quoted_spans(flat)
    out = []
    for m in re.finditer(pattern, flat, re.I):
        if any(a <= m.start() and m.end() <= b for a, b in spans):
            continue
        lo, hi = max(0, m.start() - 60), min(len(flat), m.end() + 60)
        out.append("…" + flat[lo:hi] + "…")
    return out


TOKENIZE_FAILURES: set[str] = set()


def code_and_prose(src: str) -> tuple[str, str] | None:
    """Split Python into (executable code, comments-and-docstrings).

    In prose, quotation marks mean citation closely enough to test. In source
    code they mean "this is a string", which is a different thing entirely —
    and a string in code is frequently something a user will READ: a Persian
    template, a printed label, an error message. Exempting those because they
    sit between quotes turns the guard off exactly where output lives.

    This was not a theoretical hole. Applying the split found "negotiation
    floor" in a `check(...)` label in tests/test_ingest.py — retired
    vocabulary, printed on every run, exempted by the quote rule, in the very
    file whose label was corrected for instance (4). The correction had kept
    the term and moved the sentence around it.

    So for Python: citations are honoured in comments and docstrings, and
    code gets no exemption at all. `tokenize` decides which is which.

    Returns None when the file cannot be tokenized, rather than a value the
    caller has to guess about. An earlier version signalled failure by
    returning `(src, "")` and the caller detected it with `code is text` —
    which fired on every empty `__init__.py`, because CPython interns the
    empty string. A scanner that quietly stops scanning is the failure mode
    this whole suite exists against, so the signal is explicit.
    """
    prose, code = [], []
    try:
        toks = list(tokenize.generate_tokens(io.StringIO(src).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        return None
    prev = tokenize.INDENT
    for t in toks:
        if t.type == tokenize.COMMENT:
            prose.append(t.string)
            continue
        # A statement-level string HEURISTIC, not an AST docstring. tokenize
        # cannot tell a module/class/function docstring from any other bare
        # string in those token positions, and this does not try to. The
        # boundary it draws is good enough for the question being asked and
        # cheap enough not to drag a parser in; calling it docstring
        # detection would claim more than it does.
        if t.type == tokenize.STRING and prev in (
                tokenize.INDENT, tokenize.DEDENT, tokenize.NEWLINE,
                tokenize.NL, tokenize.ENCODING):
            prose.append(t.string)
        elif t.type not in (tokenize.NEWLINE, tokenize.NL, tokenize.INDENT,
                            tokenize.DEDENT, tokenize.ENDMARKER,
                            tokenize.ENCODING):
            code.append(t.string)
        if t.type not in (tokenize.NL, tokenize.COMMENT):
            prev = t.type
    return " ".join(code), "\n".join(prose)


def hits_in(rel: str, text: str, pattern: str,
            failures: set[str] | None = None) -> list[str]:
    """Own-voice occurrences in one surface, with Python treated as code.

    `failures` is the set unreadable filenames are recorded in; it defaults
    to the module-level one used by the real scan. Probes pass their own, so
    a deliberately broken fixture cannot contaminate the summary assertion
    and no cleanup line has to run in the right order to undo it.

    An untokenizable Python file is reported as an offender rather than
    scanned by the prose rule or skipped.

    Both alternatives were considered and both misrepresent something.
    Falling back to `unquoted_hits` presents a weaker rule's verdict as if
    the surface had been scanned under policy. Returning `[]` makes the file
    read as clean in the per-pattern output, and leaves the whole guard for
    that surface resting on one summary assertion — remove or weaken that
    assertion later and the hole is silent, which is the failure shape this
    suite is built against.

    Failing the pattern outright misrepresents nothing: the honest verdict
    on a surface the scanner cannot read is not "clean", it is "unknown",
    and unknown must be as loud as a hit. `TOKENIZE_FAILURES` still collects
    the names so the summary can say which files and why.
    """
    if not rel.endswith(".py"):
        return unquoted_hits(text, pattern)
    split = code_and_prose(text)
    if split is None:
        (TOKENIZE_FAILURES if failures is None else failures).add(rel)
        return ["[UNSCANNED — this file does not tokenize, so it was "
                "neither checked nor cleared]"]
    code, prose = split
    out = unquoted_hits(prose, pattern)
    flat = normalise(code)
    for m in re.finditer(pattern, flat, re.I):
        lo, hi = max(0, m.start() - 60), min(len(flat), m.end() + 60)
        out.append("[in code, no exemption] …" + flat[lo:hi] + "…")
    return out


def d36_instance_numbers() -> set[int]:
    """The entry numbers in D36's own catalogue, read from the design record.

    The alternative is to write the count here as well, and this project's
    record on numbers written down twice is poor: `MIN_PER_TRIM_FLOOR` was
    two constants before it was one, `asking_asking_price_toman` survived a
    rename in EVAL.md, and this very file said "five claims" for two commits
    after there were nine.

    Parsing is deliberately narrow — a catalogue row is four spaces, an
    integer, two spaces, a source. If the format changes the parse returns
    nothing and the caller fails loudly. A cross-file check that silently
    passes when it can no longer see one of the files is worse than no check,
    because it reads as coverage.
    """
    txt = (ROOT / "docs" / "DECISIONS.md").read_text(encoding="utf-8")
    start = txt.find("## D36")
    if start < 0:
        return set()
    end = txt.find("\n## D", start + 6)
    body = txt[start:end if end > 0 else len(txt)]
    return {int(m) for m in re.findall(r"(?m)^ {4}(\d+) {2}\S", body)}


_covered = sorted({i for c in RETIRED for i in c["instances"]})
_d36 = sorted(d36_instance_numbers())

print("D36 — retired claims do not return")
print(f"  {len(RETIRED)} patterns covering {len(_covered)} instances "
      f"(a pattern can cover several: the same sentence has twice been "
      f"caught in two places)")
print(f"  scanning {len(SURFACES)} surfaces "
      f"({sum(1 for s in SURFACES if s.endswith('.md'))} prose, "
      f"{sum(1 for s in SURFACES if s.endswith('.py'))} source)")
print()

for claim in RETIRED:
    offenders = []
    for rel in SURFACES:
        p = ROOT / rel
        if not p.exists():
            continue
        for hit in hits_in(rel, p.read_text(encoding="utf-8"),
                           claim["pattern"]):
            offenders.append(f"{rel}: {hit}")
    check(f"{claim['id']:<16} [{claim['kind']:<10}] not in own voice  "
          f"({claim['where']})",
          not offenders,
          "\n      " + "\n      ".join(offenders) + f"\n      why: "
          f"{claim['why']}\n      instead: {claim['instead']}")

# ---------------------------------------------------------------------------
# The catalogue and the design record must not drift apart
# ---------------------------------------------------------------------------
#
# Adding an instance to D36 and forgetting the pattern here leaves a claim
# retired in prose and unguarded in fact — the exact gap this suite exists to
# close, reopened by the act of documenting it. The check runs in both
# directions, so a pattern for an instance D36 never recorded fails too.

print()
check(f"D36's catalogue parses ({len(_d36)} numbered instances found)", _d36)
check("  every D36 instance has a pattern here",
      set(_d36) <= set(_covered),
      f"unguarded: {sorted(set(_d36) - set(_covered))}")
check("  every pattern here maps to a D36 instance",
      set(_covered) <= set(_d36),
      f"not in the design record: {sorted(set(_covered) - set(_d36))}")
check("  the instance numbers run 1..N with no gaps",
      _d36 == list(range(1, len(_d36) + 1)), str(_d36))

# A set() hides a repeated number, so the coverage checks above would pass
# happily on `instances=(1, 1, 3)`. Two different repeats are possible and
# only one of them is ever right.
_flat = [i for c in RETIRED for i in c["instances"]]
_dupe_within = sorted({i for c in RETIRED
                       for i in c["instances"]
                       if list(c["instances"]).count(i) > 1})
check("  no entry lists the same instance twice", not _dupe_within,
      f"a typo, always: {_dupe_within}")

# Across entries it CAN be right. README instance (3) carried two separate
# claims in one place — "the cheapest listing is usually the most damaged
# one" and "a number the seller has already accepted" — so it maps to two
# patterns. That is a fact about the instance, not a mistake, and it has to
# be declared here rather than inferred, or the check below means nothing.
MULTI_CLAIM_INSTANCES = {3}
_dupe_across = {i for i in _flat if _flat.count(i) > 1}
check("  instances mapped by several patterns are declared ones",
      _dupe_across <= MULTI_CLAIM_INSTANCES,
      f"undeclared: {sorted(_dupe_across - MULTI_CLAIM_INSTANCES)} — either "
      f"a typo, or an instance that really did carry two claims, in which "
      f"case say so in MULTI_CLAIM_INSTANCES")
check("  and every declared one is actually mapped twice",
      MULTI_CLAIM_INSTANCES <= _dupe_across,
      f"stale declaration: {sorted(MULTI_CLAIM_INSTANCES - _dupe_across)}")

# ---------------------------------------------------------------------------
# The test's own escape hatch, tested
# ---------------------------------------------------------------------------
#
# The quotation exemption is the one thing that could silently disable this
# suite: if `quoted_spans` ever matched too much, every claim would count as
# a citation and every check above would pass while testing nothing. So the
# exemption is exercised in both directions on a fixture.

print()
_probe = ("D36 records that an earlier draft said \"the seller has already "
          "accepted this price\", which was wrong.")
check("a claim inside quotation marks is a citation, and allowed",
      not unquoted_hits(_probe, RETIRED[0]["pattern"]))
check("  the same words asserted in our own voice are caught",
      len(unquoted_hits("the seller has already accepted this price",
                        RETIRED[0]["pattern"])) == 1)
check("  a claim wrapped across two lines is still caught",
      len(unquoted_hits("...the seller has already\naccepted this price.",
                        RETIRED[0]["pattern"])) == 1)
check("  a blockquote marker does not hide it",
      len(unquoted_hits("> the seller has already\n> accepted this price.",
                        RETIRED[0]["pattern"])) == 1)

_PY_PROBE = '''"""A docstring citing "the seller has already accepted"."""
LABEL = "the seller has already accepted this price"
'''
check("  in Python, a docstring citation is still exempt",
      not unquoted_hits(code_and_prose(_PY_PROBE)[1], RETIRED[0]["pattern"]))
check("  a file that cannot be tokenized reports it",
      code_and_prose("def broken(:\n") is None)
check("  but the same words in a code string are NOT",
      len(hits_in("probe.py", _PY_PROBE, RETIRED[0]["pattern"])) == 1,
      "a quoted string in code is output, not a citation")
check("  every Python surface was actually tokenized",
      not TOKENIZE_FAILURES,
      f"unscanned, and reported as offenders above: "
      f"{sorted(TOKENIZE_FAILURES)}")
check("  an unreadable surface fails rather than reading clean",
      hits_in("broken.py", "def f(:\n", RETIRED[0]["pattern"],
              failures=set()) != [],
      "unknown must be as loud as a hit")

# ---------------------------------------------------------------------------
# The scan set says `caro/**/*.py`. Does it mean it?
# ---------------------------------------------------------------------------
#
# `Path.glob` semantics are easy to get subtly wrong, and a scope declared in
# a docstring is worth exactly as much as the glob under it. So the recursive
# claim is verified against an independent enumeration — os.walk, which knows
# nothing about the pattern that produced SURFACES. Two ways of listing the
# same files, compared, rather than one way trusted.

print()
_walked = {str(Path(dp, f).relative_to(ROOT))
           for dp, _, fs in os.walk(ROOT / "caro")
           for f in fs if f.endswith(".py") and "__pycache__" not in dp}
_nested = {p for p in _walked if p.count("/") > 1}
check(f"caro/ has nested python to find ({len(_nested)} below the top level)",
      _nested)
# Equality, not containment. A subset check only catches the glob missing a
# file; the declaration says `caro/**/*.py`, so a surface list that picked up
# something os.walk does not see is also a scope that no longer matches what
# the file says about itself.
_globbed = {p for p in SURFACES if p.startswith("caro/")}
check("  the recursive glob is EXACTLY the os.walk set",
      _walked == _globbed,
      f"declared caro/**/*.py — missed: {sorted(_walked - _globbed)}; "
      f"unexpected: {sorted(_globbed - _walked)}")

# ---------------------------------------------------------------------------
# Runtime semantic guardrails — NOT the D36 catalogue
# ---------------------------------------------------------------------------
#
# Everything above this line is D36: specific claims, historically made,
# mechanically prevented from returning. Everything below is a different and
# weaker thing — a standing wordlist for Persian copy, enforcing the same
# claim boundary without any of it being a retired instance.
#
# The distinction is kept sharp on purpose. These words carry no `instances`,
# take no part in the pattern/instance accounting, and must never be cited as
# D36 entries. A decision that starts absorbing every adjacent good idea ends
# up asserting nothing, and this one earns its keep by being narrow.
#
# Why they exist here at all: the catalogue reads files, and a file cannot
# show a sentence assembled at run time from fragments — which is exactly
# what W2's Persian copy is, and where instance #1 lived. So the shipped
# functions are called and their output inspected.

print()
from caro.ingest.cross_source import CrossSourceCandidate, cluster_across_sources  # noqa: E402

def _cand(source: str, lid: str, price: int, km: int):
    return CrossSourceCandidate(
        source=source, listing_id=lid, make="Peugeot", model="206",
        trim="تیپ ۵", year_jalali=1396, mileage_km=km, color="سفید",
        province="تهران", asking_price_toman=price,
        description="بدون رنگ، بیمه یک سال", image_phashes=("h1", "h2"))


_cands = [_cand("bama", "b1", 1_450_000_000, 120_000),
          _cand("divar", "d1", 1_420_000_000, 121_000)]
_xs = [c for c in cluster_across_sources(_cands) if c.is_cross_source]
check("fixture builds a cross-source cluster to read copy from", len(_xs) == 1)

if _xs:
    _copy = " ".join(filter(None, [_xs[0].claim_fa(), _xs[0].price_gap_fa()]))
    # Probes for THIS fixture's two sentences — the cross-source claim and
    # the price gap, the strings instance (1) lived in. They are not the
    # standing demo wordlist further down, and not D36 catalogue entries:
    # three separate lists doing three separate jobs, kept apart on purpose.
    _RED_FLAGS = {"پذیرفته": "says the seller accepted it",
                  "قبول کرده": "says the seller accepted it",
                  "تأیید": "calls one seller in several places corroboration",
                  "قطعاً": "certainty CARO does not have",
                  "حتماً": "certainty CARO does not have"}
    for word, why in _RED_FLAGS.items():
        check(f"  runtime copy never says «{word}»  — {why}",
              word not in _copy, _copy)
    check("  and it does state what was observed",
          "منتشر شده" in _copy, _copy)
else:
    # Without this, a broken fixture reports one failure — "no cluster" —
    # and the five probes below it simply never run. The suite still goes
    # red, so nothing passes silently, but the transcript would suggest the
    # copy was checked and found clean. Not exercised is its own result and
    # says so.
    check("  runtime copy probes were exercised at all", False,
          "no cross-source cluster was built, so NONE of the Persian "
          "guardrails ran — this is unchecked copy, not clean copy")

# ---------------------------------------------------------------------------
# The shipped demo, as it sits on disk
# ---------------------------------------------------------------------------
#
# `tests/test_agents.py` already asserts that no GENERATED response says
# «فروخته» or «قیمت واقعی». That guard runs against a live orchestrator. The
# demo artefacts are frozen output — written once, committed, and read by
# everyone who opens the project without running anything. If a guard is added
# after an export, the committed file keeps the old words and every test still
# passes.
#
# So the artefacts are checked as artefacts. These are not retired claims;
# they are the tiers D36 forbids outright, in the language the demo speaks.

print()
NEVER_IN_OUTPUT = {
    "قیمت واقعی": "a transaction price CARO has never observed",
    "ارزش واقعی": "a true value, which is not an estimand here",
    "کف بازار": "a market floor, inferred from asks alone",
    "فروخته": "a sale; disappearance is not sale (D3)",
    "قبول می‌کند": "what the seller will accept — D36 #1",
    "می‌ارزد": "what the car is worth, rather than what it is asked at",
    "قطعاً": "certainty this project does not have",
}
_artefacts = [p for p in ROOT.glob("demo/*")
              if p.suffix in {".html", ".json"}]

# The website says these things to actual users, which the demo page does not,
# so it belongs in the same scan set. It was outside it for as long as it
# existed: the guard covered `demo/*` because that was the only user-facing
# surface at the time, and nothing announced when a second one appeared.
_artefacts += sorted(
    p for d in ("webapp/web/app", "webapp/web/components")
    for p in (ROOT / d).rglob("*")
    if p.is_file() and p.suffix in {".tsx", ".ts"})

check(f"user-facing artefacts present to check ({len(_artefacts)})", _artefacts)
for p in _artefacts:
    body = p.read_text(encoding="utf-8")
    for word, why in NEVER_IN_OUTPUT.items():
        check(f"  {p.name} never says «{word}»  — {why}", word not in body)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
