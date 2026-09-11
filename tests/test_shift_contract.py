"""The contract for distribution shift, written BEFORE the implementation.

    Run: PYTHONPATH=. python3 tests/test_shift_contract.py

RED BY CONSTRUCTION. This suite is not in `tests/run_all.py` yet and it does
not pass. That is deliberate: the decision table is settled here first, and
the implementation is then obliged to satisfy a specification it did not get
to write. Wiring it into `run_all` is part of the implementation commit, not
this one.

THE ONE QUESTION STEP 4 ASKS

    Are train and test different enough that test error is no longer
    trustworthy evidence about the temporal question?

And explicitly NOT:

    Did the estimator do badly?

Those two have one verdict between them today, and collapsing them is how a
sampling problem gets recorded as a model failure — after which a perfectly
good estimator is retired for a fault in the corpus.

THE DECISION TABLE

    train/test comparable                → continue to estimator evaluation
    not enough evidence to compare       → UNJUDGEABLE / evidence_missing
    severe shift, representativeness bad → UNJUDGEABLE / evidence_missing
    comparable, and MAE fails the gate   → REJECTED

    A distribution shift NEVER produces REJECTED on its own. REJECTED is
    reserved for a measured failure of the estimator on a valid evaluation
    population, and nothing else may spend it.

THE SEPARATION THIS PROTECTS

    split
      ↓
    distribution_shift        evidence about comparability. Nothing else.
      ↓
    severe?
      ├─ yes → UNJUDGEABLE / evidence_missing
      └─ no  → estimator evaluation

The runner decides; the measurement does not. Without that line, a threshold
inside `distribution_shift` becomes a hidden gate on the estimator, tunable
by anyone who does not like a verdict, and invisible in the one place a
reader would look for a gate.

WHAT THIS SUITE CANNOT TEST YET, SAID RATHER THAN FAKED

An end-to-end run — artifact in, verdict out — needs a corpus with a real
temporal axis, and no such artifact exists (§9/§10 of the temporal
contract). So the runner's half is asserted structurally: that it consults
the shift at all, that it maps severity to the right verdict, and that the
missing-axis refusal still comes first. The behavioural half arrives with
step 5 and this file is where it goes.
"""

import inspect
import os
import re
import sys
from pathlib import Path

os.environ.setdefault("CARO_SELLER_SALT", "test-salt")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from caro.appraisal import (                                      # noqa: E402
    Row, Split, distribution_shift,
)

FAILS: list[str] = []
TOTAL = 0


def check(name, cond, detail=""):
    global TOTAL
    TOTAL += 1
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def rows(prices, *, start=0) -> list[Row]:
    return [Row(listing_id=f"l{i}", cluster_id=f"c{i}", first_seen_ordinal=i,
                model_key="saipa|pride|se", year_jalali=1395,
                mileage_km=100_000.0, asking_price_toman=float(p))
            for i, p in enumerate(prices, start=start)]


def split_of(train_prices, test_prices) -> Split:
    return Split(rows(train_prices), rows(test_prices, start=1000), 0, 500)


SRC = inspect.getsource(distribution_shift)

# The BODY, with the docstring removed. Scanning raw source for words like
# "model" flags the docstring sentence "a model can look broken while being
# fine" — which is the explanation, not a dependency. This suite has made
# that mistake before in another file; a contract point that fails on prose
# forces the implementer to satisfy something meaningless, and the fastest
# way past it is to delete the sentence.
BODY = re.sub(r'"""'.join(("", ".*?", "")), "", SRC, count=1, flags=re.S)

# ---------------------------------------------------------------------------
print("\nWHAT THE MEASUREMENT MUST NOT DO")
# ---------------------------------------------------------------------------

sig = inspect.signature(distribution_shift)
check("it takes a split and tolerances, and no model",
      not any(p in sig.parameters
              for p in ("model", "estimator", "preds", "predictions", "mae")),
      f"signature is {sig}")

check("it never reads an error term",
      not re.search(r"\bmae\b|\bpredict\b|\bbaseline\b", BODY, re.I),
      "a comparability measurement that can see the estimator's error is a "
      "hidden gate on the estimator")

_sp = split_of([100, 110, 120, 130] * 20, [105, 115, 125, 135] * 20)
_train_before = list(_sp.train)
_test_before = list(_sp.test)
_n_before = (len(_sp.train), len(_sp.test))
distribution_shift(_sp)
check("it does not change split membership",
      _sp.train == _train_before and _sp.test == _test_before,
      "the split it was handed must be the split that is evaluated")
check("it does not drop rows",
      (len(_sp.train), len(_sp.test)) == _n_before,
      f"{_n_before} became {(len(_sp.train), len(_sp.test))}")

_r = distribution_shift(_sp)
check("its result carries no verdict about the estimator",
      not any(hasattr(_r, a) for a in
              ("verdict", "accepted", "rejected", "passed", "mae")),
      f"fields: {sorted(vars(_r))}")

# ---------------------------------------------------------------------------
print("\nTHREE STATES, NOT TWO  — the defect this step exists to fix")
# ---------------------------------------------------------------------------
#
# `distribution_shift` returns `severe: bool`. A boolean has room for two
# answers and the decision table needs three, so the third is currently
# reported as one of the other two:
#
#     if a.size == 0 or b.size == 0:
#         return ShiftReport(0.0, 0.0, 1.0, 0.0, False)
#
# An EMPTY test set comes back `severe=False` — which the runner and
# `agents.py:717` both read as "train and test are comparable, carry on".
# Nothing was compared. That is D54 exactly: an answer about missing
# evidence dressed as an answer about the thing.

_empty = distribution_shift(Split(rows([100] * 60), [], 0, 0))
check("an empty test set is NOT reported as comparable",
      getattr(_empty, "severe", None) is not False,
      "severe=False means 'no shift detected', and nothing was compared")

check("the report can express 'cannot say' distinctly from 'no shift'",
      hasattr(_empty, "comparability") or hasattr(_empty, "insufficient"),
      "a bool cannot carry three states; the report needs a tri-state — "
      "COMPARABLE / SHIFTED / INSUFFICIENT — and the runner must be able to "
      "tell the third from the first")

_one = distribution_shift(split_of([100], [900]))
check("one row a side cannot establish comparability either way",
      getattr(_one, "comparability", None) not in (None, "comparable"),
      "a KS statistic on n=1 is not evidence; it is arithmetic")

check("the floor for judging comparability is a NAMED constant, not a "
      "literal in the function",
      any(n.startswith("MIN_COMPAR") or n.startswith("MIN_SHIFT")
          for n in dir(sys.modules["caro.appraisal"])),
      "derive it and name it, the way MIN_SLICE_N was derived — a bare "
      "number inside the function is a threshold nobody can find")

# ---------------------------------------------------------------------------
print("\nTHE STATES IT MUST STILL GET RIGHT")
# ---------------------------------------------------------------------------

_same = distribution_shift(split_of(list(range(100, 200)),
                                    list(range(100, 200))))
check("identical distributions are comparable",
      getattr(_same, "comparability", None) in ("comparable", None)
      and not _same.severe,
      f"ratio {_same.ratio:.3f} ks {_same.ks_statistic:.3f}")

_moved = distribution_shift(split_of(list(range(100, 200)),
                                     list(range(300, 400))))
check("a test set at triple the price level is a severe shift",
      _moved.severe, f"ratio {_moved.ratio:.3f}")

check("  and severity is computed without reference to the estimator",
      not re.search(r"estimator|\bmodel\b", BODY, re.I),
      "the docstring may explain why this matters to a model; the code may "
      "not touch one")

# ---------------------------------------------------------------------------
print("\nTHE RUNNER'S DECISION TABLE")
# ---------------------------------------------------------------------------
#
# Structural until an artifact with a real temporal axis exists. Named as
# such at the top of this file rather than approximated with a fixture that
# would assert a behaviour nothing has ever executed.

import benchmark_corpus as BC                                     # noqa: E402

RSRC = inspect.getsource(BC)

check("the runner consults the shift at all",
      "distribution_shift" in RSRC,
      "it does not today: the benchmark never asks whether train and test "
      "are comparable before believing the test error")

check("severe shift has its own reason in the closed vocabulary",
      "severe_shift" in getattr(BC, "REASONS", {}),
      f"REASONS has {sorted(getattr(BC, 'REASONS', {}))}")

check("insufficient evidence to compare has its own reason too",
      "shift_unknown" in getattr(BC, "REASONS", {})
      or "incomparable" in getattr(BC, "REASONS", {}),
      "the third state needs a name a transcript can be grepped for")

_severe_line = re.search(
    r'report\(\s*"(\w+)"\s*,\s*"severe_shift"', RSRC)
check("a severe shift reports UNJUDGEABLE, never rejected",
      _severe_line is not None and _severe_line.group(1) == "unjudgeable",
      f"got {_severe_line.group(1) if _severe_line else '<no such call>'}")

# Precisely: the ONLY producer of a rejected verdict is the gate's own
# mapping. Counting occurrences of the string would count the vocabulary
# entry too, and would be satisfied or broken by things that are not the
# property. The property is that no call site hands `report` a rejection
# directly.
check("REJECTED is spent only on the gate's measured failure",
      'GateVerdict.REJECTED: "measured_failure"' in RSRC
      and not re.search(r'report\(\s*"rejected"', RSRC),
      "if a second path can produce REJECTED, the word stops meaning "
      "'the estimator was assessed and fell short'")

# ---------------------------------------------------------------------------
print("\nRUN 11 IS NOT RESCUED BY THIS")
# ---------------------------------------------------------------------------
#
# Run 11 is frozen at UNJUDGEABLE — missing_temporal_axis. A shift check
# added ahead of the axis check would change which reason it reports, and a
# frozen result whose reason moves is not frozen.

# Inside main(), not across the module. The first version of this point
# searched the whole file, where `from caro.appraisal import
# distribution_shift` sits above everything and would have matched — failing
# the implementation for having an import in the usual place. The property
# is about the ORDER OF THE CHECKS, so it is asserted where the checks are.
MSRC = inspect.getsource(BC.main)
_axis = MSRC.find("missing_temporal_axis")
_shift = MSRC.find("distribution_shift")
check("the missing-axis refusal still comes first",
      _axis != -1 and (_shift == -1 or _axis < _shift),
      "a corpus with no temporal axis must refuse on the axis, before "
      "anything is measured about distributions that do not exist")

check("nothing added here can turn a refusal into a number",
      "PROTOCOL" in RSRC and 'PROTOCOL = "temporal"' in RSRC,
      "the protocol is what the verdict is about; it does not become a "
      "flag because a new state was added")

print()
if FAILS:
    print(f"{len(FAILS)} of {TOTAL} contract points are NOT met yet.")
    print("That is this file's purpose. Each line above is a thing the")
    print("implementation must do; none of them is a thing it may choose.")
    for f in FAILS:
        print(f"  · {f}")
    raise SystemExit(1)
print("shift contract: every point met — wire this into tests/run_all.py")
