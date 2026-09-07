"""D36 — a retired overclaim does not come back.

Run: PYTHONPATH=. python3 tests/test_claims.py

Five times now, a mechanism the design supports has been restated as an
observed fact about the Iranian used-car market. D36 catalogues them. This
suite is the mechanical half of that decision.

**What it is.** A regression test over every surface a reader sees — the
README, the design record, the data contract, the package, the scripts and
the other suites. It knows the five claims that have already been caught and
asserts none of them returns.

**What it is not.** A lint for overclaiming in general. It cannot recognise a
sixth claim phrased in new words; that judgement is semantic and belongs to
whoever writes the sentence, using D36's five-tier vocabulary. Saying this
plainly matters more here than anywhere else in the project: a test that
claimed to prevent overclaiming would itself be an overclaim.

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

import re
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

RETIRED = [
    dict(
        id="accepted",
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
        pattern=r"cannot credibly refuse it elsewhere",
        where="D36 #2 — D18",
        why="asserts what the seller would do, from one number they "
            "published somewhere.",
        instead="report the spread; let the buyer draw the inference",
    ),
    dict(
        id="cheapest",
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
        pattern=r"negotiation floor",
        where="D36 #4 — a label in tests/test_ingest.py",
        why="min(prices) is the lowest price the seller has published. "
            "Calling it a floor asserts they will not go below it.",
        instead="the lowest PUBLISHED price",
    ),
    dict(
        id="usually-differ",
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
        pattern=r"(the )?upper bound on performance",
        where="D36 #9 — the Oracle's docstring in tests/test_appraisal.py",
        why="the Oracle reads quantiles out of the fixture's own generating "
            "formula. It is a ceiling for that formula and those three "
            "features, not for performance. Unscoped, it invites putting "
            "D34's real MAE beside a synthetic number and calling the gap "
            "headroom — a comparison with no meaning.",
        instead="a reference ceiling for THIS synthetic benchmark",
    ),
    dict(
        id="fa-negotiate-above",
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

# Everything a reader of this repository could reasonably encounter. Scanning
# widely is not thoroughness theatre: of the eight instances in D36, one was a
# test label, two were in the design record and one was a module docstring.
# A scan limited to the README would have found three.
#
# This file is the single exclusion. It has to contain every retired claim
# verbatim — that is what a catalogue is — so treating the definition as an
# occurrence is a category error, and the quotation exemption would be doing
# the work of an exclusion anyway, less legibly.
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

_QUOTED = re.compile(r'"[^"]*"' r"|«[^»]*»" r"|'[^'\n]{12,}'")


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

    Straight double quotes, Persian guillemets, and long single-quoted runs.
    Pairing is non-greedy and left-to-right, which is what a reader does.
    """
    return [(m.start(), m.end()) for m in _QUOTED.finditer(text)]


def unquoted_hits(text: str, pattern: str) -> list[str]:
    """Occurrences asserted in the project's own voice.

    An occurrence inside quotation marks is a citation and is allowed —
    without that exemption D36 could not catalogue the very claims it
    retires, and the fix would be to stop writing down our mistakes.
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


print("D36 — retired claims do not return")
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
        for hit in unquoted_hits(p.read_text(encoding="utf-8"),
                                 claim["pattern"]):
            offenders.append(f"{rel}: {hit}")
    check(f"{claim['id']:<16} not asserted anywhere  ({claim['where']})",
          not offenders,
          "\n      " + "\n      ".join(offenders) + f"\n      why: "
          f"{claim['why']}\n      instead: {claim['instead']}")

# ---------------------------------------------------------------------------
# The test's own escape hatch, tested
# ---------------------------------------------------------------------------
#
# The quotation exemption is the one thing that could silently disable this
# suite: if `quoted_spans` ever matched too much, every claim would count as
# a citation and all five checks would pass while testing nothing. So the
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

# ---------------------------------------------------------------------------
# The runtime copy, generated rather than grepped
# ---------------------------------------------------------------------------
#
# The catalogue above reads files. That cannot see a sentence assembled at
# run time from fragments, which is exactly what W2's Persian copy is — and
# instance #1 lived in precisely that kind of string. So the shipped
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
    # The Persian shape of instance #1: any wording that puts the seller in
    # agreement with the lowest published number.
    _banned = {"پذیرفته": "says the seller accepted it",
               "قبول کرده": "says the seller accepted it",
               "تأیید": "calls one seller in several places corroboration",
               "قطعاً": "certainty CARO does not have",
               "حتماً": "certainty CARO does not have"}
    for word, why in _banned.items():
        check(f"  runtime copy never says «{word}»  — {why}",
              word not in _copy, _copy)
    check("  and it does state what was observed",
          "منتشر شده" in _copy, _copy)

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
check(f"demo artefacts present to check ({len(_artefacts)})", _artefacts)
for p in _artefacts:
    body = p.read_text(encoding="utf-8")
    for word, why in NEVER_IN_OUTPUT.items():
        check(f"  {p.name} never says «{word}»  — {why}", word not in body)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
