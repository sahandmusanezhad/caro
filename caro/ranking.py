"""
CARO W3 — intent parsing and ranking.

The half the brief asks for that W0-W2 did not have. W2 evaluates ONE listing;
this turns a Persian sentence into a ranked shortlist, and every item on that
shortlist can then be handed to the decision layer.

The thesis, made testable
-------------------------
Sorting by price can systematically favour damaged cars, and where it does,
it actively harms the buyer. `winrate_vs_price_sort` is the experiment that
settles whether ranking answers that better than price order does. If it
cannot beat sort-by-price, the product has no reason to exist and the honest
move is to find that out here rather than in the demo.

What the experiment tests, precisely: in a world where the cheapest listings
*are* disproportionately damaged, does ranking respond correctly while price
order does not. Whether Iranian used-car prices actually have that property
is a separate, open question — the generating process was built with it, so
this benchmark cannot also be evidence for it. See D36.

Where the LLM is, and is not
----------------------------
Intent parsing is the one place in CARO where a language model genuinely
earns its keep — Persian free text is exactly what deterministic code is bad
at. So `IntentParser` is a Protocol with two implementations: a deterministic
parser that ships and runs offline, and a slot for an LLM parser that must
produce the same frozen `IntentSpec`.

Everything after parsing — filtering, the relaxation ladder, scoring,
diversity — is deterministic. The ranking must be reproducible, inspectable
term by term, and recomputable client-side when a user drags a weight.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, replace
from typing import Protocol, Sequence

import numpy as np

from caro.appraisal import QUANTILES, MarketEstimator, NotBenchmarked, Row
from caro.ingest.persian import PROVINCE_SPELLINGS, PROVINCES

# ---------------------------------------------------------------------------
# Persian text normalisation
# ---------------------------------------------------------------------------

_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_ZWNJ = "‌"


def normalize_fa(s: str) -> str:
    """Fold the variants a real query actually arrives in.

    Arabic yeh/kaf for Persian ones, both digit sets to Latin, ZWNJ to a
    space so «کم‌کارکرد» and «کم کارکرد» are one token.
    """
    s = unicodedata.normalize("NFKC", s)
    s = s.translate(_DIGITS)
    s = s.replace("ي", "ی").replace("ك", "ک").replace(_ZWNJ, " ")
    return re.sub(r"\s+", " ", s).strip()


# Amount words, in IRR. Iranian sellers quote in both tomans and rials and
# the unit is usually implied by scale, so `parse_amount` disambiguates on
# magnitude rather than trusting the word.
_SCALE = {"میلیارد": 1_000_000_000, "ملیارد": 1_000_000_000,
          "میلیون": 1_000_000, "ملیون": 1_000_000, "م": 1_000_000}

_AMOUNT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(میلیارد|ملیارد|میلیون|ملیون|م)?(?:\s*و\s*(\d+))?")


def parse_amount(text: str) -> int | None:
    """«۱.۵ میلیارد» · «1 میلیارد و 480» · «۸۰۰ میلیون» · «۱۴۸۰م» → IRR."""
    m = _AMOUNT.search(text)
    if not m:
        return None
    base = float(m.group(1).replace(",", "."))
    unit = m.group(2)
    tail = m.group(3)
    if unit in ("میلیارد", "ملیارد"):
        total = base * 1e9 + (float(tail) * 1e6 if tail else 0.0)
    elif unit:
        total = base * _SCALE[unit]
    else:
        total = base * 1e6 if base < 10_000 else base
    return int(total)


# A number that is an amount of MONEY, as opposed to a number that merely
# exists. The distinction is not pedantic: `parse_amount` answers "what number
# is this?" and will happily answer it for an odometer reading or a model
# year, because a bare `206` and a bare `800` are the same object to it. This
# regex answers the prior question — *is this number money at all?* — and the
# only evidence it accepts is a scale word attached to the number.
#
# Four measured failures motivate it, all of them silent:
#
#     «کارکرد زیر ۹۰ هزار، تا ۸۰۰ میلیون»    budget became 90,000,000
#     «۲۰۶ زیر ۱۰۰ هزار کیلومتر، بودجه ۹۰۰ میلیون»  budget became 100,000,000
#     «تیبا مدل ۹۵»                            budget became 95,000,000
#     «۲۰۶»                                    budget became 206,000,000
#
# The last is the one that matters most for the product: a buyer who types a
# model name and nothing else was handed an invisible ceiling that filtered
# out most of the cars they had just asked for.
#
# `هزار` is deliberately NOT a money word. In these queries it counts
# kilometres, and treating it as currency is how «زیر ۹۰ هزار» became a
# budget. `م` is accepted only when no letter follows it, so «۸۰۰م» is an
# amount and the «م» of «مشکی» in «مدل ۹۵ مشکی» is not.
#
# What this deliberately does not do is guess. «۸۰۰ تومان» sets no budget,
# because a currency word with no scale is genuinely ambiguous at these
# magnitudes; the text stays in `unparsed`, where the user can see it.
_MONEY = re.compile(
    r"\d+(?:[.,]\d+)?\s*"
    r"(?:(?:میلیارد|ملیارد|میلیون|ملیون)(?:\s*و\s*\d+)?|م(?!\w))")


def money_amount(text: str) -> int | None:
    """The first amount of money in `text`, or None if it names none."""
    m = _MONEY.search(text)
    return parse_amount(m.group(0)) if m else None


def after_amount(text: str) -> str:
    """What `text` says after its first amount of money; empty if it names
    none."""
    m = _MONEY.search(text)
    return text[m.end():] if m else ""


# A budget FLOOR: a cue, an amount of money and «به بالا», with nothing between
# them -- «از ۲۰۰ میلیون به بالا». It was whatever stood between a «از» and the
# first «به بالا», handed to `parse_amount`, which takes a bare number for
# millions. «از» also ends many words («شیراز», «نیاز») and is the word of
# «غیر از», and «به بالا» also ends a year clause. So «پراید از مدل ۹۸ به بالا»
# set a floor of 98,000,000, and in «پراید غیر از مشهد ۸۰۰ میلیون مدل ۹۸ به
# بالا» the budget was the floor.
#
# `_SOFT` and `_UNIT_TAIL` are what may stand inside the phrase: a soft word
# before the amount, and after it the unit that «۱ میلیارد و ۲۰۰ میلیون» leaves
# (`_MONEY` takes «۱ میلیارد و ۲۰۰» only) and a currency word. A floor and a
# year are also written together -- «از ۲۰۰ میلیون مدل ۹۸ به بالا» -- and the
# only «به بالا» is the year clause's, which says the same of both: `_FLOOR_Y`
# reads the floor there and leaves the year clause as it is.
_UNIT_TAIL = (r"(?:\s*(?:میلیون|ملیون)(?!\w))?"
              r"(?:\s*(?:تومان|تومن)(?!\w))?")
_SOFT = r"(?:(?:حدود|تقریبا)\s*)?"
_CUE = r"(?<!\w)(?:بالای|از)\s*"
_FLOOR_S = re.compile(_CUE + _SOFT + "(" + _MONEY.pattern + ")" + _UNIT_TAIL
                      + r"\s*به بالا")
_FLOOR_Y = re.compile(_CUE + _SOFT + "(" + _MONEY.pattern + ")" + _UNIT_TAIL
                      + r"(?=\s*مدل\s*\d{2,4}\s*به\s*بالا)")

# The OTHER WORDS for a floor. «حداقل ۴۰۰ میلیون» and «۴۰۰ میلیون و بالاتر» set
# no floor, and the amount was taken for the ceiling, with «عدد قیمت را سقف
# بودجه فرض کردیم» printed: the meaning reversed, said once and easy to miss.
# Of 192 phrasings of eight forms (six amounts, with no model and with three)
# all 192 were read so. Two words are read now, the two that carry no second
# meaning:
#
#   _FLOOR_L  «حداقل», then «قیمت» if it is written, a soft word, an amount of
#             money and the unit after it: «حداقل ۴۰۰ میلیون», «حداقل قیمت ۴۰۰
#             میلیون تومان». The amount is right after the word, so «حداقل ۲ سال
#             بیمه» and «حداقل ۱۰۰ هزار کیلومتر ۴۰۰ میلیون» are not it.
#   _FLOOR_T  an amount of money and the unit after it, then «و» or «یا» and
#             «بالاتر» or «بیشتر»: «۴۰۰ میلیون و بالاتر», «۱ میلیارد و ۲۰۰ میلیون
#             یا بیشتر». Not «و بیشتر از»: «۴۰۰ میلیون و بیشتر از ۱۰۰ هزار
#             کیلومتر» is two statements. Its amount takes «و ۲۰۰» only after a
#             billion, where it means something: `_MONEY` takes it after a
#             million too, and «زیر ۸۰۰ میلیون و ۴۰۰ میلیون و بالاتر» was one
#             amount of 800 million, with no ceiling (found by hand, 2026-10-25).
#
# A phrase that a negation follows at once -- «۴۰۰ میلیون و بالاتر نباشه» -- is
# no floor and is left to the ceiling rules, as it was. The words are the ones
# `_NEGATED_AFTER` holds for the places and six more (نشه نره نرسه نگذره نزنه
# خرج نکنم); a negation outside that list, or one before the phrase, is not
# seen, and the phrase is read as a floor. Known, and left, each pinned by a
# test so that it changes on purpose:
#
#   - «حداقل بودجه X» is a ceiling, as it was: the «بودجه» cue takes the amount.
#     It may say what the buyer has to spend and not the price asked.
#   - «بیشتر از X», «بیش از X» and «بالاتر از X» are ceilings, as they were. They
#     are the ambiguity of «بالای X» (the owner chose to leave it): «نباید بیشتر
#     از ۴۰۰ میلیون باشه» is a ceiling, and no guard that looks after the phrase
#     sees the «نباید» before it. A year clause right after the amount is read
#     by `_FLOOR_Y`, whose cue is the bare «از», as it was.
#   - «حداقل ۴۰۰ میلیون پول دارم», what the buyer has, is read as a floor.
_MONEY_T = (r"\d+(?:[.,]\d+)?\s*"
            r"(?:(?:میلیارد|ملیارد)(?:\s*و\s*\d+)?|میلیون|ملیون|م(?!\w))")
_FLOOR_L = re.compile(r"(?<!\w)حداقل\s*(?:قیمت\s*)?" + _SOFT
                      + "(" + _MONEY.pattern + ")" + _UNIT_TAIL)
_FLOOR_T = re.compile(r"(?<!\w)(" + _MONEY_T + ")" + _UNIT_TAIL
                      + r"\s*(?:و|یا)\s*(?:بالاتر|بیشتر)(?!\w)(?!\s*از(?!\w))")
_NOT_A_FLOOR_AFTER = re.compile(
    r"\s*(?:نباش(?:ه|د|ن|ند)?|نیست(?:ن)?|نمی\s*خوا(?:م|هم|یم)"
    r"|نخوا(?:م|هم|یم)|نشه|نره|نرسه|نگذره|نزنه|خرج\s+نکنم)(?!\w)")


def _floor_by_word(q: str):
    """The floor `_FLOOR_L` or `_FLOOR_T` reads in `q`, or None: the first
    phrase of either that no negation follows at once."""
    for rx in (_FLOOR_L, _FLOOR_T):
        for m in rx.finditer(q):
            if not _NOT_A_FLOOR_AFTER.match(q, m.end()):
                return m
    return None


# Model aliases. Sellers and buyers type the same car a dozen ways; the
# taxonomy is data, not code, so a new model is one line.
MODEL_ALIASES: dict[str, tuple[str, ...]] = {
    "206": ("206", "پژو 206", "پژو206", "دویست و شش"),
    "207": ("207", "پژو 207", "پژو207"),
    "pride": ("پراید", "pride", "131", "111"),
    "tiba": ("تیبا", "tiba"),
    "quik": ("کوییک", "quick", "quik"),
    "pars": ("پارس", "پژو پارس", "pars"),
    "405": ("405", "پژو 405"),
    "dena": ("دنا", "dena"),
    "shahin": ("شاهین", "shahin"),
    "saina": ("ساینا", "saina"),
}

# A model's number is a model only where it stands alone. «دنا تا ۱۳۱۰ میلیون»
# holds 131, which is Pride's, inside an amount of money, and «تیبا مدل ۱۴۰۵»
# holds 405 inside a year; each added a model nobody wrote (D83). So a number
# is looked for in the query less its amounts of money, and is not taken beside
# another digit. A name is matched as ever, anywhere in the query.
_NUMERIC_ALIASES = frozenset(a for als in MODEL_ALIASES.values() for a in als
                             if a.isdigit())


def _names_model(q: str, alias: str, bare: str) -> bool:
    """Does `q` name a model by `alias`? `bare` is `q` less its amounts of
    money, which is where a number is read."""
    if alias not in _NUMERIC_ALIASES:
        return alias in q
    for m in re.finditer(re.escape(alias), bare):
        if not ((m.start() and bare[m.start() - 1].isdigit())
                or (m.end() < len(bare) and bare[m.end()].isdigit())):
            return True
    return False


USE_CASE_CUES: dict[str, tuple[str, ...]] = {
    "ride_hailing": ("اسنپ", "تپسی", "مسافرکشی", "تاکسی", "کار "),
    "family_first_car": ("خانواده", "خانوادگی", "ماشین اول", "بچه"),
    "commute": ("سرکار", "رفت و آمد", "شهری", "داخل شهر"),
    "resale_flip": ("سرمایه", "فروش مجدد", "سود"),
    "cargo": ("بار", "وانت", "باربری"),
}

# What each use case is called on the page. The intent panel prints these
# names under «کاربرد» (USE_CASE_FA in components/IntentPanel.tsx), and the
# assumption that says the weights started from a use case's defaults names it
# the same way. It used to print the key: «ride_hailing» inside a Persian
# sentence, the bare-token failure the panel's own risk labels once had. The
# contract suite holds the two maps equal, member for member.
USE_CASE_FA: dict[str, str] = {
    "ride_hailing": "مسافرکشی (اسنپ/تپسی)",
    "family_first_car": "ماشین اول خانواده",
    "commute": "رفت‌وآمد شهری",
    "resale_flip": "خرید برای فروش مجدد",
    "cargo": "باربری",
    "unspecified": "مشخص نشده",
}

DEAL_BREAKER_CUES: dict[str, tuple[str, ...]] = {
    "accident": ("تصادفی نباشه", "تصادفی نباش", "بدون تصادف", "سالم باشه"),
    "repaint": ("بدون رنگ", "رنگ نداشته باشه", "بی رنگ"),
    "unclear_documents": ("سند آزاد", "سند تک برگ", "در گرو نباشه"),
    "manual": ("اتومات", "اتوماتیک", "دنده اتومات"),
}

# The VAGUE odometer cue — «کم‌کارکرد» and its forms — as distinct from a
# stated number. It earns a constant because of the trailing `\b`, which is
# load-bearing rather than tidy.
#
# The alternatives used to be bare substrings, and «کم» is a prefix of
# «کمتر»: `کارکرد کم` therefore matched inside «کارکرد کمتر از ۲۰۰ هزار» —
# a query that states its limit exactly and is not vague at all. The cue
# fired, and the user was told about a 120,000 default they had just
# overridden. Persian letters are `\w`, so `\b` refuses the match when a
# letter follows, and accepts «کم کارکرد», «کم کارکرده», «کم کارکردی» and
# «کارکرد کمی» — all of which the old pattern also caught, and all of which
# really are vague.
_LOW_MILEAGE_CUE = re.compile(
    r"(?:کم\s*کارکرد(?:ه|ی)?|کم\s*کار|کارکرد\s*کم(?:ی)?)\b")

# A distance cap with no «کارکرد» before it. The «کارکرد» form reads
# «کارکرد زیر ۱۰۰ هزار», and «۲۰۶ زیر ۱۰۰ هزار کیلومتر» was neither read nor
# listed (D83). These are tried only when that form finds nothing, in this
# order: a cap word, a figure and a distance word; the figure first and
# «یا کمتر» after it; «کیلومتر» or «کارکرد» and then the cap; and «k».
# A letter after the distance word ends the match: «تا ۵۰ کیلومتری تهران» is
# a place that is near, not an odometer.
_NO_LETTER = r"(?![^\W\d_])"
_CAP_WORD = r"(?:زیر|تا|کمتر از|حداکثر)"
_MILEAGE_CAPS = (
    re.compile(_CAP_WORD + r"\s*(\d+)\s*(هزار)?\s*(?:کیلومتر|کیلو|km)"
               + _NO_LETTER),
    re.compile(r"(\d+)\s*(هزار)?\s*(?:کیلومتر|کیلو|km)\s*"
               r"(?:یا کمتر|و کمتر|به پایین)"),
    re.compile(r"(?:کیلومتر|کارکرد)\s*" + _CAP_WORD + r"\s*(\d+)\s*(هزار)?"),
    re.compile(_CAP_WORD + r"\s*(\d+)\s*(k)" + _NO_LETTER),
)
# With neither «هزار» nor «k» and no «کارکرد» before the figure, nothing says
# it is an odometer: «تا ۱۰۰۰ کیلومتر دورتر» is a distance to travel, «وانت
# تا ۱۵۰۰ کیلو» a weight. No road in Iran is 10000 km long, so from there on
# a figure can only be a mileage. «تا ۵۰۰۰ کیلومتر کارکرد» is left unread.
_MILEAGE_FLOOR = 10_000


# ---------------------------------------------------------------------------
# Where the car should be
# ---------------------------------------------------------------------------
#
# A province named in the query is a constraint (D82). The names are the ones
# the corpus carries -- `PROVINCES`, and the one spelling `PROVINCE_SPELLINGS`
# holds -- read as whole words, and nothing else. No city is read: the
# vocabulary is not a geography (D74), so «مشهد» is still a word the parser did
# not map. It is no longer dropped without a word, though: after a cue the
# reader knows it is listed under «نفهمیدیم» (`read_unknown_places`, below).
#
# This reading is hazardous as no other cue here is, because a wrong one
# inverts and says nothing: «غیر از تهران» taken for Tehran would answer with
# nothing but Tehran's cars, under a panel that says «استان: تهران». So a name
# is read only where it is a place the buyer wants the car to be in, and each
# phrase that names a province and is not read stays on the page, under
# «بخش‌هایی که نفهمیدیم».
#
#   read          a locative before it -- در · توی · تو · ساکن · استان, with
#                 «شهر» or «استان» between: «در تهران», «ساکن استان یزد»
#   read, and     nothing before it: «پراید تهران», «پراید، تهران». The panel
#   assumed       says «تهران» را استان تهران گرفتیم, to be corrected.
#   several       joined by « و », « یا » or «،», they are one group and take
#                 the first one's reading: «در تهران یا اصفهان». Any one meets
#                 it.
#   not read      a negation before -- غیر (از) · به جز · بجز · نه · خارج از ·
#                 بدون -- or after -- نباشه · نیست · نمی‌خوام; a nearness
#                 -- نزدیک (به) · اطراف · حوالی · حومه; or a plate -- «پلاک
#                 تهران» says where a car was registered, not where the
#                 listing is, and no corpus field carries a plate.
#   not read      «مرکزی» and «گلستان» with no locative: they are ordinary
#                 words («قفل مرکزی»).
#   not read      «خراسان» and «آذربایجان» alone: each begins the names of
#                 several provinces, so none of them is meant.
#   not read      «خلیج فارس»: it holds a province's name and is not one. It is
#                 declined wherever it stands, with what stands before it --
#                 «در خلیج فارس», «غیر از خلیج فارس» -- the way a family is.
#
# What the corpus says to the constraint is `webapp/api/constraints.judge`'s
# to say; this decides only what the buyer asked.
_PROVINCE_BY_TEXT: dict[str, str] = {normalize_fa(p): p for p in PROVINCES}
_PROVINCE_BY_TEXT.update({normalize_fa(seen): meant
                          for seen, meant in PROVINCE_SPELLINGS.items()})
_PROVINCE_FAMILIES = frozenset({"خراسان", "آذربایجان"})
_PLAIN_WORDS = frozenset({"مرکزی", "گلستان"})
# A name that holds a province's and is not a province. It is matched as one
# name, so the «فارس» inside it is never read on its own.
_NOT_PROVINCES = frozenset({"خلیج فارس"})
_PLACE = re.compile(
    r"(?<!\w)(?:" + "|".join(re.escape(n) for n in sorted(
        [*_PROVINCE_BY_TEXT, *_PROVINCE_FAMILIES, *_NOT_PROVINCES],
        key=len, reverse=True))
    + r")(?!\w)")

_PLACE_WORD = r"(?:(?:در|توی|تو|استان|شهر)\s+){0,2}"
_NEGATED_BEFORE = re.compile(
    r"(?:^|\s)(?:غیر(?:\s+از)?|به\s*جز|بجز|نه|خارج\s+از|بدون)\s+"
    + _PLACE_WORD + r"$")
_NEAR_BEFORE = re.compile(
    r"(?:^|\s)(?:نزدیکی?(?:\s+به)?|اطراف|حوالی|حومه)\s+" + _PLACE_WORD + r"$")
_PLATE_BEFORE = re.compile(
    r"(?:^|\s)پلاک(?:\s*:\s*|\s+)(?:(?:استان|شهر)\s+)?$")
_IN_BEFORE = re.compile(
    r"(?:^|\s)(?:(?:در|توی|تو|ساکن)\s+(?:(?:استان|شهر)\s+)?|استان\s+)$")
_NEGATED_AFTER = re.compile(
    r"\s*(?:نباش(?:ه|د|ن|ند)?|نیست(?:ن)?|نمی\s*خوا(?:م|هم|یم)"
    r"|نخوا(?:م|هم|یم))(?!\w)")
_BETWEEN_NAMES = re.compile(r"\s*(?:،|,|و|یا)?\s*")


@dataclass(frozen=True)
class PlaceReading:
    """What `read_provinces` made of a query.

    `understood` is text of the normalised query the parser acted on, handed
    to the clause rule as a cue is; `declined` is text that names a province
    and was not taken, which the parser lists as not understood by hand,
    because a clause that names a model is otherwise taken as understood
    whole.
    """
    provinces: tuple[str, ...] = ()
    understood: tuple[str, ...] = ()
    declined: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()


def read_provinces(text: str) -> PlaceReading:
    q = normalize_fa(text)
    groups: list[list[tuple[int, int, str]]] = []
    for m in _PLACE.finditer(q):
        hit = (m.start(), m.end(), m.group(0))
        if groups and _BETWEEN_NAMES.fullmatch(q[groups[-1][-1][1]:hit[0]]):
            groups[-1].append(hit)
        else:
            groups.append([hit])

    provinces: list[str] = []
    understood: list[str] = []
    declined: list[str] = []
    assumptions: list[str] = []
    for g in groups:
        first, end = g[0][0], g[-1][1]
        before = q[:first]
        mode, begin = "bare", first
        for kind, rx in (("not", _NEGATED_BEFORE), ("not", _NEAR_BEFORE),
                         ("not", _PLATE_BEFORE), ("in", _IN_BEFORE)):
            m = rx.search(before)
            if m:
                mode, begin = kind, m.start()
                break
        after = _NEGATED_AFTER.match(q, end)
        if after and mode != "not":
            mode, end = "not", after.end()
        if mode == "not":
            declined.append(q[begin:end].strip())
            continue

        read = []
        for s, e, name in g:
            if name in _PROVINCE_FAMILIES or name in _NOT_PROVINCES or (
                    name in _PLAIN_WORDS and mode != "in"):
                declined.append(q[begin:e].strip()
                                if s == first and mode == "in" else name)
            else:
                read.append((s, e, _PROVINCE_BY_TEXT[name]))
        if not read:
            continue
        for _, _, province in read:
            if province not in provinces:
                provinces.append(province)
        understood.append(q[begin if mode == "in" else read[0][0]:read[-1][1]]
                          .strip())
        if mode == "bare":
            for s, e, province in read:
                note = f"«{q[s:e]}» را استان {province} گرفتیم"
                if note not in assumptions:
                    assumptions.append(note)

    return PlaceReading(
        provinces=tuple(provinces), understood=tuple(understood),
        declined=tuple(dict.fromkeys(declined)),
        assumptions=tuple(assumptions))


# ---------------------------------------------------------------------------
# A place the reader does not know
# ---------------------------------------------------------------------------
#
# «پراید در مشهد» names a model, so the clause rule counted it understood whole
# and «مشهد» was dropped without a word: a buyer who named a city was answered
# as if they had not. The reader cannot say so -- it knows the names the corpus
# carries, and a city is not one (D74). What it does know is the words a place
# comes after. This lists such a word and the one or two after it under
# «بخش‌هایی که نفهمیدیم» -- «در مشهد» -- so the page says the city was seen and
# not used. It reads no city, and changes nothing in the spec but that list.
#
#   cue       a word of `_CUE_WORDS`, or a pair of `_CUE_PAIRS` side by side:
#             the reader's own, less «نه» and «بدون», which stand before a
#             province there and before any word here -- «بدون ایراد فنی» is
#             no place.
#   skipped   what follows the cue directly and is «استان», «شهر» or another
#             cue: «ساکن در شهر مشهد» is one phrase, «پلاک ملی در مشهد» two,
#             «پلاک ملی» and «در مشهد».
#   taken     then up to two words that follow directly, are no cue, are not
#             one of `_NEVER_A_PLACE` and have two letters or more. Two,
#             because a city is often two words -- «بندر عباس». If none is
#             taken nothing is listed: a cue at the end of a phrase says
#             nothing.
#   blanked   before the words are cut, what the parser acted on, the model
#             names, the province names and the digits are blanked, and a
#             blanked stretch is no word and ends a run: «غیر از تیبا» and
#             «برای مسافرکشی در اسنپ» list nothing, «در تهران» is the
#             reader's, and «پلاک ملی تهران» lists the plate and no more.
#   listed    last in `unparsed`, unless a phrase already there holds it:
#             «ماشین سفید در مشهد» is listed whole by the clause rule, and
#             «در مشهد» adds nothing.
#   after a   the budget clause is taken whole, up to the next «،», and what
#   budget    it holds after the amount is read as one more clause, for a cue
#             and no more: «تا ۳۰۰ میلیون در مشهد» lists «در مشهد», and so does
#             «تا ۳۰۰ میلیون تومان در مشهد». Nothing else in it is listed, as
#             it never was: «تا ۳۰۰ میلیون سفید» says nothing of «سفید». What
#             stands between the cue and the amount is not read:
#             «قیمت در مشهد ۳۰۰ میلیون».
#
# What this does not find stays dropped, and the tests pin it so that it
# changes on purpose: a city no cue stands before («پراید مشهد»); one after
# « و » or «یا» («در تهران و مشهد»; «یا» is itself taken as the second word of
# «در مشهد یا شیراز»); and one inside a word that holds a model's name
# («تهرانپارس» lists «در تهران», the part before «پارس»). And `_NEVER_A_PLACE`
# is three words because three put a phrase on the page that is no place --
# «در حد نو», «در حال حاضر», «توی بودجه ام» -- in the sentences measured; it is
# a list that grows with what buyers write, not a rule.
_CUE_WORDS = frozenset({"در", "توی", "تو", "ساکن", "اطراف", "حوالی", "حومه",
                        "بجز", "پلاک", "نزدیک", "نزدیکی", "غیر"})
_CUE_PAIRS = frozenset({("نزدیک", "به"), ("نزدیکی", "به"), ("غیر", "از"),
                        ("به", "جز"), ("خارج", "از")})
_CUE_LINKS = frozenset({"استان", "شهر"})
_NEVER_A_PLACE = frozenset({"حد", "حال", "بودجه"})
_WORD = re.compile(r"[^\s،,.;:؛()\[\]{}\-–—!؟?«»\"'/\\|]+")
_FIGURE = re.compile(r"\d+(?:[.,]\d+)?")


def _joined(rest, words, k):
    """`words[k]` follows `words[k - 1]` with only whitespace between."""
    return not rest[words[k - 1][2]:words[k][1]].strip()


def _cue_length(rest, words, k):
    """How many words the cue that starts at `words[k]` has: 2, 1 or 0."""
    if (k + 1 < len(words) and _joined(rest, words, k + 1)
            and (words[k][0], words[k + 1][0]) in _CUE_PAIRS):
        return 2
    return 1 if words[k][0] in _CUE_WORDS else 0


def read_unknown_places(rest: str, clauses: list[tuple[int, int]],
                        spans: list[tuple[int, int]]) -> tuple[str, ...]:
    """The cues in the clauses of `rest`, each with the words it takes.

    `spans` is where the parser acted on `rest`. A word is the part of a
    token that nothing blanks: a blanked stretch inside one splits it.
    """
    blank = [False] * len(rest)

    def cover(a, b):
        blank[a:b] = [True] * (b - a)

    for a, b in spans:
        cover(a, b)
    for aliases in MODEL_ALIASES.values():
        for alias in aliases:
            for m in re.finditer(re.escape(alias), rest):
                cover(m.start(), m.end())
    for m in (*_PLACE.finditer(rest), *_FIGURE.finditer(rest)):
        cover(m.start(), m.end())

    items: list[str] = []
    for a, b in clauses:
        words = []
        for token in _WORD.finditer(rest, a, b):
            i = token.start()
            while i < token.end():
                if blank[i]:
                    i += 1
                    continue
                j = i
                while j < token.end() and not blank[j]:
                    j += 1
                words.append((rest[i:j], i, j))
                i = j
        i = 0
        while i < len(words):
            n = _cue_length(rest, words, i)
            if not n:
                i += 1
                continue
            j = i + n
            while j < len(words) and _joined(rest, words, j):
                if words[j][0] in _CUE_LINKS:
                    j += 1
                elif _cue_length(rest, words, j):
                    j += _cue_length(rest, words, j)
                else:
                    break
            end = j
            while (end < len(words) and end - j < 2
                   and _joined(rest, words, end)
                   and not _cue_length(rest, words, end)
                   and words[end][0] not in _NEVER_A_PLACE
                   and len(words[end][0]) > 1):
                end += 1
            if end > j:
                items.append(" ".join(w[0] for w in words[i:end]))
            i = end
    return tuple(items)


# ---------------------------------------------------------------------------
# IntentSpec
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Weights:
    """Sums to 1.0. Shown to the user and adjustable — the tradeoff is theirs."""
    value: float = 0.35
    risk: float = 0.25
    running_cost: float = 0.15
    liquidity: float = 0.10
    mileage: float = 0.10
    recency: float = 0.05

    def normalized(self) -> "Weights":
        t = (self.value + self.risk + self.running_cost + self.liquidity
             + self.mileage + self.recency)
        if t <= 0:
            return Weights()
        return Weights(self.value / t, self.risk / t, self.running_cost / t,
                       self.liquidity / t, self.mileage / t, self.recency / t)


# A use case is a starting point for the weights, never a verdict on them.
# The user's slider always wins.
WEIGHT_PRESETS: dict[str, Weights] = {
    "ride_hailing": Weights(value=0.25, risk=0.25, running_cost=0.30,
                            liquidity=0.10, mileage=0.08, recency=0.02),
    "family_first_car": Weights(value=0.22, risk=0.40, running_cost=0.12,
                                liquidity=0.08, mileage=0.15, recency=0.03),
    "commute": Weights(value=0.30, risk=0.25, running_cost=0.22,
                       liquidity=0.08, mileage=0.12, recency=0.03),
    "resale_flip": Weights(value=0.45, risk=0.18, running_cost=0.05,
                           liquidity=0.22, mileage=0.08, recency=0.02),
    "cargo": Weights(value=0.30, risk=0.28, running_cost=0.22,
                     liquidity=0.10, mileage=0.08, recency=0.02),
    "unspecified": Weights(),
}


@dataclass(frozen=True)
class IntentSpec:
    raw_query: str
    budget_max_toman: int | None = None
    budget_min_toman: int | None = None
    budget_hard: bool = True
    model_hints: tuple[str, ...] = ()
    year_min: int | None = None
    max_mileage_km: int | None = None
    # Where the buyer said the car should be: the provinces named, any one of
    # which meets it. Empty when none was stated. The search over listings
    # judges it (webapp/api/constraints.py); the ranked path does not — an
    # appraisal Row carries no province, and `_passes` has nothing to compare.
    provinces: tuple[str, ...] = ()
    use_case: str = "unspecified"
    deal_breakers: tuple[str, ...] = ()
    weights: Weights = field(default_factory=Weights)
    risk_profile: str = "balanced"
    # What we INFERRED rather than were told. Surfaced so the user can correct
    # it — an assumption the user cannot see is an assumption they cannot fix.
    assumptions: tuple[str, ...] = ()
    # Text we saw and could not map. Never silently dropped: this is a
    # roadmap of what the parser is missing.
    unparsed: tuple[str, ...] = ()

    def with_weights(self, w: Weights) -> "IntentSpec":
        return replace(self, weights=w.normalized())


class IntentParser(Protocol):
    def parse(self, query: str) -> IntentSpec: ...


@dataclass
class RuleIntentParser:
    """Deterministic Persian parser. Ships, runs offline, never hallucinates.

    An LLM parser can replace this by producing the same `IntentSpec` — the
    contract is the frozen dataclass, not the mechanism. This one is the
    fallback that keeps the product working when the model is unavailable.
    """

    def parse(self, query: str) -> IntentSpec:
        q = normalize_fa(query)
        assumptions: list[str] = []
        consumed: list[str] = []
        # Cues that changed the spec — a use case, a red line, a weight, a
        # soft budget, an odometer. Not removed from the text the way a
        # number's clause is; a clause holding one is understood. See
        # `unparsed` below.
        acted: list[str] = []

        budget_max = budget_min = None
        hard = True
        # The floor is read first, and the budget is read from the query with the
        # floor's phrase blanked out: «از ۴۰۰ میلیون به بالا» is a floor and
        # nothing else, and its amount was also taken for the ceiling.
        qc = q
        m = _FLOOR_S.search(q) or _FLOOR_Y.search(q) or _floor_by_word(q)
        if m:
            budget_min = parse_amount(m.group(1))
            acted.append(m.group(0))
            qc = q[:m.start()] + " " * (m.end() - m.start()) + q[m.end():]
        # Every budget-ish clause, not just the first one in the string. The
        # first clause is frequently about something else — «کارکرد زیر ۹۰
        # هزار، تا ۸۰۰ میلیون» opens with an odometer — so a clause is taken
        # only once it is shown to name an amount of money. The clause is
        # taken whole, up to the next «،», so a word after the amount goes
        # with it; `budget_tail` is what follows the amount, and is handed to
        # `read_unknown_places` below.
        budget_tail = ""
        for m in re.finditer(r"(?:زیر|تا|حداکثر|کمتر از|بودجه|قیمت)\s*([^،]*)",
                             qc):
            got = money_amount(m.group(1))
            if got is not None:
                budget_max = got
                # Found in `qc`, taken from `q` by the same span: a floor's
                # phrase inside the clause goes with it.
                consumed.append(q[m.start():m.end()])
                budget_tail = after_amount(q[m.start(1):m.end(1)])
                break
        if budget_max is None:
            # No clause said it, but the query may still name a price. This
            # is an inference, so it is recorded as one; what it may not do
            # is read a model number or a year as a budget, which is why it
            # goes through `_MONEY` — `money_amount`, with the span kept —
            # rather than `parse_amount`.
            mm = _MONEY.search(qc)
            budget_max = parse_amount(mm.group(0)) if mm else None
            if budget_max is not None:
                acted.append(mm.group(0))
                assumptions.append("عدد قیمت را سقف بودجه فرض کردیم")
        m = re.search(r"(انعطاف|تقریبا|حدود|کمی بیشتر)", q)
        if m:
            hard = False
            acted.append(m.group(0))
            assumptions.append("بودجه را انعطاف‌پذیر در نظر گرفتیم")

        bare = _MONEY.sub(" ", q)
        models = tuple(k for k, al in MODEL_ALIASES.items()
                       if any(_names_model(q, a, bare) for a in al))

        year_min = None
        # «به بالا» after the year is the same statement — a floor — so it
        # is consumed with it rather than left behind as text not understood.
        m = re.search(r"مدل\s*(\d{2,4})(?:\s*به\s*بالا)?", q)
        if m:
            y = int(m.group(1))
            year_min = 1300 + y if y < 100 else y
            consumed.append(m.group(0))

        # ORDER IS PART OF THE FIX, not a style choice. The stated number is
        # read FIRST and the vague cue only fills the gap it leaves, so the
        # default is recorded in the same breath as being adopted.
        #
        # Written the other way round — cue first, number second — the note
        # was appended before the explicit parse could overwrite `max_km`,
        # and nothing retracted it. «کارکرد کمتر از ۲۰۰ هزار» then filtered
        # at 200,000 while the screen said «۱۲۰٬۰۰۰ گرفتیم». The assumption
        # bar exists so a buyer can correct a guess we made; one that names a
        # guess we did NOT make is worse than none, because the correction it
        # invites changes nothing.
        max_km = None
        m = re.search(
            r"(?:کارکرد\s*(?:زیر|تا|کمتر از|حداکثر)|حداکثر\s*کارکرد)"
            r"\s*(\d+)\s*(هزار|k|کیلومتر|کیلو)?", q)
        if m:
            n, unit = int(m.group(1)), m.group(2)
            v = n * 1000 if unit in ("هزار", "k") else n
            # Without a unit, a small number is not a distance — it is the
            # budget phrase leaking in ("کارکرد ... تا ۱.۵ میلیارد").
            if unit or v >= 1000:
                max_km = v
                acted.append(m.group(0))
        if max_km is None:
            for rx in _MILEAGE_CAPS:
                m = rx.search(q)
                if not m:
                    continue
                n, unit = int(m.group(1)), m.group(2)
                v = n * 1000 if unit in ("هزار", "k") else n
                if unit or v >= _MILEAGE_FLOOR:
                    max_km = v
                    acted.append(m.group(0))
                    break
        cue = _LOW_MILEAGE_CUE.search(q)
        if max_km is None and cue:
            max_km = 120_000
            acted.append(cue.group(0))
            assumptions.append("«کم‌کارکرد» را حداکثر ۱۲۰٬۰۰۰ کیلومتر گرفتیم")

        use_case = "unspecified"
        for uc, cues in USE_CASE_CUES.items():
            if any(c in q for c in cues):
                use_case = uc
                acted.extend(c for c in cues if c in q)
                break
        if use_case == "unspecified" and re.search(r"(کم مصرف|کم خرج|کم هزینه)", q):
            use_case = "commute"
            assumptions.append("از «کم‌خرج» کاربری روزمره برداشت شد")

        breakers = tuple(k for k, cues in DEAL_BREAKER_CUES.items()
                         if any(c in q for c in cues))
        for k in breakers:
            acted.extend(c for c in DEAL_BREAKER_CUES[k] if c in q)

        place = read_provinces(q)
        acted.extend(place.understood)

        risk = ("risk_averse" if ("accident" in breakers or
                                  use_case == "family_first_car")
                else "risk_tolerant" if use_case == "resale_flip"
                else "balanced")

        w = WEIGHT_PRESETS.get(use_case, Weights())
        costs = re.findall(r"(کم مصرف|کم خرج|کم هزینه|بنزین)", q)
        if costs:
            w = replace(w, running_cost=w.running_cost + 0.10)
            acted.extend(costs)
        if use_case != "unspecified":
            assumptions.append(
                f"وزن‌ها از پیش‌فرض «{USE_CASE_FA.get(use_case, use_case)}» "
                "شروع شد — قابل تغییر است")
        assumptions.extend(place.assumptions)

        # What is left for «بخش‌هایی که نفهمیدیم»: the clauses between
        # commas, once the clauses that set a number are taken out, less any
        # that names a model or holds a cue the parser acted on. It used to
        # keep the second kind, so a query's own red line could sit under
        # «فهمیدیم» as «خط قرمز» and under «نفهمیدیم» as ignored, both at once —
        # «تصادفی نباشه» on the family example, «ماشین برای اسنپ» and
        # «کم مصرف» on the Snapp one.
        #
        # A clause is understood as a whole, the way one naming a model always
        # was. Overlap is measured on spans, so a cue that runs across a
        # separator — «رفت و آمد» across « و » — covers both sides; and a
        # point between two digits is a decimal, not a separator, so
        # «۱.۲ میلیارد» is not cut into «… 1» and «2 میلیارد».
        rest = q
        for c in consumed:
            rest = rest.replace(c, " ")
        spans = [(m.start(), m.end()) for c in acted
                 for m in re.finditer(re.escape(c), rest)]
        clauses, start = [], 0
        for sep in re.finditer(r"،|(?<!\d)\.|\.(?!\d)| و ", rest):
            clauses.append((start, sep.start()))
            start = sep.end()
        clauses.append((start, len(rest)))
        unparsed = tuple(rest[a:b] for a, b in clauses
                         if len(rest[a:b].strip()) > 6
                         and not any(al in rest[a:b]
                                     for als in MODEL_ALIASES.values()
                                     for al in als)
                         and not any(s < b and e > a for s, e in spans))[:4]
        # A phrase that names a province and was not taken is listed by hand:
        # «پراید غیر از تهران» is a clause that names a model, so the rule
        # above has already counted it understood. One the clauses already
        # list is not listed twice, and one that holds a listed clause
        # replaces it.
        for d in place.declined:
            if not any(d in u for u in unparsed):
                unparsed = tuple(u for u in unparsed
                                 if u.strip() not in d) + (d,)
        # A cue the reader knows before a word it does not -- a city -- is
        # listed last, unless a phrase already listed holds it.
        for item in read_unknown_places(rest, clauses, spans):
            if not any(item in u for u in unparsed):
                unparsed += (item,)
        # And the same for what the budget clause took with its amount, read
        # as one more clause: «تا ۳۰۰ میلیون در مشهد» lists «در مشهد». It is
        # cut the way `rest` is -- what the parser consumed is taken out of
        # it and what it acted on is blanked where it stands -- so that «در
        # مشهد مدل ۹۵» lists the same with a budget before it as without.
        if budget_tail:
            for c in consumed:
                budget_tail = budget_tail.replace(c, " ")
            tail_spans = [(x.start(), x.end()) for a in acted
                          for x in re.finditer(re.escape(a), budget_tail)]
            for item in read_unknown_places(
                    budget_tail, [(0, len(budget_tail))], tail_spans):
                if not any(item in u for u in unparsed):
                    unparsed += (item,)

        return IntentSpec(
            raw_query=query, budget_max_toman=budget_max,
            budget_min_toman=budget_min, budget_hard=hard,
            model_hints=models, year_min=year_min, max_mileage_km=max_km,
            provinces=place.provinces,
            use_case=use_case, deal_breakers=breakers,
            weights=w.normalized(), risk_profile=risk,
            assumptions=tuple(assumptions), unparsed=unparsed)


# ---------------------------------------------------------------------------
# Retrieval and the relaxation ladder
# ---------------------------------------------------------------------------

MIN_SHORTLIST = 3


@dataclass
class RelaxationReport:
    """What we loosened, in the user's words.

    Trading off FOR the user is fine. Doing it silently is not: a shortlist
    that quietly ignores the stated budget is worse than an empty one,
    because the user cannot tell it happened.
    """
    steps: list[str] = field(default_factory=list)

    @property
    def relaxed(self) -> bool:
        return bool(self.steps)

    def text_fa(self) -> str:
        if not self.steps:
            return ""
        return "با شرایط دقیق شما گزینه‌ی کافی نبود، پس: " + "؛ ".join(self.steps)


def _model_matches(model_key: str, hints: Sequence[str]) -> bool:
    """Does this row's model_key satisfy any of the parsed model hints?

    Two vocabularies meet here and they were never the same one. The parser
    emits a bare canonical slug — `206`, `pride` — from `MODEL_ALIASES`.
    Ingest emits `make|model|trim`: `Peugeot|206|type1`, `Saipa|Pride|111 ex`.
    The original test was `row.model_key not in spec.model_hints`, an exact
    equality against the WHOLE key, so on real data every model-constrained
    query retrieved nothing — six real 206s inside the stated budget, all
    filtered out, and the relaxation ladder then loosened a budget that was
    never the binding constraint.

    Nothing caught it because every ranking test builds its corpus with
    `model_key=m` where m is already the canonical slug. The ranker was being
    tested against its own vocabulary; W3 and W4 had never been run against
    each other. That is the general lesson and it is bigger than this line:
    a passing suite over a corpus the code shaped is not evidence about data
    the code did not shape.

    Compare the MODEL SEGMENT, case-folded, against the canonical slug and
    its latin aliases. Persian aliases are the query's vocabulary, not the
    key's, so they are not matched here. Keys without a separator (the
    synthetic corpora) are their own model segment.
    """
    seg = model_key.split("|")[1] if "|" in model_key else model_key
    seg = seg.casefold()
    for h in hints:
        if seg == h.casefold():
            return True
        for alias in MODEL_ALIASES.get(h, ()):
            if alias.isascii() and seg == alias.casefold():
                return True
    return False


def _passes(row: Row, spec: IntentSpec) -> bool:
    if spec.budget_max_toman and row.asking_price_toman > spec.budget_max_toman:
        return False
    if spec.budget_min_toman and row.asking_price_toman < spec.budget_min_toman:
        return False
    if spec.model_hints and not _model_matches(row.model_key, spec.model_hints):
        return False
    if spec.year_min and row.year_jalali < spec.year_min:
        return False
    if spec.max_mileage_km and row.mileage_km > spec.max_mileage_km:
        return False
    for db in spec.deal_breakers:
        if row.features.get(f"has_{db}", 0.0) > 0.5:
            return False
    return True


def retrieve(rows: Sequence[Row], spec: IntentSpec,
             min_results: int = MIN_SHORTLIST) -> tuple[list[Row], IntentSpec,
                                                        RelaxationReport]:
    """Hard filters, then walk the ladder if too few survive.

    Never returns an empty shortlist without saying what was loosened to
    avoid one — and never loosens a deal-breaker, which is the difference
    between a preference and a requirement.
    """
    rep = RelaxationReport()
    cur = spec
    out = [r for r in rows if _passes(r, cur)]
    if len(out) >= min_results:
        return out, cur, rep

    ladder = [
        ("budget", lambda s: replace(
            s, budget_max_toman=int(s.budget_max_toman * 1.10))
         if s.budget_max_toman else None,
         "بودجه ۱۰٪ افزایش یافت"),
        ("mileage", lambda s: replace(
            s, max_mileage_km=int(s.max_mileage_km * 1.30))
         if s.max_mileage_km else None,
         "سقف کارکرد ۳۰٪ بالاتر رفت"),
        ("year", lambda s: replace(s, year_min=s.year_min - 1)
         if s.year_min else None,
         "یک سال مدل پایین‌تر هم بررسی شد"),
        ("budget2", lambda s: replace(
            s, budget_max_toman=int(s.budget_max_toman * 1.10))
         if s.budget_max_toman and not s.budget_hard else None,
         "بودجه ۱۰٪ دیگر افزایش یافت"),
    ]
    for _, step, label in ladder:
        nxt = step(cur)
        if nxt is None:
            continue
        cur = nxt
        rep.steps.append(label)
        out = [r for r in rows if _passes(r, cur)]
        if len(out) >= min_results:
            break
    return out, cur, rep


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------

RISK_PROFILE_QUANTILE = {"risk_averse": 0.15, "balanced": 0.35,
                         "risk_tolerant": 0.50}

# What a unit of risk costs, as a fraction of the car's value.
#
# This constant exists because of a bug the win-rate benchmark caught. The
# first implementation normalised risk to [0,1] across the candidate set and
# blended it as a weighted term — which throws away magnitude. A 20% defect
# probability on a 2B car costs the buyer ~240M; the same 20% on an 800M car
# costs ~96M. Scale-free risk cannot see that difference, so the ranker kept
# picking expensive moderately-damaged cars and LOST to sorting by price.
#
# The fix restores the product thesis as originally stated:
#
#     value = estimate − asking − risk_discount
#
# with every term in tomans, subtracted before any normalisation. Risk is
# priced, not scored.
#
# The value is policy, not a fitted parameter, and is deliberately
# conservative — a defect usually costs less than the full proportional
# share of the car because not every flagged risk materialises.
DAMAGE_COST_FACTOR = 0.60


# ---------------------------------------------------------------------------
# Body condition → the risk input, as a published table
# ---------------------------------------------------------------------------
#
# `features["risk"]` was absent on every real row until this existed, which is
# why four of six scoring terms were constant on Bama data (D41). The evidence
# was there the whole time: Bama publishes «وضعیت بدنه» on the detail page and
# Run 3 recorded it on 214 of 221 listings, in the five classes below. Run 5's
# extractor lost it (D45).
#
# These numbers are a PUBLISHED POLICY, calibrated by judgement, and that is
# stated here rather than implied — the same rule the confidence bands follow.
# They are not fitted, and no data in this repository could fit them: fitting a
# damage probability needs inspection outcomes, and CARO has never observed
# one. What they encode is an ordering the market agrees on and a rough spacing
# between its steps, which is enough for a ranking input and is not enough to
# be quoted as a probability of anything.
#
# UNKNOWN is the interesting row. It is not zero. A listing that does not state
# its condition is not a listing with no damage — treating silence as "intact"
# would systematically rank undisclosed cars above disclosed ones, which is
# exactly backwards, and would reward sellers for saying less. It sits between
# minor_paint and multi_paint: worse than the good disclosures, better than the
# bad ones, because it could be either.
CONDITION_RISK: dict[str, float] = {
    "intact":        0.05,   # «بدون رنگ» — stated and specific
    "minor_paint":   0.20,   # a spot or a scratch, disclosed
    "unknown":       0.35,   # nothing said: see above, NOT 0.0
    "multi_paint":   0.50,   # «دور رنگ» / several panels
    "replaced_part": 0.65,   # a panel has been changed
    "accident":      0.85,   # «تصادفی» / chassis
}


def risk_from_condition(body_condition: str | None) -> float:
    """The one place a condition label becomes a number. Unknown is not zero."""
    return CONDITION_RISK.get(body_condition or "unknown",
                              CONDITION_RISK["unknown"])


# Keys whose value was IMPUTED rather than observed. See the note below.
IMPUTED_MARK = "_imputed"


def features_from_listing(listing) -> dict[str, float]:
    """Ranking inputs a real listing can actually supply today.

    Deliberately partial and deliberately explicit about the difference between
    three states, which is this project's UNKNOWN-vs-ABSENT rule (D4) applied
    one level deeper than it was:

        OBSERVED   the page stated it. `risk` from a real condition label.
        IMPUTED    the page did not state it, and leaving the key out would be
                   worse than filling it — `Ranker.score` reads risk with
                   `.get("risk", 0.0)`, so an absent key scores silence as a
                   PERFECT car. That is the one failure the whole table exists
                   to prevent, so unknown is filled at 0.35 and marked.
        ABSENT     nothing supports a value at all. `ownership_risk` and
                   `liquidity` are NOT invented from make or model, because a
                   plausible-looking constant turns a missing input into a fake
                   one the ledger can no longer report.

    The middle state is the one that needed adding. Filling `unknown` silently
    would have been exactly the error this module names two paragraphs earlier
    — a value I chose, indistinguishable downstream from a value Bama printed.
    So it is filled AND flagged: `features["_imputed"]` carries the keys whose
    value nobody observed, and the decision ledger reports them separately.
    """
    feats: dict[str, float] = {}
    imputed: list[str] = []
    cond = getattr(listing, "body_condition", None)
    if cond:
        feats["risk"] = risk_from_condition(cond)
        feats["has_accident"] = 1.0 if cond == "accident" else 0.0
        if cond == "unknown":
            # The page carried no condition line. The number below is ours.
            imputed.append("risk")
    if getattr(listing, "document_issue", None):
        feats["has_unclear_documents"] = 1.0
    if imputed:
        feats[IMPUTED_MARK] = imputed          # type: ignore[assignment]
    return feats


def _norm(v: np.ndarray) -> np.ndarray:
    """Min-max to [0,1]; a constant column contributes nothing rather than NaN."""
    if v.size == 0:
        return v
    lo, hi = float(np.min(v)), float(np.max(v))
    return np.full_like(v, 0.5) if hi - lo < 1e-9 else (v - lo) / (hi - lo)


@dataclass
class ScoredRow:
    row: Row
    score: float
    breakdown: dict[str, float]
    conservative_estimate_toman: float
    adjusted_opportunity_toman: float
    expected_damage_toman: float = 0.0

    @property
    def role_fa(self) -> str:
        return self.breakdown.get("_role", "")  # set by the diversity pass


@dataclass
class Ranker:
    """Deterministic scoring over a retrieved candidate set.

    Every term is kept separately in `breakdown` so the card can show why a
    car ranked where it did, and so a weight change recomputes client-side
    without a round trip.

    Value uses a LOWER QUANTILE of the estimate rather than the median: an
    uncertain estimate is a riskier bet, not a smaller opportunity, and
    scaling a delta by a confidence scalar encodes the wrong claim. The
    quantile comes straight from the user's risk profile.
    """
    estimator: MarketEstimator

    def score(self, rows: Sequence[Row], spec: IntentSpec) -> list[ScoredRow]:
        if not rows:
            return []
        preds = self.estimator.predict(rows)            # raises if ungated
        alpha = RISK_PROFILE_QUANTILE[spec.risk_profile]
        qi = min(range(len(QUANTILES)),
                 key=lambda i: abs(QUANTILES[i] - alpha))

        asking = np.array([r.asking_price_toman for r in rows], dtype=float)
        conservative = preds[:, qi]
        risk = np.array([r.features.get("risk", 0.0) for r in rows])

        # Risk is priced in tomans against the car's own value, then
        # subtracted — not normalised and blended. See DAMAGE_COST_FACTOR.
        expected_damage_toman = risk * conservative * DAMAGE_COST_FACTOR
        opportunity = conservative - asking - expected_damage_toman
        owning = np.array([r.features.get("ownership_risk", 0.0) for r in rows])
        liquid = np.array([r.features.get("liquidity", 0.5) for r in rows])
        mileage = np.array([r.mileage_km for r in rows], dtype=float)
        recency = np.array([float(r.first_seen_ordinal) for r in rows])

        w = spec.weights.normalized()
        terms = {
            "value": w.value * _norm(opportunity),
            "risk": -w.risk * _norm(risk),
            "running_cost": -w.running_cost * _norm(owning),
            "liquidity": w.liquidity * _norm(liquid),
            "mileage": -w.mileage * _norm(mileage),
            "recency": w.recency * _norm(recency),
        }
        total = sum(terms.values())

        return [ScoredRow(
            row=r, score=float(total[i]),
            breakdown={k: float(v[i]) for k, v in terms.items()},
            conservative_estimate_toman=float(conservative[i]),
            adjusted_opportunity_toman=float(opportunity[i]),
            expected_damage_toman=float(expected_damage_toman[i]),
        ) for i, r in enumerate(rows)]


# ---------------------------------------------------------------------------
# Diversity and shortlist
# ---------------------------------------------------------------------------

def diversify(scored: Sequence[ScoredRow], k: int = 5) -> list[ScoredRow]:
    """Pick the top item, then the best of each distinct role.

    Three near-identical Prides is a failed shortlist even if all three score
    well. The roles are also what the card labels each pick with, so the
    diversity pass is user-visible rather than a hidden reranking.
    """
    if not scored:
        return []
    ordered = sorted(scored, key=lambda s: s.score, reverse=True)
    picks: list[ScoredRow] = [ordered[0]]
    ordered[0].breakdown["_role"] = "بهترین تطابق کلی"

    def best(pred, label):
        for s in ordered:
            if s in picks:
                continue
            if pred(s):
                s.breakdown["_role"] = label
                picks.append(s)
                return

    best(lambda s: s.row.features.get("risk", 0.0) <= 0.15, "امن‌ترین گزینه")
    best(lambda s: s.adjusted_opportunity_toman > 0, "بیشترین صرفه")
    best(lambda s: s.row.asking_price_toman <= np.percentile(
        [x.row.asking_price_toman for x in ordered], 25), "ارزان‌ترین قابل قبول")
    for s in ordered:
        if len(picks) >= k:
            break
        if s not in picks:
            s.breakdown.setdefault("_role", "گزینه‌ی جایگزین")
            picks.append(s)
    return picks[:k]


# ---------------------------------------------------------------------------
# The decision ledger — what the ranker actually had to work with
# ---------------------------------------------------------------------------
#
# There is no ground truth for ranking quality on real listings. Buyer utility
# is not published, disappearance is not a sale (D2), and a rubric written
# here — or handed to a language model as a judging prompt — is the same
# self-written utility function wearing a different coat. So "CARO's ranking
# beats price-sort on Iranian used cars" is not a claim this project can
# support today, and D41 says so in the status table.
#
# A different claim IS supportable, and it is the one this ledger measures:
#
#     are the inputs the ranking says it uses actually PRESENT, observable
#     and traceable in real listings?
#
# That is a question about construct validity rather than outcome quality. It
# needs no ground truth, it runs on real data with no estimator, and it fails
# loudly when the answer is no — which on this corpus it largely is. Four of
# six scoring terms have no input on Bama data (D41), so a ledger over real
# listings is mostly `missing`, and printing that is the point: an absent
# input is a term that cannot move a ranking however its weight is set.
#
# What this is NOT: evidence that the ordering is good. A ledger showing every
# input present would say the ranker is well-fed, not that it is right.


LEDGER_INPUTS: tuple[tuple[str, str], ...] = (
    ("hard_filter_pass", "did this candidate satisfy the stated constraints"),
    ("price_delta_to_estimate", "asking price against the market estimate"),
    ("risk_score", "priced body/accident risk"),
    ("mileage", "odometer reading"),
    ("year", "model year"),
    ("running_cost_signals", "ownership cost proxy"),
    ("reliability_signals", "liquidity / resale proxy"),
    ("recency", "how long the listing has been observed"),
    ("data_completeness", "share of the above that is present"),
)


@dataclass(frozen=True)
class LedgerRow:
    """One candidate, and which decision inputs really existed for it.

    Three states, not two. `values` holds what the ranker had; `imputed` names
    the subset of those the SOURCE never stated and this project supplied;
    `missing` names what had no value at all, with the reason. The middle set
    is the one worth having — a number we chose and a number Bama printed are
    indistinguishable downstream, and a ledger that cannot tell them apart is
    reporting our own assumptions back to us as observations.
    """
    candidate_id: str
    values: dict[str, float | int | bool]
    missing: dict[str, str]
    final_rank: int | None
    imputed: dict[str, str] = field(default_factory=dict)

    @property
    def completeness(self) -> float:
        """Share of inputs that had a value, imputed ones INCLUDED."""
        n = len(LEDGER_INPUTS) - 1          # data_completeness is derived
        return len(self.values) / n if n else 0.0

    @property
    def observed_completeness(self) -> float:
        """The stricter number: share whose value the source actually stated."""
        n = len(LEDGER_INPUTS) - 1
        return (len(self.values) - len(self.imputed)) / n if n else 0.0


def decision_ledger(rows: Sequence[Row], spec: IntentSpec,
                    estimator: MarketEstimator | None = None,
                    ranked: Sequence[ScoredRow] = ()) -> list[LedgerRow]:
    """Record, per candidate, which ranking inputs were actually available.

    Deliberately runs WITHOUT an estimator. When one is absent or ungated the
    price-delta input is recorded as missing with the reason, rather than the
    whole ledger refusing — because "the estimate was not available" is the
    single most informative line this can print on real data, and refusing to
    print it would hide exactly the thing worth seeing.
    """
    order = {s.row.listing_id: i + 1 for i, s in enumerate(
        sorted(ranked, key=lambda s: s.score, reverse=True))}

    preds = None
    if estimator is not None:
        try:
            preds = estimator.predict(rows)
        except NotBenchmarked:
            preds = None

    out: list[LedgerRow] = []
    for i, r in enumerate(rows):
        values: dict[str, float | int | bool] = {}
        missing: dict[str, str] = {}
        imputed: dict[str, str] = {}
        marked = set(r.features.get(IMPUTED_MARK) or ())

        values["hard_filter_pass"] = _passes(r, spec)
        values["mileage"] = r.mileage_km
        values["year"] = r.year_jalali

        if preds is not None:
            mid = preds.shape[1] // 2
            values["price_delta_to_estimate"] = float(
                preds[i, mid] - r.asking_price_toman)
        else:
            missing["price_delta_to_estimate"] = (
                "no gated estimator: the acceptance gate has not approved one "
                "on this corpus, so no market estimate may be served")

        for key, label in (("risk", "risk_score"),
                           ("ownership_risk", "running_cost_signals"),
                           ("liquidity", "reliability_signals")):
            if key in r.features:
                values[label] = float(r.features[key])
                if key in marked:
                    imputed[label] = (
                        "the listing stated no condition; this is CONDITION_RISK"
                        "['unknown'], a value this project chose and the source "
                        "never published")
            else:
                missing[label] = f"features['{key}'] absent — ingest does not populate it"

        if r.first_seen_ordinal:
            values["recency"] = int(r.first_seen_ordinal)
        else:
            missing["recency"] = "first_seen_ordinal is 0 — single snapshot, no observation history"

        out.append(LedgerRow(candidate_id=r.listing_id, values=values,
                             missing=missing, imputed=imputed,
                             final_rank=order.get(r.listing_id)))
    return out


@dataclass
class Shortlist:
    spec: IntentSpec
    items: list[ScoredRow]
    relaxation: RelaxationReport
    considered: int

    def summary_fa(self) -> str:
        L = [f"{self.considered} آگهی بررسی شد؛ {len(self.items)} گزینه انتخاب شد."]
        if self.relaxation.relaxed:
            L.append(self.relaxation.text_fa())
        if self.spec.assumptions:
            L.append("فرض‌های ما: " + "؛ ".join(self.spec.assumptions))
        return "\n".join(L)


@dataclass
class RankingPipeline:
    parser: IntentParser
    ranker: Ranker

    def run(self, query: str, rows: Sequence[Row], k: int = 5) -> Shortlist:
        spec = self.parser.parse(query)
        cands, used_spec, rep = retrieve(rows, spec)
        scored = self.ranker.score(cands, used_spec)
        return Shortlist(used_spec, diversify(scored, k), rep, len(cands))


# ---------------------------------------------------------------------------
# The experiment that decides whether this product should exist
# ---------------------------------------------------------------------------

@dataclass
class WinRateResult:
    n_queries: int
    caro_mean_utility: float
    price_sort_mean_utility: float
    random_mean_utility: float
    caro_wins: int
    ties: int

    @property
    def win_rate(self) -> float:
        return self.caro_wins / self.n_queries if self.n_queries else 0.0

    @property
    def uplift(self) -> float:
        base = abs(self.price_sort_mean_utility) or 1.0
        return (self.caro_mean_utility - self.price_sort_mean_utility) / base

    def __str__(self) -> str:
        return (f"queries={self.n_queries}  win-rate={self.win_rate:.0%}  "
                f"CARO={self.caro_mean_utility:,.0f}  "
                f"price-sort={self.price_sort_mean_utility:,.0f}  "
                f"random={self.random_mean_utility:,.0f}")


def winrate_vs_price_sort(pipeline: RankingPipeline, rows: Sequence[Row],
                          queries: Sequence[str],
                          utility_fn, k: int = 3) -> WinRateResult:
    """Compare CARO's shortlist against sorting by price, and against chance.

    `utility_fn(row) -> float` is the ground truth: what the buyer actually
    gains. On a synthetic corpus it comes from the generating process, which
    the ranker never sees — the ranker works from a FITTED estimator, so this
    is not circular.

    On real data there is no such function, and the honest substitute is a
    blind human panel: same queries, shuffled unlabelled shortlists, one
    question — "which list is more useful to buy from". That result belongs
    in EVAL.md whatever it says.

    Random is included because beating price-sort is only impressive if
    price-sort is not itself worse than chance.
    """
    rng = np.random.default_rng(0)
    caro_u, price_u, rand_u = [], [], []
    wins = ties = 0

    for q in queries:
        sl = pipeline.run(q, rows, k=k)
        if not sl.items:
            continue
        cands, _, _ = retrieve(rows, pipeline.parser.parse(q))
        if not cands:
            continue

        c = float(np.mean([utility_fn(s.row) for s in sl.items[:k]]))
        p = float(np.mean([utility_fn(r) for r in sorted(
            cands, key=lambda r: r.asking_price_toman)[:k]]))
        idx = rng.choice(len(cands), size=min(k, len(cands)), replace=False)
        rnd = float(np.mean([utility_fn(cands[i]) for i in idx]))

        caro_u.append(c); price_u.append(p); rand_u.append(rnd)
        if c > p:
            wins += 1
        elif c == p:
            ties += 1

    n = len(caro_u)
    return WinRateResult(
        n_queries=n,
        caro_mean_utility=float(np.mean(caro_u)) if n else 0.0,
        price_sort_mean_utility=float(np.mean(price_u)) if n else 0.0,
        random_mean_utility=float(np.mean(rand_u)) if n else 0.0,
        caro_wins=wins, ties=ties)
