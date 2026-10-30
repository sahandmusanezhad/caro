"""
Persian text normalisation for listing data.

The reusable half of any Iranian marketplace scraper. Adapted from the
normalisation approach in SorinFlow (Tecso-Dev/SorinFlow-DaTA-mAmager, MIT),
which solves the same problem for property listings; the numeral, separator
and amount-word handling transfers unchanged, the domain fields do not.

Nothing here touches the network. It is pure text → value, which is why it
is the part worth testing hardest: a price parsed one order of magnitude
wrong poisons every downstream estimate silently.
"""

from __future__ import annotations

import re
import unicodedata

# Persian and Arabic-Indic digits both appear in the wild, often in the same
# listing, because sellers copy-paste between keyboards.
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# Thousands separators sellers actually type: Latin comma, Persian comma,
# Arabic thousands separator, apostrophe, and the Persian decimal mark.
_SEPARATORS = "٬،,'`"

ZWNJ = "‌"


def normalize(text: str) -> str:
    """Fold everything that is the same character wearing a different hat."""
    if not text:
        return ""
    s = unicodedata.normalize("NFKC", text)
    s = s.translate(_DIGITS)
    s = (s.replace("ي", "ی").replace("ك", "ک")
          .replace("ۀ", "ه").replace("ة", "ه")
          .replace(ZWNJ, " ").replace("‏", "").replace("‎", ""))
    return re.sub(r"\s+", " ", s).strip()


def digits_only(text: str) -> str:
    return re.sub(rf"[{re.escape(_SEPARATORS)}\s]", "", normalize(text))


_SCALE_WORDS = {
    "میلیارد": 1_000_000_000, "ملیارد": 1_000_000_000,
    "میلیون": 1_000_000, "ملیون": 1_000_000,
    "هزار": 1_000,
}

_TOMAN_WORDS = ("تومان", "تومن", "ت")
_RIAL_WORDS = ("ریال",)


def parse_price(text: str, *, assume_toman: bool = True) -> int | None:
    """Listing price → integer.

    Handles «۱٬۴۸۰٬۰۰۰٬۰۰۰ تومان», «۱ میلیارد و ۴۸۰ میلیون», «۱.۵ میلیارد»,
    «۱۴۸۰ میلیون», and the bare digit strings Divar puts in its structured
    fields.

    Returns None for «توافقی» / «تماس بگیرید» rather than guessing — a
    negotiable price is missing data, not a zero, and the distinction
    survives all the way to the appraiser.
    """
    s = normalize(text)
    if not s:
        return None
    if re.search(r"(توافقی|تماس|توافق|رایگان|مجانی)", s):
        return None

    is_rial = any(w in s for w in _RIAL_WORDS)

    # «۱ میلیارد و ۴۸۰ میلیون» — the compound form, most common in speech
    m = re.search(r"(\d+(?:\.\d+)?)\s*(میلیارد|ملیارد)\s*(?:و\s*)?"
                  r"(?:(\d+(?:\.\d+)?)\s*(میلیون|ملیون)?)?", s)
    if m:
        total = float(m.group(1)) * 1_000_000_000
        if m.group(3):
            tail = float(m.group(3))
            # A bare tail after "میلیارد" is millions by convention.
            total += tail * 1_000_000
        return int(total / 10) if is_rial else int(total)

    m = re.search(r"(\d+(?:\.\d+)?)\s*(میلیون|ملیون|هزار)", s)
    if m:
        total = float(m.group(1)) * _SCALE_WORDS[m.group(2)]
        return int(total / 10) if is_rial else int(total)

    raw = re.search(rf"[\d{re.escape(_SEPARATORS)}]{{3,}}", s)
    if not raw:
        return None
    n = digits_only(raw.group(0))
    if not n.isdigit():
        return None
    v = int(n)
    if is_rial:
        v //= 10
    return v if v > 0 else None


def parse_mileage_km(text: str) -> int | None:
    """«۸۰ هزار کیلومتر» · «۱۲۰,۰۰۰ کیلومتر» · «کارکرد ۴۵۰۰۰» → km.

    Divar also carries «کارکرد صفر» for unused cars, which is a real zero
    and not missing data — so it returns 0, not None.
    """
    s = normalize(text)
    if not s:
        return None
    if re.search(r"(صفر کیلومتر|کارکرد صفر|صفرکیلومتر)", s):
        return 0

    m = re.search(r"(\d+(?:\.\d+)?)\s*هزار", s)
    if m:
        return int(float(m.group(1)) * 1000)

    raw = re.search(rf"[\d{re.escape(_SEPARATORS)}]+", s)
    if not raw:
        return None
    n = digits_only(raw.group(0))
    if not n.isdigit():
        return None
    v = int(n)
    # A bare small number next to a km label is thousands: "کارکرد ۸۰" means
    # 80,000 km, not 80. Cars with genuinely two-digit mileage are new, and
    # those say «صفر».
    if v < 1000 and re.search(r"(کارکرد|کیلومتر|کیلومتر|km)", s):
        return v * 1000
    return v


def parse_year_jalali(text: str) -> int | None:
    """«مدل ۱۳۹۹» · «۹۹» · «مدل ۲۰۱۸» → Jalali year.

    Gregorian years appear on imported cars and are converted, because a
    corpus mixing 1399 and 2018 in one column silently breaks every
    year-based comparison.
    """
    s = normalize(text)
    m = re.search(r"(1[34]\d{2})", s)
    if m:
        return int(m.group(1))
    m = re.search(r"(19\d{2}|20\d{2})", s)
    if m:
        return int(m.group(1)) - 621
    m = re.search(r"\b(\d{2})\b", s)
    if m:
        y = int(m.group(1))
        # Two-digit years are 13xx unless that lands in the future.
        return 1300 + y if y >= 60 else 1400 + y
    return None


# ---------------------------------------------------------------------------
# Provinces
# ---------------------------------------------------------------------------
#
# Iran has thirty-one, and that closed set is the whole reason this module
# can validate a location instead of trusting one. A positional rule that
# takes "the line after the odometer" will one day take the price, and the
# only thing standing between that and a corpus recording «۳۵۰٬۰۰۰٬۰۰۰» as a
# province is a membership test the price cannot pass.
#
# NOT a geography. There is no city list here on purpose: cities are open,
# they change, and a list of them would be a permanent invitation to treat
# absence-from-the-list as absence-from-Iran. The city is kept verbatim by the
# caller; only the province — the part that can be checked — is ever promoted
# to a field that something downstream will compare on.
#
# One exception, closed and named below: the thirteen provinces whose capital
# carries the province's own name. That is a fact about thirteen of the
# thirty-one, not a list of cities, and it cannot be incomplete.
PROVINCES: tuple[str, ...] = (
    "آذربایجان شرقی", "آذربایجان غربی", "اردبیل", "اصفهان", "البرز", "ایلام",
    "بوشهر", "تهران", "چهارمحال و بختیاری", "خراسان جنوبی", "خراسان رضوی",
    "خراسان شمالی", "خوزستان", "زنجان", "سمنان", "سیستان و بلوچستان", "فارس",
    "قزوین", "قم", "کردستان", "کرمان", "کرمانشاه", "کهگیلویه و بویراحمد",
    "گلستان", "گیلان", "لرستان", "مازندران", "مرکزی", "هرمزگان", "همدان",
    "یزد",
)

# A province as a source spells it, where that is not the spelling above —
# each seen on a page, and named here with where. A closed table, not a
# folding rule: ک and گ are different letters, and making them one would make
# words equal that are not. Read as the province it names, never as itself.
#
#   «کهکیلویه و بویراحمد»   bama:4flyapjw, «یاسوج، کهکیلویه و بویراحمد»,
#                            probed 2026-10-11 — run14's one listing with no
#                            province
PROVINCE_SPELLINGS: dict[str, str] = {
    "کهکیلویه و بویراحمد": "کهگیلویه و بویراحمد",
}

_PROVINCE_BY_NORM = {normalize(p): p for p in PROVINCES}
_PROVINCE_BY_NORM.update(
    {normalize(seen): PROVINCES[PROVINCES.index(meant)]
     for seen, meant in PROVINCE_SPELLINGS.items()})

# The provinces whose capital is named as the province is, from the table of
# all thirty-one (Wikipedia, «Provinces of Iran», read 2026-10-10). Alborz's
# capital is Karaj, Golestan's is Gorgan, and eighteen more differ the same
# way; those are not here, and neither is any other city.
SAME_NAME_CAPITALS: frozenset[str] = frozenset({
    "اردبیل", "اصفهان", "ایلام", "بوشهر", "تهران", "زنجان", "سمنان",
    "قزوین", "قم", "کرمان", "کرمانشاه", "همدان", "یزد",
})

_CAPITAL_BY_NORM = {normalize(c): c for c in SAME_NAME_CAPITALS}

# The eighteen other capitals, each with the province it is the capital of,
# from the same table. The owner chose on 2026-10-30 that a capital gives its
# province whatever its name (run17 held 236 of 492 rows with none, Karaj,
# Shiraz, Mashhad, Ahvaz, Bandar Abbas, Tabriz and Sari among them); any other
# city still gives none. Two are written with a space as well as without.
OTHER_CAPITALS: dict[str, str] = {
    "تبریز": "آذربایجان شرقی", "ارومیه": "آذربایجان غربی", "کرج": "البرز",
    "شهرکرد": "چهارمحال و بختیاری", "بیرجند": "خراسان جنوبی",
    "مشهد": "خراسان رضوی", "بجنورد": "خراسان شمالی", "اهواز": "خوزستان",
    "زاهدان": "سیستان و بلوچستان", "شیراز": "فارس", "سنندج": "کردستان",
    "یاسوج": "کهگیلویه و بویراحمد", "گرگان": "گلستان", "رشت": "گیلان",
    "خرم\u200cآباد": "لرستان", "خرم آباد": "لرستان", "ساری": "مازندران",
    "اراک": "مرکزی", "بندرعباس": "هرمزگان", "بندر عباس": "هرمزگان",
}
_CAPITAL_BY_NORM.update({normalize(c): p for c, p in OTHER_CAPITALS.items()})


def province_of(text: str | None) -> str | None:
    """The province named by `text`, or None — never a guess.

    Bama puts the city first, separated by the Arabic comma: «رباط کریم،
    تهران» is a city and its province, and «مشهد، خراسان رضوی، فلسطین» a city,
    its province and a district — the second shape measured on real pages on
    2026-10-06 and 2026-10-10, and missed while only the last part was read.
    So a province is read from any part AFTER the first, the last tried
    first, and never from the first: that part is the city. «تهران، آذری»
    names the city of Tehran and a district of it; whether that says which
    province is a question about the city, not something the line states.
    And a line that is only a city («کرج») yields nothing rather than the
    province it happens to sit in — inferring البرز from کرج would be this
    module asserting a geography it does not hold.

    The whole string is also tried, for a page that states the province with
    no city in front of it — but not when it is one of the thirteen capitals
    named as their province. Bama leaves the province out of the line where
    it is named as the city — «تهران، آذری», never «تهران، تهران، آذری» — and
    the district where there is none, so «کرمان» alone is the city of Kerman
    and states nothing: run15's lines (2026-10-14) hold it three times, and
    «زنجان» and «یزد» once each, and none of the other 43 lines run15 read as
    stated is a province alone. That province is known from the city, which
    is `province_from_city`'s to say.
    """
    if not text:
        return None
    s = normalize(text)
    if s in _PROVINCE_BY_NORM and s not in _CAPITAL_BY_NORM:
        return _PROVINCE_BY_NORM[s]
    parts = [p.strip() for p in re.split(r"[،,]", s) if p.strip()]
    for part in reversed(parts[1:]):
        if part in _PROVINCE_BY_NORM:
            return _PROVINCE_BY_NORM[part]
    return None


def province_from_city(text: str | None) -> str | None:
    """The province a line's city gives, when that city is one of the
    thirty-one capitals -- the thirteen named as their province is, and since
    the owner's choice of 2026-10-30 the eighteen of OTHER_CAPITALS; otherwise
    None. (What follows was written for the thirteen; for Karaj it now reads
    البرز.)

    «تهران، آذری» is the city of Tehran and a district of it, and «کرمان» the
    city of Kerman with no district: Bama leaves the province out where it is
    named as the city (`province_of`). Neither line states a province, and
    the city does not need one stated: Tehran is in Tehran. So: a line of one
    part or two, its first part, one of the thirteen. «کرج، گلشهر» and «کرج»
    stay unread — Karaj is in البرز, and knowing that would be holding a
    geography — and so does a first part that names a province whose capital
    has another name («گلستان، …», «البرز، …»): the first part is a city, and
    no city of that name is that province's capital.

    The caller records a province found this way as coming from the city,
    never as stated (`province_source`).
    """
    if not text:
        return None
    parts = [p.strip() for p in re.split(r"[،,]", normalize(text)) if p.strip()]
    if len(parts) not in (1, 2):
        return None
    return _CAPITAL_BY_NORM.get(parts[0])
