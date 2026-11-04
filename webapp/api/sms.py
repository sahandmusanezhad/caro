"""Who sends a seller's login code: one interface, a fake, and Kavenegar.

A provider is anything with `send(phone, text, code) -> bool`, True when the
message was handed over; `code` is the six digits alone, for a provider that
fills a template of its own. The owner chooses the provider
(docs/SELLER_LISTINGS.md, «What the owner gives»); Kavenegar is the one the
plan proposes (phase 2), and is built here. Its key is read from the
environment, like every key here, and it is tried by the owner on the
owner's own number first.

**Kavenegar** (CARO_SMS_PROVIDER=kavenegar). CARO_SMS_KAVENEGAR_KEY is the
account's API key, which Kavenegar puts in the path of every request. With
CARO_SMS_KAVENEGAR_TEMPLATE set, the code goes by verify/lookup, the
template's %token being the six digits -- the route Kavenegar keeps for
one-time codes; without it, sms/send carries the whole text, from
CARO_SMS_KAVENEGAR_SENDER's line where that is set. Handed over means
Kavenegar answered its own status 200. Anything else -- another status, a
refusal, no answer within ten seconds -- is False, and the login says the
code was not sent. Nothing about a request is raised, and one line goes to
the log, `kavenegar: not sent (status 418)` or `(TimeoutError)`: Kavenegar's
own status, or the kind of failure, and never the address, which holds the
key, nor the number.

**Off unless asked for.** With CARO_SMS_PROVIDER unset there is no provider,
and the login answers that it is off rather than pretending to send.

**The fake never stands in front of a real seller.** CARO_SMS_PROVIDER=fake
is honoured only with a SQLite store, which is a laptop's and the suites'
(the owner's choice: Postgres in production). Against Postgres it is refused,
so a fake left in a production setting turns the login off instead of
swallowing codes. It sends nothing: it keeps what it would have sent, for
the suites, and prints it to stderr only where CARO_SMS_FAKE_ECHO=1 -- a
developer logging in on a laptop.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Callable, Protocol


class Provider(Protocol):
    name: str

    def send(self, phone: str, text: str, code: str | None = None) -> bool: ...


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.outbox: list[tuple[str, str]] = []

    def send(self, phone: str, text: str, code: str | None = None) -> bool:
        self.outbox.append((phone, text))
        if os.environ.get("CARO_SMS_FAKE_ECHO", "").strip() == "1":
            print(f"[fake SMS, nothing sent] {phone}: {text}", file=sys.stderr)
        return True


FAKE = FakeProvider()


class KavenegarProvider:
    name = "kavenegar"
    BASE = "https://api.kavenegar.com/v1"

    def __init__(self, key: str, *, template: str = "", sender: str = "",
                 opener: Callable = urllib.request.urlopen, timeout: float = 10) -> None:
        self._key = key
        self.template, self.sender = template, sender
        self._open, self._timeout = opener, timeout

    def request(self, phone: str, text: str, code: str | None) -> tuple[str, dict[str, str]]:
        """The path and the form of the request that sends one message."""
        if self.template and code:
            return "verify/lookup.json", {"receptor": phone, "token": code, "template": self.template}
        form = {"receptor": phone, "message": text}
        if self.sender:
            form["sender"] = self.sender
        return "sms/send.json", form

    def send(self, phone: str, text: str, code: str | None = None) -> bool:
        path, form = self.request(phone, text, code)
        req = urllib.request.Request(
            f"{self.BASE}/{urllib.parse.quote(self._key, safe='')}/{path}",
            data=urllib.parse.urlencode(form).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"})
        try:
            with self._open(req, timeout=self._timeout) as r:
                body = json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:   # Kavenegar refuses with its status as the HTTP one
            return _not_sent(f"status {e.code}")
        except Exception as e:     # noqa: BLE001 -- any failure is "not sent"
            return _not_sent(type(e).__name__)
        ret = body.get("return") if isinstance(body, dict) else None
        status = ret.get("status") if isinstance(ret, dict) else None
        if status == 200:
            return True
        return _not_sent(f"status {status}" if type(status) is int else "no status in the answer")


def _not_sent(why: str) -> bool:
    """One line for the log, with nothing of the key or the number in it."""
    print(f"kavenegar: not sent ({why})", file=sys.stderr)
    return False


def _env(name: str) -> str:
    return os.environ.get(name, "").strip()


def state() -> str:
    """off, fake, kavenegar, or refused (the fake asked for in front of a
    Postgres store, Kavenegar without its key, or a provider this code does
    not have)."""
    name = _env("CARO_SMS_PROVIDER").lower()
    if not name:
        return "off"
    if name == "fake" and _env("DATABASE_URL").lower().startswith("sqlite:"):
        return "fake"
    if name == "kavenegar" and _env("CARO_SMS_KAVENEGAR_KEY"):
        return "kavenegar"
    return "refused"


def provider() -> Provider | None:
    which = state()
    if which == "fake":
        return FAKE
    if which == "kavenegar":
        return KavenegarProvider(_env("CARO_SMS_KAVENEGAR_KEY"),
                                 template=_env("CARO_SMS_KAVENEGAR_TEMPLATE"),
                                 sender=_env("CARO_SMS_KAVENEGAR_SENDER"))
    return None
