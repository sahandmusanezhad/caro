"""The contact inbox: one append-only file, and a token that fails closed.

Four properties, and each of them is a decision rather than an accident.

**It is not the corpus.** `data/inbox/` holds messages people chose to send us,
with the contact details they chose to give. That is categorically different
from a seller's phone number lifted out of an advertisement, which the data
contract forbids ever storing. The two must not share a directory, a lifecycle
or a guard: `data/corpora/` is published and scanned for contact identifiers,
this is neither published nor scanned. It is `.gitignore`d, and nothing in the
promotion path can read it.

**The admin endpoint fails closed.** With `CARO_ADMIN_TOKEN` unset there is no
token that opens it, rather than a default that does. An admin surface whose
lock is "the environment variable was not configured" is a surface with no
lock, and that mistake is invisible until it is not.

**Append-only, never a database.** A JSONL file is enough for a contact inbox
and it is honest about what it is. It also means a message cannot be silently
edited after the fact — the file grows, and what was written stays written.

**Off where the disk does not keep what is written.** A serverless function,
or a container without a volume, would accept a message, answer with a
reference, and lose the file — a receipt for nothing. Only the operator knows
which kind of disk a deployment has, so it is a setting: `CARO_INBOX=off`.
Then the inbox refuses with 503 and names a place where a message does stay.
With the setting absent the inbox is on, as it always was; and a write that
fails anyway is the same 503, never a 500 and never a reference.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import BaseModel, Field

from webapp.api.security import RateLimiter, client_address, too_many
from webapp.api.totp import SecretError, Verifier, decode_secret

ROOT = Path(__file__).resolve().parent.parent.parent
INBOX = ROOT / "data" / "inbox"
MESSAGES = INBOX / "messages.jsonl"

router = APIRouter()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")

# Where a person is sent when this deployment keeps no inbox. The repository is
# public, and an issue stays where it was written — publicly, which the page
# says before anyone writes one. It is the repository the code lives in,
# Tecso-Dev/caro; a fork starts with Issues off, so it has to be on there
# before a deployment sends anyone to it.
ELSEWHERE = "https://github.com/Tecso-Dev/caro/issues"
CLOSED_FA = ("صندوق پیام در این استقرار خاموش است، چون اینجا پیامی ماندگار "
             f"ذخیره نمی‌شود. پیامت را در GitHub Issues بنویس: {ELSEWHERE}")
UNWRITABLE_FA = ("این استقرار نتوانست پیام را ذخیره کند، پس ثبت نشد. "
                 f"پیامت را در GitHub Issues بنویس: {ELSEWHERE}")


# One address may post 5 messages in 10 minutes, and fail the admin token 10
# times in 10 minutes; per process, in memory (webapp/api/security.py says
# what that is and is not). The inbox stops taking messages at 5 MB: a file
# that only grows is a disk anyone can fill.
CONTACT_LIMIT = RateLimiter(5, 600)
ADMIN_FAILURES = RateLimiter(10, 600)
INBOX_MAX_BYTES = 5 * 1024 * 1024


def inbox_open() -> bool:
    """False when the operator has switched the inbox off with CARO_INBOX=off."""
    return os.environ.get("CARO_INBOX", "").strip().lower() != "off"


class Message(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    subject: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=10, max_length=4000)


@router.get("/api/contact/status")
def contact_status() -> dict:
    """Whether this deployment keeps messages, and where to go if it does not.

    The contact page asks before it draws a form: a form on a deployment that
    cannot keep what it receives is an invitation to write into nothing.
    """
    return {"open": inbox_open(), "elsewhere": ELSEWHERE}


@router.post("/api/contact")
def submit(msg: Message, request: Request) -> dict:
    """Accept one message. Returns the reference the sender can quote back."""
    if not inbox_open():
        raise HTTPException(503, CLOSED_FA)
    if not _EMAIL.match(msg.email.strip()):
        raise HTTPException(422, "نشانی ایمیل معتبر نیست")
    wait = CONTACT_LIMIT.hit(client_address(request))
    if wait is not None:
        raise too_many(wait)
    try:
        full = MESSAGES.exists() and MESSAGES.stat().st_size >= INBOX_MAX_BYTES
    except OSError:
        full = False
    if full:
        raise HTTPException(503, UNWRITABLE_FA)

    ref = uuid.uuid4().hex[:10]
    record = {
        "ref": ref,
        "received_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "name": msg.name.strip(),
        "email": msg.email.strip().lower(),
        "subject": msg.subject.strip(),
        "body": msg.body.strip(),
        "read": False,
    }
    try:
        INBOX.mkdir(parents=True, exist_ok=True)
        with MESSAGES.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except OSError:
        # A read-only or missing disk. The sender is told it was not kept;
        # a reference for a message that was never written would be a lie.
        raise HTTPException(503, UNWRITABLE_FA) from None

    return {"ok": True, "ref": ref,
            "fa": "پیام ثبت شد. شماره‌ی پیگیری را نگه دار."}


# The second step of the operator's login (O1, webapp/api/totp.py): with
# CARO_ADMIN_TOTP_SECRET set, the token opens nothing without a code from the
# owner's authenticator app. Unset, the token alone opens, as it did before the
# owner chose O1, so a deployment is not locked out before its secret is set;
# set but unreadable, nothing opens -- a lock that cannot be read is not taken
# off.
ADMIN_CODES = Verifier()


def second_factor() -> str:
    """"off" (no secret), "on", or "unreadable" (a secret that is not a key)."""
    raw = os.environ.get("CARO_ADMIN_TOTP_SECRET", "")
    if not raw.strip():
        return "off"
    try:
        decode_secret(raw)
    except SecretError:
        return "unreadable"
    return "on"


def _authorised(token: str | None, code: str | None = None) -> bool:
    """Constant-time compare against a token that must actually be set, then,
    where a second factor is configured, the code. The token comes first, so a
    wrong token never spends a code."""
    expected = os.environ.get("CARO_ADMIN_TOKEN", "")
    if not expected or not token:
        return False
    if not secrets.compare_digest(token, expected):
        return False
    state = second_factor()
    if state == "off":
        return True
    if state == "unreadable":
        return False
    return ADMIN_CODES.check(decode_secret(os.environ["CARO_ADMIN_TOTP_SECRET"]), code)


def require_operator(request: Request, token: str | None, code: str | None) -> None:
    """The operator's check, in one place for every operator's endpoint: the
    inbox here, and the listings sellers post (webapp/api/review.py)."""
    # An address that has failed the token ten times in ten minutes is
    # refused before the token is even compared, the right one included: a
    # guess that lands is a guess, and guessing is what is being slowed.
    addr = client_address(request)
    wait = ADMIN_FAILURES.blocked(addr)
    if wait is not None:
        raise too_many(wait)
    if not _authorised(token, code):
        ADMIN_FAILURES.hit(addr)
        # The same 401 whether the token or the code was wrong, or neither was
        # ever configured.
        # Telling an unauthenticated caller which of the two it is hands them
        # the one fact they came for.
        raise HTTPException(401, "دسترسی مدیریت تأیید نشد")


@router.get("/api/admin/messages")
def inbox(request: Request,
          x_admin_token: str | None = Header(default=None),
          x_admin_code: str | None = Header(default=None)) -> dict:
    """Everything received, newest first. Refuses when no token is configured."""
    require_operator(request, x_admin_token, x_admin_code)

    if not MESSAGES.exists():
        return {"count": 0, "messages": []}

    out = []
    for line in MESSAGES.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            # One malformed line must not hide every other message.
            out.append({"ref": "?", "received_at": "", "name": "",
                        "email": "", "subject": "(رکورد ناخوانا)",
                        "body": line[:200], "read": False})
    out.reverse()
    return {"count": len(out), "messages": out}


@router.get("/api/admin/status")
def status() -> dict:
    """Whether an admin token is configured at all. Reveals no secret.

    The admin page needs to distinguish "your token is wrong" from "this
    deployment has no admin token", and it cannot learn that from a 401 —
    deliberately, since the 401 refuses to say. So it is published here as the
    single boolean it is, with nothing derived from the token itself; and
    beside it whether the page must ask for a code, which says nothing of the
    secret either.
    """
    return {"configured": bool(os.environ.get("CARO_ADMIN_TOKEN", "")),
            "second_factor": second_factor()}
