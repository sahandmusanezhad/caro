"""A six-digit code from an authenticator app, for the operator's login (O1).

The owner chose it on 2026-10-30 (docs/ACCOUNTS_AND_PAYMENT.md, «The
operator's login»). It is TOTP, RFC 6238, as every authenticator app computes
it: HMAC-SHA1 of the number of 30-second steps since the epoch, under a secret
the app and the deployment share, cut to six digits. The secret is
`CARO_ADMIN_TOTP_SECRET`, in base32 -- the form an app asks for when a key is
typed in rather than scanned -- and at least 128 bits, as RFC 4226 requires.

What a code is accepted for, and what it is not:

- the step before, the step now and the step after, because a phone's clock
  is not the server's; nothing further;
- once. A code is never accepted for a step at or before the last one that
  was (RFC 6238, 5.2), so a code read over a shoulder or out of a log is
  already spent. That memory is the process's, like the rate limiter's in
  security.py, and says so: a serverless deployment runs several processes,
  and in each of them a spent code is spent for the 90 seconds it lives;
- typed in Persian or Arabic-Indic digits, it is read as its digits, since
  the admin page is a Persian page on a Persian keyboard.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import struct
import threading
import time
from typing import Callable

STEP = 30
DIGITS = 6
WINDOW = 1
MIN_KEY_BYTES = 16          # RFC 4226, R6: the shared secret MUST be at least 128 bits
_BASE32 = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ234567")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")


class SecretError(ValueError):
    """The configured secret is not a base32 key of at least 128 bits."""


def decode_secret(raw: str) -> bytes:
    """The key in a base32 secret as an app shows it: any case, spaces and
    padding allowed. Raises SecretError rather than guessing."""
    s = "".join(raw.split()).upper().rstrip("=")
    if not s or not set(s) <= _BASE32:
        raise SecretError("not base32")
    try:
        key = base64.b32decode(s + "=" * (-len(s) % 8))
    except (ValueError, binascii.Error) as e:
        raise SecretError("not base32") from e
    if len(key) < MIN_KEY_BYTES:
        raise SecretError(f"{len(key) * 8} bits, under {MIN_KEY_BYTES * 8}")
    return key


def code_at(key: bytes, counter: int, digits: int = DIGITS) -> str:
    """RFC 4226's HOTP of `counter`, which TOTP calls with the step number."""
    mac = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = mac[-1] & 0x0F
    value = (struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF) % 10 ** digits
    return str(value).zfill(digits)


class Verifier:
    """Checks codes against one key, each step's code at most once."""

    def __init__(self, clock: Callable[[], float] = time.time):
        self.clock = clock
        self._last = -1
        self._lock = threading.Lock()

    def check(self, key: bytes, code: str | None) -> bool:
        typed = (code or "").strip().translate(_DIGITS)
        if len(typed) != DIGITS or not (typed.isascii() and typed.isdigit()):
            return False
        now = int(self.clock() // STEP)
        with self._lock:
            for step in range(now - WINDOW, now + WINDOW + 1):
                if step > self._last and hmac.compare_digest(code_at(key, step), typed):
                    self._last = step
                    return True
        return False

    def forget(self) -> None:
        with self._lock:
            self._last = -1
