"""The car models CARO reads by name: one table, for the listings and the search.

The listing parser (`divar_car.extract_make_model`) finds a model in what a
seller wrote; the search (`caro.ranking`) finds one in what a buyer typed.
Until 2026-11-02 they read two tables, and the two had drifted: the
listings' knew IKCO's Runna, Samand and Tara and the search's did not, so
«سمند زیر ۲ میلیارد» was parsed with no model and showed every car under
two billion -- 163 of run17's listings -- with nothing said. The owner chose
then to make them one table, and to add no name neither table held.

A model is its make and its model as a corpus writes them, and the names it
is written by, Persian and Latin. The order of the models is the listing
parser's, which returns the first model whose name it finds in a text, so
the order is part of the rule. Each reader takes its own view of the table:

    MAKE_MODEL     (make, model) -> names     divar_car, divar_page
    search_aliases model, lower-cased -> names  ranking.MODEL_ALIASES

The search's key for a model is its model's name lower-cased -- what the
corpus holds, compared case-folded with a listing's model -- so a hint and a
row meet without a second vocabulary.

Both readers find a name by one rule, `names` below: a name is a word of its
own. It was found anywhere in a text, and three of run17's Grand Vitaras
were read as IKCO Taras, «تارا» inside «ویتارا», and two Renault Pars Tondars
as Peugeot Parses (2026-11-19).
"""

from __future__ import annotations

import re

MODELS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Peugeot", "206", ("پژو 206", "206", "پژو206", "دویست و شش")),
    ("Peugeot", "207", ("پژو 207", "207i", "207", "پژو207")),
    ("Peugeot", "405", ("پژو 405", "405")),
    ("Peugeot", "Pars", ("پژو پارس", "پارس", "pars")),
    ("Saipa", "Pride", ("پراید", "سایپا 131", "131", "111", "132", "pride")),
    ("Saipa", "Tiba", ("تیبا", "tiba")),
    ("Saipa", "Quik", ("کوییک", "کوئیک", "quick", "quik")),
    ("Saipa", "Saina", ("ساینا", "saina")),
    ("Saipa", "Shahin", ("شاهین", "shahin")),
    ("IKCO", "Dena", ("دنا", "dena")),
    ("IKCO", "Runna", ("رانا",)),
    ("IKCO", "Samand", ("سمند",)),
    ("IKCO", "Tara", ("تارا",)),
)

MAKE_MODEL: dict[tuple[str, str], tuple[str, ...]] = {
    (make, model): names for make, model, names in MODELS}


# A NAME IS A WORD OF ITS OWN. A name was found anywhere in a text, so the
# listing parser read a model inside another word and, the table read in its
# order, before the model the text named. In run17, three Suzuki Grand
# Vitaras were IKCO Taras, «تارا» inside «ویتارا», and two Renault Pars Tondars
# Peugeot Parses: the Tara page's highest price was a Vitara's, 7.575 billion
# toman, where a Tara's is 4.04. A Divar description that says «تهرانپارس» put a
# Pride, a Tiba or a Dena under Peugeot Pars, which the table holds first, and
# the search hinted «pars» for «پراید تهرانپارس». Measured on 2026-11-19 on
# made titles and queries, the predictions locked first; no Persian title of
# Khodro45's is in the repository. Today's reading was right on 0 of 8 Vitara
# titles, 0 of 5 Pars Tondar's, 0 of 5 with «تهرانپارس» and 0 of 5 with a place
# in two words, and on 29 of 29 ordinary titles; the owner chose this rule:
#
#   - a name is no name where a letter stands right before it but a «و» typed
#     on («وتیبا»), or right after it but for an ending Persian puts on a
#     noun: «ی», «یی», «م», «ت», «ش», «مو», «تو», «شو», «مون», «تون», «شون»,
#     «مان», «تان», «شان», «ها», «های», «هایی» («پرایدم», «تیباش», «پرایدها» are
#     read as they were);
#   - nor where «تندر», «شهر» or «آباد» is the next word, or «تهران» or «تندر»
#     the word before: Renault's «پارس تندر» and «تندر پارس», and the places
#     «شاهین شهر», «پارس آباد» and «تهران پارس».
#
# Read so, 8 of 8, 4 of 5, 5 of 5 and 5 of 5, and 29 of 29. The endings and the
# «و» were found after the owner's first choice, which read 24 of 27 such true
# forms as no model, and the owner chose them on the second measurement: 27 of
# 27 kept, and 9 of 10 words that hold a name and are none cleared («پارسال»,
# «پارسیان», «پارسا», «سمندر»). The same question was measured in D84's round
# and left then. Left: «پارسی» is Peugeot's Pars, «ی» being an ending. «تندر»
# as the word before was the owner's choice of the same night, measured, the
# predictions locked first: right on 7 of 7 titles and 3 of 3 queries with
# the words the other way round («تندر پارس رنو»), where the rule was right on
# none, and nothing else read differently. A name of digits alone is found
# anywhere, as it was; the search keeps its own rule for those
# (`caro.ranking._names_model`).
_LETTER = r"[^\W\d_]"
_BEFORE = r"(?:(?<!" + _LETTER + r")|(?<=(?<!" + _LETTER + r")و))"
_ENDING = r"(?:ی|یی|م|ت|ش|مو|تو|شو|مون|تون|شون|مان|تان|شان|ها|های|هایی)?"
_NOT_A_MODEL_AFTER = re.compile(r"\s*(?:تندر|شهر|آباد)(?!\w)")
_NOT_A_MODEL_BEFORE = re.compile(r"(?:تهران|تندر)\s*$")


def names(text: str, name: str) -> bool:
    """Does `text` hold `name` as a model's name? Both as the reader
    normalizes them."""
    if name.isdigit():
        return name in text
    for m in re.finditer(_BEFORE + re.escape(name) + _ENDING + r"(?!" + _LETTER + ")",
                         text):
        if _NOT_A_MODEL_AFTER.match(text, m.end()):
            continue
        if _NOT_A_MODEL_BEFORE.search(text, 0, m.start()):
            continue
        return True
    return False


def search_aliases() -> dict[str, tuple[str, ...]]:
    """The search's view: a model's name lower-cased, and the names it is
    written by."""
    return {model.lower(): names for _make, model, names in MODELS}
