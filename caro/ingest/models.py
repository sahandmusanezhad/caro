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
"""

from __future__ import annotations

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


def search_aliases() -> dict[str, tuple[str, ...]]:
    """The search's view: a model's name lower-cased, and the names it is
    written by."""
    return {model.lower(): names for _make, model, names in MODELS}
