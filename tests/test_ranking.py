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
from caro.ingest.persian import OTHER_CAPITALS, PROVINCES
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
# is how a floor and a year are written together. What it did not read, each
# measured and left to a round of its own, is read by the rules after it since
# 2026-11-18: a word between the cue and the amount, and the «از» that ends a
# word, by the bare floor; a range with a year clause, by the range. Every
# phrasing is made here; no log of what buyers write exists, so these test the
# rule, not the buyers.
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
    ("پراید از ۲۰۰ میلیون به بالا، تا ۳۰۰ میلیون در کاشان", ("در کاشان",),
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
    ("پراید در کاشان حداقل ۴۰۰ میلیون", ("در کاشان",),
     "the city, without the word that stood after it"),
    ("پراید ۴۰۰ میلیون و بالاتر در کاشان", ("در کاشان",),
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
print("\nthe decimal part of an amount: «.» «,» «/» «٫» (2026-10-29), and «،» (2026-11-22), the owner's calls")
# «۱/۵ میلیارد» and «۱٫۵ میلیارد» (U+066B) were read as 5 billion, silently; «.» and
# «,» were read right. 20 phrasings a separator were made (five amounts, four
# shapes): «/» and «٫» 0 of 20 before and 20 of 20 then. «،» stayed 0 of 20,
# being the clause separator and a thousands separator too, until the owner
# chose on 2026-11-22, on a measurement, to read it as a decimal mark where one
# or two digits stand on each side of it and no year before it (C2): 20 of 20
# then, the ten separators measured as before. A part of three digits is not a
# decimal («۱۱۱/۳۰۰ میلیون»).
for sep, name in [(".", "«.»"), (",", "«,»"), ("/", "«/»"), ("٫", "«٫» (U+066B)"),
                  ("،", "«،», one or two digits each side")]:
    for amount, want in [("۱{s}۵ میلیارد", 1_500_000_000), ("۲{s}۵ میلیارد", 2_500_000_000),
                         ("۱{s}۲۵ میلیارد", 1_250_000_000), ("۳{s}۷۵ میلیارد", 3_750_000_000)]:
        for shape in ("پراید زیر {a}", "{a} پراید", "بودجه {a}، پراید سفید"):
            q_dec = shape.format(a=amount.format(s=sep))
            got_dec = P.parse(q_dec).budget_max_toman
            check(f"«{q_dec}» → ceiling {want:,}  ({name})", got_dec == want, str(got_dec))
# «،» between digits (C2): read where it is a decimal, left where it is not.
for q_dec, want, why in [
        ("پراید زیر ۱،۵ میلیارد", (None, 1_500_000_000), "was 5 billion"),
        ("بین ۱،۲ تا ۱،۵ میلیارد", (1_200_000_000, 1_500_000_000), "a range, both ends"),
        ("پراید از ۱،۲ میلیارد به بالا", (1_200_000_000, None), "a floor"),
        ("حداقل ۱،۲ میلیارد", (1_200_000_000, None), "a floor by its word"),
        ("مدل ۹۹،۲ میلیارد", (None, 2_000_000_000), "after «مدل» the number is a year"),
        ("مدل۹۸،۵ میلیارد", (None, 5_000_000_000), "after «مدل» with no space too"),
        ("سال ۹۹،۳ میلیارد", (None, 3_000_000_000), "after «سال»"),
        ("سال۹۹،۳ میلیارد", (None, 3_000_000_000), "after «سال» with no space"),
        ("پراید زیر ۱۲،۵ میلیارد", (None, 12_500_000_000), "a whole part of two digits"),
        ("پژو ۴۰۵،۲ میلیارد", (None, 2_000_000_000), "a whole part of three digits is a model"),
        ("مدل ۱۴۰۰،۲ میلیارد", (None, 2_000_000_000), "a year of four digits"),
        ("سفید،۵۰۰ میلیون", (None, 500_000_000), "no digit before it"),
        ("پراید زیر ۱،۵۰۰ میلیون", (None, 500_000_000),
         "left: three digits after it are a thousands separator or a clause, not read"),
        ("۱،۵ تا ۲ میلیارد", (1_500_000_000, 2_000_000_000),
         "a range's lower end with a decimal and no scale word, D111's guard letting it through (G3)"),
        ("1.5 تا 2 میلیارد", (1_500_000_000, 2_000_000_000), "the same with «.»")]:
    sp_dec = P.parse(q_dec)
    check(f"«{q_dec}» → floor {want[0]}, ceiling {want[1]}  ({why})",
          (sp_dec.budget_min_toman, sp_dec.budget_max_toman) == want,
          f"{sp_dec.budget_min_toman} {sp_dec.budget_max_toman}")
sp_dec = P.parse("مدل ۹۹،۲ میلیارد")
check("«مدل ۹۹،۲ میلیارد» → the year 1399, read as before", sp_dec.year_min == 1399, str(sp_dec.year_min))

# A range whose lower end has a decimal and no scale word (G3, the owner's choice of 2026-11-22
# on a measurement): D111's guard left «X تا Y» with neither «بین» nor «از» and no scale word on X
# as it was, X being perhaps a model's number; a model's number and a year have no decimal part,
# so an X with one is a range's lower end, unless it stands right after «موتور» or «حجم».
for q_rng, want, why in [
        ("پراید ۱.۲ تا ۱.۸ میلیارد", (1_200_000_000, 1_800_000_000), "a range"),
        ("سمند ۲.۵ تا ۳ میلیارد سفید", (2_500_000_000, 3_000_000_000), "a range, a word after it"),
        ("یه ماشین خانوادگی ۱/۵ تا ۲ میلیارد میخوام", (1_500_000_000, 2_000_000_000), "with «/»"),
        ("موتور ۱.۸ تا ۲ میلیارد", (None, 2_000_000_000), "after «موتور» it is an engine's size"),
        ("حجم ۱.۸ تا ۲ میلیارد", (None, 2_000_000_000), "after «حجم» too"),
        ("پژو ۲۰۷ موتور ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000), "a model, then the engine"),
        ("موتور ۱.۶ تا ۵۰۰ میلیون", (None, 500_000_000), "the ten-times bound"),
        ("پژو ۲۰۶ تا ۴۰۰ میلیون", (None, 400_000_000), "D111's guard: a model's number"),
        ("پراید ۱.۵ تا ۱ میلیارد", (None, 1_000_000_000), "upside down, as before"),
        ("۱.۵ تا ۲ میلیارد نباشه", (None, 2_000_000_000), "a negation after it, as before"),
        ("سی سی ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000), "after «سی سی» too, since E2"),
        ("توربو ۱.۷ تا ۲ میلیارد", (None, 2_000_000_000), "  after «توربو»")]:
    sp_rng = P.parse(q_rng)
    check(f"«{q_rng}» → floor {want[0]}, ceiling {want[1]}  ({why})",
          (sp_rng.budget_min_toman, sp_rng.budget_max_toman) == want,
          f"{sp_rng.budget_min_toman} {sp_rng.budget_max_toman}")
# A range whose lower end is a whole number with no scale word (W3, the owner's choice of
# 2026-11-22 on a measurement): D111's guard held back every such X, as perhaps a model's number
# or a year, so «۵۰۰ تا ۸۰۰ میلیون» was a ceiling of 800 million alone. It holds back a year (two
# digits from 60 to 99, four from 1300 to 1499 or 1950 to 2030), an X right after «سال», «موتور»
# or «حجم», and an X of three or four digits that is not a multiple of 50; the range rule judges
# the rest as it judges the X of «الی».
for q_rng, want, why in [
        ("۵۰۰ تا ۸۰۰ میلیون", (500_000_000, 800_000_000), "a range, where it was a ceiling alone"),
        ("پراید ۳۰۰ تا ۴۵۰ میلیون", (300_000_000, 450_000_000), "after a model's name"),
        ("یه ماشین خانوادگی ۱ تا ۲ میلیارد میخوام", (1_000_000_000, 2_000_000_000),
         "one digit, in billions"),
        ("سمند ۸۰۰ تا ۱.۲ میلیارد سفید", (800_000_000, 1_200_000_000), "a million below a billion"),
        ("۱۲۰۰ تا ۱۵۰۰ میلیون", (1_200_000_000, 1_500_000_000), "four digits, no year"),
        ("پراید شیراز ۳۰۰ تا ۴۰۰ میلیون", (300_000_000, 400_000_000), "after a place"),
        ("۱۵ تا ۲۰ میلیارد", (15_000_000_000, 20_000_000_000), "two digits, no year"),
        ("پراید ۱۳۱ تا ۳۰۰ میلیون", (None, 300_000_000), "the table's model number, as before"),
        ("پراید ۹۸ تا ۴۰۰ میلیون", (None, 400_000_000), "a year of two digits"),
        ("هیوندای ۲۰۱۵ تا ۳ میلیارد", (None, 3_000_000_000), "a Gregorian year"),
        ("پراید سال ۹۵ تا ۲۵۰ میلیون", (None, 250_000_000), "a year after «سال»"),
        ("بنز سال ۵۵ تا ۴۰۰ میلیون", (None, 400_000_000),
         "after «سال», though its two digits are below 60"),
        ("تندر ۹۰ تا ۸۰۰ میلیون", (None, 800_000_000), "a model's number of two digits, read as a year"),
        ("پراید ۱۴۱ تا ۳۰۰ میلیون", (None, 300_000_000), "three digits, not round: a model's number"),
        ("پژو ۳۰۱ تا ۹۰۰ میلیون", (None, 900_000_000), "  another"),
        ("پژو ۵۰۸ تا ۲ میلیارد", (None, 2_000_000_000), "  in billions"),
        ("پژو ۳۰۰۸ تا ۵ میلیارد", (None, 5_000_000_000), "  four digits"),
        ("موتور ۱۶۰۰ تا ۲ میلیارد", (None, 2_000_000_000), "after «موتور», a whole engine's size"),
        ("۲۰۶ تیپ ۲ تا ۹۰۰ میلیون", (None, 900_000_000), "a trim's number, by the ten-times bound"),
        ("پراید ۵۰۰ تا ۴۰۰ میلیون", (None, 400_000_000), "upside down, as before"),
        ("۵۰۰ تا ۸۰۰ میلیون نباشه", (None, 800_000_000), "a negation after it, as before"),
        ("ام وی ام ۵۵۰ تا ۹۰۰ میلیون", (None, 900_000_000),
         "a model's number that is round, held back since M3 by the owner's list"),
        ("تیگو ۸ تا ۹ میلیارد", (None, 9_000_000_000), "  of one digit"),
        ("۳۸۰ تا ۴۲۰ میلیون", (None, 420_000_000), "left: a lower end that is not round is held back"),
        ("۱۴۰۰ تا ۱۸۰۰ میلیون", (None, 1_800_000_000), "left: the same, one that is a year"),
        ("۲۰۰۰ تا ۲۵۰۰ میلیون", (None, 2_500_000_000), "  a Gregorian one"),
        ("۷۰ تا ۹۰ میلیارد", (None, 90_000_000_000), "  two digits")]:
    sp_rng = P.parse(q_rng)
    check(f"«{q_rng}» → floor {want[0]}, ceiling {want[1]}  ({why})",
          (sp_rng.budget_min_toman, sp_rng.budget_max_toman) == want,
          f"{sp_rng.budget_min_toman} {sp_rng.budget_max_toman}")
# An engine's size after a word other than «موتور» or «حجم» (E2, the owner's choice of 2026-11-22
# on a measurement): «پیشرانه», «توربو», «سی سی» and «cc» hold the X after them back from being a
# range's lower end, «سی سی» and «cc» not right after a number, which has said the size already.
for q_rng, want, why in [
        ("سی‌سی ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000), "«سی‌سی» with a ZWNJ"),
        ("سیسی ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000), "  glued"),
        ("cc 1.6 تا 2 میلیارد", (None, 2_000_000_000), "«cc»"),
        ("CC ۱.۸ تا ۳ میلیارد", (None, 3_000_000_000), "  in capitals"),
        ("پیشرانه ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000), "«پیشرانه»"),
        ("دنا پلاس توربو ۱.۷ تا ۲ میلیارد", (None, 2_000_000_000), "«توربو» after a model's name"),
        ("سی سی ۱۶۰۰ تا ۲ میلیارد", (None, 2_000_000_000), "a whole X"),
        ("پیشرانه ۱۸۰۰ تا ۳ میلیارد", (None, 3_000_000_000), "  another"),
        ("۱۶۰۰ سی سی ۱.۵ تا ۲ میلیارد", (1_500_000_000, 2_000_000_000),
         "«سی سی» after a number has said the size: a price's range"),
        ("۱۶۰۰سی سی ۱.۵ تا ۲ میلیارد", (1_500_000_000, 2_000_000_000), "  the number glued to it"),
        ("موتور ۱۶۰۰ سی سی ۱.۲ تا ۱.۸ میلیارد", (1_200_000_000, 1_800_000_000), "  after «موتور ۱۶۰۰»"),
        ("حجم ۱۸۰۰ cc ۲ تا ۳ میلیارد", (2_000_000_000, 3_000_000_000), "  «cc», and a whole X"),
        ("۱.۶ لیتر ۱.۵ تا ۲ میلیارد", (1_500_000_000, 2_000_000_000), "«لیتر» is no such word"),
        ("پژو ۲۰۷ سی سی ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000),
         "the table's model number before «سی سی» is no size said, since M3"),
        ("دنا توربو ۱.۵ تا ۲ میلیارد", (None, 2_000_000_000),
         "left: «توربو» after a model's name holds back a price's lower end"),
        ("تارا توربو ۲ تا ۳ میلیارد", (None, 3_000_000_000), "  a whole one")]:
    sp_rng = P.parse(q_rng)
    check(f"«{q_rng}» → floor {want[0]}, ceiling {want[1]}  ({why})",
          (sp_rng.budget_min_toman, sp_rng.budget_max_toman) == want,
          f"{sp_rng.budget_min_toman} {sp_rng.budget_max_toman}")
# A model's number right after a name (M3, the owner's choice of 2026-11-22 on a measurement):
# «سی سی» or «cc» after one of the table's model numbers holds X back, the number being a model's
# and no size said; and a whole X that is one of the numbers the owner's list gives the name
# right before it («تیگو» 5, 7, 8; «آریزو» 5, 6; «مزدا» 2, 3, 6; «ام وی ام» 110, 315, 530, 550) is
# a model's, not a price's lower end.
for q_rng, want, why in [
        ("چری تیگو ۷ تا ۹ میلیارد", (None, 9_000_000_000), "«تیگو» 7, after its make"),
        ("آریزو ۵ تا ۶ میلیارد", (None, 6_000_000_000), "«آریزو» 5"),
        ("مزدا ۳ تا ۵ میلیارد", (None, 5_000_000_000), "«مزدا» 3"),
        ("ام‌وی‌ام ۵۵۰ تا ۹۰۰ میلیون", (None, 900_000_000), "«ام وی ام» with ZWNJs"),
        ("پژو ۴۰۵ سی سی ۱.۸ تا ۲ میلیارد", (None, 2_000_000_000), "405 before «سی سی»"),
        ("پژو ۲۰۶ CC ۱.۴ تا ۲ میلیارد", (None, 2_000_000_000), "  «CC», in capitals"),
        ("پژو ۲۰۷ سیسی ۱.۶ تا ۲ میلیارد", (None, 2_000_000_000), "  «سیسی», glued"),
        ("مزدا سفید ۳ تا ۵ میلیارد", (3_000_000_000, 5_000_000_000),
         "a listed number not right after the name is a price's lower end"),
        ("تیگو ۷.۵ تا ۹ میلیارد", (7_500_000_000, 9_000_000_000), "  and so is a decimal after it"),
        ("۱۲۰۶ سی سی ۱.۵ تا ۲ میلیارد", (1_500_000_000, 2_000_000_000),
         "a number that holds 206 is a size said: a price's range"),
        ("تیگو ۴ تا ۵ میلیارد", (4_000_000_000, 5_000_000_000), "a number the list does not give the name"),
        ("سمند ۱ تا ۲ میلیارد", (1_000_000_000, 2_000_000_000), "a name the list does not hold"),
        ("ام وی ام ۶۰۰ تا ۸۰۰ میلیون", (600_000_000, 800_000_000), "  «ام وی ام» 600"),
        ("یه ماشین خانوادگی ۲ تا ۳ میلیارد میخوام", (2_000_000_000, 3_000_000_000), "no name before it"),
        ("هایما ۷ تا ۹ میلیارد", (None, 9_000_000_000), "«هایما» 7, in the list since 2026-11-25"),
        ("هایما ۸ تا ۱۰ میلیارد", (None, 10_000_000_000), "  «هایما» 8"),
        ("جک اس ۵ تا ۸ میلیارد", (None, 8_000_000_000), "«اس» 5, a series word before the number"),
        ("هایما اس ۷ تا ۹ میلیارد", (None, 9_000_000_000), "  «اس» 7, after «هایما»"),
        ("جک اس ۳ تا ۵ میلیارد", (None, 5_000_000_000), "  «اس» 3"),
        ("اس ۵ تا ۸ میلیارد", (None, 8_000_000_000), "  «اس» with no make before it"),
        ("هایما ۴ تا ۶ میلیارد", (4_000_000_000, 6_000_000_000), "a number the list does not give «هایما»"),
        ("جک اس ۵ ۳ تا ۴ میلیارد", (3_000_000_000, 4_000_000_000), "a price's range after the model's number"),
        ("اس ۲ تا ۳ میلیارد", (2_000_000_000, 3_000_000_000), "a number the list does not give «اس»"),
        ("بنز اس کلاس ۵ تا ۸ میلیارد", (5_000_000_000, 8_000_000_000),
         "«کلاس» ends in «اس» and is no «اس»: a price's range"),
        ("هایما ۷ تا ۸ میلیارد", (None, 8_000_000_000),
         "left: a number the list gives the name is held back, a price meant or not"),
        ("اس ۵ تا ۶ میلیارد", (None, 6_000_000_000), "  after «اس»"),
        ("مزدا ۲ تا ۳ میلیارد", (None, 3_000_000_000),
         "left: a number the list gives the name is held back, a price meant or not")]:
    sp_rng = P.parse(q_rng)
    check(f"«{q_rng}» → floor {want[0]}, ceiling {want[1]}  ({why})",
          (sp_rng.budget_min_toman, sp_rng.budget_max_toman) == want,
          f"{sp_rng.budget_min_toman} {sp_rng.budget_max_toman}")
sp_rng = P.parse("حدود ۱.۵ تا ۲ میلیارد")
check("«حدود ۱.۵ تا ۲ میلیارد» → 1.5 to 2 billion, soft",
      (sp_rng.budget_min_toman, sp_rng.budget_max_toman, sp_rng.budget_hard) == (1_500_000_000, 2_000_000_000, False),
      f"{sp_rng.budget_min_toman} {sp_rng.budget_max_toman} {sp_rng.budget_hard}")
sp_dec = P.parse("موتور ۱،۶ باشه")
check("«موتور ۱،۶ باشه» → no budget, and «موتور 1/6 باشه» not understood, «،» written as «/» (left)",
      (sp_dec.budget_min_toman, sp_dec.budget_max_toman, sp_dec.unparsed) == (None, None, ("موتور 1/6 باشه",)),
      f"{sp_dec.budget_min_toman} {sp_dec.budget_max_toman} {sp_dec.unparsed}")
for q_dec, want in [("پراید ۱۱۱/۳۰۰ میلیون", 300_000_000),
                    ("پراید ۱۳۱/۱۱۱ تا ۳۰۰ میلیون", 300_000_000),
                    ("پراید مدل ۱۴۰۰/۰۵/۰۲ زیر ۳۰۰ میلیون", 300_000_000)]:
    check(f"«{q_dec}» → ceiling {want:,}  (a part of three digits, or a date, is no decimal)",
          P.parse(q_dec).budget_max_toman == want, str(P.parse(q_dec).budget_max_toman))
q_dec = "پراید ۱۰/۱۲ میلیون کارکرد"
check(f"«{q_dec}» → 10,120,000, left  (two numbers with a slash between and a scale word "
      "are read as one decimal; as a range they are 10 to 12)",
      P.parse(q_dec).budget_max_toman == 10_120_000, str(P.parse(q_dec).budget_max_toman))
q_dec = "پراید از ۱/۲ میلیارد به بالا"
check(f"«{q_dec}» → floor 1,200,000,000  (the floor's amount reads it too)",
      P.parse(q_dec).budget_min_toman == 1_200_000_000, str(P.parse(q_dec).budget_min_toman))
q_dec = "پراید ۲/۵ میلیارد و بالاتر"
check(f"«{q_dec}» → floor 2,500,000,000  (so does «و بالاتر»)",
      P.parse(q_dec).budget_min_toman == 2_500_000_000, str(P.parse(q_dec).budget_min_toman))

# ---------------------------------------------------------------------------
print("\na floor that a negation follows is a ceiling (2026-10-29, the owner's call)")
# «پراید از ۴۰۰ میلیون به بالا نباشه» is not-above-400-million. It was read as a
# floor of 400 million and no ceiling, the meaning reversed: 312 of 312 made
# phrasings (thirteen negations, six amounts, four contexts). The thirteen
# words `_floor_by_word` already refuses after its phrase are refused after
# `_FLOOR_S`'s too, and the ceiling rules read the query, with the assumption
# printed. After a year clause the negation may be the year's and is not read.
for neg in ("نباشه", "نباشد", "نباشن", "نباشند", "نیست", "نیستن", "نمی‌خوام", "نمی‌خواهم",
            "نمی‌خوایم", "نخوام", "نخواهم", "نخوایم", "نشه", "نره", "نرسه", "نگذره", "نزنه",
            "خرج نکنم"):
    q_neg = f"پراید از ۴۰۰ میلیون به بالا {neg}"
    sp_n = P.parse(q_neg)
    check(f"«{q_neg}» → no floor, ceiling 400,000,000, assumption printed",
          (sp_n.budget_min_toman, sp_n.budget_max_toman) == (None, 400_000_000)
          and any("سقف" in a for a in sp_n.assumptions),
          f"{sp_n.budget_min_toman} {sp_n.budget_max_toman} {sp_n.assumptions}")
for q_neg in ("206 بالای ۸۰۰ میلیون به بالا نباشه", "سمند، از ۱ میلیارد به بالا نشه",
              "از ۵۵۰ میلیون به بالا نباشه پراید"):
    sp_n = P.parse(q_neg)
    check(f"«{q_neg}» → no floor",
          sp_n.budget_min_toman is None and sp_n.budget_max_toman is not None,
          f"{sp_n.budget_min_toman} {sp_n.budget_max_toman}")
for q_neg, why in [
    ("پراید از ۴۰۰ میلیون به بالا باشه", "a positive tail"),
    ("پراید از ۴۰۰ میلیون به بالا، سفید", "a comma and a colour"),
    ("پراید از ۴۰۰ میلیون به بالا می‌خوام", "«می‌خوام» is not «نمی‌خوام»"),
    ("پراید از ۴۰۰ میلیون به بالا نمی‌رسه", "a negation outside the list, left"),
    ("پراید از ۴۰۰ میلیون به بالا نباید باشه", "«نباید», left"),
    ("پراید از ۴۰۰ میلیون به بالا اصلا نباشه", "a word between, left"),
    ("پراید از ۴۰۰ میلیون مدل ۹۸ به بالا نباشه", "after a year clause: the year's, left"),
    ("پراید از ۴۰۰ میلیون مدل ۱۳۹۸ به بالا نشه", "after a year clause, left"),
]:
    got_n = P.parse(q_neg).budget_min_toman
    check(f"«{q_neg}» → still floor 400,000,000  ({why})", got_n == 400_000_000, str(got_n))

# ---------------------------------------------------------------------------
print("\na bare «X به بالا» is a floor (2026-11-18, the owner's call)")
# «پراید ۴۰۰ میلیون به بالا», with no «از» or «بالای» before the amount, set no
# floor, and the amount was taken for the ceiling with «عدد قیمت را سقف بودجه
# فرض کردیم» printed: the meaning reversed, on 120 of 120 made phrasings of
# five forms (six amounts, four contexts). It is a floor now, with nothing
# printed, unless a negation follows at once or a ceiling's cue stands right
# before the amount; then the ceiling rules read the query as they did. Every
# phrasing is made here; no log of what buyers write exists.
_BARE_AMOUNTS = [("۴۰۰ میلیون", 400_000_000), ("۱.۵ میلیارد", 1_500_000_000),
                 ("۱ میلیارد و ۲۰۰ میلیون", 1_200_000_000), ("۴۰۰م", 400_000_000)]
for _form in ("{a} به بالا", "{a} تومان به بالا", "حدود {a} به بالا", "{a} به‌بالا",
              "{a} به بالاتر"):
    for _ctx in ("", "پراید ", "پژو ۲۰۶ ", "پراید مدل ۹۸ به بالا، "):
        got_b = [P.parse(_ctx + _form.format(a=a)) for a, _ in _BARE_AMOUNTS]
        check(f"«{_ctx}{_form.format(a='X')}», four amounts → floor X, no ceiling, nothing assumed",
              [(s.budget_min_toman, s.budget_max_toman) for s in got_b]
              == [(v, None) for _, v in _BARE_AMOUNTS]
              and not any(_FL_NOTE in a for s in got_b for a in s.assumptions),
              str([(s.budget_min_toman, s.budget_max_toman, s.assumptions) for s in got_b]))

for text, want_f, want_c, why in [
    # the rows that pinned it as left until this round
    ("پراید ۲۰۰ میلیون به بالا", 200_000_000, None, "no cue at all"),
    ("پراید ۴۰۰ میلیون به بالا", 400_000_000, None, "  another amount"),
    ("پراید شیراز ۲۰۰ میلیون به بالا", 200_000_000, None, "after a word that ends in «از»"),
    ("پراید اهواز ۲۰۰ میلیون به بالا", 200_000_000, None, "  the same"),
    ("پراید از قیمت ۲۰۰ میلیون به بالا", 200_000_000, None,
     "a word between a «از» and the amount"),
    ("پراید از مبلغ ۲۰۰ میلیون به بالا", 200_000_000, None, "  the same"),
    # with a ceiling, and with a year
    ("زیر ۸۰۰ میلیون، ۴۰۰ میلیون به بالا", 400_000_000, 800_000_000,
     "a ceiling clause before it"),
    ("پراید ۴۰۰ میلیون به بالا، تا ۸۰۰ میلیون", 400_000_000, 800_000_000,
     "  and after it"),
    ("پراید ۴۰۰ میلیون به بالا مدل ۹۸ به بالا", 400_000_000, None,
     "a year clause after it, its own «به بالا»"),
    ("پراید مدل ۹۵ تا ۹۸ ۴۰۰ میلیون به بالا", 400_000_000, None,
     "the «تا» of a year's range is not right before the amount"),
    ("پراید بودجه ۴۰۰ میلیون به بالا", 400_000_000, None,
     "«بودجه» before it, as «بودجه از X به بالا» is read"),
    ("پراید قیمت ۴۰۰ میلیون به بالا", 400_000_000, None, "  «قیمت»"),
    ("پراید ۴۰۰ میلیون به بالا در مشهد", 400_000_000, None, "a city after it"),
    ("پراید ۴۰۰ میلیون بهبالا", 400_000_000, None, "«بهبالا» with no space"),
    ("پراید ۴۰۰ میلیونبه بالا", 400_000_000, None, "  «میلیونبه» typed as one"),
    ("پراید ۳۰۰ میلیون به بالا، از ۴۰۰ میلیون به بالا", 400_000_000, 300_000_000,
     "two floors, left: the one with a cue is read, and the other amount is the ceiling"),
    ("پراید برای روستا ۴۰۰ میلیون به بالا", 400_000_000, None,
     "a word that ends in «تا» is no cue"),
    ("پراید تا ۸۰۰ میلیون به بالا نره، ۴۰۰ میلیون به بالا", 400_000_000, 800_000_000,
     "the first phrase refused, the second read"),
    ("پراید ۴۰۰ میلیون به بالاترین قیمت", None, 400_000_000,
     "a longer word after: not «به بالا»"),
    # a negation right after the phrase: the ceiling it was
    ("پراید ۴۰۰ میلیون به بالا نباشه", None, 400_000_000, "«نباشه»"),
    ("پراید ۴۰۰ میلیون به بالا نمی‌خوام", None, 400_000_000, "«نمی‌خوام»"),
    ("پراید ۴۰۰ میلیون به بالا نره", None, 400_000_000, "«نره»"),
    ("پراید ۴۰۰ میلیون به بالاتر نشه", None, 400_000_000, "«به بالاتر» and «نشه»"),
    # a ceiling's cue right before the amount: the ceiling it was
    ("پراید تا ۴۰۰ میلیون به بالا نمی‌تونم", None, 400_000_000,
     "«تا», and a negation outside the list"),
    ("پراید تا ۴۰۰ میلیون به بالا نره", None, 400_000_000, "«تا», and «نره»"),
    ("پراید تا ۴۰۰ میلیون به بالا", None, 400_000_000, "«تا» alone"),
    ("پراید تا حدود ۴۰۰ میلیون به بالا", None, 400_000_000, "  and a soft word"),
    ("پراید زیر ۴۰۰ میلیون به بالا", None, 400_000_000, "«زیر»"),
    ("پراید حداکثر ۴۰۰ میلیون به بالا", None, 400_000_000, "«حداکثر»"),
    ("پراید کمتر از ۴۰۰ میلیون به بالا", None, 400_000_000, "«کمتر از»"),
    ("پراید کم‌تر از ۴۰۰ میلیون به بالا", None, 400_000_000, "  «کم‌تر از»"),
    ("پراید ارزان‌تر از ۴۰۰ میلیون به بالا", None, 400_000_000, "«ارزان‌تر از»"),
    ("پراید پایین تر از ۴۰۰ میلیون به بالا", None, 400_000_000, "«پایین تر از»"),
    ("پراید کمتر ۴۰۰ میلیون به بالا", None, 400_000_000,
     "a comparative right before the amount, with no «از»"),
    ("پراید مدل ۹۸ تا ۴۰۰ میلیون به بالا", None, 400_000_000,
     "«مدل ۹۸ تا X»: the «تا» before the amount"),
    # measured and left, as for the suffix
    ("پراید ۴۰۰ میلیون به بالا نمی‌تونم", 400_000_000, None,
     "a negation outside the list is not seen, left"),
    ("پراید۴۰۰ میلیون به بالا", None, 400_000_000,
     "a figure glued to a word is not read, left"),
]:
    sp_b = P.parse(text)
    check(f"«{text}» → floor {_fl_amt(want_f)}, ceiling {_fl_amt(want_c)}  ({why})",
          (sp_b.budget_min_toman, sp_b.budget_max_toman) == (want_f, want_c),
          f"{sp_b.budget_min_toman} {sp_b.budget_max_toman}")

for text, printed, year, listed, why in [   # what is said, read and listed beside it
    ("پراید ۴۰۰ میلیون به بالا", False, None, (), "a floor: nothing assumed or listed"),
    ("پراید ۴۰۰ میلیون به بالا مدل ۹۸ به بالا", False, 1398, (), "  and the year read"),
    ("۴۰۰ میلیون به بالا در کاشان", False, None, ("در کاشان",), "a city after it is listed"),
    ("پراید ۴۰۰ میلیون به بالا نباشه", True, None, (),
     "negated: the ceiling is assumed, and said so"),
]:
    sp_b = P.parse(text)
    check(f"«{text}» → {'assumed' if printed else 'not assumed'}, year {year or '—'}, "
          f"listed {list(listed) or '—'}  ({why})",
          (any(_FL_NOTE in a for a in sp_b.assumptions), sp_b.year_min,
           tuple(t.strip() for t in sp_b.unparsed)) == (printed, year, listed),
          f"{sp_b.assumptions} {sp_b.year_min} {sp_b.unparsed}")

# ---------------------------------------------------------------------------
print("\na range gives both ends (2026-11-18, the owner's call)")
# «بین ۳۰۰ تا ۴۰۰ میلیون» read no floor: the upper end was the ceiling and the
# lower was dropped, or the first amount was taken for the ceiling with the
# assumption printed, which after «بین X و Y» and «X الی Y» was the lower end
# where it had a scale word. Right on 0 of 136 made phrasings of six forms (six
# pairs, four contexts). Both ends are read now, on 120 of 136; «X تا Y» with
# neither «بین» nor «از» and no scale word on X is left as it was, since
# «پژو ۲۰۶ تا ۴۰۰ میلیون» is written so. A range written upside down is the
# ceiling it was, the owner's choice. Every phrasing is made here; no log of
# what buyers write exists.
_RANGE_PAIRS = [("۳۰۰", "۴۰۰ میلیون", 300_000_000, 400_000_000),
                ("۸۰۰", "۱.۲ میلیارد", 800_000_000, 1_200_000_000),
                ("۱", "۱.۵ میلیارد", 1_000_000_000, 1_500_000_000),
                ("۹۰۰ میلیون", "۱ میلیارد", 900_000_000, 1_000_000_000)]
for _form, _pairs in [("بین {x} تا {y}", _RANGE_PAIRS), ("از {x} تا {y}", _RANGE_PAIRS),
                      ("بین {x} و {y}", _RANGE_PAIRS), ("{x} الی {y}", _RANGE_PAIRS),
                      ("{x}-{y}", _RANGE_PAIRS[:3]),
                      ("{x} تا {y}", [("۳۰۰ میلیون", "۴۰۰ میلیون", 300_000_000, 400_000_000),
                                      ("۹۰۰ میلیون", "۱ میلیارد", 900_000_000, 1_000_000_000)])]:
    for _ctx in ("", "پراید ", "پژو ۲۰۶ ", "پراید مدل ۹۸ به بالا، "):
        got_r = [P.parse(_ctx + _form.format(x=x, y=y)) for x, y, _, _ in _pairs]
        check(f"«{_ctx}{_form.format(x='X', y='Y')}», {len(_pairs)} pairs → floor X, ceiling Y, "
              "nothing assumed",
              [(s.budget_min_toman, s.budget_max_toman) for s in got_r]
              == [(lo, hi) for _, _, lo, hi in _pairs]
              and not any(_FL_NOTE in a for s in got_r for a in s.assumptions),
              str([(s.budget_min_toman, s.budget_max_toman, s.assumptions) for s in got_r]))

for text, want_f, want_c, why in [
    # the rows that pinned it as left until this round
    ("پراید از ۲۰۰ تا ۴۰۰ میلیون مدل ۹۸ به بالا", 200_000_000, 400_000_000,
     "a range with a year clause"),
    ("پراید از ۲۰۰ میلیون تا ۴۰۰ میلیون مدل ۹۸ به بالا", 200_000_000, 400_000_000,
     "  a unit on both"),
    # the lower end's scale
    ("بین ۰.۸ تا ۱.۲ میلیارد", 800_000_000, 1_200_000_000, "a decimal lower end"),
    ("بین ۱۲۰ تا ۱.۲ میلیارد", 120_000_000, 1_200_000_000, "  ten times apart"),
    ("بین ۱۰۰ تا ۱.۲ میلیارد", None, 1_200_000_000, "more than ten times: no range"),
    ("بین ۳۰ تا ۴۰۰ میلیون", None, 400_000_000, "  the same in millions"),
    ("۳۰ میلیون تا ۴۰۰ میلیون", 30_000_000, 400_000_000,
     "a lower end with its own scale word is taken as written"),
    ("بین ۴۰۰ تا ۴۰۰ میلیون", None, 400_000_000, "the two ends equal: no range"),
    ("بین ۴۰۰ میلیون تا ۴۰۰ میلیون", None, 400_000_000, "  each with its scale word"),
    ("بین ۴۰۰ تا ۳۰۰ میلیون", None, 300_000_000, "upside down: the ceiling it was"),
    ("بین ۴۰۰ میلیون تا ۳۰۰ میلیون", None, 300_000_000, "  each with its scale word"),
    ("بین ۱.۵ تا ۱ میلیارد", None, 1_000_000_000, "  in billions"),
    ("بین ۱ تا ۱.۵ ملیارد", 1_000_000_000, 1_500_000_000, "«ملیارد», as it is also typed"),
    ("بین ۱/۵ تا ۲ میلیارد", 1_500_000_000, 2_000_000_000, "«/» as the decimal mark"),
    ("بین ۱٫۵ تا ۲ میلیارد", 1_500_000_000, 2_000_000_000, "  «٫»"),
    ("از ۳۰۰ تا ۴۰۰م", 300_000_000, 400_000_000, "«م» on the upper end"),
    ("بین ۳۰۰م تا ۴۰۰م", 300_000_000, 400_000_000, "  and on the lower"),
    ("بین ۳۰۰ تا حدود ۴۰۰ میلیون", 300_000_000, 400_000_000, "a soft word on the upper end"),
    ("۳۰۰-۴۰۰ میلیون به بالا", 300_000_000, 400_000_000,
     "«به بالا» after a range: the range is read first"),
    ("بین ۳۰۰ تا ۴۰۰ میلیون، زیر ۵۰۰ میلیون", 300_000_000, 400_000_000,
     "a ceiling clause after a range is not asked"),
    ("بین ۳۰۰ میلیون تومان تا ۴۰۰ میلیون تومان", 300_000_000, 400_000_000,
     "a currency word on both ends"),
    ("بین حدود ۳۰۰ تا ۴۰۰ میلیون", 300_000_000, 400_000_000, "a soft word"),
    ("۳۰۰–۴۰۰ میلیون", 300_000_000, 400_000_000, "an en dash"),
    ("بین ۳۰۰ - ۴۰۰ میلیون", 300_000_000, 400_000_000, "a spaced dash after «بین»"),
    ("پراید مدل ۹۵ تا ۹۸ ۳۰۰ میلیون تا ۴۰۰ میلیون", 300_000_000, 400_000_000,
     "after a year's range, whose «تا» took the lower end for the ceiling"),
    ("کارکرد زیر ۱۰۰ هزار، بین ۳۰۰ تا ۴۰۰ میلیون", 300_000_000, 400_000_000,
     "after an odometer"),
    # with neither «بین» nor «از»: a whole X, read since W3 (2026-11-22) where it is no
    # model's number and no year; the rest read as it was
    ("پراید ۳۰۰ تا ۴۰۰ میلیون", 300_000_000, 400_000_000, "«X تا Y», X with no scale word"),
    ("کوییک ۸۰۰ تا ۹۰۰ میلیون", 800_000_000, 900_000_000, "  another"),
    ("پژو ۲۰۶ تا ۴۰۰ میلیون", None, 400_000_000, "  a model's number and a ceiling"),
    ("تیبا ۱۴۰۰ تا ۲ میلیارد", None, 2_000_000_000, "  a year and a ceiling"),
    ("۳۰۰ و ۴۰۰ میلیون", None, 400_000_000, "«و» without «بین»"),
    ("از ۳۰۰ و ۴۰۰ میلیون", None, 400_000_000, "  after «از»"),
    ("پراید شیراز ۹۸ تا ۴۰۰ میلیون", None, 400_000_000,
     "the «از» that ends a word is no «از», which would let the year through"),
    ("۳۰۰ - ۴۰۰ میلیون", None, 400_000_000, "a spaced dash"),
    ("۳۰۰ -۴۰۰ میلیون", None, 400_000_000, "  a space before it only"),
    ("۳۰۰- ۴۰۰ میلیون", None, 400_000_000, "  a space after it only"),
    ("۳۰۰ – ۴۰۰ میلیون", None, 400_000_000, "  an en dash, spaced"),
    ("پژو ۲۰۶ - ۴۰۰ میلیون", None, 400_000_000, "  a field and a price"),
    ("پژو ۲۰۶ – ۴۰۰ میلیون", None, 400_000_000, "  an en dash"),
    ("پژو ۲۰۶-۴۰۰ میلیون", None, 400_000_000, "a model's number before a bare dash"),
    ("پژو ۲۰۶ الی ۴۰۰ میلیون", None, 400_000_000, "  before «الی»"),
    ("پراید ۱۳۱ الی ۴۰۰ میلیون", None, 400_000_000, "  Pride's 131"),
    ("پراید مدل ۹۸ - ۴۰۰ میلیون", None, 400_000_000, "a year after «مدل»"),
    ("پراید مدل ۹۸-۴۰۰ میلیون", None, 400_000_000, "  before a bare dash"),
    ("پراید مدل ۹۸ تا ۴۰۰ میلیون", None, 400_000_000, "  before «تا»"),
    # a ceiling's cue before it, or a negation after: read as it was
    ("حداکثر ۳۰۰ میلیون تا ۴۰۰ میلیون", None, 300_000_000, "«حداکثر»"),
    ("زیر ۳۰۰ میلیون تا ۴۰۰ میلیون", None, 300_000_000, "«زیر»"),
    ("پراید کمتر از ۳۰۰ تا ۴۰۰ میلیون", None, 400_000_000, "«کمتر از»"),
    ("پراید ارزان‌تر از ۳۰۰ تا ۴۰۰ میلیون", None, 400_000_000, "«ارزان‌تر از»"),
    ("بین ۳۰۰ تا ۴۰۰ میلیون نباشه", None, 400_000_000, "a negation right after"),
    ("بین ۳۰۰ تا ۴۰۰ میلیون تومان نباشه", None, 400_000_000, "  after a currency word"),
    # no money: no range
    ("پراید مدل ۹۵ تا ۹۸", None, None, "a year's range"),
    ("پراید ۵۰ تا ۱۰۰ هزار کیلومتر", None, None, "an odometer's"),
    ("بین ۳۰۰ تا ۴۰۰ هزار کیلومتر", None, None, "  with «بین»"),
    # measured and left
    ("بین ۱ میلیارد و ۲۰۰ میلیون تا ۲ میلیارد", None, 2_000_000_000,
     "a lower end with «و» and a second unit is not taken, left"),
    ("تیبا ۱۴۰۰-۲ میلیارد", 1_400_000_000, 2_000_000_000,
     "a year against a price with a bare dash is a range, left"),
    ("تیبا از ۹۵ تا ۴۰۰ میلیون", 95_000_000, 400_000_000,
     "«از» and a figure with no «مدل» is the lower end, left"),
    ("پراید۳۰۰ میلیون تا ۴۰۰ میلیون", None, 400_000_000,
     "a figure glued to a word is not read, left"),
]:
    sp_r = P.parse(text)
    check(f"«{text}» → floor {_fl_amt(want_f)}, ceiling {_fl_amt(want_c)}  ({why})",
          (sp_r.budget_min_toman, sp_r.budget_max_toman) == (want_f, want_c),
          f"{sp_r.budget_min_toman} {sp_r.budget_max_toman}")

for text, year, listed, why in [   # what is read beside a range, and what is listed
    ("بین ۳۰۰ تا ۴۰۰ میلیون", None, (), "the lower end is read, not listed"),
    ("بین ۳۰۰ و ۴۰۰ میلیون", None, (), "  and nothing assumed"),
    ("بین ۳۰۰ تا ۴۰۰ میلیون در کاشان", None, ("در کاشان",), "a city after it is listed"),
    ("پراید بین ۳۰۰ تا ۴۰۰ میلیون مدل ۱۴۰۰ به بالا", 1400, (), "a year clause after it"),
    ("پراید مدل ۹۵ تا ۹۸ ۳۰۰ میلیون تا ۴۰۰ میلیون", 1395, (), "  a year's range before it"),
]:
    sp_r = P.parse(text)
    check(f"«{text}» → year {year or '—'}, listed {list(listed) or '—'}, nothing assumed  ({why})",
          (sp_r.year_min, tuple(t.strip() for t in sp_r.unparsed)) == (year, listed)
          and not any(_FL_NOTE in a for a in sp_r.assumptions),
          f"{sp_r.year_min} {sp_r.unparsed} {sp_r.assumptions}")
check("«بین حدود ۳۰۰ تا ۴۰۰ میلیون» → the budget is soft, as «حدود» makes any budget",
      P.parse("بین حدود ۳۰۰ تا ۴۰۰ میلیون").budget_hard is False)

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
print("\na Latin name is read in capitals too (2026-11-26, the owner's choice on a measurement)")
# The table writes its Latin names in lower case and `names` compared the text
# as written: «Pride زیر ۵۰۰ میلیون» named nothing, and its clause was listed as
# not understood. Measured, the predictions locked first: none of six such
# queries named its model, all six do; none of the 1,338 queries the suites
# hand the parser reads differently. A Persian name is not touched.
for q, want, budget in [
    ("Pride زیر 500 میلیون", {"pride"}, 500_000_000),
    ("TIBA 2 مدل 98", {"tiba"}, None),
    ("Dena Plus زیر 2 میلیارد", {"dena"}, 2_000_000_000),
    ("QUIK اتوماتیک زیر 1 میلیارد", {"quik"}, 1_000_000_000),
    ("Saina زیر 600 میلیون", {"saina"}, 600_000_000),
    ("Shahin تا 1 میلیارد", {"shahin"}, 1_000_000_000),
]:
    _sp = P.parse(q)
    check(f"«{q}» → {sorted(want)}, the budget as written", set(_sp.model_hints) == want
          and _sp.budget_max_toman == budget, str((_sp.model_hints, _sp.budget_max_toman)))
_cap, _low = P.parse("Pride سفید خوشگل"), P.parse("pride سفید خوشگل")
check("a clause that holds a name in capitals is understood as the same name in lower case is: "
      "«Pride سفید خوشگل» is not listed under «نفهمیدیم»",
      _cap.unparsed == _low.unparsed == () and _cap.model_hints == _low.model_hints == ("pride",),
      str((_cap.unparsed, _low.unparsed)))


# ---------------------------------------------------------------------------
print("\nrun17's hundred, by name (2026-11-26, the owner's choice on a measurement, M2kc)")
# 211 of run17's 492 listings were of 104 models no table named, and a query
# could not name them (D98). The owner chose names for 100 of them, written
# before anything was measured (caro/ingest/models.py). Each model below is
# written out with its first Persian name and its first Latin one -- not read
# from the table, so that a name dropped from it turns a row red -- and each
# is asked for by either, the Latin in capitals, under a ceiling. A name that
# holds another model's name names both: «x22 پرو» is the X22 Pro's and holds
# the X22's, as measured.
_RN_HUNDRED = [
    ("s7", "هایما اس 7", "haima s7"),
    ("8s", "هایما 8 اس", "haima 8s"),
    ("7x", "هایما 7 ایکس", "haima 7x"),
    ("j7", "کی ام سی j7", "kmc j7"),
    ("x5", "کی ام سی x5", "kmc x5"),
    ("eagle", "کی ام سی ایگل", "kmc eagle"),
    ("t8", "کی ام سی t8", "kmc t8"),
    ("a5", "کی ام سی a5", "kmc a5"),
    ("k7", "کی ام سی k7", "kmc k7"),
    ("eama", "لاماری ایما", "lamari eama"),
    ("x33 cross", "ام وی ام x33 کراس", "x33 cross"),
    ("x33s", "ام وی ام x33 اس", "x33s"),
    ("x33", "ام وی ام x33", "mvm x33"),
    ("x22 pro", "ام وی ام x22 پرو", "x22 pro"),
    ("x22", "ام وی ام x22", "mvm x22"),
    ("x55 pro", "ام وی ام x55 پرو", "x55 pro"),
    ("x55", "ام وی ام x55", "mvm x55"),
    ("550", "ام وی ام 550", "mvm 550"),
    ("hatchback-315", "ام وی ام 315", "mvm 315"),
    ("h30 cross", "دانگ فنگ h30", "h30 cross"),
    ("sonata", "سوناتا", "sonata"),
    ("azera (grandeur)", "آزرا", "azera"),
    ("i20", "آی 20", "i20"),
    ("accent assembled", "اکسنت", "accent"),
    ("avante", "آوانته", "avante"),
    ("elantra", "النترا", "elantra"),
    ("genesis", "جنسیس", "genesis"),
    ("santafe (ix45)", "سانتافه", "santafe"),
    ("tucson (ix35)", "توسان", "tucson"),
    ("s3", "جک اس 3", "jac s3"),
    ("j4", "جک j4", "jac j4"),
    ("j5", "جک j5", "jac j5"),
    ("3 sedan-assembled (new)", "مزدا 3", "mazda 3"),
    ("gl", "اطلس جی ال", "atlas gl"),
    ("g", "اطلس جی", "atlas g"),
    ("arrizo 5t sport fl", "آریزو 5 تی اسپرت", "arrizo 5t sport"),
    ("arrizo 5t", "آریزو 5 تی", "arrizo 5t"),
    ("arrizo 6", "چری آریزو 6", "chery arrizo 6"),
    ("tiggo 5", "تیگو 5", "tiggo 5"),
    ("tiggo 7", "چری تیگو 7", "chery tiggo 7"),
    ("tiggo8 pro max (f8 max)", "تیگو 8", "tiggo 8"),
    ("tiggo7pro max", "تیگو 7 پرو مکس", "tiggo 7 pro max"),
    ("tiggo7pro hybrid", "تیگو 7 پرو هیبرید", "tiggo 7 pro hybrid"),
    ("arrizo 6 gt (z6)", "آریزو 6 جی تی", "arrizo 6 gt"),
    ("arrizo6pro", "آریزو 6 پرو", "arrizo 6 pro"),
    ("arizo 8 (z8)", "آریزو 8", "arrizo 8"),
    ("fx", "فونیکس fx", "fownix fx"),
    ("emgrand x7", "امگرند x7", "emgrand x7"),
    ("emgrand 7", "امگرند 7", "emgrand 7"),
    ("cerato-assembled", "سراتو", "cerato"),
    ("sorento", "سورنتو", "sorento"),
    ("optima", "اپتیما", "optima"),
    ("soul", "کیا سول", "kia soul"),
    ("sportage", "اسپورتیج", "sportage"),
    ("x60", "لیفان x60", "x60"),
    ("x70", "لیفان x70", "x70"),
    ("620", "لیفان 620", "lifan 620"),
    ("820", "لیفان 820", "lifan 820"),
    ("gs", "ام جی gs", "mg gs"),
    ("6", "ام جی 6", "mg6"),
    ("3", "ام جی 3", "mg3"),
    ("2008", "پژو 2008", "peugeot 2008"),
    ("tondar 90", "تندر 90", "tondar 90"),
    ("captur", "کپچر", "captur"),
    ("sandero-stepway", "ساندرو استپ وی", "sandero stepway"),
    ("sandero", "ساندرو", "sandero"),
    ("talisman", "تالیسمان", "talisman"),
    ("u5 plus", "یو5 پلاس", "u5 plus"),
    ("cs-55-plus", "cs55 پلاس", "cs55 plus"),
    ("cs55 assembled", "cs55 مونتاژ", "cs55 assembled"),
    ("cs35-assembled", "چانگان cs35", "cs35"),
    ("sx5", "فردا sx5", "sx5"),
    ("suba m4", "سوبا m4", "suba m4"),
    ("t5", "فردا t5", "farda t5"),
    ("elite", "فیدلیتی الیت", "fidelity elite"),
    ("prestige", "فیدلیتی پرستیژ", "fidelity prestige"),
    ("s", "سهند اس", "sahand s"),
    ("ciaz", "سیاز", "ciaz"),
    ("tissan s05", "تیگارد", "tigard"),
    ("camry", "کمری", "camry"),
    ("b30", "بسترن b30", "besturn b30"),
    ("h320", "برلیانس h320", "h320"),
    ("c5", "سیتروئن c5", "citroen c5"),
    ("trumpchi ga3s", "ترامپچی", "ga3s"),
    ("haval m4", "هاوال m4", "haval m4"),
    ("accord", "آکورد", "accord"),
    ("eqm5", "هونگچی", "eqm5"),
    ("tivoli-assembled", "تیوولی مونتاژ", "tivoli assembled"),
    ("tivoli", "تیوولی", "tivoli"),
    ("nx-hybrid", "لکسوس nx", "lexus nx"),
    ("kalut", "کالوت", "kalut"),
    ("asx", "میتسوبیشی asx", "asx"),
    ("lancer", "لنسر", "lancer"),
    ("ef7p", "ریرا", "reera"),
    ("g01", "اس دبلیو ام g01", "swm g01"),
    ("d60 plus", "ونوسیا d60", "d60 plus"),
    ("golf", "گلف", "golf"),
    ("passat", "پاسات", "passat"),
    ("lx (sx)", "اکستریم lx", "xtrim lx"),
    ("ario", "آریو", "ario"),
]
_RN_ALSO_FA = {"x33 cross": "x33", "x33s": "x33", "x22 pro": "x22", "x55 pro": "x55",
               "arrizo 5t sport fl": "arrizo 5t", "tivoli-assembled": "tivoli", "sandero-stepway": "sandero",
               "gl": "g"}
_RN_ALSO_LA = {k: v for k, v in _RN_ALSO_FA.items() if k not in ("x33s", "gl")}
_rn_bad = []
for _key, _fa, _la in _RN_HUNDRED:
    for _name, _also in ((_fa, _RN_ALSO_FA), (_la.upper(), _RN_ALSO_LA)):
        _sp = P.parse(f"{_name} زیر 5 میلیارد")
        _want = {_key, _also[_key]} if _key in _also else {_key}
        if set(_sp.model_hints) != _want or _sp.budget_max_toman != 5_000_000_000 or _sp.budget_min_toman:
            _rn_bad.append((_name, _sp.model_hints, _sp.budget_max_toman, _sp.budget_min_toman))
check(f"RN1: each of the {len(_RN_HUNDRED)} is named by its Persian name and by its Latin one in capitals, under "
      "a ceiling of five billion and no floor; alone, but the eight whose name holds another's, and the six of "
      "them whose Latin name does", len(_RN_HUNDRED) == 100 and not _rn_bad, str(_rn_bad[:6]))
_rn_four = [P.parse(f"{n} زیر 10 میلیارد").model_hints
            for n in ("دیگنیتی پرایم", "فیدلیتی پرایم", "جک اس 5", "هایما اس 5", "DIGNITY PRIME", "JAC S5")]
check("RN2: the four models two makes write -- «Prime» of Dignity and of Fidelity, «S5» of JAC and of Haima -- "
      "are named by their make and model alone, the search keying them so (2026-11-27, the owner's choice)",
      _rn_four == [("dignity|prime",), ("fidelity|prime",), ("jac|s5",), ("haima|s5",), ("dignity|prime",), ("jac|s5",)],
      str(_rn_four))
for q, want, why in [
    ("مزدا 323 تمیز زیر 1 میلیارد", set(), "«مزدا 3» is not in «مزدا 323», another model"),
    ("ام جی 350 زیر 2 میلیارد", set(), "  nor «ام جی 3» in «ام جی 350»"),
    ("پژو۲۰۶۹", {"206"}, "  a name of the thirteen is matched beside a digit, as D83's rows pin"),
    ("پرستیژ بالا زیر 2 میلیارد", set(), "a trim's word that is a model's only with its make"),
    ("فردا میرم ماشین بخرم زیر 1 میلیارد", set(), "  a make that is a word, alone"),
    ("گلفروشی ونک", set(), "a name inside a word"),
    ("کراس اوور زیر 3 میلیارد", set(), "a name's second word alone"),
    ("ماشین هیبرید زیر 5 میلیارد", set(), "  the same"),
    ("تندر پارس زیر 1 میلیارد", set(), "Renault's «تندر پارس» is no Tondar 90 and no Pars"),
    ("کمربند ایمنی سالم پراید", {"pride"}, "«کمری» is not in «کمربند»"),
    ("پژو 206 تیپ الیت", {"206"}, "«الیت» names Fidelity's only with its make"),
    ("تیگو ۸ تا ۹ میلیارد", {"tiggo8 pro max (f8 max)"}, "a model's number after «تیگو» is the model's"),
    ("چری تیگو ۷ تا ۹ میلیارد", {"tiggo 7"}, "  and «تیگو 7» with its make, Chery's"),
]:
    _sp = P.parse(q)
    check(f"«{q}» → {sorted(want) or 'no model'} ({why})", set(_sp.model_hints) == want, str(_sp.model_hints))


# ---------------------------------------------------------------------------
print("\na make named in the sentence (2026-11-27, the owner's choice on a measurement, B3)")
# «هایما زیر ۲ میلیارد» named no model and no make. A make is read where the
# query names no model (caro/ingest/models.py, MAKES). Each of run17's 45
# makes is written out with its first Persian name and its first Latin one --
# not read from the table, so that a name dropped from it turns a row red --
# and asked for by either, the Latin in capitals; where a make's name is its
# one model's too, the model is read, and the listings are the same.
_MK_ALL = [
    ("Peugeot", "پژو", "peugeot", ('make', 'Peugeot'), ('make', 'Peugeot')),
    ("IKCO", "ایران خودرو", "ikco", ('make', 'IKCO'), ('make', 'IKCO')),
    ("Saipa", "سایپا", "saipa", ('make', 'Saipa'), ('make', 'Saipa')),
    ("MVM", "ام وی ام", "mvm", ('make', 'MVM'), ('make', 'MVM')),
    ("KMC", "کی ام سی", "kmc", ('make', 'KMC'), ('make', 'KMC')),
    ("JAC", "جک", "jac", ('make', 'JAC'), ('make', 'JAC')),
    ("Hyundai", "هیوندای", "hyundai", ('make', 'Hyundai'), ('make', 'Hyundai')),
    ("Haima", "هایما", "haima", ('make', 'Haima'), ('make', 'Haima')),
    ("Chery", "چری", "chery", ('make', 'Chery'), ('make', 'Chery')),
    ("Fidelity", "فیدلیتی", "fidelity", ('make', 'Fidelity'), ('make', 'Fidelity')),
    ("Kia", "کیا", "kia", ('make', 'Kia'), ('make', 'Kia')),
    ("Fownix", "فونیکس", "fownix", ('make', 'Fownix'), ('make', 'Fownix')),
    ("Lifan", "لیفان", "lifan", ('make', 'Lifan'), ('make', 'Lifan')),
    ("Renault", "رنو", "renault", ('make', 'Renault'), ('make', 'Renault')),
    ("Dignity", "دیگنیتی", "dignity", ('make', 'Dignity'), ('make', 'Dignity')),
    ("Lamari", "لاماری", "lamari", ('model', 'eama'), ('model', 'eama')),
    ("Farda", "فردا موتورز", "farda", ('make', 'Farda'), ('make', 'Farda')),
    ("MG", "ام جی", "mg", ('make', 'MG'), ('make', 'MG')),
    ("Dongfeng", "دانگ فنگ", "dongfeng", ('make', 'Dongfeng'), ('make', 'Dongfeng')),
    ("Geely", "جیلی", "geely", ('make', 'Geely'), ('make', 'Geely')),
    ("Changan", "چانگان", "changan", ('make', 'Changan'), ('make', 'Changan')),
    ("Atlas", "اطلس", "atlas", ('make', 'Atlas'), ('make', 'Atlas')),
    ("Mazda", "مزدا", "mazda", ('make', 'Mazda'), ('make', 'Mazda')),
    ("Tigard", "تیگارد", "tigard", ('model', 'tissan s05'), ('model', 'tissan s05')),
    ("Sahand", "سهند", "sahand", ('make', 'Sahand'), ('make', 'Sahand')),
    ("Suzuki", "سوزوکی", "suzuki", ('make', 'Suzuki'), ('make', 'Suzuki')),
    ("Toyota", "تویوتا", "toyota", ('make', 'Toyota'), ('make', 'Toyota')),
    ("Volkswagen", "فولکس واگن", "volkswagen", ('make', 'Volkswagen'), ('make', 'Volkswagen')),
    ("KGM", "کی جی ام", "kgm", ('make', 'KGM'), ('make', 'KGM')),
    ("Mitsubishi", "میتسوبیشی", "mitsubishi", ('make', 'Mitsubishi'), ('make', 'Mitsubishi')),
    ("Beijing", "بیجینگ", "beijing", ('make', 'Beijing'), ('make', 'Beijing')),
    ("Great Wall", "گریت وال", "great wall", ('make', 'Great Wall'), ('make', 'Great Wall')),
    ("Honda", "هوندا", "honda", ('make', 'Honda'), ('make', 'Honda')),
    ("Lexus", "لکسوس", "lexus", ('make', 'Lexus'), ('make', 'Lexus')),
    ("Xtrim", "اکستریم", "xtrim", ('make', 'Xtrim'), ('model', 'lx (sx)')),
    ("GAC", "جی ای سی", "gac", ('make', 'GAC'), ('make', 'GAC')),
    ("Max Motor", "مکث موتور", "max motor", ('make', 'Max Motor'), ('make', 'Max Motor')),
    ("Reera", "ریرا", "reera", ('model', 'ef7p'), ('model', 'ef7p')),
    ("Hongqi", "هونگچی", "hongqi", ('model', 'eqm5'), ('make', 'Hongqi')),
    ("Brilliance", "برلیانس", "brilliance", ('make', 'Brilliance'), ('make', 'Brilliance')),
    ("SWM", "اس دبلیو ام", "swm", ('make', 'SWM'), ('make', 'SWM')),
    ("Citroen", "سیتروئن", "citroen", ('make', 'Citroen'), ('make', 'Citroen')),
    ("Venucia", "ونوسیا", "venucia", ('model', 'd60 plus'), ('make', 'Venucia')),
    ("Besturn", "بسترن", "besturn", ('model', 'b30'), ('make', 'Besturn')),
    ("Zotye", "زوتی", "zotye", ('make', 'Zotye'), ('make', 'Zotye')),
]
_mk_bad = []
for _mk, _fa, _la, _wf, _wl in _MK_ALL:
    for _name, (_kind, _what) in ((_fa, _wf), (_la.upper(), _wl)):
        _sp = P.parse(f"{_name} زیر 20 میلیارد")
        _got = ("model", _sp.model_hints[0]) if _sp.model_hints and not _sp.makes else (
            ("make", _sp.makes[0]) if _sp.makes and not _sp.model_hints and len(_sp.makes) == 1 else None)
        if _got != (_kind, _what) or _sp.budget_max_toman != 20_000_000_000:
            _mk_bad.append((_name, _sp.makes, _sp.model_hints))
check(f"MK1: each of the {len(_MK_ALL)} makes is read by its Persian name and by its Latin one in capitals, under a "
      "ceiling of twenty billion -- or, where its name is its one model's, the model", len(_MK_ALL) == 45 and not _mk_bad,
      str(_mk_bad[:6]))
for q, models, makes, why in [
    ("هیوندای سوناتا زیر 5 میلیارد", ("sonata",), (), "a make beside its model: the model, no make"),
    ("پراید با جک و زاپاس زیر 500 میلیون", ("pride",), (), "  a model and a make's name of another sense: no JAC"),
    ("سایپا پراید زیر 500 میلیون", ("pride",), (), "  the same"),
    ("پژو یا کیا زیر 1 میلیارد", (), ("Peugeot", "Kia"), "two makes, no model: both"),
    ("هایما 7 تا 9 میلیارد", (), ("Haima",), "a make and a number the owner's list holds back"),
    ("فردا میرم ماشین بخرم زیر 1 میلیارد", (), (), "«فردا» alone is no make: Farda is «فردا موتورز»"),
    ("مکث کردم سر خرید پراید", ("pride",), (), "  nor «مکث» alone, Max Motor's «مکث موتور»"),
    ("کیا دارن ماشین میفروشن", (), ("Kia",), "a make's name that is a word too is read: the cost, measured"),
    ("یه ماشین برای سهند زیر 1 میلیارد", (), ("Sahand",), "  the same"),
]:
    _sp = P.parse(q)
    check(f"«{q}» → models {list(models) or 'none'}, makes {list(makes) or 'none'} ({why})",
          _sp.model_hints == models and _sp.makes == makes, str((_sp.model_hints, _sp.makes)))
check("a clause that holds a make's name is understood: «هایما 7 تا 9 میلیارد» lists nothing under «نفهمیدیم»",
      P.parse("هایما 7 تا 9 میلیارد").unparsed == (), str(P.parse("هایما 7 تا 9 میلیارد").unparsed))


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

for q in [f"{_Q} در کاشان", f"{_Q} در دزفول", f"{_Q} در ساوه",
          f"{_Q} تهرانی", f"{_Q} تهرانپارس"]:
    check(f"«{q}» → no province: a city, or a word that only holds a name",
          P.parse(q).provinces == (), str(P.parse(q).provinces))

# The names of companies that hold a province's or a capital's, declined as «خلیج فارس» is (K2, the
# owner's choice of 2026-11-25 on a measurement): «کرمان موتور» and «کرمان خودرو», and Iran Khodro
# with four of its plants', «ایران خودرو» with a space and as one word. The owner's list is written
# out here, not read from the parser, so that a name dropped from its table turns a row red.
_K2 = ["کرمان موتور", "کرمان خودرو"] + [f"{i} {p}" for i in ("ایران خودرو", "ایرانخودرو")
                                        for p in ("تبریز", "مازندران", "کرمانشاه", "خراسان")]
for name in _K2:
    sp = P.parse(f"{_Q} {name}")
    check(f"«{_Q} {name}» → no province, «{name}» listed as not understood, no note",
          sp.provinces == () and [t.strip() for t in sp.unparsed] == [name]
          and not any("را استان" in a for a in sp.assumptions),
          f"{sp.provinces} {sp.unparsed} {sp.assumptions}")
for q, want, why in [
        ("جک J4 کرمان موتور", (), "a company's name"),
        ("هیوندای اکسنت کرمان موتور زیر ۲ میلیارد", (), "  beside a budget"),
        ("لیفان X60 کرمان خودرو", (), "  «کرمان خودرو»"),
        ("محصولات کرمان خودرو تا ۱.۵ میلیارد", (), "  beside a budget"),
        ("سمند ایران خودرو تبریز", (), "  a plant's"),
        ("دنا پلاس ایران خودرو تبریز", (), "  the same"),
        ("پژو ۴۰۵ ایران خودرو مازندران", (), "  another"),
        ("رانا ایران خودرو مازندران مدل ۹۸ به بالا", (), "  beside a year"),
        ("سمند ایران خودرو کرمانشاه", (), "  another"),
        ("پژو پارس ایران خودرو کرمانشاه", (), "  the same"),
        ("دنا ایران خودرو خراسان", (), "  «خراسان», a family, declined as before"),
        ("پژو ۲۰۶ ایران خودرو خراسان", (), "  the same"),
        ("جک کرمان موتور در تهران", ("تهران",), "a company's name and a place: the place alone"),
        ("دنا ایران خودرو تبریز در مشهد", ("خراسان رضوی",), "  a capital after «در»"),
        ("لیفان کرمان خودرو، اصفهان", ("اصفهان",), "  after «،»"),
        ("سمند ایران خودرو مازندران ساکن کرج", ("البرز",), "  after «ساکن»"),
        ("سمند ایرانخودرو تبریز", (), "«ایرانخودرو» as one word"),
        ("دنا ایران\u200cخودرو تبریز", (), "  with a ZWNJ, a space after normalising"),
        ("جک کرمان\u200cموتور", (), "  the same"),
        ("جک کرمانموتور", (), "  as one word, no «کرمان» in it"),
        ("پراید در کرمان", ("کرمان",), "no name of the list: as before"),
        ("ماشین کرمانشاه", ("کرمانشاه",), "  «کرمانشاه», not «کرمان»"),
        ("سمند تبریز", ("آذربایجان شرقی",), "  a capital"),
        ("سمند ایران خودرو", (), "  Iran Khodro with no plant"),
        ("سمند ایران خودرو، تبریز", ("آذربایجان شرقی",), "  a «،» between: a make, then a place"),
        ("خودرو کرمان زیر ۱ میلیارد", ("کرمان",), "  «خودرو» before the name"),
        ("پژو ۲۰۶ مازندران", ("مازندران",), "  a province"),
        ("موتور سالم، کرمان", ("کرمان",), "  «موتور» elsewhere"),
        ("پراید کرمان موتور سالم", (), "left: Kerman, and an engine in good order, reads no Kerman"),
        ("پژو ۴۰۵ کرمان موتور تعمیر شده", (), "  the same"),
        ("سمند در کرمان موتور سالم", (), "  after «در»"),
        ("پراید در کرمان خودرو بی رنگ", (), "  «خودرو»")]:
    sp = P.parse(q)
    check(f"«{q}» → provinces {want}  ({why})", sp.provinces == want, f"{sp.provinces} {sp.unparsed}")
sp = P.parse("جک J4 کرمان موتور")
check("«جک J4 کرمان موتور» → «کرمان موتور» is listed, inside the clause, and no note is left",
      any("کرمان موتور" in t for t in sp.unparsed) and not any("را استان" in a for a in sp.assumptions),
      f"{sp.unparsed} {sp.assumptions}")

# A province's capital is read as its province (P1, the owner's choice of 2026-11-25 on a
# measurement): the eighteen whose name is not their province's, `OTHER_CAPITALS`, the listing
# parser's table, wherever a province's name is read and declined wherever one is; the page says
# which province each was taken for.
for c, prov in OTHER_CAPITALS.items():
    sp = P.parse(f"{_Q} در {c}")
    check(f"«{_Q} در {c}» → province {prov}, the note says so, nothing left",
          sp.provinces == (prov,)
          and f"«{normalize_fa(c)}» را استان {prov} گرفتیم" in sp.assumptions
          and not sp.unparsed,
          f"{sp.provinces} {sp.assumptions} {sp.unparsed}")
for q, want, why in [
        ("پراید مشهد", ("خراسان رضوی",), "with nothing before it"),
        ("سمند شیراز زیر ۵۰۰ میلیون", ("فارس",), "  beside a budget"),
        ("تبریز تیبا سفید", ("آذربایجان شرقی",), "  first"),
        ("ماشین کرج", ("البرز",), "  after a plain word"),
        ("اهواز پژو ۲۰۶", ("خوزستان",), "  before a model's number"),
        ("رشت دنا", ("گیلان",), "  before a model"),
        ("پراید در مشهد یا شیراز", ("خراسان رضوی", "فارس"), "two, joined by «یا»"),
        ("در تهران یا مشهد", ("تهران", "خراسان رضوی"), "a province, then a capital"),
        ("پراید غیر از مشهد", (), "declined after «غیر از»"),
        ("پراید نزدیک شیراز", (), "  after «نزدیک»"),
        ("پلاک تبریز", (), "  after «پلاک»"),
        ("پراید در کرج نباشه", (), "  before «نباشه»"),
        ("اطراف اهواز", (), "  after «اطراف»"),
        ("سمند بجز رشت", (), "  after «بجز»"),
        ("ماشین مشهدی", (), "a word that holds a capital's letters"),
        ("پراید شیرازی", (), "  another"),
        ("لاستیک درشت", (), "  «رشت» inside a word"),
        ("پژو ۲۰۶ تبریزی", (), "  another"),
        ("سمند کرجی", (), "  another"),
        ("پراید تا ۵۰ کیلومتر فاصله از کرج", ("البرز",),
         "left: a distance from a capital is read as its province"),
        ("پراید حداکثر ۱۰۰ کیلومتر از شیراز", ("فارس",), "  the same")]:
    sp = P.parse(q)
    check(f"«{q}» → provinces {want}  ({why})", sp.provinces == want, f"{sp.provinces} {sp.unparsed}")
sp = P.parse("پراید مشهد")
check("«پراید مشهد» → the note says Mashhad was taken for Razavi Khorasan",
      "«مشهد» را استان خراسان رضوی گرفتیم" in sp.assumptions, str(sp.assumptions))
sp = P.parse("پراید نه مشهد")
check("«پراید نه مشهد» → no province, and «نه مشهد» listed, where nothing was",
      sp.provinces == () and sp.unparsed == ("نه مشهد",), f"{sp.provinces} {sp.unparsed}")

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
# «پراید در کاشان» names a model, so its clause was understood whole and the
# city was dropped without a word. A cue the province reader knows is now
# listed with the one or two words after it. Nothing is read from them: the
# city narrows nothing, and the page says so. Every phrasing is made here; no
# log of what buyers write exists, so these test the rule, not the buyers.
def _listed(q):
    sp = P.parse(q)
    return [t.strip() for t in sp.unparsed], sp.provinces


for q, want in [   # each cue alone, before a word nothing knows
    (f"{_Q} در کاشان", ["در کاشان"]),
    (f"{_Q} توی کاشان", ["توی کاشان"]),
    (f"{_Q} تو کاشان", ["تو کاشان"]),
    (f"{_Q} ساکن کاشان", ["ساکن کاشان"]),
    (f"{_Q} اطراف کاشان", ["اطراف کاشان"]),
    (f"{_Q} حوالی کاشان", ["حوالی کاشان"]),
    (f"{_Q} حومه کاشان", ["حومه کاشان"]),
    (f"{_Q} بجز کاشان", ["بجز کاشان"]),
    (f"{_Q} پلاک کاشان", ["پلاک کاشان"]),
    (f"{_Q} نزدیک کاشان", ["نزدیک کاشان"]),
    (f"{_Q} نزدیکی کاشان", ["نزدیکی کاشان"]),
    (f"{_Q} غیر کاشان", ["غیر کاشان"]),
    # a cue of two words, before a name of two: the pair is one cue
    (f"{_Q} نزدیک به بندر انزلی", ["نزدیک به بندر انزلی"]),
    (f"{_Q} نزدیکی به بندر انزلی", ["نزدیکی به بندر انزلی"]),
    (f"{_Q} غیر از بندر انزلی", ["غیر از بندر انزلی"]),
    (f"{_Q} به جز بندر انزلی", ["به جز بندر انزلی"]),
    (f"{_Q} خارج از بندر انزلی", ["خارج از بندر انزلی"]),
    (f"{_Q} نزدیک{_ZWNJ}به بندر انزلی", ["نزدیک به بندر انزلی"]),
    # two words are taken, not one and not three
    (f"{_Q} ساکن در بندر انزلی", ["ساکن در بندر انزلی"]),
    (f"{_Q} در بندر ماهشهر میخوام", ["در بندر ماهشهر"]),
    # «شهر» and «استان» are skipped, and so is a cue after a cue
    (f"{_Q} ساکن در شهر کاشان", ["ساکن در شهر کاشان"]),
    (f"{_Q} در شهر بندر انزلی", ["در شهر بندر انزلی"]),
    (f"{_Q} پلاک ملی در کاشان", ["پلاک ملی", "در کاشان"]),
    # listed once: the clause rule already lists this one whole
    ("ماشین سفید در کاشان", ["ماشین سفید در کاشان"]),
    # after what is already there, and not counted in its cap of four
    (f"{_Q} غیر از تهران در کاشان", ["غیر از تهران", "در کاشان"]),
    ("ماشین قرمز، دوست دارم، حتما سالم، خیلی تمیز، پراید در کاشان",
     ["ماشین قرمز", "دوست دارم", "حتما سالم", "خیلی تمیز", "در کاشان"]),
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
    (f"{_Q} ساکن، کاشان", "a comma ends the phrase"),
    (f"{_Q} در حد نو", "«حد» is no name"),
    (f"{_Q} در حال حاضر", "«حال» is no name"),
    (f"{_Q} توی بودجه ام باشه", "«بودجه» is no name"),
    (f"{_Q} غیر از تیبا", "a model's name is blanked, so it is no word"),
    (f"{_Q} غیر از تیبایی", "what a blanked name leaves is no word of its own"),
    (f"{_Q} در تیبا کاشان", "a blanked name between ends the run"),
    (f"{_Q} پلاک ب", "one letter is no word"),
    (f"{_Q} نزدیک؛ به کاشان", "a mark between the two words of a pair ends it"),
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
    (f"{_Q} در تهران در کاشان", ["در کاشان"], ("تهران",)),
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
    (f"{_Q} تا ۳۰۰ میلیون در کاشان", ["در کاشان"], "after «تا»"),
    (f"{_Q} زیر ۳۰۰ میلیون ساکن دزفول", ["ساکن دزفول"], "after «زیر»"),
    (f"{_Q} بودجه ۳۰۰ میلیون نزدیک ساوه", ["نزدیک ساوه"], "after «بودجه»"),
    (f"{_Q} حداکثر ۱.۵ میلیارد توی مراغه", ["توی مراغه"], "a decimal amount"),
    (f"{_Q} تا ۳۰۰ میلیون تومان در کاشان", ["در کاشان"], "a unit word between"),
    (f"{_Q} تا ۳۰۰ میلیون پلاک ملی در کاشان", ["پلاک ملی", "در کاشان"],
     "two phrases"),
    (f"{_Q} تا ۳۰۰ میلیون در شهر بندر انزلی", ["در شهر بندر انزلی"],
     "two words are taken"),
    (f"{_Q} تا ۳۰۰ میلیون نزدیک به بندر انزلی", ["نزدیک به بندر انزلی"],
     "a pair"),
    (f"{_Q} تا ۳۰۰ میلیون غیر از کاشان در دزفول", ["غیر از کاشان", "در دزفول"],
     "two cues in it"),
    (f"{_Q} تا ۳۰۰ میلیون در کاشان، ساکن دزفول", ["ساکن دزفول", "در کاشان"],
     "the clause ends at «،»; what it holds is listed last"),
    ("ماشین سفید در کاشان، تا ۳۰۰ میلیون در دزفول",
     ["ماشین سفید در کاشان", "در دزفول"], "one before the budget, one after"),
    ("ماشین تا ۳۰۰ میلیون در کاشان، ماشین سفید در کاشان",
     ["ماشین سفید در کاشان"], "listed once, since a phrase holds it"),
    (f"{_Q} تا ۳۰۰ میلیون در کاشان ۴۰۰ میلیون", ["در کاشان"],
     "the first amount is the budget; a second is a figure, blanked"),
    (f"{_Q} تا ۳۰۰ میلیون در کاشان مدل ۹۵", ["در کاشان"],
     "the year clause is cut from it, as from the rest"),
    (f"{_Q} تا ۳۰۰ میلیون در کاشان مدل ۱۴۰۱ به بالا", ["در کاشان"],
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
    (f"{_Q} کاشان", [], (), "no cue stands before it"),
    (f"{_Q} قیمت در کاشان ۳۰۰ میلیون", [], (),
     "before the amount, the budget clause takes it whole"),
    (f"{_Q} تا ۳۰۰ میلیون در کاشان تا ۴۰۰ میلیون", ["در کاشان تا"], (),
     "a second budget lends its «تا» to the place, as «یا» does"),
    (f"{_Q} در تهران و کاشان", [], ("تهران",),
     "a second name after « و » has no cue"),
    (f"{_Q} غیر از دزفول و کاشان", ["غیر از دزفول"], (), "the same, after a cue"),
    (f"{_Q} در کاشان یا دزفول", ["در کاشان یا"], (), "«یا» is taken as a word"),
    (f"{_Q} نه کاشان", [], (), "«نه» is the reader's cue and not this one's"),
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
              (f"{_Q} در کاشان", _Q),
              (f"{_Q} پلاک ملی در کاشان", _Q),
              (f"{_Q} ساکن در شهر بندر انزلی", _Q),
              (f"{_Q} زیر ۳۰۰ میلیون، نزدیک کاشان", f"{_Q} زیر ۳۰۰ میلیون"),
              (f"{_Q} اسنپ، توی بندر انزلی", f"{_Q} اسنپ"),
              (f"{_Q} غیر از تهران در کاشان", f"{_Q} غیر از تهران"),
          ]))
check("a place is listed the same with a budget before it as without",
      all(_listed(f"{_Q} تا ۳۰۰ میلیون {t}") == _listed(f"{_Q} {t}")
          for t in ["در کاشان", "ساکن دزفول", "پلاک ملی در کاشان",
                    "نزدیک به بندر انزلی", "در تهران", "غیر از تهران",
                    "در کاشان مدل ۹۵", "در کاشان مدل ۱۴۰۱ به بالا"]),
      str([t for t in ["در کاشان", "ساکن دزفول", "پلاک ملی در کاشان",
                       "نزدیک به بندر انزلی", "در تهران", "غیر از تهران",
                       "در کاشان مدل ۹۵", "در کاشان مدل ۱۴۰۱ به بالا"]
           if _listed(f"{_Q} تا ۳۰۰ میلیون {t}") != _listed(f"{_Q} {t}")]))
check("a phrase listed after a budget changes nothing in the spec but the list",
      all(dataclasses.replace(P.parse(a), raw_query="", unparsed=())
          == dataclasses.replace(P.parse(b), raw_query="", unparsed=())
          for a, b in [
              (f"{_Q} تا ۳۰۰ میلیون در کاشان", f"{_Q} تا ۳۰۰ میلیون"),
              (f"{_Q} زیر ۳۰۰ میلیون پلاک ملی در کاشان", f"{_Q} زیر ۳۰۰ میلیون"),
              (f"{_Q} بودجه ۱.۵ میلیارد نزدیک به بندر انزلی",
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


# ---------------------------------------------------------------------------
print("\nthe models a buyer can name: one table with the listing parser's")
# Predictions MODELS and MODELS-B1 (2026-11-02, locked before the build): the
# search read ten models and the listing parser thirteen, so «سمند زیر ۲
# میلیارد» had no model and showed every car under two billion. The owner
# chose one table (caro/ingest/models.py), with no name added.
_md_q = {q: P.parse(q).model_hints for q in (
    "سمند زیر ۲ میلیارد", "تارا زیر ۲ میلیارد", "رانا زیر ۲ میلیارد", "کوئیک زیر ۲ میلیارد",
    "کوییک زیر ۲ میلیارد", "پراید ۱۳۲", "207i دنده ای", "تا ۱۳۲ میلیون")}
check("MD2: the search reads IKCO's Samand, Tara and Runna, and the names only the listing parser had -- "
      "«کوئیک», «۱۳۲», «207i» -- for the models it knew; a number inside an amount is still no model",
      _md_q == {"سمند زیر ۲ میلیارد": ("samand",), "تارا زیر ۲ میلیارد": ("tara",),
                "رانا زیر ۲ میلیارد": ("runna",), "کوئیک زیر ۲ میلیارد": ("quik",),
                "کوییک زیر ۲ میلیارد": ("quik",), "پراید ۱۳۲": ("pride",), "207i دنده ای": ("207",),
                "تا ۱۳۲ میلیون": ()}, str(_md_q))

# A model's name is a word of its own (2026-11-19, the owner's call): the
# search found a name anywhere in the query, as the listing parser did, so «گرند
# ویتارا» hinted Tara and «پراید تهرانپارس» Pars as well as Pride. Measured on
# made queries, the predictions locked first: right on 0 of 4, 0 of 3, 0 of 2
# and 0 of 3 today, and on 12 of 12 ordinary ones.
for _mn_q, _mn_want, _mn_why in [
    ("گرند ویتارا زیر ۵ میلیارد", (), "a Grand Vitara names no Tara"),
    ("ویتارا مونتاژ", (), "  assembled"),
    ("سوزوکی گرند ویتارا", (), "  with its make"),
    ("گرندویتارا تا ۴ میلیارد", (), "  written as one word"),
    ("پارس تندر زیر ۲ میلیارد", (), "Renault's Pars Tondar names no Peugeot Pars"),
    ("رنو پارس تندر", (), "  with its make"),
    ("پارس تندر ۹۷", (), "  with a year"),
    ("تندر پارس زیر ۲ میلیارد", (), "  its words the other way round (the same night, measured)"),
    ("رنو تندر پارس", (), "  the other way round, with its make"),
    ("تندر پارس ۹۷", (), "  the other way round, with a year"),
    ("پژو پارس، تندر هم میخوام", ("pars",), "  «تندر» not right before the name leaves it"),
    ("پراید در تهرانپارس", ("pride",), "a name inside a place's word"),
    ("تیبا تهرانپارس زیر ۸۰۰ میلیون", ("tiba",), "  another"),
    ("پراید در تهران پارس", ("pride",), "a place of two words: «تهران» before"),
    ("دنا در شاهین شهر", ("dena",), "  «شهر» after"),
    ("تیبا پارس آباد", ("tiba",), "  «آباد» after"),
    ("پراید بیمه پارسیان", ("pride",), "a longer word after the name"),
    ("یه پرایدی زیر ۳۰۰ میلیون", ("pride",), "an ending on the name keeps it, as it was"),
    ("سمندی تمیز", ("samand",), "  another"),
    ("پراید غیر از تیبایی", ("pride", "tiba"), "  «یی», as it was"),
    ("پرایدها زیر ۳۰۰ میلیون", ("pride",), "  «ها»"),
    ("پراید وتیبا", ("pride", "tiba"), "  a «و» typed on"),
    ("ماشینم پرایده زیر ۳۰۰ میلیون", ("pride",), "  the spoken copula «ه» (2026-11-20)"),
    ("تیباست یا دناست", ("tiba", "dena"), "  and «ست»"),
    ("پارسال پراید خریدم", ("pride",), "a word that holds a name and is none"),
    ("پژو پارس زیر ۲ میلیارد", ("pars",), "the ordinary ones, as they were"),
    ("پارس ELX", ("pars",), "  "),
    ("تارا زیر ۳ میلیارد", ("tara",), "  "),
    ("شاهین اتومات", ("shahin",), "  "),
    ("دنا پلاس", ("dena",), "  "),
    ("تیبا و ساینا", ("tiba", "saina"), "  two"),
    ("پژو پارس در تهران", ("pars",), "  «تهران» after the name, not before it"),
    ("پراید شهری", ("pride",), "  «شهری» is not «شهر»"),
]:
    _mn_got = P.parse(_mn_q).model_hints
    check(f"MN: «{_mn_q}» → models {list(_mn_want) or '—'}  ({_mn_why.strip() or 'as it was'})",
          _mn_got == _mn_want, str(_mn_got))


# A cue is a word of its own (2026-11-20, the owner's call), the model names' rule
# with the adverb's «ا» and the copula allowed after it and the five compounds cues of
# their own; «کار », written with a trailing space, takes no ending. Measured on two
# made sets, the predictions locked first each time.
def _cw_read(q, what):
    s = P.parse(q)
    return {"use": s.use_case, "flex": not s.budget_hard, "brk": s.deal_breakers}[what]


for _cw_q, _cw_what, _cw_want, _cw_why in [
    ("پراید در محدوده تهران", "flex", False, "«حدود» inside «محدوده» is no soft budget"),
    ("محدودیت بودجه دارم", "flex", False, "  nor inside «محدودیت»"),
    ("اعتبار دارم پراید میخوام", "use", "unspecified", "«بار» inside «اعتبار» is no cargo"),
    ("پراید انبار شده", "use", "unspecified", "  nor inside «انبار»"),
    ("باران زده نباشه", "use", "unspecified", "  nor inside «باران»"),
    ("سمند فرسوده نباشه", "use", "unspecified", "«سود» inside «فرسوده» is no resale"),
    ("پراید در شهریار", "use", "unspecified", "«شهری» inside «شهریار» is no commute"),
    ("مدل شهریور ۹۸ پراید", "use", "unspecified", "  nor inside «شهریور»"),
    ("کارت ماشین دارد", "use", "unspecified", "«کار » takes no ending: «کارت» is no ride-hailing"),
    ("کارش تمیزه", "use", "unspecified", "  nor «کارش»"),
    ("برای سرکار رفتن", "use", "commute", "«سرکار» is commute, no longer «کار » inside it"),
    ("حدودا ۵۰۰ میلیون پراید", "flex", True, "the adverb's «ا» keeps the cue"),
    ("تقریباً ۵۰۰ میلیون", "flex", True, "  and the tanvin"),
    ("پراید اتوماتیکه", "brk", ("manual",), "the copula «ه» keeps the cue"),
    ("وانته میخوام", "use", "cargo", "  another"),
    ("ماشین خانوادگیه", "use", "family_first_car", "  another"),
    ("ماشین خانوادگیست", "use", "family_first_car", "  and «ست»"),
    ("پراید وتاکسی میخوام", "use", "ride_hailing", "a «و» typed on keeps the cue"),
    ("برای سرکارم", "use", "commute", "a noun's ending keeps it"),
    ("پراید برای بچه‌هام", "use", "family_first_car", "  another"),
    ("وانت بارکش", "use", "cargo", "the compounds are cues of their own: «بارکش»"),
    ("پراید باربر", "use", "cargo", "  «باربر»"),
    ("پراید برای تاکسیرانی", "use", "ride_hailing", "  «تاکسیرانی»"),
    ("پراید سودآور", "use", "resale_flip", "  «سودآور»"),
    ("معامله پرسود", "use", "resale_flip", "  «پرسود»"),
    ("یه ماشین برای کار میخوام", "use", "ride_hailing", "the cues as words, as they were: «کار »"),
    ("اسنپ کار کنم", "use", "ride_hailing", "  «اسنپ»"),
    ("وانت برای بار", "use", "cargo", "  «بار»"),
    ("برای رفت و آمد", "use", "commute", "  a cue of words"),
    ("پراید کم مصرف", "use", "commute", "  «کم مصرف»"),
    ("حدود ۳۰۰ میلیون پراید", "flex", True, "  «حدود»"),
    ("پراید بدون رنگ", "brk", ("repaint",), "  a red line"),
    ("پراید آبی رنگ", "brk", (), "«بی رنگ» inside «آبی رنگ», a blue car, is no red line"),
    ("سند آزاد باشه", "brk", ("unclear_documents",), "  another"),
    ("بارها گفتم پراید", "use", "cargo", "left: «بارها», «ها» an ending"),
    ("شهریه دانشگاه دارم", "use", "commute", "left: «شهریه», «ه» allowed"),
    ("این بار پراید میخوام", "use", "cargo", "left: «بار» a word of another meaning"),
    ("کم مصرفترین ماشین", "use", "unspecified", "left: «کم مصرف» glued to «ترین» is no longer read"),
]:
    _cw_got = _cw_read(_cw_q, _cw_what)
    check(f"CW: «{_cw_q}» → {_cw_what} {_cw_want}  ({_cw_why.strip()})", _cw_got == _cw_want, str(_cw_got))

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
