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

# THE THIRTEEN: the models the table named until 2026-11-26, Persian names
# that sellers on Divar, Sheypoor and Bama write and Khodro45's Persian titles
# are read by, to one model however Khodro45's English titles spell it.
_THIRTEEN: tuple[tuple[str, str, tuple[str, ...]], ...] = (
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

# RUN17'S HUNDRED (2026-11-26, the owner's choice on a measurement, M2kc). Of
# run17's 492 listings, 211 were of 104 models no table named, and a buyer
# could not ask for them by name (D98). These are 100 of them, 190 listings,
# each make and model as run17 writes it -- Khodro45's English titles -- and
# the names written for it before anything was measured: Persian and Latin,
# the Latin read in capitals too. A name names one model of run17. A name a
# buyer writes for more than one is given only with the word that tells them
# apart: «تیگو 7» is Chery's Tiggo 7 and Fownix's two Tiggo 7 Pros, so
# «چری تیگو 7»; and «آریزو 6», «cs55», «x22» beside «x22 پرو». A model's number
# alone is no name, and a name of two Latin letters or digits («s5», «j7»,
# «fx») is given only with its make. Within a make a model whose name holds
# another's comes first, since the listing parser takes the first model it
# finds; the search names both, so «x22 پرو» shows the X22s too.
#
# Measured on made queries and titles, the predictions locked first, and on
# the queries and texts the suites hand the readers: each of the hundred named
# by its Persian name in 100 of 100 queries and by its Latin one in 100 of 100,
# alone in 92 and 94 (the rest name the shorter-named model too, as said);
# read right in 100 of 100 made titles; the API on run17 returns that model's
# listings exactly for 92, and for the 8 its own and the shorter-named one's;
# of the 1,338 queries the suites hand the search, the 12 that hold one of the
# names read it, and nothing else in any query changes but what is listed as
# not understood. run17's listings a query can name: 281 (57%) to 471 (96%).
#
# Left: four models whose model two makes write, Dignity's and Fidelity's
# «Prime», JAC's and Haima's «S5» (21 listings): the search keys a model by its
# model alone, lower-cased, and could not tell them apart.
_RUN17: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Haima", "S7", ("هایما اس 7", "هایما اس7", "هایما s7", "haima s7")),
    ("Haima", "8S", ("هایما 8 اس", "هایما 8اس", "هایما 8s", "haima 8s")),
    ("Haima", "7X", ("هایما 7 ایکس", "هایما 7x", "haima 7x")),
    ("KMC", "j7", ("کی ام سی j7", "کی ام سی جی 7", "kmc j7")),
    ("KMC", "X5", ("کی ام سی x5", "کی ام سی ایکس 5", "kmc x5")),
    ("KMC", "Eagle", ("کی ام سی ایگل", "kmc eagle")),
    ("KMC", "T8", ("کی ام سی t8", "کی ام سی تی 8", "kmc t8")),
    ("KMC", "a5", ("کی ام سی a5", "kmc a5")),
    ("KMC", "K7", ("کی ام سی k7", "kmc k7")),
    ("Lamari", "Eama", ("لاماری ایما", "لاماری", "lamari eama", "lamari")),
    ("MVM", "X33 Cross", ("ام وی ام x33 کراس", "x33 کراس", "x33 cross")),
    ("MVM", "X33s", ("x33s", "ام وی ام x33 اس", "x33 اس")),
    ("MVM", "X33", ("ام وی ام x33", "mvm x33", "x33")),
    ("MVM", "X22 Pro", ("ام وی ام x22 پرو", "x22 پرو", "x22 pro")),
    ("MVM", "X22", ("ام وی ام x22", "mvm x22", "x22")),
    ("MVM", "X55 Pro", ("ام وی ام x55 پرو", "x55 پرو", "x55 pro")),
    ("MVM", "X55", ("ام وی ام x55", "mvm x55", "x55")),
    ("MVM", "550", ("ام وی ام 550", "mvm 550")),
    ("MVM", "Hatchback-315", ("ام وی ام 315", "mvm 315")),
    ("Dongfeng", "H30 Cross", ("دانگ فنگ h30", "دانگفنگ h30", "h30 کراس", "h30 cross")),
    ("Hyundai", "Sonata", ("سوناتا", "sonata")),
    ("Hyundai", "Azera (Grandeur)", ("آزرا", "گرنجور", "گرندیور", "azera", "grandeur")),
    ("Hyundai", "i20", ("i20", "آی 20")),
    ("Hyundai", "Accent Assembled", ("اکسنت", "accent")),
    ("Hyundai", "Avante", ("آوانته", "avante")),
    ("Hyundai", "Elantra", ("النترا", "elantra")),
    ("Hyundai", "Genesis", ("جنسیس", "genesis")),
    ("Hyundai", "SantaFe (ix45)", ("سانتافه", "سانتا فه", "santafe", "santa fe", "ix45")),
    ("Hyundai", "Tucson (ix35)", ("توسان", "tucson", "ix35")),
    ("JAC", "S3", ("جک اس 3", "جک اس3", "جک s3", "jac s3")),
    ("JAC", "J4", ("جک j4", "جک جی 4", "jac j4")),
    ("JAC", "J5", ("جک j5", "جک جی 5", "jac j5")),
    ("Mazda", "3 Sedan-Assembled (New)", ("مزدا 3", "مزدا3", "mazda 3", "mazda3")),
    ("Atlas", "GL", ("اطلس جی ال", "اطلس gl", "atlas gl")),
    ("Atlas", "G", ("اطلس جی", "اطلس g", "atlas g")),
    ("Chery", "Arrizo 5T Sport FL", ("آریزو 5 تی اسپرت", "آریزو 5t اسپرت", "آریزو 5 اسپرت", "arrizo 5t sport")),
    ("Chery", "Arrizo 5T", ("آریزو 5 تی", "آریزو 5t", "آریزو 5", "arrizo 5t", "arrizo 5")),
    ("Chery", "Arrizo 6", ("چری آریزو 6", "chery arrizo 6")),
    ("Chery", "Tiggo 5", ("تیگو 5", "tiggo 5")),
    ("Chery", "Tiggo 7", ("چری تیگو 7", "chery tiggo 7")),
    ("Fownix", "tiggo8 PRO MAX (F8 Max)", ("تیگو 8", "tiggo 8", "tiggo8")),
    ("Fownix", "Tiggo7pro Max", ("تیگو 7 پرو مکس", "tiggo 7 pro max", "tiggo7pro max")),
    ("Fownix", "Tiggo7pro Hybrid", ("تیگو 7 پرو هیبرید", "tiggo 7 pro hybrid", "tiggo7pro hybrid")),
    ("Fownix", "Arrizo 6 GT (Z6)", ("آریزو 6 جی تی", "آریزو 6 gt", "arrizo 6 gt")),
    ("Fownix", "Arrizo6pro", ("آریزو 6 پرو", "arrizo 6 pro", "arrizo6pro")),
    ("Fownix", "Arizo 8 (Z8)", ("آریزو 8", "arrizo 8", "arizo 8")),
    ("Fownix", "FX", ("فونیکس fx", "fownix fx")),
    ("Geely", "Emgrand X7", ("امگرند x7", "emgrand x7")),
    ("Geely", "Emgrand 7", ("امگرند 7", "emgrand 7")),
    ("Kia", "Cerato-Assembled", ("سراتو", "cerato")),
    ("Kia", "Sorento", ("سورنتو", "sorento")),
    ("Kia", "Optima", ("اپتیما", "optima")),
    ("Kia", "Soul", ("کیا سول", "kia soul")),
    ("Kia", "Sportage", ("اسپورتیج", "sportage")),
    ("Lifan", "X60", ("لیفان x60", "x60")),
    ("Lifan", "X70", ("لیفان x70", "x70")),
    ("Lifan", "620", ("لیفان 620", "lifan 620")),
    ("Lifan", "820", ("لیفان 820", "lifan 820")),
    ("MG", "GS", ("ام جی gs", "mg gs")),
    ("MG", "6", ("ام جی 6", "ام جی6", "mg6", "mg 6")),
    ("MG", "3", ("ام جی 3", "ام جی3", "mg3", "mg 3")),
    ("Peugeot", "2008", ("پژو 2008", "پژو2008", "peugeot 2008")),
    ("Renault", "Tondar 90", ("تندر 90", "ال 90", "tondar 90", "l90")),
    ("Renault", "Captur", ("کپچر", "captur")),
    ("Renault", "Sandero-Stepway", ("ساندرو استپ وی", "ساندرو استپوی", "sandero stepway", "stepway")),
    ("Renault", "Sandero", ("ساندرو", "sandero")),
    ("Renault", "Talisman", ("تالیسمان", "talisman")),
    ("Beijing", "U5 plus", ("یو5 پلاس", "یو 5 پلاس", "u5 پلاس", "u5 plus", "بیجینگ u5", "بیجینگ یو5", "beijing u5")),
    ("Changan", "CS-55-plus", ("cs55 پلاس", "cs 55 پلاس", "cs55 plus", "cs55plus")),
    ("Changan", "cs55 assembled", ("cs55 مونتاژ", "cs 55 مونتاژ", "cs55 assembled")),
    ("Changan", "CS35-Assembled", ("cs35", "cs 35", "چانگان cs35")),
    ("Farda", "SX5", ("فردا sx5", "sx5")),
    ("Farda", "Suba M4", ("سوبا m4", "فردا m4", "سوبا ام 4", "suba m4")),
    ("Farda", "T5", ("فردا t5", "فردا تی 5", "farda t5")),
    ("Fidelity", "elite", ("فیدلیتی الیت", "fidelity elite")),
    ("Fidelity", "prestige", ("فیدلیتی پرستیژ", "fidelity prestige")),
    ("Sahand", "s", ("سهند اس", "سهند s", "sahand s")),
    ("Suzuki", "ciaz", ("سیاز", "ciaz")),
    ("Tigard", "Tissan S05", ("تیگارد", "tigard", "s05")),
    ("Toyota", "Camry", ("کمری", "camry")),
    ("Besturn", "B30", ("بسترن b30", "بسترن", "besturn b30", "b30")),
    ("Brilliance", "H320", ("برلیانس h320", "h320", "برلیانس 320")),
    ("Citroen", "C5", ("سیتروئن c5", "سیتروئن سی 5", "citroen c5")),
    ("GAC", "Trumpchi GA3S", ("ga3s", "ترامپچی", "trumpchi")),
    ("Great Wall", "Haval M4", ("هاوال m4", "هاوال ام 4", "haval m4")),
    ("Honda", "Accord", ("آکورد", "accord")),
    ("Hongqi", "EQM5", ("eqm5", "هونگچی")),
    ("KGM", "Tivoli-Assembled", ("تیوولی مونتاژ", "تیولی مونتاژ", "tivoli assembled")),
    ("KGM", "Tivoli", ("تیوولی", "تیولی", "tivoli")),
    ("Lexus", "NX-Hybrid", ("لکسوس nx", "nx هیبرید", "lexus nx", "nx hybrid")),
    ("Max Motor", "kalut", ("کالوت", "kalut")),
    ("Mitsubishi", "ASX", ("میتسوبیشی asx", "asx")),
    ("Mitsubishi", "Lancer", ("لنسر", "lancer")),
    ("Reera", "EF7P", ("ریرا", "reera")),
    ("SWM", "G01", ("swm g01", "اس دبلیو ام g01", "g01")),
    ("Venucia", "D60 plus", ("ونوسیا d60", "d60 پلاس", "d60 plus", "ونوسیا")),
    ("Volkswagen", "Golf", ("گلف", "golf")),
    ("Volkswagen", "Passat", ("پاسات", "passat")),
    ("Xtrim", "LX (SX)", ("اکستریم lx", "اکستریم sx", "xtrim lx", "xtrim")),
    ("Zotye", "Ario", ("آریو", "زوتی آریو", "ario")),
)

# THE FOUR WHOSE MODEL TWO MAKES WRITE (2026-11-27, the owner's choice on a
# measurement, B3): Dignity's and Fidelity's «Prime», JAC's and Haima's «S5»,
# 21 of run17's listings, left out on 2026-11-26 because the search keyed a
# model by its model alone. Each name holds its make, and the search keys
# these four by make and model («jac|s5», `search_aliases`), so «جک اس 5» is
# JAC's S5 and not Haima's. Measured: each of the four named alone, and the
# API on run17 returning exactly its listings, where none was named.
_TWO_MAKES: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("Dignity", "Prime", ("دیگنیتی پرایم", "dignity prime")),
    ("Fidelity", "Prime", ("فیدلیتی پرایم", "fidelity prime")),
    ("JAC", "S5", ("جک اس 5", "جک اس5", "جک s5", "jac s5")),
    ("Haima", "S5", ("هایما اس 5", "هایما اس5", "هایما s5", "haima s5")),
)

MODELS: tuple[tuple[str, str, tuple[str, ...]], ...] = _THIRTEEN + _RUN17 + _TWO_MAKES

# Khodro45 reads a listing's Persian titles by the table for the thirteen and
# its English titles for every other model (`khodro45._make_model`).
THIRTEEN: frozenset[tuple[str, str]] = frozenset((make, model) for make, model, _ in _THIRTEEN)

# A MAKE NAMED IN THE SENTENCE (2026-11-27, the owner's choice on a
# measurement, B3). «هایما زیر ۲ میلیارد» named no model and no make and showed
# every car under two billion. Each make below is written as run17 writes it,
# every make of its 492 listings, with its names; a make's name that is a word
# of another sense is given only with a word that tells it apart («فردا
# موتورز», «مکث موتور»). The search reads a make where the query names no
# model (`caro.ranking`): a JAC is not asked for in «پراید با جک و زاپاس».
# Measured, the predictions locked first: each of the 45 asked for by its
# Persian name and by its Latin one, the make read in 39 and 41 and the make's
# one model in the rest, whose make's name is its model's; the API on run17
# returning exactly the make's listings for 45 of 45; of the 1,338 queries the
# suites hand the parser, the 17 that name a make alone read it and nothing
# else changed. The cost, measured on made sentences: «کیا» and «سهند» are
# words too, so «کیا دارن ماشین میفروشن» reads Kia and «یه ماشین برای سهند»
# reads Sahand.
MAKES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("Peugeot", ("پژو", "peugeot")),
    ("IKCO", ("ایران خودرو", "ایرانخودرو", "ikco", "iran khodro")),
    ("Saipa", ("سایپا", "saipa")),
    ("MVM", ("ام وی ام", "mvm")),
    ("KMC", ("کی ام سی", "kmc")),
    ("JAC", ("جک", "jac")),
    ("Hyundai", ("هیوندای", "هیوندا", "hyundai")),
    ("Haima", ("هایما", "haima")),
    ("Chery", ("چری", "chery")),
    ("Fidelity", ("فیدلیتی", "fidelity")),
    ("Kia", ("کیا", "kia")),
    ("Fownix", ("فونیکس", "fownix")),
    ("Lifan", ("لیفان", "lifan")),
    ("Renault", ("رنو", "renault")),
    ("Dignity", ("دیگنیتی", "dignity")),
    ("Lamari", ("لاماری", "lamari")),
    ("Farda", ("فردا موتورز", "farda")),
    ("MG", ("ام جی", "mg")),
    ("Dongfeng", ("دانگ فنگ", "دانگفنگ", "دونگ فنگ", "dongfeng")),
    ("Geely", ("جیلی", "geely")),
    ("Changan", ("چانگان", "changan")),
    ("Atlas", ("اطلس", "atlas")),
    ("Mazda", ("مزدا", "mazda")),
    ("Tigard", ("تیگارد", "tigard")),
    ("Sahand", ("سهند", "sahand")),
    ("Suzuki", ("سوزوکی", "suzuki")),
    ("Toyota", ("تویوتا", "toyota")),
    ("Volkswagen", ("فولکس واگن", "فولکس", "volkswagen")),
    ("KGM", ("کی جی ام", "سانگ یانگ", "سانگیانگ", "kgm", "ssangyong")),
    ("Mitsubishi", ("میتسوبیشی", "mitsubishi")),
    ("Beijing", ("بیجینگ", "بی جینگ", "beijing", "baic")),
    ("Great Wall", ("گریت وال", "هاوال", "great wall", "haval")),
    ("Honda", ("هوندا", "honda")),
    ("Lexus", ("لکسوس", "lexus")),
    ("Xtrim", ("اکستریم", "xtrim")),
    ("GAC", ("جی ای سی", "gac")),
    ("Max Motor", ("مکث موتور", "max motor")),
    ("Reera", ("ریرا", "reera")),
    ("Hongqi", ("هونگچی", "hongqi")),
    ("Brilliance", ("برلیانس", "brilliance")),
    ("SWM", ("اس دبلیو ام", "swm")),
    ("Citroen", ("سیتروئن", "citroen")),
    ("Venucia", ("ونوسیا", "venucia")),
    ("Besturn", ("بسترن", "besturn")),
    ("Zotye", ("زوتی", "zotye")),
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
#     read as they were), and the spoken copula «ه» and «ست» («ماشینم پرایده»,
#     «تیباست»);
#   - nor where «تندر», «شهر» or «آباد» is the next word, or «تهران» or «تندر»
#     the word before: Renault's «پارس تندر» and «تندر پارس», and the places
#     «شاهین شهر», «پارس آباد» and «تهران پارس».
#
# Read so, 8 of 8, 4 of 5, 5 of 5 and 5 of 5, and 29 of 29. The endings and the
# «و» were found after the owner's first choice, which read 24 of 27 such true
# forms as no model, and the owner chose them on the second measurement: 27 of
# 27 kept, and 9 of 10 words that hold a name and are none cleared («پارسال»,
# «پارسیان», «پارسا», «سمندر»). The same question was measured in D84's round
# and left then. Left: «پارسی» is Peugeot's Pars, «ی» being an ending, and so,
# since the copula, are «پارسه» (Persepolis) and «شاهینه» Shahin, as they were
# before the rule. The copula was the owner's choice of 2026-11-20, on the
# night's measurement: «ماشینم پرایده», «تیباست», «سمنده», «دناست» and «یه پژو
# پارسه» had named no model since the rule, where they had before it, and
# nothing else the suites hand either reader reads differently. «تندر»
# as the word before was the owner's choice of the same night, measured, the
# predictions locked first: right on 7 of 7 titles and 3 of 3 queries with
# the words the other way round («تندر پارس رنو»), where the rule was right on
# none, and nothing else read differently. A name of digits alone is found
# anywhere, as it was; the search keeps its own rule for those
# (`caro.ranking._names_model`).
_LETTER = r"[^\W\d_]"
_BEFORE = r"(?:(?<!" + _LETTER + r")|(?<=(?<!" + _LETTER + r")و))"
_ENDING = r"(?:ی|یی|م|ت|ش|مو|تو|شو|مون|تون|شون|مان|تان|شان|ها|های|هایی|ه|ست)?"
_NOT_A_MODEL_AFTER = re.compile(r"\s*(?:تندر|شهر|آباد)(?!\w)")
_NOT_A_MODEL_BEFORE = re.compile(r"(?:تهران|تندر)\s*$")

# A LATIN NAME IS READ IN CAPITALS TOO (2026-11-26, the owner's choice on a
# measurement, M2kc). The table writes its Latin names in lower case and the
# text was compared as written, so «pride زیر ۵۰۰ میلیون» named Pride and
# «Pride زیر ۵۰۰ میلیون» nothing, and the listing parser read «tiba 2» and not
# «TIBA 2». Latin letters are compared case-folded, A-Z as a-z; no other
# letter is touched. Measured, the predictions locked first: six queries
# naming the thirteen in capitals, none named today, six so; none of the
# 1,338 queries the suites hand the search read differently; one of the 178
# texts they hand the listing parser, «Pars» (Peugeot Pars, a page's model
# whose make the page gives, which reads as it did).
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")

# A NAME OF THE HUNDRED THAT ENDS IN A NUMBER IS NO NAME WHERE THE NUMBER RUNS
# ON (2026-11-26, with the hundred): «مزدا 3» is not in «مزدا 323», nor «ام جی 3»
# in «ام جی 350», each another model. Held to the hundred's names, measured so:
# for every name it found «پژو206» in «پژو۲۰۶۹», which D83's rows pin as a name
# matched beside a digit, and it reads so still.
_RUNS_ON = frozenset(n for _make, _model, ns in _RUN17 + _TWO_MAKES for n in ns if n[-1].isdigit())


def names(text: str, name: str) -> bool:
    """Does `text` hold `name` as a model's name? Both as the reader
    normalizes them, Latin letters case-folded."""
    text, name = text.translate(_ASCII_LOWER), name.translate(_ASCII_LOWER)
    if name.isdigit():
        return name in text
    runs_on = r"(?!\d)" if name in _RUNS_ON else ""
    for m in re.finditer(_BEFORE + re.escape(name) + runs_on + _ENDING + r"(?!" + _LETTER + ")",
                         text):
        if _NOT_A_MODEL_AFTER.match(text, m.end()):
            continue
        if _NOT_A_MODEL_BEFORE.search(text, 0, m.start()):
            continue
        return True
    return False


def search_aliases() -> dict[str, tuple[str, ...]]:
    """The search's view: a model's name lower-cased, and the names it is
    written by. A model two makes write is keyed by its make and model,
    «jac|s5», which a listing matches by both (`caro.ranking._model_matches`)."""
    written: dict[str, int] = {}
    for _make, model, _names in MODELS:
        written[model.lower()] = written.get(model.lower(), 0) + 1
    return {(f"{make}|{model}" if written[model.lower()] > 1 else model).lower(): names
            for make, model, names in MODELS}
