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
