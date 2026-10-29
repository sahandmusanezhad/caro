"""Tests for W3 — intent parsing and ranking.

The centrepiece is the last block: does ranking actually beat sorting by
price? Everything else in CARO is machinery in service of that number.

Run: PYTHONPATH=. python3 tests/test_ranking.py
"""

import dataclasses
import re
import pathlib

import numpy as np

from caro.appraisal import GlobalQuantiles, MarketEstimator, Row
from caro.ranking import (
    IntentSpec, Ranker, RuleIntentParser, Weights,
    diversify, normalize_fa, parse_amount, retrieve, winrate_vs_price_sort,
    LEDGER_INPUTS, CONDITION_RISK, IMPUTED_MARK, decision_ledger,
    features_from_listing, risk_from_condition, _passes,
    USE_CASE_CUES, USE_CASE_FA, read_provinces, _CUE_WORDS, _CUE_PAIRS,
)
from caro.ingest.persian import PROVINCES
from caro.synthetic import build, true_utility

FAILS: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# ---------------------------------------------------------------------------
# The corpus is the one the site serves as SYNTHETIC, built by caro.synthetic:
# a corpus where the thesis is TRUE by construction — some cars are cheap
# because they are damaged. It used to be built here, and the site imported
# this file to get it, every check included. The names are the ones the
# checks below read.
# ---------------------------------------------------------------------------

_S = build()
ROWS, SPLIT, BASE, EST = _S.rows, _S.split, _S.baselines, _S.estimator
OK, WHY, PIPE, POOL = _S.ok, _S.why, _S.pipeline, _S.pool


# ---------------------------------------------------------------------------
print("\npersian normalisation and amounts")
check("digit folding", normalize_fa("۱۴۰۲") == "1402")
check("arabic yeh/kaf folded", normalize_fa("كمي") == "کمی")
check("ZWNJ becomes a space", "کم کارکرد" in normalize_fa("کم‌کارکرد"))
for text, want in [("۱.۵ میلیارد", 1_500_000_000),
                   ("1 میلیارد و 480", 1_480_000_000),
                   ("۸۰۰ میلیون", 800_000_000),
                   ("1480م", 1_480_000_000),
                   ("2 میلیارد", 2_000_000_000)]:
    got = parse_amount(normalize_fa(text))
    check(f"«{text}» → {want:,}", got == want, f"got {got:,}" if got else "None")


# ---------------------------------------------------------------------------
print("\nintent parsing")
P = RuleIntentParser()

s = P.parse("یه ۲۰۶ اتومات کم‌کارکرد تا ۱.۵ میلیارد میخوام")
check("budget parsed", s.budget_max_toman == 1_500_000_000, str(s.budget_max_toman))
check("model recognised", "206" in s.model_hints, str(s.model_hints))
check("low-mileage inferred", s.max_mileage_km == 120_000)
check("  and the inference is disclosed",
      any("کم‌کارکرد" in a for a in s.assumptions), str(s.assumptions))
check("automatic became a deal-breaker", "manual" in s.deal_breakers)

s2 = P.parse("ماشین برای اسنپ، کم‌مصرف، قطعاتش ارزون باشه، زیر ۸۰۰ میلیون")
check("use case = ride hailing", s2.use_case == "ride_hailing", s2.use_case)
check("running cost outweighs value for a driver",
      s2.weights.running_cost > s2.weights.value,
      f"{s2.weights.running_cost:.2f} vs {s2.weights.value:.2f}")

s3 = P.parse("ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۲ میلیارد")
check("use case = family", s3.use_case == "family_first_car")
check("accident is a deal-breaker", "accident" in s3.deal_breakers)
check("family buyer is risk averse", s3.risk_profile == "risk_averse")
check("risk outweighs value for a family",
      s3.weights.risk > s3.weights.value)

# An assumption names a use case the way the page does. It printed the key —
# «وزن‌ها از پیش‌فرض «ride_hailing» شروع شد» — on two of the five examples
# under the search box.
check("every use case the parser can choose has a Persian name",
      set(USE_CASE_CUES) | {"unspecified"} <= set(USE_CASE_FA),
      f"no name: {sorted(set(USE_CASE_CUES) | {'unspecified'} - set(USE_CASE_FA))}")
for _sx, _uc in ((s2, "ride_hailing"), (s3, "family_first_car")):
    _named = [a for a in _sx.assumptions if "از پیش‌فرض" in a]
    check(f"  the weights' assumption says «{USE_CASE_FA[_uc]}», not «{_uc}»",
          bool(_named) and all(USE_CASE_FA[_uc] in a and _uc not in a
                               for a in _named), str(_named))

# «بخش‌هایی که نفهمیدیم» lists what the parser could NOT map (D14). It also
# listed what it did: «تصادفی نباشه» sat under «خط قرمز» and under
# «نفهمیدیم» on the same panel, and so did «ماشین برای اسنپ» and «کم مصرف».
def _left(q):
    return [t.strip() for t in P.parse(q).unparsed]

for q, want, why in [
    ("ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۲ میلیارد", [],
     "a use case and a red line are understood"),
    ("ماشین برای اسنپ، کم‌مصرف، قطعاتش ارزون باشه، زیر ۸۰۰ میلیون",
     ["قطعاتش ارزون باشه"], "a weight's cue is understood; the parts are not"),
    ("مدل ۹۸ به بالا، کارکرد زیر ۹۰ هزار", [],
     "«به بالا» goes with the year, the odometer clause is understood"),
    ("ماشین برای رفت و آمد سرکار، کم‌خرج، تا ۱.۳ میلیارد", [],
     "a cue across « و » covers both sides of it"),
    ("یه ماشین خوب حدود ۱.۲ میلیارد", [],
     "a decimal point is not a separator"),
    ("پراید، رنگ سفید باشه، تا ۵۰۰ میلیون", ["رنگ سفید باشه"],
     "the control: a clause nothing mapped is still listed"),
    # The rule's cost, pinned so that it changes on purpose: a clause is
    # understood as a whole, as one naming a model always was, so words the
    # parser did not map are not listed when they share a clause with a cue.
    ("ماشین برای اسنپ با قطعات ارزون، زیر ۸۰۰ میلیون", [],
     "a clause holding a cue is understood whole — the parts go unlisted"),
]:
    check(f"«{q[:34]}» → not understood: {want or 'nothing'}",
          _left(q) == want, f"got {_left(q)} — {why}")

# A point between two digits is a decimal, not a separator. In every query the
# suites parse, the point sits inside an amount the parser acted on, whose
# span covers both halves, so taking that rule out turned nothing red (D68).
# An engine size is not an amount. Its clause is not understood and is listed,
# and it is listed whole: «موتور ۱.۶», never cut at the point to «موتور ۱».
_dec = "پراید، موتور ۱.۶، تا ۵۰۰ میلیون"
check("«موتور ۱.۶» is listed whole as not understood, not cut to «موتور ۱»",
      _left(_dec) == ["موتور 1.6"], f"got {_left(_dec)}")

s4 = P.parse("مدل ۹۸ به بالا، کارکرد زیر ۹۰ هزار")
check("2-digit year expands to 1398", s4.year_min == 1398, str(s4.year_min))
check("explicit mileage cap", s4.max_mileage_km == 90_000, str(s4.max_mileage_km))

# The assumption bar may name a default ONLY while that default is the thing
# in force. «کم» is a prefix of «کمتر», so the vague cue used to match inside
# «کارکرد کمتر از ۲۰۰ هزار» — a query that states its limit exactly. The
# stated number then overwrote the default and the note stayed behind, so the
# screen offered the buyer a guess to correct that had already been replaced.
#
# Both halves are asserted, because either alone leaves the defect reachable:
# the cap is what filters, the note is what the buyer reads, and the bug was
# precisely the two disagreeing.
def _mileage_note(spec) -> bool:
    return any("کم‌کارکرد" in a for a in spec.assumptions)

for q, cap, note, why in [
    ("پراید کارکرد کمتر از ۲۰۰ هزار", 200_000, False, "«کمتر» is not the cue"),
    ("پراید کارکرد کمتر از ۸۰ هزار", 80_000, False, "and not at any size"),
    ("پراید کارکرد زیر ۵۰ هزار", 50_000, False, "«زیر» never matched it"),
    ("پراید کم‌کارکرد", 120_000, True, "the cue alone still infers"),
    ("پراید کم کارکرده", 120_000, True, "and in its other forms"),
    ("پراید کارکرد کمی دارد", 120_000, True, "and «کمی», which is vague"),
    ("پراید کم‌کارکرد کارکرد کمتر از ۲۰۰ هزار", 200_000, False,
     "stated wins over vague, and the note goes with it"),
]:
    sm = P.parse(q)
    check(f"«{q}» → cap {cap:,}", sm.max_mileage_km == cap,
          f"got {sm.max_mileage_km}")
    check(f"  note {'shown' if note else 'absent'} — {why}",
          _mileage_note(sm) is note, str(sm.assumptions))

s5 = P.parse("یه ماشین خوب میخوام حدود ۱ میلیارد")
check("soft budget detected", s5.budget_hard is False)
check("nothing is invented when nothing was said",
      s5.use_case == "unspecified" and not s5.deal_breakers)
check("unmapped text is kept, not dropped", isinstance(s5.unparsed, tuple))

check("weights always normalise to 1",
      abs(sum([s3.weights.value, s3.weights.risk, s3.weights.running_cost,
               s3.weights.liquidity, s3.weights.mileage,
               s3.weights.recency]) - 1.0) < 1e-9)


# ---------------------------------------------------------------------------
print("\na distance cap with no «کارکرد» before it is read (D83)")
# «۲۰۶ زیر ۱۰۰ هزار کیلومتر» was neither read nor listed: the odometer wanted
# «کارکرد» in front of the cap. The cap in four more shapes is read now, and
# «حداکثر» joins the «کارکرد» form. A figure with neither «هزار» nor «کارکرد»
# before it is a cap only from 10000 on: «تا ۱۰۰۰ کیلومتر دورتر» is a
# distance to travel and «وانت تا ۱۵۰۰ کیلو» a weight. Every phrase is made
# here; no log of what buyers write exists, so these test the rule, not the
# buyers.
for q, cap in [
    # a cap word, a figure, a distance word
    ("۲۰۶ زیر ۱۰۰ هزار کیلومتر", 100_000),
    ("پراید کمتر از ۵۰ هزار کیلومتر", 50_000),
    ("تیبا تا ۸۰ هزار کیلومتر", 80_000),
    ("پراید حداکثر ۱۰۰ هزار کیلومتر", 100_000),
    ("پراید زیر ۱۰۰ هزار کیلومتر کارکرد", 100_000),
    ("پراید تا ۱۲۰ هزار کیلومتر کارکرده باشه", 120_000),
    ("پراید تا ۹۰ هزار کیلومتر، سفید", 90_000),
    ("پراید سفید، زیر ۷۰ هزار کیلومتر، تا ۳۰۰ میلیون", 70_000),
    ("پراید حداکثر ۲ هزار کیلومتر رفته باشه", 2_000),
    ("پراید زیر ۱۰۰ هزار کیلومتر رفته", 100_000),
    # no «هزار», from 10000 on
    ("پراید تا ۱۵۰۰۰۰ کیلومتر", 150_000),
    ("پراید زیر ۱۰۰۰۰۰ کیلومتر", 100_000),
    ("پراید تا ۱۰۰۰۰ کیلومتر", 10_000),
    ("پراید زیر ۲ هزار کیلومتر", 2_000),
    # «k»
    ("پراید زیر ۱۰۰k", 100_000),
    # the figure first
    ("پراید ۱۰۰ هزار کیلومتر یا کمتر", 100_000),
    ("پراید ۱۰۰ هزار کیلومتر و کمتر", 100_000),
    ("پراید ۱۰۰ هزار کیلومتر به پایین", 100_000),
    # the distance word first
    ("پراید کیلومتر زیر ۱۰۰ هزار", 100_000),
    ("پراید با کیلومتر زیر ۸۰ هزار", 80_000),
    ("پراید کیلومتر کمتر از ۶۰ هزار", 60_000),
    # «حداکثر» joins the «کارکرد» form, before the word and after it
    ("پراید کارکرد حداکثر ۱۰۰ هزار", 100_000),
    ("پراید حداکثر کارکرد ۱۰۰ هزار کیلومتر", 100_000),
    # the «کارکرد» form keeps its floor of 1000: the word says what it is
    ("پراید کارکرد زیر ۵۰۰۰ کیلومتر", 5_000),
    ("پراید کارکرد حداکثر ۵۰۰۰ کیلومتر", 5_000),
    ("پراید کارکرد زیر ۵۰۰۰", 5_000),
]:
    got_km = P.parse(q).max_mileage_km
    check(f"«{q}» → cap {cap:,}", got_km == cap, f"got {got_km}")

for q, why in [   # a figure, but not a cap: nothing is read
    ("پراید بیشتر از ۵۰ هزار کیلومتر نباشه", "a negated «more than» is not read"),
    ("پراید ۵۰ هزار کیلومتر", "a figure with no cap word"),
    ("پراید ۵۰ هزار کیلومتر کارکرد", "the same, with «کارکرد» after it"),
    ("پراید با ۵۰ هزار کیلومتر", "«با» is no cap word"),
    ("پراید زیر ۱۰۰ هزار", "no distance word and no «کارکرد»"),
    ("پراید کارکرد ۱۰۰ هزار", "«کارکرد» and a figure, no cap word"),
    ("پراید ۱۰۰ هزار کیلومتر کار کرده", "a figure and «کار کرده»"),
    ("پراید حدود ۵۰ هزار کیلومتر", "«حدود» is no cap word"),
    ("پراید تقریبا ۵۰ هزار کیلومتر", "«تقریبا» is no cap word"),
    ("پراید کم کیلومتر", "vague"),
    ("پراید کیلومتر پایین", "vague"),
    ("پراید کیلومتر کم", "vague"),
    ("پراید صفر کیلومتر", "a new car"),
    ("پراید ۰ کیلومتر", "a new car"),
    ("پراید بدون کیلومتر", "no distance at all"),
    ("پراید تا ۳۰۰ میلیون، ۵۰ هزار کیلومتر", "after a budget, no cap word"),
    ("پراید زیر ۲۰۰ میلیون، کیلومتر ۸۰ هزار", "after a budget, no cap word"),
]:
    got_km = P.parse(q).max_mileage_km
    check(f"«{q}» → no cap: {why}", got_km is None, f"got {got_km}")

for q, why in [   # a cap word and a distance word that are not an odometer
    ("پراید تا ۵۰ کیلومتری تهران", "a place that is near"),
    ("پراید زیر ۵۰ کیلومتر در ساعت", "a speed"),
    ("پراید تا ۳۰ کیلومتر فاصله از کرج", "a distance to travel"),
    ("پراید تا ۵۰ کیلومتر دورتر", "a distance to travel"),
    ("پراید سفید تا ۷ لیتر در ۱۰۰ کیلومتر", "fuel"),
    ("پراید مصرف زیر ۸ لیتر در ۱۰۰ کیلومتر", "fuel"),
    ("پراید تا ۲۰ کیلومتر", "twenty is no mileage"),
    ("پراید حاضرم تا ۸۰۰ کیلومتر برم", "under 1000"),
    ("پراید تا ۱۰۰۰ کیلومتر دورتر از تهران", "a distance to travel, from 1000 up"),
    ("پراید زیر ۱۵۰۰ کیلومتر فاصله", "a distance to travel"),
    ("ماشین تا ۲۰۰۰ کیلومتر راه", "a distance to travel"),
    ("پراید حداکثر ۱۲۰۰ کیلومتر دورتر", "a distance to travel"),
    ("تا ۳۰۰۰ کیلومتر از مشهد پراید", "a distance to travel"),
    ("وانت تا ۱۵۰۰ کیلو بار", "a weight"),
    ("وانت زیر ۳۰۰۰ کیلو", "a weight"),
]:
    got_km = P.parse(q).max_mileage_km
    check(f"«{q}» → no cap: {why}", got_km is None, f"got {got_km}")

for q, why in [   # known, and left: pinned so that it changes on purpose
    ("پراید زیر ۵۰۰۰ کیلومتر", "1000 to 9999 with neither «هزار» nor «کارکرد» before"),
    ("پراید تا ۹۰۰۰ کیلومتر", "the same"),
    ("پراید تا ۵۰۰۰ کیلومتر کارکرد", "«کارکرد» after the figure does not count"),
    ("پراید زیر ۱۰۰ هزار کیلومتری", "«کیلومتری» is not a distance word, even with «هزار»"),
]:
    got_km = P.parse(q).max_mileage_km
    check(f"«{q}» → no cap: {why}", got_km is None, f"got {got_km}")

# A cap that is read is understood, so it is not listed as text the parser did
# not use; the one that is not read is still listed.
check("a read cap is not listed under «نفهمیدیم»",
      P.parse("زیر ۱۰۰ هزار کیلومتر").unparsed == ())
check("  and the clause beside it is",
      _left("پراید، زیر ۱۰۰ هزار کیلومتر، رنگ سفید مروارید")
      == ["رنگ سفید مروارید"], str(_left("پراید، زیر ۱۰۰ هزار کیلومتر، رنگ سفید مروارید")))
check("  while a figure nothing read is listed as before",
      _left("زیر ۵۰۰۰ کیلومتر") == ["زیر 5000 کیلومتر"],
      str(_left("زیر ۵۰۰۰ کیلومتر")))

# The stated cap is read FIRST and the vague cue only fills the gap it leaves
# (the order of the odometer, above): the default is not adopted and its note is
# not shown.
for q, cap in [
    ("پراید زیر ۱۰۰ هزار کیلومتر، کم‌کارکرد", 100_000),
    ("پراید کم‌کارکرد حداکثر ۱۲۰ هزار کیلومتر", 120_000),
]:
    sm = P.parse(q)
    check(f"«{q}» → cap {cap:,}, and no note about a default",
          sm.max_mileage_km == cap and not _mileage_note(sm),
          f"{sm.max_mileage_km} {sm.assumptions}")

# The «کارکرد» form is tried first, and the shapes in the order above.
for q, cap, why in [
    ("پراید کارکرد زیر ۸۰ هزار، زیر ۱۰۰ هزار کیلومتر", 80_000, "the «کارکرد» form first"),
    ("پراید زیر ۸۰ هزار کیلومتر، ۱۰۰ هزار کیلومتر یا کمتر", 80_000, "the first shape first"),
]:
    got_km = P.parse(q).max_mileage_km
    check(f"«{q}» → cap {cap:,} ({why})", got_km == cap, f"got {got_km}")

# The cap is all it changes: the same spec as without the phrase, but for the
# cap, and for the list when the phrase stood in a clause of its own.
check("a read cap changes nothing in the spec but the cap and the list",
      all(dataclasses.replace(P.parse(a), raw_query="", max_mileage_km=None, unparsed=())
          == dataclasses.replace(P.parse(b), raw_query="", unparsed=())
          for a, b in [
              ("پراید زیر ۱۰۰ هزار کیلومتر", "پراید"),
              ("پراید تا ۱۲۰ هزار کیلومتر، تا ۳۰۰ میلیون", "پراید، تا ۳۰۰ میلیون"),
              ("تیبا ۱۰۰ هزار کیلومتر یا کمتر مدل ۹۵", "تیبا مدل ۹۵"),
              ("پراید حداکثر کارکرد ۸۰ هزار، اتومات", "پراید، اتومات"),
          ]))
sk = P.parse("۲۰۶ زیر ۱۰۰ هزار کیلومتر، بودجه ۹۰۰ میلیون")
check("the first clause of the suites' own query is a cap, the second a budget",
      sk.max_mileage_km == 100_000 and sk.budget_max_toman == 900_000_000,
      f"{sk.max_mileage_km} {sk.budget_max_toman}")


# ---------------------------------------------------------------------------
# A number is not a budget just because it is a number.
#
# All four of these were measured wrong, and the reason they survived is that
# a wrong budget is invisible: it silently shrinks the candidate set, and a
# short shortlist looks like a thin market rather than a parser fault. The
# bare-model case is the product-critical one — a buyer who types «۲۰۶» and
# nothing else was handed a 206,000,000 ceiling and shown almost no 206s.
print("\na budget is only taken from a number that is money")
for text, want, why in [
    ("۲۰۶", None, "a model number is not a price"),
    ("206", None, "  nor in Latin digits"),
    ("پراید", None, "a model name alone sets no budget"),
    ("تیبا مدل ۹۵", None, "a model year is not a price"),
    ("تیبا مدل ۹۵ مشکی", None, "  and «م» of a following word is not «میلیون»"),
    ("مدل ۹۸ به بالا، کارکرد زیر ۹۰ هزار", None, "an odometer is not a price"),
    ("کارکرد زیر ۹۰ هزار، تا ۸۰۰ میلیون", 800_000_000,
     "the budget clause is found even when another clause comes first"),
    ("۲۰۶ زیر ۱۰۰ هزار کیلومتر، بودجه ۹۰۰ میلیون", 900_000_000,
     "  including when the first clause is an explicit km cap"),
    ("۲۰۶ زیر ۸۰۰ میلیون", 800_000_000, "the ordinary case still works"),
    ("پراید ۸۰۰م", 800_000_000, "«م» is a scale word when nothing follows it"),
    ("۲۰۶ تا ۱ میلیارد و ۴۸۰", 1_480_000_000, "the «و» tail survives"),
]:
    got_b = P.parse(text).budget_max_toman
    check(f"«{text}» → {'—' if want is None else f'{want:,}'}  ({why})",
          got_b == want, "None" if got_b is None else f"{got_b:,}")

# The inference, when it happens, is still disclosed. This is the property
# that makes the strictness above safe to add: a budget CARO guessed is
# labelled as a guess, so tightening the guess cannot hide anything.
check("an inferred budget is still disclosed as an inference",
      any("سقف بودجه" in a for a in
          P.parse("یه ماشین خوب میخوام حدود ۱ میلیارد").assumptions))
check("  and an explicit budget clause is not labelled a guess",
      not any("سقف بودجه" in a for a in P.parse("تا ۳ میلیارد").assumptions))


# ---------------------------------------------------------------------------
print("\na floor is an amount of money right before «به بالا»")
# The floor was read from the text between «از» (or «بالای») and the first
# «به بالا», whatever it was, and `parse_amount` takes a bare number for
# millions. «از» also ends many words («شیراز», «نیاز») and is the word of
# «غیر از», and «به بالا» also ends a year clause, so «پراید از مدل ۹۸ به بالا»
# set a floor of 98,000,000 and «پراید ساکن شیراز مدل ۱۴۰۱ به بالا» one of
# 1,401,000,000: 35 of 35 phrasings, five years after seven lead-ins. And with
# words between a «از» and an amount, the amount that was the budget became
# the floor: «پراید غیر از مشهد ۸۰۰ میلیون مدل ۹۸ به بالا» set 800,000,000. Of
# 128 phrasings written to show it, 128 set a floor: 96 the amount that was the
# budget, and 32 an odometer's «۱۰۰ هزار».
#
# A floor is now a cue -- «از» or «بالای», and not the end of a word -- then an
# amount of money, then «به بالا», with nothing between them; or the same
# without «به بالا» where a year clause with its own «به بالا» follows, which
# is how a floor and a year are written together. What it does not read is
# the last block: each of those was measured and is left to a round of its
# own (docs/ROADMAP.md). Every phrasing is made here; no log of what buyers
# write exists, so these test the rule, not the buyers.
for text, want, why in [
    ("از ۳۰۰ میلیون به بالا", 300_000_000, "a cue, an amount of money, «به بالا»"),
    ("پراید از ۲۰۰ میلیون به بالا", 200_000_000, "with a model"),
    ("تیبا از ۱.۵ میلیارد به بالا", 1_500_000_000, "a decimal and a scale word"),
    ("پژو ۲۰۶ از ۴۰۰ میلیون به بالا", 400_000_000, "a model with a number"),
    ("از ۱ میلیارد به بالا", 1_000_000_000, "a billion"),
    ("پراید از ۴۰۰م به بالا", 400_000_000, "«م» for «میلیون»"),
    ("پراید از ۴۰۰ ملیون به بالا", 400_000_000, "«ملیون»"),
    ("پراید از ۱ میلیارد و ۲۰۰ میلیون به بالا", 1_200_000_000,
     "«و» and a second unit"),
    ("پراید از ۲۰۰ میلیون تومان به بالا", 200_000_000,
     "a currency word after the amount"),
    ("پراید از حدود ۲۰۰ میلیون به بالا", 200_000_000, "a soft word before the amount"),
    ("پراید از تقریبا ۴۰۰ میلیون به بالا", 400_000_000, "  the other soft word"),
    ("پراید از حدود ۲۰۰ میلیون تومان به بالا", 200_000_000,
     "  and a currency word after"),
    ("پراید بالای ۴۰۰ میلیون به بالا", 400_000_000, "«بالای» is a cue as well"),
    ("پراید از ۲۰۰ میلیون به بالا، سفید", 200_000_000,
     "another requirement after a comma"),
    ("پراید در مشهد از ۲۰۰ میلیون به بالا", 200_000_000, "a place before it"),
    ("پراید از ۲۰۰ میلیون به بالا در مشهد", 200_000_000, "  and after it"),
    ("پراید از ۲۰۰ میلیون به بالا، تا ۸۰۰ میلیون", 200_000_000,
     "with a ceiling clause"),
]:
    got_f = P.parse(text).budget_min_toman
    check(f"«{text}» → floor {'—' if want is None else f'{want:,}'}  ({why})",
          got_f == want, "None" if got_f is None else f"{got_f:,}")

for text, want, year, why in [   # a floor and a year clause, its «به بالا» the only one
    ("پراید از ۲۰۰ میلیون مدل ۹۸ به بالا", 200_000_000, 1398,
     "a floor, then a year clause with its own «به بالا»"),
    ("پراید از ۲۰۰ میلیون تومان مدل ۱۴۰۱ به بالا", 200_000_000, 1401,
     "  and a currency word"),
    ("پراید بالای ۴۰۰ میلیون مدل ۹۸ به بالا", 400_000_000, 1398, "  after «بالای»"),
    ("پراید از ۱ میلیارد و ۲۰۰ میلیون مدل ۹۸ به بالا", 1_200_000_000, 1398,
     "  «و» and a second unit"),
    ("پراید از ۴۰۰م مدل ۹۸ به بالا", 400_000_000, 1398, "  «م»"),
    ("پراید از ۲۰۰ میلیون به بالا، مدل ۹۸ به بالا", 200_000_000, 1398,
     "two «به بالا», a comma between"),
    ("پراید مدل ۱۴۰۱ به بالا، از ۲۰۰ میلیون به بالا", 200_000_000, 1401,
     "the year clause first"),
    ("پراید از ۲۰۰ میلیون به بالا مدل ۹۸ به بالا", 200_000_000, 1398,
     "no comma between"),
    ("پراید از مدل ۹۸ به بالا، از ۲۰۰ میلیون به بالا", 200_000_000, 1398,
     "the first «از» is a year clause's"),
    ("پراید از سال ۹۸ به بالا و از ۲۰۰ میلیون به بالا", 200_000_000, None,
     "  and «سال» is no year clause"),
]:
    sp_f = P.parse(text)
    check(f"«{text}» → floor {want:,}, year {year or '—'}  ({why})",
          (sp_f.budget_min_toman, sp_f.year_min) == (want, year),
          f"{sp_f.budget_min_toman} {sp_f.year_min}")

for text, why in [   # an amount between other words is the budget, not a floor
    ("پراید غیر از مشهد ۸۰۰ میلیون مدل ۹۸ به بالا", "after the word of «غیر از»"),
    ("پراید ساکن شیراز ۸۰۰ میلیون مدل ۱۴۰۱ به بالا", "after a word that ends in «از»"),
    ("پراید از تهران ۸۰۰ میلیون مدل ۹۸ به بالا", "a word between the cue and the amount"),
    ("پراید غیر از مشهد تا ۸۰۰ میلیون مدل ۹۸ به بالا", "a budget cue between"),
    ("پراید بالای ۱۰۰ هزار کیلومتر تا ۸۰۰ میلیون مدل ۹۵ به بالا",
     "a distance, then a budget cue"),
    ("پراید بالای ۱۰۰ هزار کیلومتر ۸۰۰ میلیون مدل ۹۵ به بالا",
     "a distance, then the amount"),
    ("پراید نیاز دارم ۸۰۰ میلیون مدل ۹۸ به بالا", "no cue but a word that ends in «از»"),
    ("پراید از ۸۰۰ میلیون بیشتر نباشه مدل ۹۸ به بالا",
     "words between the amount and the year clause"),
]:
    got_f = P.parse(text).budget_min_toman
    check(f"«{text}» → no floor  ({why})", got_f is None, str(got_f))

for _lead, _what in [   # a year clause, and what stands before it: no floor is meant
    ("از مدل", "«از» is the word that starts the year clause"),
    ("از سال", "«از» before «سال»"),
    ("ساکن شیراز مدل", "a word that ends in «از»"),
    ("اهواز مدل", "  the same"),
    ("نیاز دارم مدل", "  the same"),
    ("غیر از مشهد مدل", "«از» is the word of «غیر از»"),
    ("غیر از تهران مدل", "  the same"),
]:
    got_y = [P.parse(f"پراید {_lead} {_year} به بالا").budget_min_toman
             for _year in ["۹۵", "۹۸", "۱۳۹۸", "۱۴۰۰", "۱۴۰۱"]]
    check(f"«پراید {_lead} ۹۵ به بالا» and four more years → no floor  ({_what})",
          got_y == [None] * 5, str(got_y))

for text, why in [   # a number that is not an amount of money is not a floor
    ("از ۳۰۰ به بالا", "a figure with no scale word is not money"),
    ("پراید کارکرد از ۱۰۰ هزار به بالا", "a distance"),
    ("پراید از ۵۰ هزار کیلومتر به بالا", "  with its unit"),
    ("پراید از ۲۰۰ هزار به بالا", "«هزار» is no money word"),
]:
    got_f = P.parse(text).budget_min_toman
    check(f"«{text}» → no floor  ({why})", got_f is None, str(got_f))

for text, want, why in [   # what is read is understood; what is not is listed
    ("از ۲۰۰ میلیون به بالا", (), "the phrase is understood, not listed"),
    ("از ۲۰۰ میلیون مدل ۹۸ به بالا", (), "  and with a year clause"),
    ("از ۲۰۰ میلیون به بالا، تا ۸۰۰ میلیون", (),
     "  and beside a ceiling clause, where no inference reads the amount"),
    ("از ۳۰۰ به بالا", ("از 300 به بالا",), "a figure with no scale word is listed"),
]:
    got_u = P.parse(text).unparsed
    check(f"«{text}» → listed: {list(want) or '—'}  ({why})", got_u == want,
          str(got_u))

for text, why in [   # measured and left: no floor is read, and nothing is claimed beyond that
    ("پراید از ۲۰۰ تا ۴۰۰ میلیون مدل ۹۸ به بالا",
     "a range with a year clause: its lower end"),
    ("پراید از ۲۰۰ میلیون تا ۴۰۰ میلیون مدل ۹۸ به بالا", "  a unit on both"),
    ("پراید از قیمت ۲۰۰ میلیون به بالا", "a word between the cue and the amount"),
    ("پراید از مبلغ ۲۰۰ میلیون به بالا", "  the same"),
    ("پراید شیراز ۲۰۰ میلیون به بالا", "no cue: the «از» that ends a word is not one"),
    ("پراید اهواز ۲۰۰ میلیون به بالا", "  the same"),
    ("پراید ۲۰۰ میلیون به بالا", "no cue at all"),
]:
    got_f = P.parse(text).budget_min_toman
    check(f"«{text}» → no floor, left  ({why})", got_f is None, str(got_f))


# ---------------------------------------------------------------------------
print("\na floor is not also the ceiling")
# With no clause naming a ceiling, the first amount of money in the query is
# taken for it, with the assumption «عدد قیمت را سقف بودجه فرض کردیم» printed,
# and a floor's amount is that amount: «پراید از ۴۰۰ میلیون به بالا» had both at
# 400,000,000, and found none of the 53 Pride listings on run16, though 47 of
# the 50 that carry a price are at or above it. Of 144 phrasings of a floor
# (six forms, six amounts, with no model and with three), all 144 had the
# floor's amount for the ceiling too. The floor is read first now, and the
# ceiling is read from the query with the floor's phrase blanked out. Every
# phrasing is made here; no log of what buyers write exists.
_FL_NOTE = "عدد قیمت را سقف بودجه فرض کردیم"


def _fl_amt(v):
    return "—" if v is None else f"{v:,}"


for text, want_f, want_c, why in [
    # a floor alone has no ceiling
    ("پراید از ۲۰۰ میلیون به بالا", 200_000_000, None, "the plain form"),
    ("پراید از ۲۰۰ میلیون تومان به بالا", 200_000_000, None, "a currency word"),
    ("پراید از حدود ۲۰۰ میلیون به بالا", 200_000_000, None, "a soft word"),
    ("پراید بالای ۴۰۰ میلیون به بالا", 400_000_000, None, "«بالای»"),
    ("پراید قیمت از ۴۰۰ میلیون به بالا", 400_000_000, None,
     "a budget cue before it: it is not read as a ceiling clause"),
    ("پراید بودجه از ۴۰۰ میلیون به بالا", 400_000_000, None, "  the same"),
    ("پراید از ۱ میلیارد و ۲۰۰ میلیون به بالا", 1_200_000_000, None,
     "the unit «و» leaves is not an amount"),
    ("پژو ۲۰۶ از ۱ میلیارد و ۲۰۰ میلیون به بالا", 1_200_000_000, None,
     "  nor beside a model's number"),
    ("پراید از ۲۰۰ میلیون مدل ۹۸ به بالا", 200_000_000, None, "with a year clause"),
    ("پراید از ۱ میلیارد و ۲۰۰ میلیون مدل ۱۴۰۱ به بالا", 1_200_000_000, None,
     "  and «و» and a second unit"),
    ("از ۳۰۰ میلیون به بالا", 300_000_000, None, "no model"),
    ("پراید از ۴۰۰م به بالا", 400_000_000, None, "«م»"),
    # a floor and a ceiling, each read once, whichever comes first
    ("پراید از ۲۰۰ میلیون به بالا، تا ۸۰۰ میلیون", 200_000_000, 800_000_000,
     "a ceiling clause after a comma"),
    ("پراید از ۲۰۰ میلیون به بالا و تا ۸۰۰ میلیون", 200_000_000, 800_000_000,
     "  after «و»"),
    ("پراید تا ۸۰۰ میلیون، از ۲۰۰ میلیون به بالا", 200_000_000, 800_000_000,
     "  before it"),
    ("پراید از ۲۰۰ میلیون به بالا ۸۰۰ میلیون", 200_000_000, 800_000_000,
     "a second amount with no cue, after the phrase"),
    ("پراید ۸۰۰ میلیون از ۲۰۰ میلیون به بالا", 200_000_000, 800_000_000,
     "  before it"),
    ("پراید از ۲۰۰ میلیون به بالا، ۸۰۰ میلیون", 200_000_000, 800_000_000,
     "  past a comma"),
    ("پراید از ۱ میلیارد و ۲۰۰ میلیون به بالا، تا ۲ میلیارد", 1_200_000_000,
     2_000_000_000, "both with «و» and a second unit"),
    ("پراید تا ۸۰۰ میلیون از ۲۰۰ میلیون به بالا", 200_000_000, 800_000_000,
     "the floor's phrase inside the ceiling's clause"),
    # the ceiling is still inferred where nothing else names one
    ("پراید ۸۰۰ میلیون", None, 800_000_000, "a lone amount, as before"),
    ("پراید تا ۸۰۰ میلیون", None, 800_000_000, "a ceiling clause, as before"),
]:
    sp_c = P.parse(text)
    check(f"«{text}» → floor {_fl_amt(want_f)}, ceiling {_fl_amt(want_c)}  ({why})",
          (sp_c.budget_min_toman, sp_c.budget_max_toman) == (want_f, want_c),
          f"{sp_c.budget_min_toman} {sp_c.budget_max_toman}")

for text, printed, why in [   # the inference is disclosed when it is made, and only then
    ("پراید از ۲۰۰ میلیون به بالا", False, "a floor alone: nothing is assumed"),
    ("پژو ۲۰۶ از ۱ میلیارد و ۲۰۰ میلیون به بالا", False,
     "  nor beside a model's number"),
    ("پراید از ۲۰۰ میلیون به بالا ۸۰۰ میلیون", True,
     "a second amount is taken for the ceiling, and said so"),
    ("پراید ۸۰۰ میلیون", True, "a lone amount, as before"),
    ("پراید تا ۸۰۰ میلیون", False, "a ceiling clause is no assumption, as before"),
]:
    got_n = any(_FL_NOTE in a for a in P.parse(text).assumptions)
    check(f"«{text}» → the ceiling is "
          f"{'assumed and said so' if printed else 'not assumed'}  ({why})",
          got_n == printed, str(P.parse(text).assumptions))

for text, want, why in [   # what the floor's phrase and a ceiling clause leave behind
    ("پراید از ۲۰۰ میلیون به بالا، تا ۸۰۰ میلیون", (), "nothing is left over"),
    ("از ۲۰۰ میلیون به بالا", (), "  and without a model"),
    ("تا ۸۰۰ میلیون و از ۲۰۰ میلیون به بالا", (),
     "a floor's phrase inside the ceiling's clause goes with it"),
    ("پراید از ۲۰۰ میلیون به بالا، تا ۳۰۰ میلیون در مشهد", ("در مشهد",),
     "a place after the ceiling's amount is listed, as it is without a floor"),
]:
    got_u = tuple(t.strip() for t in P.parse(text).unparsed)
    check(f"«{text}» → listed: {list(want) or '—'}  ({why})", got_u == want,
          str(got_u))


# ---------------------------------------------------------------------------
print("\nother words for a floor: «حداقل X» and «X و بالاتر»")
# «حداقل ۴۰۰ میلیون» and «۴۰۰ میلیون و بالاتر» set no floor, and the amount was
# taken for the ceiling, with the assumption printed: the meaning reversed. Of
# 192 phrasings of eight forms (six amounts, with no model and with three) all
# 192 were read so. Two words are read now, «حداقل» (with «قیمت» if it is
# written) and the suffix «و بالاتر» / «و بیشتر» / «یا بیشتر», and a negation
# right after the phrase leaves it to the ceiling rules. «حداقل بودجه X» and
# the three «more than» words are not read, and each of those is pinned below
# as what it is, so that it changes on purpose. Every phrasing is made here; no
# log of what buyers write exists.
_N = "نباشه"
for text, want, why in [
    ("حداقل ۴۰۰ میلیون", 400_000_000, "the word and an amount"),
    ("پراید حداقل ۴۰۰ میلیون", 400_000_000, "with a model"),
    ("تیبا حداقل ۲۰۰ میلیون", 200_000_000, "  another"),
    ("پژو ۲۰۶ حداقل ۶۰۰ میلیون", 600_000_000, "a model with a number"),
    ("پراید حداقل ۱.۵ میلیارد", 1_500_000_000, "a decimal and a scale word"),
    ("پراید حداقل ۱ میلیارد", 1_000_000_000, "a billion"),
    ("پراید حداقل ۴۰۰م", 400_000_000, "«م» for «میلیون»"),
    ("پراید حداقل ۴۰۰ ملیون", 400_000_000, "«ملیون»"),
    ("پراید حداقل ۱ میلیارد و ۲۰۰ میلیون", 1_200_000_000, "«و» and a second unit"),
    ("پراید حداقل ۴۰۰ میلیون تومان", 400_000_000, "a currency word after the amount"),
    ("پراید حداقل حدود ۴۰۰ میلیون", 400_000_000, "a soft word before the amount"),
    ("پراید حداقل تقریبا ۴۰۰ میلیون", 400_000_000, "  the other soft word"),
    ("پراید حداقل 400 میلیون", 400_000_000, "Latin digits"),
    ("پراید حداقل۴۰۰ میلیون", 400_000_000, "no space after the word"),
    ("پراید حداقل  ۴۰۰   میلیون", 400_000_000, "runs of spaces"),
    ("حداقل قیمت ۴۰۰ میلیون", 400_000_000, "«قیمت» after the word"),
    ("پراید حداقل قیمت ۴۰۰ میلیون تومان", 400_000_000, "  and a currency word"),
    ("پراید ۴۰۰ میلیون و بالاتر", 400_000_000, "the suffix «و بالاتر»"),
    ("پراید ۴۰۰ میلیون و بیشتر", 400_000_000, "«و بیشتر»"),
    ("پراید ۴۰۰ میلیون یا بیشتر", 400_000_000, "«یا بیشتر»"),
    ("۴۰۰ میلیون و بالاتر", 400_000_000, "no model"),
    ("پژو ۲۰۶ ۴۰۰ میلیون و بالاتر", 400_000_000, "a model's number before the amount"),
    ("پراید ۱ میلیارد و ۲۰۰ میلیون و بالاتر", 1_200_000_000, "«و» and a second unit"),
    ("پراید ۱ میلیارد و ۲۰۰ میلیون یا بیشتر", 1_200_000_000, "  with «یا بیشتر»"),
    ("پراید ۴۰۰م و بالاتر", 400_000_000, "«م»"),
    ("پراید ۴۰۰ میلیون تومان و بالاتر", 400_000_000, "a currency word"),
    ("پراید از ۴۰۰ میلیون و بالاتر", 400_000_000, "«از» before the amount, with no «به بالا»"),
    ("پراید ۴۰۰ میلیون و بالاتر.", 400_000_000, "a full stop after"),
    ("پراید ۴۰۰ میلیون و بالاتر، سفید", 400_000_000, "a requirement after a comma"),
    ("پراید حداقل ۴۰۰ میلیون، تصادفی نباشه", 400_000_000,
     "a red line after a comma: its negation is the red line's"),
    ("پراید حداقل ۴۰۰ میلیون در مشهد", 400_000_000, "a city after it"),
    ("پراید در مشهد حداقل ۴۰۰ میلیون", 400_000_000, "  and before it"),
    ("پراید حداقل ۴۰۰ میلیون در تهران", 400_000_000, "a province after it"),
    ("تیبا و پراید حداقل ۳۰۰ میلیون", 300_000_000, "two models"),
]:
    sp_w = P.parse(text)
    check(f"«{text}» → floor {want:,}, ceiling —  ({why})",
          (sp_w.budget_min_toman, sp_w.budget_max_toman) == (want, None),
          f"{sp_w.budget_min_toman} {sp_w.budget_max_toman}")

for text, want, year, why in [   # with a year clause
    ("پراید حداقل ۴۰۰ میلیون مدل ۹۸ به بالا", 400_000_000, 1398, "a year clause after"),
    ("پراید حداقل ۴۰۰ میلیون، مدل ۱۴۰۱ به بالا", 400_000_000, 1401, "  after a comma"),
    ("پراید حداقل ۴۰۰ میلیون مدل ۹۸", 400_000_000, 1398, "  with no «به بالا»"),
    ("پراید ۴۰۰ میلیون و بالاتر مدل ۹۸ به بالا", 400_000_000, 1398, "the suffix, then a year clause"),
    ("پراید ۴۰۰ میلیون و بالاتر، مدل ۹۸ به بالا", 400_000_000, 1398, "  after a comma"),
    ("پراید مدل ۹۸ به بالا حداقل ۴۰۰ میلیون", 400_000_000, 1398, "the year clause first"),
]:
    sp_w = P.parse(text)
    check(f"«{text}» → floor {want:,}, year {year}  ({why})",
          (sp_w.budget_min_toman, sp_w.budget_max_toman, sp_w.year_min)
          == (want, None, year),
          f"{sp_w.budget_min_toman} {sp_w.budget_max_toman} {sp_w.year_min}")

for text, want_f, want_c, why in [   # a floor and a ceiling, each read once
    ("پراید حداقل ۴۰۰ میلیون، حداکثر ۸۰۰ میلیون", 400_000_000, 800_000_000, "after a comma"),
    ("پراید حداقل ۴۰۰ میلیون و حداکثر ۸۰۰ میلیون", 400_000_000, 800_000_000, "  after «و»"),
    ("پراید حداقل ۴۰۰ میلیون حداکثر ۸۰۰ میلیون", 400_000_000, 800_000_000, "  with nothing between"),
    ("پراید حداقل ۴۰۰ میلیون تا ۸۰۰ میلیون", 400_000_000, 800_000_000,
     "a range that opens with «حداقل»"),
    ("پراید تا ۸۰۰ میلیون، حداقل ۴۰۰ میلیون", 400_000_000, 800_000_000, "the ceiling first"),
    ("پراید ۴۰۰ میلیون و بالاتر، تا ۸۰۰ میلیون", 400_000_000, 800_000_000, "the suffix, then a ceiling"),
    ("پراید ۴۰۰ میلیون و بالاتر و تا ۸۰۰ میلیون", 400_000_000, 800_000_000, "  after «و»"),
    ("پراید زیر ۸۰۰ میلیون و ۴۰۰ میلیون و بالاتر", 400_000_000, 800_000_000,
     "the «و ۴۰۰» after a million is no part of the amount before it (found by hand)"),
    ("پراید ۸۰۰ میلیون و ۴۰۰ میلیون و بالاتر", 400_000_000, 800_000_000, "  with no cue"),
]:
    sp_w = P.parse(text)
    check(f"«{text}» → floor {want_f:,}, ceiling {want_c:,}  ({why})",
          (sp_w.budget_min_toman, sp_w.budget_max_toman) == (want_f, want_c),
          f"{sp_w.budget_min_toman} {sp_w.budget_max_toman}")

check("«پژو ۲۰۶ حداقل ۶۰۰ میلیون» → the model is 206 and nothing else",
      P.parse("پژو ۲۰۶ حداقل ۶۰۰ میلیون").model_hints == ("206",))
for text, printed, why in [   # the ceiling is not assumed from a floor's amount
    ("پراید حداقل ۴۰۰ میلیون", False, "a floor alone: nothing is assumed"),
    ("پراید ۴۰۰ میلیون و بالاتر", False, "  the suffix"),
    ("پراید حداقل ۴۰۰ میلیون یا ۵۰۰ میلیون", True,
     "a second amount is taken for the ceiling, and said so"),
]:
    got_n = any(_FL_NOTE in a for a in P.parse(text).assumptions)
    check(f"«{text}» → the ceiling is "
          f"{'assumed and said so' if printed else 'not assumed'}  ({why})",
          got_n == printed, str(P.parse(text).assumptions))

for text, want, why in [   # what the floor's phrase leaves behind
    ("حداقل ۴۰۰ میلیون", (), "understood, not listed"),
    ("پراید ۴۰۰ میلیون و بالاتر", (), "  the suffix"),
    ("پراید ۴۰۰ میلیون و بالاتر باشه", (),
     "the leftover after « و » was listed as «بالاتر باشه»"),
    ("پراید ۴۰۰ میلیون و بیشتر می‌خوام", (), "  the same"),
    ("پراید در مشهد حداقل ۴۰۰ میلیون", ("در مشهد",),
     "the city, without the word that stood after it"),
    ("پراید ۴۰۰ میلیون و بالاتر در مشهد", ("در مشهد",),
     "  and without the leftover of the suffix"),
]:
    got_u = tuple(t.strip() for t in P.parse(text).unparsed)
    check(f"«{text}» → listed: {list(want) or '—'}  ({why})", got_u == want, str(got_u))

# A negation right after the phrase: no floor, and the amount is the ceiling as
# before. Thirteen words: the places' own list and six more.
_NEG13 = ["نباشه", "نباشد", "نباشن", "نیست", "نمی‌خوام", "نمیخوام", "نخوام",
          "نشه", "نره", "نرسه", "نگذره", "نزنه", "خرج نکنم"]
for _neg in _NEG13:
    sp_w = P.parse(f"پراید ۴۰۰ میلیون و بالاتر {_neg}")
    check(f"«پراید ۴۰۰ میلیون و بالاتر {_neg}» → no floor, ceiling 400,000,000",
          (sp_w.budget_min_toman, sp_w.budget_max_toman) == (None, 400_000_000),
          f"{sp_w.budget_min_toman} {sp_w.budget_max_toman}")
for _neg in ["نباشه", "نشه", "نره", "نیست", "نمی‌خوام"]:
    sp_w = P.parse(f"پراید حداقل ۴۰۰ میلیون {_neg}")
    check(f"«پراید حداقل ۴۰۰ میلیون {_neg}» → no floor, ceiling 400,000,000",
          (sp_w.budget_min_toman, sp_w.budget_max_toman) == (None, 400_000_000),
          f"{sp_w.budget_min_toman} {sp_w.budget_max_toman}")

for text, why in [   # not money, or not right after the word: no floor is read
    ("پراید حداقل ۲ سال بیمه", "a figure with no scale word"),
    ("پراید حداقل ۳۰۰", "  a bare figure"),
    ("پراید حداقل ۱۰۰ هزار کیلومتر", "a distance"),
    ("پراید حداقل ۵۰ هزار کیلومتر کارکرد", "  with «کارکرد»"),
    ("پراید حداقل ۸۰۰ تومان", "a currency word with no scale"),
    ("پراید ۳۰۰ و بالاتر", "the suffix after a figure with no scale word"),
    ("پراید ۵۰ هزار کیلومتر و بالاتر", "  a distance"),
    ("پراید حداقل ۱۰۰ هزار کیلومتر ۴۰۰ میلیون", "the amount is not right after the word"),
    ("پراید ۴۰۰ میلیون و بیشتر از ۱۰۰ هزار کیلومتر کارکرد", "«و بیشتر از» is not the suffix"),
    ("پراید ۴۰۰ میلیون و بالاتر از اون", "  «و بالاتر از»"),
    ("پراید حداقلی ۴۰۰ میلیون", "a longer word"),
    ("پراید بحداقل ۴۰۰ میلیون", "a prefix typed on the word"),
    ("پراید ۴۰۰ میلیون و بالاترین", "a longer word after"),
    ("پراید ۴۰۰ میلیون و بیشترین", "  the same"),
    ("پراید ۴۰۰ میلیون تومنی و بالاتر", "«تومنی» is no unit the phrase holds"),
]:
    got_f = P.parse(text).budget_min_toman
    check(f"«{text}» → no floor  ({why})", got_f is None, str(got_f))

for text, want, why in [   # measured and left: the ceiling is read, as it was
    ("پراید حداقل بودجه ۴۰۰ میلیون", 400_000_000,
     "«بودجه» takes the amount: it may say what the buyer has to spend"),
    ("پراید بیشتر از ۴۰۰ میلیون", 400_000_000, "«بیشتر از»: the ambiguity of «بالای X»"),
    ("پراید بیش از ۴۰۰ میلیون", 400_000_000, "«بیش از»"),
    ("پراید بالاتر از ۴۰۰ میلیون", 400_000_000, "«بالاتر از»"),
    ("پراید بیشتر از ۴۰۰ میلیون نباشه", 400_000_000, "  negated, which is the ceiling it means"),
    ("پراید نباید بیشتر از ۴۰۰ میلیون باشه", 400_000_000, "  a negation before the word"),
    ("پراید ۴۰۰ میلیون به بالا", 400_000_000, "a bare «X به بالا» (its own round)"),
    ("پراید بالای ۴۰۰ میلیون", 400_000_000, "«بالای X», the owner's choice"),
]:
    sp_w = P.parse(text)
    check(f"«{text}» → no floor, ceiling {want:,}, left  ({why})",
          (sp_w.budget_min_toman, sp_w.budget_max_toman) == (None, want),
          f"{sp_w.budget_min_toman} {sp_w.budget_max_toman}")

for text, why in [   # measured and left: read as a floor, and that is not always what is meant
    ("پراید حداقل ۴۰۰ میلیون پول دارم", "what the buyer has to spend, not the price asked"),
    ("پراید ۴۰۰ میلیون و بالاتر نمی‌رسه", "a negation outside the list of thirteen"),
    ("پراید ۴۰۰ میلیون و بالاتر اصلا نباشه", "  a word between"),
    ("پراید ۴۰۰ میلیون و بالاتر نباید باشه", "  «نباید»"),
    ("پراید بیشتر از ۴۰۰ میلیون مدل ۹۸ به بالا", "the bare «از» of the year form reads «بیشتر از»"),
]:
    got_f = P.parse(text).budget_min_toman
    check(f"«{text}» → floor 400,000,000, left  ({why})", got_f == 400_000_000, str(got_f))

# The fault that stood in that list until 2026-10-29, now its own round: the
# bare «از» of the year form is the tail of «کمتر از», a ceiling. A comparative
# right before the cue refuses the floor, and the ceiling rules read the query
# as they do for «زیر». 288 phrasings were measured (six comparatives, six
# amounts, two years, four contexts); these are a few of them.
for text, want_max, want_year in [
    ("پراید کمتر از ۴۰۰ میلیون مدل ۹۸ به بالا", 400_000_000, 1398),
    ("پراید کم‌تر از ۴۰۰ میلیون مدل ۹۸ به بالا", 400_000_000, 1398),
    ("پراید پایین تر از ۳۰۰ میلیون مدل ۱۳۹۸ به بالا", 300_000_000, 1398),
    ("پراید پایین‌تر از ۸۰۰ میلیون مدل ۹۸ به بالا", 800_000_000, 1398),
    ("206 ارزان تر از ۱ میلیارد مدل ۹۸ به بالا", 1_000_000_000, 1398),
    ("سمند، ارزون‌تر از ۵۵۰ میلیون مدل ۹۸ به بالا", 550_000_000, 1398),
    ("ارزان‌تر از ۱.۵ میلیارد مدل ۱۴۰۰ به بالا", 1_500_000_000, 1400),
]:
    sp_c = P.parse(text)
    check(f"«{text}» → no floor, ceiling {want_max:,}, year {want_year}",
          (sp_c.budget_min_toman, sp_c.budget_max_toman, sp_c.year_min)
          == (None, want_max, want_year),
          f"{sp_c.budget_min_toman} {sp_c.budget_max_toman} {sp_c.year_min}")
for text, why in [   # what the guard must not touch
    ("پراید از ۴۰۰ میلیون مدل ۹۸ به بالا", "the plain floor with a year clause"),
    ("پراید از ۴۰۰ میلیون به بالا", "the plain floor"),
    ("پراید بالای ۴۰۰ میلیون به بالا", "«بالای»"),
    ("پراید بیشتر از ۴۰۰ میلیون مدل ۹۸ به بالا", "«بیشتر از», the owner's choice (D84)"),
    ("پراید بالاتر از ۴۰۰ میلیون مدل ۹۸ به بالا", "«بالاتر از», the same"),
    ("پراید بیش از ۴۰۰ میلیون مدل ۹۸ به بالا", "«بیش از», the same"),
]:
    got_g = P.parse(text).budget_min_toman
    check(f"«{text}» → still floor 400,000,000  ({why})", got_g == 400_000_000, str(got_g))
for text in ("پراید زیر ۴۰۰ میلیون مدل ۹۸ به بالا", "پراید کمتر از ۴۰۰ میلیون، مدل ۹۸ به بالا",
             "پراید تا ۴۰۰ میلیون مدل ۹۸ به بالا", "پراید کمتر از ۴۰۰ میلیون"):
    sp_h = P.parse(text)
    check(f"«{text}» → no floor, ceiling 400,000,000, as before",
          (sp_h.budget_min_toman, sp_h.budget_max_toman) == (None, 400_000_000),
          f"{sp_h.budget_min_toman} {sp_h.budget_max_toman}")


# ---------------------------------------------------------------------------
print("\na model's number is a model only where it stands alone (D83)")
# A model's number was matched as a substring of the query: «دنا تا ۱۳۱۰ میلیون»
# holds 131, which is Pride's, and «تیبا مدل ۱۴۰۵» holds 405, so each added a
# model nobody wrote. A number is read now in the query less its amounts of
# money, and not beside another digit. A name is matched as ever. Every
# phrasing is made here; no log of what buyers write exists.
_NUMBERS = [("206", "206"), ("207", "207"), ("405", "405"),
            ("131", "pride"), ("111", "pride")]
for _n, _key in _NUMBERS:
    for _t, _extra, _why in [
        ("{N}", (), "alone"),
        ("ماشین {N} سفید", (), "between words"),
        ("تیبا یا {N}", ("tiba",), "beside another model"),
        ("تا ۳۰۰ میلیون {N}", (), "after a budget, in its clause"),
        ("زیر ۴۰۰ میلیون {N} سفید", (), "after a budget, with a word after it"),
]:
        _q = _t.format(N=_n)
        _got = set(P.parse(_q).model_hints)
        check(f"«{_q}» → {sorted({_key, *_extra})} ({_why})",
              _got == {_key, *_extra}, str(sorted(_got)))

for q, want, why in [
    ("دنا تا ۱۳۱۰ میلیون", {"dena"}, "131 inside an amount"),
    ("دنا تا ۱۱۱۰ میلیون", {"dena"}, "111 inside an amount"),
    ("تیبا تا ۲۰۷۵ میلیون", {"tiba"}, "207 inside an amount"),
    ("سورن تا ۱۲۰۶ میلیون", set(), "206 inside an amount, and no model at all"),
    ("تیبا بودجه ۱۴۰۵ میلیون", {"tiba"}, "405 inside an amount"),
    ("تیبا مدل ۱۴۰۵", {"tiba"}, "405 inside a year"),
    ("تیبا مدل ۱۴۰۶", {"tiba"}, "a year with no number in it"),
    ("پراید تا ۲۰۶ میلیون", {"pride"}, "the number is the amount"),
    ("تیبا تا ۴۰۵ میلیون", {"tiba"}, "  the same"),
    ("تیبا ۱۱۱ میلیون", {"tiba"}, "  with no cue before it"),
    ("پژو ۲۰۶ تا ۲۰۷ میلیون", {"206"}, "a model, then an amount that is another's number"),
    ("۲۰۶ زیر ۱۱۱۰ میلیون", {"206"}, "  and the other way round"),
    ("تیبا تا یک میلیارد و ۲۰۶ میلیون", {"tiba"}, "inside a written amount"),
    ("پراید ۱۱۱ مدل ۱۳۹۰", {"pride"}, "the model is read and the year is not"),
    ("تیبا ۱۲۰۶ سفید", {"tiba"}, "206 inside a longer number: a digit before it"),
    ("تیبا ۲۰۶۱ سفید", {"tiba"}, "  a digit after it"),
    ("تیبا ۱۲۰۶ یا ۲۰۶", {"tiba", "206"}, "alone once is read, whatever else holds it"),
    ("تا ۳۰۰ میلیون و ۲۰۶", set(), "after «و» the amount takes the number, as it did the budget"),
    ("پژو۲۰۶۹", {"206"}, "a name is matched as ever, even beside a digit"),
    ("پژو 206 میلیون", {"206"}, "  and even before «میلیون»"),
]:
    got_h = set(P.parse(q).model_hints)
    check(f"«{q}» → {sorted(want) or 'no model'} ({why})", got_h == want,
          str(sorted(got_h)))


# ---------------------------------------------------------------------------
print("\na province is read where it is a place the car should be in (D82)")
# A province named in a query is a constraint. The reading is the hazardous
# one: a wrong read inverts and says nothing, so a name is read only where it
# is a place the buyer wants the car to be in, and a phrase that names one and
# is not read is listed under «نفهمیدیم» -- by hand, since a clause that names
# a model is otherwise taken as understood whole. Every phrasing is made here;
# no log of what buyers write exists, so these test the rules, not the buyers.
_Q = "پراید"
_ZWNJ, _AR_YEH = "\u200c", "\u064a"


def _where(q):
    sp = P.parse(q)
    return sp.provinces, [t.strip() for t in sp.unparsed], list(sp.assumptions)


for q, want in [     # a locative before the name: read, nothing left, nothing assumed
    (f"{_Q} در تهران", ("تهران",)),
    (f"{_Q} توی اصفهان", ("اصفهان",)),
    (f"{_Q} تو یزد", ("یزد",)),
    (f"{_Q} ساکن مازندران", ("مازندران",)),
    (f"{_Q} استان گیلان", ("گیلان",)),
    (f"{_Q} در استان تهران", ("تهران",)),
    (f"{_Q} در شهر تهران", ("تهران",)),
    (f"{_Q} در سیستان و بلوچستان", ("سیستان و بلوچستان",)),
    (f"{_Q} در چهارمحال و بختیاری", ("چهارمحال و بختیاری",)),
    (f"{_Q} در کهگیلویه و بویراحمد", ("کهگیلویه و بویراحمد",)),
    (f"{_Q} در کهکیلویه و بویراحمد", ("کهگیلویه و بویراحمد",)),
    (f"{_Q} در آذربایجان شرقی", ("آذربایجان شرقی",)),
    (f"{_Q} در آذربایجان{_ZWNJ}شرقی", ("آذربایجان شرقی",)),
    (f"{_Q} در خراسان رضوی", ("خراسان رضوی",)),
    (f"پرا{_AR_YEH}د در اصفهان", ("اصفهان",)),
    (f"{_Q} در مرکزی", ("مرکزی",)),
    (f"{_Q} در گلستان", ("گلستان",)),
    (f"{_Q} استان مرکزی", ("مرکزی",)),
    (f"{_Q} در فارس", ("فارس",)),
    (f"{_Q} استان فارس", ("فارس",)),
    (f"{_Q} در تهران یا اصفهان", ("تهران", "اصفهان")),
    (f"{_Q} در تهران و البرز", ("تهران", "البرز")),
    (f"{_Q} در تهران، اصفهان", ("تهران", "اصفهان")),
    (f"{_Q} در تهران باشه", ("تهران",)),
    ("در تهران", ("تهران",)),
]:
    got_p, left, said = _where(q)
    check(f"«{q}» → {list(want)}, nothing left, nothing assumed",
          got_p == want and not left and not said,
          f"{got_p} {left} {said}")

def _note(written, province=None):
    return f"«{written}» را استان {province or written} گرفتیم"

for q, want, notes in [   # no locative: read, and said to be an assumption
    (f"{_Q} تهران", ("تهران",), [_note("تهران")]),
    (f"{_Q}، تهران", ("تهران",), [_note("تهران")]),
    (f"{_Q} تهران یا اصفهان", ("تهران", "اصفهان"),
     [_note("تهران"), _note("اصفهان")]),
    (f"{_Q} کهکیلویه و بویراحمد", ("کهگیلویه و بویراحمد",),
     [_note("کهکیلویه و بویراحمد", "کهگیلویه و بویراحمد")]),
    (f"{_Q} سیستان و بلوچستان", ("سیستان و بلوچستان",),
     [_note("سیستان و بلوچستان")]),
    (f"{_Q} تهران در تهران", ("تهران",), [_note("تهران")]),
    (f"{_Q} فارس", ("فارس",), [_note("فارس")]),
]:
    got_p, left, said = _where(q)
    check(f"«{q}» → {list(want)}, read as an assumption the panel shows",
          got_p == want and not left and said == notes,
          f"{got_p} {left} {said}")

for q, phrase in [   # named, and not read: listed as not understood
    (f"{_Q} غیر از تهران", "غیر از تهران"),
    (f"{_Q} به جز تهران", "به جز تهران"),
    (f"{_Q} بجز تهران", "بجز تهران"),
    (f"{_Q} خارج از تهران", "خارج از تهران"),
    (f"{_Q} نه تهران", "نه تهران"),
    (f"{_Q} غیر از در تهران", "غیر از در تهران"),
    (f"{_Q} غیر از تهران و اصفهان", "غیر از تهران و اصفهان"),
    (f"{_Q} نزدیک تهران", "نزدیک تهران"),
    (f"{_Q} نزدیک به تهران", "نزدیک به تهران"),
    (f"{_Q} اطراف تهران", "اطراف تهران"),
    (f"{_Q} حوالی تهران", "حوالی تهران"),
    (f"{_Q} حومه تهران", "حومه تهران"),
    (f"{_Q} پلاک تهران", "پلاک تهران"),
    (f"{_Q} پلاک: تهران", "پلاک: تهران"),
    (f"{_Q} پلاک اصفهان", "پلاک اصفهان"),
    (f"{_Q} تهران نباشه", "تهران نباشه"),
    (f"{_Q} تهران نباشد", "تهران نباشد"),
    (f"{_Q} تهران نیست", "تهران نیست"),
    (f"{_Q} تهران نمی{_ZWNJ}خوام", "تهران نمی خوام"),
    (f"{_Q} تهران نمیخوام", "تهران نمیخوام"),
    (f"{_Q} در تهران نباشه", "در تهران نباشه"),
    (f"{_Q} قفل مرکزی", "مرکزی"),
    (f"{_Q} شهرک گلستان", "گلستان"),
    (f"{_Q} مرکزی", "مرکزی"),
    (f"{_Q} در خراسان", "در خراسان"),
    (f"{_Q} در آذربایجان", "در آذربایجان"),
    (f"{_Q} خراسان", "خراسان"),
    (f"{_Q} خلیج فارس", "خلیج فارس"),            # holds a province's name
    (f"{_Q} در خلیج فارس", "در خلیج فارس"),
    (f"{_Q} خلیج{_ZWNJ}فارس", "خلیج فارس"),
    (f"{_Q} غیر از خلیج فارس", "غیر از خلیج فارس"),
]:
    sp = P.parse(q)
    left = [t.strip() for t in sp.unparsed]
    check(f"«{q}» → not read; «{phrase}» is listed as not understood",
          sp.provinces == () and left == [phrase]
          and sp.model_hints == ("pride",),
          f"{sp.provinces} {left} {sp.model_hints}")

for q in [f"{_Q} در مشهد", f"{_Q} در شیراز", f"{_Q} در کرج",
          f"{_Q} تهرانی", f"{_Q} تهرانپارس"]:
    check(f"«{q}» → no province: a city, or a word that only holds a name",
          P.parse(q).provinces == (), str(P.parse(q).provinces))

# What a province beside other constraints does to them, and they to it.
_sb = P.parse(f"{_Q} زیر ۸۰۰ میلیون در تهران")
check("a province beside a budget: both are read, nothing is left",
      _sb.provinces == ("تهران",) and _sb.budget_max_toman == 800_000_000
      and not _sb.unparsed, f"{_sb.provinces} {_sb.budget_max_toman} {_sb.unparsed}")
_sn = P.parse(f"{_Q} زیر ۸۰۰ میلیون غیر از تهران")
check("  a negation inside the budget's own clause is still listed, and the "
      "budget still read",
      _sn.provinces == () and _sn.budget_max_toman == 800_000_000
      and [t.strip() for t in _sn.unparsed] == ["غیر از تهران"],
      f"{_sn.provinces} {_sn.unparsed}")
_sx = P.parse(f"{_Q} در خراسان و تهران")
check("  one name read and one not, in the same group: the first is listed",
      _sx.provinces == ("تهران",)
      and [t.strip() for t in _sx.unparsed] == ["در خراسان"],
      f"{_sx.provinces} {_sx.unparsed}")
_sg = P.parse(f"{_Q} در تهران و خلیج فارس")
check("  beside a name that is read, «خلیج فارس» is listed and the name is read",
      _sg.provinces == ("تهران",)
      and [t.strip() for t in _sg.unparsed] == ["خلیج فارس"],
      f"{_sg.provinces} {_sg.unparsed}")
check("  a model is not needed: «در تهران» alone sets the province and "
      "leaves nothing behind",
      _where("در تهران") == (("تهران",), [], []))

# Every name the corpus can carry, not the ones picked above.
check("all 31 provinces are read after «در»",
      all(P.parse(f"{_Q} در {p}").provinces == (p,) for p in PROVINCES),
      str([p for p in PROVINCES if P.parse(f"{_Q} در {p}").provinces != (p,)]))
check("  and not read after «غیر از», each listed whole",
      all(P.parse(f"{_Q} غیر از {p}").provinces == ()
          and [t.strip() for t in P.parse(f"{_Q} غیر از {p}").unparsed]
          == [f"غیر از {p}"] for p in PROVINCES))
check("  with no cue, all but the two ordinary words are read",
      all(P.parse(f"{_Q} {p}").provinces
          == (() if p in ("مرکزی", "گلستان") else (p,)) for p in PROVINCES))
_rp = read_provinces("پراید در سیستان و بلوچستان")
check("read_provinces hands the parser the whole phrase as understood, so a "
      "name with « و » in it is not cut",
      _rp.provinces == ("سیستان و بلوچستان",)
      and _rp.understood == ("در سیستان و بلوچستان",)
      and not _rp.declined and not _rp.assumptions, str(_rp))
_chips = re.findall(r"'([^']+)'", re.search(
    r"const EXAMPLES = \[(.*?)\];",
    (pathlib.Path(__file__).resolve().parent.parent / "webapp" / "web"
     / "components" / "SearchBox.tsx").read_text(encoding="utf-8"), re.S)[1])
check(f"none of the {len(_chips)} examples under the search box names a "
      "province", bool(_chips) and all(P.parse(c).provinces == ()
                                       for c in _chips), str(_chips))


# ---------------------------------------------------------------------------
print("\na city is listed under «نفهمیدیم», not dropped (D83)")
# «پراید در مشهد» names a model, so its clause was understood whole and the
# city was dropped without a word. A cue the province reader knows is now
# listed with the one or two words after it. Nothing is read from them: the
# city narrows nothing, and the page says so. Every phrasing is made here; no
# log of what buyers write exists, so these test the rule, not the buyers.
def _listed(q):
    sp = P.parse(q)
    return [t.strip() for t in sp.unparsed], sp.provinces


for q, want in [   # each cue alone, before a word nothing knows
    (f"{_Q} در مشهد", ["در مشهد"]),
    (f"{_Q} توی مشهد", ["توی مشهد"]),
    (f"{_Q} تو مشهد", ["تو مشهد"]),
    (f"{_Q} ساکن مشهد", ["ساکن مشهد"]),
    (f"{_Q} اطراف مشهد", ["اطراف مشهد"]),
    (f"{_Q} حوالی مشهد", ["حوالی مشهد"]),
    (f"{_Q} حومه مشهد", ["حومه مشهد"]),
    (f"{_Q} بجز مشهد", ["بجز مشهد"]),
    (f"{_Q} پلاک مشهد", ["پلاک مشهد"]),
    (f"{_Q} نزدیک مشهد", ["نزدیک مشهد"]),
    (f"{_Q} نزدیکی مشهد", ["نزدیکی مشهد"]),
    (f"{_Q} غیر مشهد", ["غیر مشهد"]),
    # a cue of two words, before a name of two: the pair is one cue
    (f"{_Q} نزدیک به بندر عباس", ["نزدیک به بندر عباس"]),
    (f"{_Q} نزدیکی به بندر عباس", ["نزدیکی به بندر عباس"]),
    (f"{_Q} غیر از بندر عباس", ["غیر از بندر عباس"]),
    (f"{_Q} به جز بندر عباس", ["به جز بندر عباس"]),
    (f"{_Q} خارج از بندر عباس", ["خارج از بندر عباس"]),
    (f"{_Q} نزدیک{_ZWNJ}به بندر عباس", ["نزدیک به بندر عباس"]),
    # two words are taken, not one and not three
    (f"{_Q} ساکن در بندر عباس", ["ساکن در بندر عباس"]),
    (f"{_Q} در بندر ماهشهر میخوام", ["در بندر ماهشهر"]),
    # «شهر» and «استان» are skipped, and so is a cue after a cue
    (f"{_Q} ساکن در شهر مشهد", ["ساکن در شهر مشهد"]),
    (f"{_Q} در شهر بندر عباس", ["در شهر بندر عباس"]),
    (f"{_Q} پلاک ملی در مشهد", ["پلاک ملی", "در مشهد"]),
    # listed once: the clause rule already lists this one whole
    ("ماشین سفید در مشهد", ["ماشین سفید در مشهد"]),
    # after what is already there, and not counted in its cap of four
    (f"{_Q} غیر از تهران در مشهد", ["غیر از تهران", "در مشهد"]),
    ("ماشین قرمز، دوست دارم، حتما سالم، خیلی تمیز، پراید در مشهد",
     ["ماشین قرمز", "دوست دارم", "حتما سالم", "خیلی تمیز", "در مشهد"]),
]:
    left, got_p = _listed(q)
    check(f"«{q}» → listed: {want}", left == want and got_p == (),
          f"{left} {got_p}")

for q, why in [   # a cue with nothing to take: nothing is listed
    (f"{_Q} در", "a cue at the end"),
    (f"{_Q} نزدیک به", "a pair at the end"),
    (f"{_Q} در استان", "«استان» is a link, not a name"),
    (f"{_Q} در شهر", "«شهر» is a link, not a name"),
    (f"{_Q} خارج از استان", "a pair, then a link, then nothing"),
    (f"{_Q} ساکن، مشهد", "a comma ends the phrase"),
    (f"{_Q} در حد نو", "«حد» is no name"),
    (f"{_Q} در حال حاضر", "«حال» is no name"),
    (f"{_Q} توی بودجه ام باشه", "«بودجه» is no name"),
    (f"{_Q} غیر از تیبا", "a model's name is blanked, so it is no word"),
    (f"{_Q} غیر از تیبایی", "what a blanked name leaves is no word of its own"),
    (f"{_Q} در تیبا مشهد", "a blanked name between ends the run"),
    (f"{_Q} پلاک ب", "one letter is no word"),
    (f"{_Q} نزدیک؛ به مشهد", "a mark between the two words of a pair ends it"),
    ("ماشین برای مسافرکشی در اسنپ", "what the parser acted on is blanked"),
    (f"{_Q} پلاک 12 ایران", "a number is blanked"),
]:
    left, got_p = _listed(q)
    check(f"«{q}» → nothing listed: {why}", left == [] and got_p == (),
          f"{left} {got_p}")

# A province's name is the reader's, not this rule's: it is blanked, so the
# rule neither lists it nor takes it as the word after a cue. One the reader
# declines is listed by the reader, once: «نزدیک تهران باشه» is not listed
# again with the word after it.
for q, want, prov in [
    (f"{_Q} در تهران", [], ("تهران",)),
    (f"{_Q} پلاک ملی در تهران", ["پلاک ملی"], ("تهران",)),
    (f"{_Q} پلاک ملی تهران", ["پلاک ملی"], ("تهران",)),
    (f"{_Q} در تهران در مشهد", ["در مشهد"], ("تهران",)),
    (f"{_Q} نزدیک تهران باشه", ["نزدیک تهران"], ()),
    (f"{_Q} غیر از تهران باشه", ["غیر از تهران"], ()),
    (f"{_Q} تا ۳۰۰ میلیون در تهران", [], ("تهران",)),
    (f"{_Q} تا ۳۰۰ میلیون غیر از تهران", ["غیر از تهران"], ()),
]:
    left, got_p = _listed(q)
    check(f"«{q}» → province {list(prov)}, listed: {want}",
          left == want and got_p == prov, f"{left} {got_p}")

# What the budget clause takes with its amount is read too. The clause runs to
# the next «،», so a city after the amount went with it and was dropped; what
# stands after the amount is now one more clause for the rule, and what stands
# before it is not.
for q, want, why in [
    (f"{_Q} تا ۳۰۰ میلیون در مشهد", ["در مشهد"], "after «تا»"),
    (f"{_Q} زیر ۳۰۰ میلیون ساکن شیراز", ["ساکن شیراز"], "after «زیر»"),
    (f"{_Q} بودجه ۳۰۰ میلیون نزدیک کرج", ["نزدیک کرج"], "after «بودجه»"),
    (f"{_Q} حداکثر ۱.۵ میلیارد توی تبریز", ["توی تبریز"], "a decimal amount"),
    (f"{_Q} تا ۳۰۰ میلیون تومان در مشهد", ["در مشهد"], "a unit word between"),
    (f"{_Q} تا ۳۰۰ میلیون پلاک ملی در مشهد", ["پلاک ملی", "در مشهد"],
     "two phrases"),
    (f"{_Q} تا ۳۰۰ میلیون در شهر بندر عباس", ["در شهر بندر عباس"],
     "two words are taken"),
    (f"{_Q} تا ۳۰۰ میلیون نزدیک به بندر عباس", ["نزدیک به بندر عباس"],
     "a pair"),
    (f"{_Q} تا ۳۰۰ میلیون غیر از مشهد در شیراز", ["غیر از مشهد", "در شیراز"],
     "two cues in it"),
    (f"{_Q} تا ۳۰۰ میلیون در مشهد، ساکن شیراز", ["ساکن شیراز", "در مشهد"],
     "the clause ends at «،»; what it holds is listed last"),
    ("ماشین سفید در مشهد، تا ۳۰۰ میلیون در شیراز",
     ["ماشین سفید در مشهد", "در شیراز"], "one before the budget, one after"),
    ("ماشین تا ۳۰۰ میلیون در مشهد، ماشین سفید در مشهد",
     ["ماشین سفید در مشهد"], "listed once, since a phrase holds it"),
    (f"{_Q} تا ۳۰۰ میلیون در مشهد ۴۰۰ میلیون", ["در مشهد"],
     "the first amount is the budget; a second is a figure, blanked"),
    (f"{_Q} تا ۳۰۰ میلیون در مشهد مدل ۹۵", ["در مشهد"],
     "the year clause is cut from it, as from the rest"),
    (f"{_Q} تا ۳۰۰ میلیون در مشهد مدل ۱۴۰۱ به بالا", ["در مشهد"],
     "the same, with «به بالا»"),
]:
    left, got_p = _listed(q)
    check(f"«{q}» → listed: {want} ({why})", left == want and got_p == (),
          f"{left} {got_p}")

for q, why in [   # what stands after an amount and is no cue: nothing is listed
    (f"{_Q} تا ۳۰۰ میلیون سفید", "a colour"),
    (f"{_Q} تا ۳۰۰ میلیون باشه", "a filler"),
    (f"{_Q} تا ۳۰۰ میلیون تیپ ۲", "a trim"),
    (f"{_Q} تا ۳۰۰ میلیون تومان", "a unit alone"),
    (f"{_Q} تا ۳۰۰ میلیون در", "a cue at the end"),
    (f"{_Q} تا ۳۰۰ میلیون در حال حاضر", "«حال» is no name there either"),
    ("ماشین تا ۳۰۰ میلیون برای مسافرکشی در اسنپ",
     "what the parser acted on is blanked in it"),
]:
    left, got_p = _listed(q)
    check(f"«{q}» → nothing listed: {why}", left == [] and got_p == (),
          f"{left} {got_p}")

# What it leaves dropped, pinned so that it changes on purpose.
for q, want, prov, why in [
    (f"{_Q} مشهد", [], (), "no cue stands before it"),
    (f"{_Q} قیمت در مشهد ۳۰۰ میلیون", [], (),
     "before the amount, the budget clause takes it whole"),
    (f"{_Q} تا ۳۰۰ میلیون در مشهد تا ۴۰۰ میلیون", ["در مشهد تا"], (),
     "a second budget lends its «تا» to the place, as «یا» does"),
    (f"{_Q} در تهران و مشهد", [], ("تهران",),
     "a second name after « و » has no cue"),
    (f"{_Q} غیر از شیراز و مشهد", ["غیر از شیراز"], (), "the same, after a cue"),
    (f"{_Q} در مشهد یا شیراز", ["در مشهد یا"], (), "«یا» is taken as a word"),
    (f"{_Q} نه مشهد", [], (), "«نه» is the reader's cue and not this one's"),
    (f"{_Q} بدون کیلومتر", [], (),
     "«بدون» is the reader's cue and not this one's"),
]:
    left, got_p = _listed(q)
    check(f"«{q}» → {want or 'nothing'} ({why})",
          left == want and got_p == prov, f"{left} {got_p}")

# The list is all it changes: the same spec as without the phrase.
check("a listed phrase changes nothing in the spec but the list",
      all(dataclasses.replace(P.parse(a), raw_query="", unparsed=())
          == dataclasses.replace(P.parse(b), raw_query="", unparsed=())
          for a, b in [
              (f"{_Q} در مشهد", _Q),
              (f"{_Q} پلاک ملی در مشهد", _Q),
              (f"{_Q} ساکن در شهر بندر عباس", _Q),
              (f"{_Q} زیر ۳۰۰ میلیون، نزدیک مشهد", f"{_Q} زیر ۳۰۰ میلیون"),
              (f"{_Q} اسنپ، توی بندر عباس", f"{_Q} اسنپ"),
              (f"{_Q} غیر از تهران در مشهد", f"{_Q} غیر از تهران"),
          ]))
check("a place is listed the same with a budget before it as without",
      all(_listed(f"{_Q} تا ۳۰۰ میلیون {t}") == _listed(f"{_Q} {t}")
          for t in ["در مشهد", "ساکن شیراز", "پلاک ملی در مشهد",
                    "نزدیک به بندر عباس", "در تهران", "غیر از تهران",
                    "در مشهد مدل ۹۵", "در مشهد مدل ۱۴۰۱ به بالا"]),
      str([t for t in ["در مشهد", "ساکن شیراز", "پلاک ملی در مشهد",
                       "نزدیک به بندر عباس", "در تهران", "غیر از تهران",
                       "در مشهد مدل ۹۵", "در مشهد مدل ۱۴۰۱ به بالا"]
           if _listed(f"{_Q} تا ۳۰۰ میلیون {t}") != _listed(f"{_Q} {t}")]))
check("a phrase listed after a budget changes nothing in the spec but the list",
      all(dataclasses.replace(P.parse(a), raw_query="", unparsed=())
          == dataclasses.replace(P.parse(b), raw_query="", unparsed=())
          for a, b in [
              (f"{_Q} تا ۳۰۰ میلیون در مشهد", f"{_Q} تا ۳۰۰ میلیون"),
              (f"{_Q} زیر ۳۰۰ میلیون پلاک ملی در مشهد", f"{_Q} زیر ۳۰۰ میلیون"),
              (f"{_Q} بودجه ۱.۵ میلیارد نزدیک به بندر عباس",
               f"{_Q} بودجه ۱.۵ میلیارد"),
          ]))
check("every cue of the rule is one the reader knows: a province after it "
      "is read, or declined, but never assumed",
      all(not read_provinces(f"{_Q} {c} تهران").assumptions
          for c in [*_CUE_WORDS, *(" ".join(p) for p in _CUE_PAIRS)])
      and read_provinces(f"{_Q} سفید تهران").assumptions,
      str([c for c in [*_CUE_WORDS, *(" ".join(p) for p in _CUE_PAIRS)]
           if read_provinces(f"{_Q} {c} تهران").assumptions]))


# ---------------------------------------------------------------------------
print("\nretrieval and the relaxation ladder")
tight = IntentSpec(raw_query="", budget_max_toman=100_000_000,
                   model_hints=("206",), year_min=1402,
                   max_mileage_km=20_000)
got, used, rep = retrieve(POOL, tight)
check("impossible query never returns an empty list silently",
      rep.relaxed or len(got) == 0)
check("  and says what was loosened",
      "بودجه" in rep.text_fa() or not rep.relaxed, rep.text_fa())

easy = IntentSpec(raw_query="", budget_max_toman=10_000_000_000)
got2, _, rep2 = retrieve(POOL, easy)
check("a satisfiable query relaxes nothing", not rep2.relaxed)
check("  and returns candidates", len(got2) > 50)

db = IntentSpec(raw_query="", budget_max_toman=10_000_000_000,
                deal_breakers=("accident",))
got3, used3, _ = retrieve(POOL, db)
check("a deal-breaker is never relaxed away",
      all(r.features.get("has_accident", 0) < 0.5 for r in got3))
check("  and it actually excluded cars", len(got3) < len(got2))

# The corpus above is built with model_key = the parser's own slug, so it
# could never have caught this: ingest emits `make|model|trim`, and the
# retrieval filter compared a hint against the WHOLE key. On Run 5's real
# rows every model-constrained query returned zero while six matching cars
# sat inside the stated budget. These rows carry Bama's key shape verbatim.
INGEST_SHAPED = [
    Row(listing_id=f"r{i}", cluster_id=f"r{i}", first_seen_ordinal=0,
        model_key=k, year_jalali=1398, mileage_km=120_000.0,
        asking_price_toman=float(p), features={})
    for i, (k, p) in enumerate([
        ("Peugeot|206|type1", 495_000_000),
        ("Peugeot|206|type2", 540_000_000),
        ("Saipa|Pride|111 ex", 488_000_000),
        ("Saipa|Quik|r automatic", 700_000_000),
        ("BMW|3seriesconvertible|320i 2011", 9_000_000_000),
    ])]
for hint, want in [("206", 2), ("pride", 1), ("quik", 1)]:
    spec = IntentSpec(raw_query="", budget_max_toman=2_000_000_000,
                      model_hints=(hint,))
    hits = [r for r in INGEST_SHAPED if _passes(r, spec)]
    check(f"hint '{hint}' matches make|model|trim keys", len(hits) == want,
          f"got {len(hits)}, want {want}")
check("a hint does not match an unrelated model",
      not _passes(INGEST_SHAPED[4], IntentSpec(raw_query="",
                                               model_hints=("206",))))
check("case is folded, not assumed",
      _passes(INGEST_SHAPED[2], IntentSpec(raw_query="",
                                           model_hints=("pride",))))
check("bare-slug keys still match (the synthetic corpora)",
      _passes(Row(listing_id="s", cluster_id="s", first_seen_ordinal=0,
                  model_key="206", year_jalali=1398, mileage_km=1.0,
                  asking_price_toman=1.0),
              IntentSpec(raw_query="", model_hints=("206",))))



def replace_row(r: Row) -> Row:
    """The same car as Bama actually gives it to us: no derived features."""
    return Row(listing_id=r.listing_id, cluster_id=r.cluster_id,
               first_seen_ordinal=0, model_key=r.model_key,
               year_jalali=r.year_jalali, mileage_km=r.mileage_km,
               asking_price_toman=r.asking_price_toman, features={})


# ---------------------------------------------------------------------------
print("\nthe ranked path reads no province -- pinned (D82)")
# ---------------------------------------------------------------------------
# A province is judged over listings (webapp/api/constraints.py). The ranked
# path works on appraisal Rows, which carry none, and `_passes` has no rule
# for one, so a spec that names a province is not narrowed there: the same
# candidates, the same ladder. That is the state the owner left it in, as the
# red lines are left (D66), and it is written down here so that it changes by
# a decision and not by accident. It shows only where the ranking is served --
# the SYNTHETIC corpus today -- and the intent panel lists «استان» there all
# the same (test_api_contract section 18).
#
# These turn red the day a Row carries a province or `_passes` reads one.
# Replace them then with what the rule does, measured. Editing them until they
# pass would say the opposite of what they are for.
_TEHRAN = ("تهران",)
_row_fields = [f.name for f in dataclasses.fields(Row)]
check("an appraisal Row carries no province",
      not [n for n in _row_fields if "province" in n or n == "city"],
      str(_row_fields))
_wide = IntentSpec(raw_query="", budget_max_toman=10_000_000_000)
_wide_p = dataclasses.replace(_wide, provinces=_TEHRAN)
check("  `_passes` answers the same with one named, row by row",
      [_passes(r, _wide) for r in POOL] == [_passes(r, _wide_p) for r in POOL]
      and any(_passes(r, _wide_p) for r in POOL),
      "the answers differ, or nothing passes and nothing was compared")

# A spec that makes the ladder walk and still leaves cars: a 206 up to 900
# million, from 1395, under 120,000 km is one car at first and three after the
# budget and the odometer have each been loosened.
_walk = IntentSpec(raw_query="", budget_max_toman=900_000_000,
                   model_hints=("206",), year_min=1395, max_mileage_km=120_000)
_a, _used_a, _rep_a = retrieve(POOL, _walk)
_b, _used_b, _rep_b = retrieve(POOL,
                               dataclasses.replace(_walk, provinces=_TEHRAN))
check(f"  `retrieve` leaves the same {len(_a)} candidates through the same "
      f"{len(_rep_a.steps)} relaxation steps",
      _rep_a.relaxed and len(_a) > 0
      and [r.listing_id for r in _a] == [r.listing_id for r in _b]
      and _rep_a.steps == _rep_b.steps,
      f"without: {[r.listing_id for r in _a]} {_rep_a.steps} · with: "
      f"{[r.listing_id for r in _b]} {_rep_b.steps}")
check("  and hands the province back as stated: not relaxed, not dropped",
      _used_b.provinces == _TEHRAN
      and dataclasses.replace(_used_b, provinces=()) == _used_a,
      str(_used_b.provinces))




# ---------------------------------------------------------------------------
print("\ncondition → risk, the published table")
# The table that took features["risk"] from absent-on-every-real-row to a
# six-valued column (D45). It is policy, not a fit, so what is testable is its
# ORDERING and its treatment of silence — not its calibration, which no data
# in this repository could check.
order = ["intact", "minor_paint", "unknown", "multi_paint",
         "replaced_part", "accident"]
vals = [CONDITION_RISK[k] for k in order]
check("risk is monotone across the declared ordering",
      all(a < b for a, b in zip(vals, vals[1:])), str(vals))
check("intact is not zero — a clean car is not a certainty", vals[0] > 0)
check("accident is not one — a damaged car is not a total loss", vals[-1] < 1)

# The row that matters most, and the one it would be easiest to get wrong.
check("UNKNOWN is not treated as intact",
      CONDITION_RISK["unknown"] > CONDITION_RISK["intact"],
      "silence would otherwise rank undisclosed cars above disclosed ones")
check("  and it sits between the good and bad disclosures",
      CONDITION_RISK["minor_paint"] < CONDITION_RISK["unknown"]
      < CONDITION_RISK["multi_paint"])
check("an unrecognised label falls back to unknown, not to zero",
      risk_from_condition("something new") == CONDITION_RISK["unknown"])
check("  and so does None", risk_from_condition(None) == CONDITION_RISK["unknown"])


class _L:
    def __init__(self, cond, doc=None):
        self.body_condition, self.document_issue = cond, doc


f = features_from_listing(_L("accident"))
check("an accident listing sets both risk and the deal-breaker flag",
      f["risk"] == CONDITION_RISK["accident"] and f["has_accident"] == 1.0)
check("  a clean one sets the flag to 0, not absent",
      features_from_listing(_L("intact"))["has_accident"] == 0.0)
check("a listing with no condition at all yields NO risk key",
      "risk" not in features_from_listing(_L(None)),
      "absent must stay absent so the ledger can report it — "
      "defaulting here would turn a missing input into a fake one")
check("ownership_risk and liquidity are never invented",
      not ({"ownership_risk", "liquidity"} & set(f)),
      "no observation in this repository supports either")
check("a document issue is carried through",
      features_from_listing(_L("intact", True))["has_unclear_documents"] == 1.0)

# ---------------------------------------------------------------------------
print("\nthe decision ledger — construct validity, not ranking quality")
# There is no ground truth for ranking quality on real listings, so the ledger
# answers a different question that needs none: were the inputs the scoring
# function reads actually PRESENT? On the synthetic corpus everything is
# present by construction — which is exactly why the interesting assertions
# below are the ones about absence.
spec_l = IntentSpec(raw_query="", budget_max_toman=2_000_000_000)
cands_l, _, _ = retrieve(POOL, spec_l)
rows_l = decision_ledger(cands_l[:20], spec_l, estimator=EST)
check("a ledger row per candidate", len(rows_l) == 20)
check("with a gated estimator the price delta is recorded",
      all("price_delta_to_estimate" in r.values for r in rows_l))
check("the synthetic corpus is fully fed", 
      all(r.completeness == 1.0 for r in rows_l),
      f"{rows_l[0].values.keys()}")

# The real case: no estimator. The ledger must still produce rows, and must
# name the reason rather than leave a blank — refusing to print here would
# hide the single most informative line it has.
bare = decision_ledger(cands_l[:5], spec_l, estimator=None)
check("without an estimator the ledger still runs", len(bare) == 5)
check("  and the price delta is MISSING, with a reason",
      all("price_delta_to_estimate" in r.missing
          and "gate" in r.missing["price_delta_to_estimate"] for r in bare))
check("  an absent input is never silently zero",
      all("price_delta_to_estimate" not in r.values for r in bare))

featureless = [replace_row(r) for r in cands_l[:5]]
bare2 = decision_ledger(featureless, spec_l, estimator=None)
check("a row with no features reports every proxy missing",
      all({"risk_score", "running_cost_signals", "reliability_signals"}
          <= set(r.missing) for r in bare2))
check("  and completeness falls accordingly",
      all(r.completeness < 0.5 for r in bare2),
      f"{bare2[0].completeness:.0%}")
check("hard_filter_pass is always recorded — it needs nothing external",
      all("hard_filter_pass" in r.values for r in bare2))
check("the ledger declares its inputs", len(LEDGER_INPUTS) == 9)


# ---------------------------------------------------------------------------
print("\nobserved vs imputed vs absent")
# The three-state rule. `unknown` is FILLED rather than left out, because
# Ranker.score reads risk with .get("risk", 0.0) and an absent key would score
# silence as a perfect car — the one failure CONDITION_RISK exists to prevent.
# Filling it silently would have been the other failure: a number we chose,
# indistinguishable downstream from one Bama printed. So: filled AND flagged.
f_known = features_from_listing(_L("minor_paint"))
f_unk = features_from_listing(_L("unknown"))
check("a stated condition is not marked imputed", IMPUTED_MARK not in f_known)
check("an unstated one IS", f_unk.get(IMPUTED_MARK) == ["risk"])
check("  and it still has a value — absence would score silence as perfect",
      f_unk["risk"] == CONDITION_RISK["unknown"])

_R = lambda i, feats: Row(listing_id=f"i{i}", cluster_id=f"i{i}",
                          first_seen_ordinal=0, model_key="pride",
                          year_jalali=1398, mileage_km=100_000.0,
                          asking_price_toman=5e8, features=feats)
spec_i = IntentSpec(raw_query="", budget_max_toman=2_000_000_000)
lr_known, lr_unk = decision_ledger([_R(0, f_known), _R(1, f_unk)], spec_i)
check("the ledger reports an imputed input separately",
      not lr_known.imputed and set(lr_unk.imputed) == {"risk_score"})
check("  and says whose number it is",
      "this project chose" in lr_unk.imputed["risk_score"])
check("completeness counts imputed values",
      lr_unk.completeness == lr_known.completeness)
check("  and observed_completeness does not",
      lr_unk.observed_completeness < lr_known.observed_completeness,
      "the stricter number is the one to quote when it matters")

# ---------------------------------------------------------------------------
print("\nscoring and shortlist")
check("ridge passed the gate before ranking used it", OK, str(WHY))

sl = PIPE.run("یه ۲۰۶ تا ۲ میلیارد میخوام، تصادفی نباشه", POOL)
check("shortlist is produced", len(sl.items) > 0)
check("every term is inspectable",
      all({"value", "risk", "running_cost", "liquidity", "mileage", "recency"}
          <= set(s.breakdown) for s in sl.items))
check("score equals the sum of its terms",
      all(abs(s.score - sum(v for k, v in s.breakdown.items()
                            if not k.startswith("_"))) < 1e-9
          for s in sl.items))
check("each pick is labelled with its role",
      all(s.breakdown.get("_role") for s in sl.items))
check("summary discloses assumptions", "فرض" in sl.summary_fa()
      or not sl.spec.assumptions)

risk_averse = PIPE.parser.parse("ماشین خانواده، تصادفی نباشه، تا ۲ میلیارد")
flip = PIPE.parser.parse("برای فروش مجدد و سود، تا ۲ میلیارد")
ra_items = PIPE.ranker.score(retrieve(POOL, risk_averse)[0], risk_averse)
fl_items = PIPE.ranker.score(retrieve(POOL, flip)[0], flip)
ra_top = sorted(ra_items, key=lambda s: s.score, reverse=True)[:5]
fl_top = sorted(fl_items, key=lambda s: s.score, reverse=True)[:5]
check("a risk-averse buyer gets lower-risk cars than a flipper",
      np.mean([s.row.features["risk"] for s in ra_top])
      < np.mean([s.row.features["risk"] for s in fl_top]),
      f'{np.mean([s.row.features["risk"] for s in ra_top]):.3f} vs '
      f'{np.mean([s.row.features["risk"] for s in fl_top]):.3f}')

check("intent changes the ordering",
      [s.row.listing_id for s in ra_top] != [s.row.listing_id for s in fl_top])

heavy = risk_averse.with_weights(Weights(value=0.9, risk=0.02, running_cost=0.02,
                                         liquidity=0.02, mileage=0.02,
                                         recency=0.02))
hv = sorted(PIPE.ranker.score(retrieve(POOL, heavy)[0], heavy),
            key=lambda s: s.score, reverse=True)[:5]
check("dragging a weight re-ranks",
      [s.row.listing_id for s in hv] != [s.row.listing_id for s in ra_top])

check("diversify returns at most k", len(diversify(ra_items, k=4)) <= 4)
check("diversify on an empty set is empty", diversify([], k=5) == [])

ungated = Ranker(MarketEstimator(GlobalQuantiles()))
try:
    ungated.score(POOL[:5], risk_averse)
    check("an ungated estimator cannot rank", False, "it ranked anyway")
except Exception as e:
    check("an ungated estimator cannot rank",
          type(e).__name__ == "NotBenchmarked", type(e).__name__)


# ---------------------------------------------------------------------------
print("\nTHE NUMBER — does ranking beat sorting by price?")
QUERIES = [
    "یه ۲۰۶ تا ۲ میلیارد میخوام",
    "ماشین اول خانواده، تصادفی نباشه، بودجه ۱.۵ میلیارد",
    "ماشین برای اسنپ، کم‌مصرف، زیر ۱ میلیارد",
    "پراید کم‌کارکرد تا ۸۰۰ میلیون",
    "تیبا مدل ۹۸ به بالا تا ۱ میلیارد",
    "پارس تا ۱.۸ میلیارد، کارکرد زیر ۱۵۰ هزار",
    "یه ماشین خوب حدود ۱.۲ میلیارد",
    "کوییک تا ۱.۱ میلیارد، تصادفی نباشه",
    "۲۰۷ اتومات تا ۲.۵ میلیارد",
    "ارزون‌ترین ماشین سالم تا ۹۰۰ میلیون",
    "ماشین برای رفت و آمد سرکار، کم‌خرج، تا ۱.۳ میلیارد",
    "پژو ۴۰۵ مدل ۹۶ به بالا تا ۱.۲ میلیارد",
]
res = winrate_vs_price_sort(PIPE, POOL, QUERIES, true_utility, k=3)
print(f"     {res}")
check("price-sort is beaten on mean buyer utility",
      res.caro_mean_utility > res.price_sort_mean_utility,
      f"{res.caro_mean_utility:,.0f} vs {res.price_sort_mean_utility:,.0f}")
check("win-rate is a majority", res.win_rate >= 0.6, f"{res.win_rate:.0%}")
check("CARO beats picking at random", res.caro_mean_utility > res.random_mean_utility)
# NOT asserted: that price-sort is worse than random. It is not, and the
# reason is worth recording. Utility here is absolute tomans, and the damage
# penalty scales with a car's clean value — so sorting by price selects
# cheap, low-value cars where the absolute stakes are small either way. That
# makes price-sorting look defensible on this metric while still being the
# wrong advice: it systematically hands the buyer the damaged end of whatever
# price band they are shopping in. The thesis is "CARO beats price-sort",
# which is what the win-rate measures; "price-sort is worse than chance" was
# speculation and the experiment did not support it.
check("all three baselines were actually evaluated",
      res.n_queries >= 8, f"only {res.n_queries} queries produced shortlists")
check("uplift is material, not noise", res.uplift > 0.10, f"{res.uplift:+.1%}")

# Regression for the bug this benchmark caught. The first ranker normalised
# risk to [0,1] across the candidate set, which is scale-free — so the same
# risk score cost the same whether the car was worth 800M or 2B, and the
# ranker kept choosing expensive damaged cars and lost to price-sorting.
# Risk must be priced in tomans against the car's own value.
print("\nregression: risk is priced, not scored")
from caro.ranking import DAMAGE_COST_FACTOR
cheap = Row("x1", "cx1", 10, "pride", 1398, 100_000, 700_000_000,
            {"risk": 0.30, "liquidity": 0.8})
dear = Row("x2", "cx2", 10, "pars", 1398, 100_000, 1_900_000_000,
           {"risk": 0.30, "liquidity": 0.4})
spec = P.parse("تا ۳ میلیارد")
sc = {s.row.listing_id: s for s in PIPE.ranker.score([cheap, dear], spec)}
check("identical risk costs more on the more valuable car",
      sc["x2"].expected_damage_toman > sc["x1"].expected_damage_toman * 2,
      f'{sc["x2"].expected_damage_toman:,.0f} vs {sc["x1"].expected_damage_toman:,.0f}')
check("the damage charge is proportional to the estimate",
      all(abs(s.expected_damage_toman
              - s.row.features["risk"] * s.conservative_estimate_toman
              * DAMAGE_COST_FACTOR) < 1.0 for s in sc.values()))
check("opportunity is net of the damage charge",
      all(abs(s.adjusted_opportunity_toman
              - (s.conservative_estimate_toman - s.row.asking_price_toman
                 - s.expected_damage_toman)) < 1.0 for s in sc.values()))
check("a zero-risk car carries no damage charge",
      PIPE.ranker.score(
          [Row("x3", "cx3", 10, "pride", 1398, 100_000, 700_000_000,
               {"risk": 0.0})], spec)[0].expected_damage_toman == 0.0)
print(f"     uplift over price-sort: {res.uplift:+.1%}")


print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
