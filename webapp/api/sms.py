"""Who sends a seller's login code: one interface, and for now only a fake.

The owner chooses the provider later (docs/SELLER_LISTINGS.md, «What the
owner gives»); the login is built against this until then. A provider is
anything with `send(phone, text) -> bool`, True when the message was handed
over. The real one will read its key from the environment, like every key
here, and be tried by the owner on the owner's own number first.

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

import os
import sys
from typing import Protocol


class Provider(Protocol):
    name: str

    def send(self, phone: str, text: str) -> bool: ...


class FakeProvider:
    name = "fake"

    def __init__(self) -> None:
        self.outbox: list[tuple[str, str]] = []

    def send(self, phone: str, text: str) -> bool:
        self.outbox.append((phone, text))
        if os.environ.get("CARO_SMS_FAKE_ECHO", "").strip() == "1":
            print(f"[fake SMS, nothing sent] {phone}: {text}", file=sys.stderr)
        return True


FAKE = FakeProvider()


def state() -> str:
    """off, fake, or refused (the fake asked for in front of a Postgres
    store, or a provider this code does not have)."""
    name = os.environ.get("CARO_SMS_PROVIDER", "").strip().lower()
    if not name:
        return "off"
    if name == "fake" and os.environ.get("DATABASE_URL", "").strip().lower().startswith("sqlite:"):
        return "fake"
    return "refused"


def provider() -> Provider | None:
    return FAKE if state() == "fake" else None
