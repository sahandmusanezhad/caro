"""The publishable corpus artifact — schema, and the two guards on it.

`docs/DATA_CONTRACT.md` § *The publishable corpus artifact* is the contract;
this is its enforcement. Nothing here decides policy. It decides whether a
candidate artifact satisfies the policy already written down, and it is
importable so the test suite can assert on it without running a promotion.

Two guards, because one is not enough.

    schema guard    a forbidden key, at any nesting depth. Exact, cheap, and
                    evadable by renaming a field — which is why there are two.
    content guard   a contact identifier in any VALUE, whatever its key is
                    called, run over the SERIALIZED artifact rather than the
                    object, because a serializer that flattens a structure or
                    a field added after the check defeats an in-memory scan.

Both are advisory to nobody: `promote_corpus.py` writes no file when either
fails, and the corpus test suite fails the build.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from caro.ingest.persian import normalize

SCHEMA = "caro.corpus/1"

# Fields that carry seller-authored prose today. The contract's rule is
# semantic — "no free-form seller-authored text" — and these are instances of
# it, not the definition. A new adapter introducing `notes` or `summary` is
# covered by the content guard and belongs here the day it is written.
FORBIDDEN_KEYS = frozenset({
    "description", "desc", "title", "km_line", "kmline", "km_text",
    "notes", "note", "summary", "raw_text", "body_text", "comment",
})

# Keys that are hashes or derived values and must NOT be read as identifiers.
# Recorded so the intent survives someone widening the guard later: the line
# is authorship, not shape. A guard that flagged these would be switched off
# within a week, and then nothing would be guarded.
ALLOWED_DERIVED_KEYS = frozenset({
    "seller_fingerprint", "payload_sha", "image_phashes", "listing_id", "slug",
})

_HANDLE = re.compile(
    r"(?:t\.me/|wa\.me/|instagram\.com/|telegram\.me/|@[A-Za-z0-9_]{4,})",
    re.IGNORECASE)

# A run of digits and the separators that legitimately appear inside one.
# Deliberately does NOT span whitespace or letters: joining two unrelated
# numbers into a phone-shaped string is a false positive that would get the
# guard disabled.
_DIGIT_RUN = re.compile(r"[0-9][0-9٫٬,.‐-―-]{7,20}[0-9]")
_SEPARATORS = re.compile(r"[,.٫٬‐-―-]")


@dataclass(frozen=True)
class Violation:
    guard: str          # "schema" | "content"
    where: str          # dotted path, or a byte offset for the content guard
    what: str           # what was found, redacted to its shape
    why: str

    def __str__(self) -> str:
        return f"  [{self.guard}] {self.where}: {self.what} — {self.why}"


def _looks_like_contact(digits: str) -> str | None:
    """Iranian contact shapes, on a string that is already digits only.

    A price is not caught: Iranian prices do not lead with a zero, and a
    ten-digit rial figure starting `1` matches none of these.
    """
    if re.fullmatch(r"09\d{9}", digits):
        return "mobile"
    if re.fullmatch(r"(?:00)?989\d{9}", digits):
        return "mobile, international form"
    if re.fullmatch(r"0\d{9,10}", digits):
        return "landline with area code"
    return None


def scan_text(text: str, *, where: str = "artifact") -> list[Violation]:
    """The content guard. Runs on serialized text, not on an object.

    Normalises first — Persian and Arabic digits to ASCII, ZWNJ removed,
    `ك→ک`, `ي→ی` — so «۰۹۱۲۳۴۵۶۷۸۹» is caught exactly as `09123456789` is.
    """
    out: list[Violation] = []
    s = normalize(text)

    for m in _DIGIT_RUN.finditer(s):
        digits = _SEPARATORS.sub("", m.group(0))
        kind = _looks_like_contact(digits)
        if kind:
            out.append(Violation(
                "content", f"{where}@{m.start()}",
                f"{digits[:4]}…{digits[-2:]} ({len(digits)} digits)",
                f"reads as a contact number — {kind}"))

    for m in _HANDLE.finditer(s):
        out.append(Violation(
            "content", f"{where}@{m.start()}", m.group(0),
            "reads as a messaging handle or contact link"))

    return out


def redact(text: str) -> str:
    """Remove contact identifiers, keep everything else.

    Refusing a whole line because an identifier shares it with a real value
    was measured to cost good rows: «کارکرد ۱۲۰٬۰۰۰ — تماس ۰۹۱۲۳۴۵۶۷۸۹»
    carries a genuine, plausible odometer reading next to a phone number.
    Redacting first and parsing the remainder keeps the odometer and removes
    the only path by which the identifier's digits could become the value.
    """
    s = normalize(text)
    out, cut = [], 0
    spans = []
    for m in _DIGIT_RUN.finditer(s):
        if _looks_like_contact(_SEPARATORS.sub("", m.group(0))):
            spans.append(m.span())
    spans += [m.span() for m in _HANDLE.finditer(s)]
    for a, b in sorted(spans):
        if a < cut:
            continue
        out.append(s[cut:a])
        cut = b
    out.append(s[cut:])
    return " ".join(" ".join(out).split())


def scan_keys(obj, *, path: str = "") -> list[Violation]:
    """The schema guard. Recursive, so a forbidden key cannot hide in a nest."""
    out: list[Violation] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{path}.{k}" if path else str(k)
            if str(k).strip().lower() in FORBIDDEN_KEYS:
                out.append(Violation(
                    "schema", here, str(k),
                    "carries seller-authored prose; derive from it before "
                    "promotion and do not publish the text"))
            out += scan_keys(v, path=here)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            out += scan_keys(v, path=f"{path}[{i}]")
    return out


def validate(obj, serialized: str) -> list[Violation]:
    """Both guards. `serialized` must be the exact text that would be written.

    Taking both the object and its serialization is the point: the schema
    guard needs structure and the content guard needs the bytes, and running
    the second on the first is the mistake the contract names.
    """
    v = scan_keys(obj)
    if not isinstance(obj, dict) or obj.get("schema") != SCHEMA:
        v.append(Violation(
            "schema", "schema",
            repr(obj.get("schema") if isinstance(obj, dict) else None),
            f"a published artifact must declare schema {SCHEMA!r}"))
    for field in ("run_id", "source", "collected_on", "listings"):
        if isinstance(obj, dict) and field not in obj:
            v.append(Violation("schema", field, "missing",
                               "required by the artifact contract"))
        elif isinstance(obj, dict) and not obj.get(field):
            # `not obj.get(field)` alone called an EMPTY listings array
            # "missing", which sends a reader looking for a serialisation bug
            # when the truth is that the run published nothing. Both are
            # refusals and they are not the same refusal — the first is a
            # malformed file, the second is an honest report of an empty
            # collection, and D49's whole point is that those must not share
            # a message.
            v.append(Violation(
                "schema", field,
                "present but empty",
                "an empty corpus is not publishable — the run collected "
                "nothing that survived promotion, which is a fact about the "
                "run and not a fault in this file"))
    return v + scan_text(serialized)
