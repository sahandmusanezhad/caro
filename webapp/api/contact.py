"""The contact inbox: one append-only file, and a token that fails closed.

Three properties, and each of them is a decision rather than an accident.

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
"""

from __future__ import annotations

import json
import os
import re
import secrets
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent.parent
INBOX = ROOT / "data" / "inbox"
MESSAGES = INBOX / "messages.jsonl"

router = APIRouter()

_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(?:\.[^@\s.]+)+$")


class Message(BaseModel):
    name: str = Field(min_length=2, max_length=80)
    email: str = Field(min_length=5, max_length=120)
    subject: str = Field(min_length=2, max_length=120)
    body: str = Field(min_length=10, max_length=4000)


@router.post("/api/contact")
def submit(msg: Message) -> dict:
    """Accept one message. Returns the reference the sender can quote back."""
    if not _EMAIL.match(msg.email.strip()):
        raise HTTPException(422, "نشانی ایمیل معتبر نیست")

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
    INBOX.mkdir(parents=True, exist_ok=True)
    with MESSAGES.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    return {"ok": True, "ref": ref,
            "fa": "پیام ثبت شد. شماره‌ی پیگیری را نگه دار."}


def _authorised(token: str | None) -> bool:
    """Constant-time compare against a token that must actually be set."""
    expected = os.environ.get("CARO_ADMIN_TOKEN", "")
    if not expected or not token:
        return False
    return secrets.compare_digest(token, expected)


@router.get("/api/admin/messages")
def inbox(x_admin_token: str | None = Header(default=None)) -> dict:
    """Everything received, newest first. Refuses when no token is configured."""
    if not _authorised(x_admin_token):
        # The same 401 whether the token was wrong or was never configured.
        # Telling an unauthenticated caller which of the two it is hands them
        # the one fact they came for.
        raise HTTPException(401, "دسترسی مدیریت تأیید نشد")

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
    single boolean it is, with nothing derived from the token itself.
    """
    return {"configured": bool(os.environ.get("CARO_ADMIN_TOKEN", ""))}
