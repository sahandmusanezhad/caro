"""The seller's login (A1): a code by SMS, then a session in a cookie.

Step 2 of docs/SELLER_LISTINGS.md, under the rules ACCOUNTS_AND_PAYMENT set
for A1. Each rule, and where it is held:

**A code is six digits, lives two minutes, and dies after five wrong tries.**
It is kept only as a keyed hash (`Store.key`), a new one replaces the one
before, and it is accepted once: the right answer deletes it.

**The limits are in the store**, because a message costs money and a
serverless deployment runs many processes: per phone 3 codes in 15 minutes
and 6 a day, per address 6 an hour and 20 a day, 500 a day in all, and per
address 20 wrong codes an hour (`LIMITS`). They are proposals; the owner can
move any of them.

**The same answer whether the number has an account or not.** Asking for a
code never looks at `accounts`, so the endpoint cannot be used to learn who
is a member. A wrong code, a dead one and one never sent get one answer too.

**The session** is 256 random bits in `caro_session` -- HttpOnly, Secure,
SameSite=Lax, Path=/ -- kept in the store only as its SHA-256, new at every
login, deleted at logout, and refused and deleted after thirty idle days.

**Every change is a POST whose Origin is the site's own**: one of
CARO_SITE_ORIGINS, or, where the deploy holder has set none, the host the
request came to. A browser always sends Origin with a POST, and another site
cannot write ours into it.

An account keeps its number and nothing else; «حذف حساب» deletes it and,
by the store's cascade, every session and listing under it.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import re
import secrets
import time
from typing import Iterator
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from webapp.api import sms
from webapp.api.security import client_address, too_many
from webapp.api.store import Store, StoreError, open_store, phone_09

router = APIRouter()

COOKIE = "caro_session"
CODE_SECONDS = 120
CODE_TRIES = 5
SESSION_IDLE_S = 30 * 86400
SEEN_EVERY_S = 300          # a session's last use is written at most this often
TEMPLATE = "کد ورود کارو: {code}"
LIMITS = {
    "code_phone": ((3, 15 * 60), (6, 86400)),
    "code_address": ((6, 3600), (20, 86400)),
    "code_all": ((500, 86400),),
    "wrong_address": ((20, 3600),),
}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")

# The suites set this; everything else reads the time through it.
CLOCK = time.time

OFF_FA = {
    "STORE_OFF": "ورود فروشنده‌ها در این استقرار روشن نیست: جایی برای نگه‌داشتن حساب‌ها تعیین نشده است.",
    "STORE_UNUSABLE": "ورود فروشنده‌ها فعلاً در دسترس نیست: پایگاه داده‌ی این استقرار باز نشد.",
    "SMS_OFF": "ورود فروشنده‌ها در این استقرار روشن نیست: سرویس پیامک هنوز تعیین نشده است.",
}
PHONE_FA = "شماره‌ی همراه را به شکل ۰۹۱۲۳۴۵۶۷۸۹ بنویس."
WRONG_FA = "کد درست نیست یا دیگر اعتبار ندارد. کد تازه بگیر."
SMS_FAILED_FA = "پیامک فرستاده نشد. کمی بعد دوباره امتحان کن."
ORIGIN_FA = "این درخواست از خود سایت کارو نیامده است."
NO_SESSION_FA = "وارد نشده‌ای، یا نشستت به پایان رسیده است."

_migrated: set[str] = set()


def _off(code: str) -> HTTPException:
    return HTTPException(503, {"code": code, "fa": OFF_FA[code]})


def the_store() -> Iterator[Store]:
    """The store for one request, closed after it. Migrated by the first
    request of each process, not by every one."""
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise _off("STORE_OFF")
    try:
        st = open_store(url, clock=lambda: CLOCK(), migrate=url not in _migrated)
    except StoreError:
        raise _off("STORE_UNUSABLE") from None
    _migrated.add(url)
    try:
        yield st
    finally:
        st.close()


def same_origin(request: Request) -> None:
    origin = request.headers.get("origin", "").strip().rstrip("/")
    allowed = [o.strip().rstrip("/") for o in os.environ.get("CARO_SITE_ORIGINS", "").split(",")
               if o.strip()]
    if allowed:
        ok = origin in allowed
    else:
        ok = bool(origin) and urlsplit(origin).netloc == request.headers.get("host", "")
    if not ok:
        raise HTTPException(403, ORIGIN_FA)


def _sha(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _code_key(st: Store, phone_key: str, code: str) -> str:
    return st.key("code", f"{phone_key}:{code}")


def _cookie(response: Response, token: str | None) -> None:
    if token is None:
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    else:
        response.set_cookie(COOKIE, token, max_age=SESSION_IDLE_S, path="/", secure=True,
                            httponly=True, samesite="lax")


def session_of(request: Request, st: Store) -> dict | None:
    """The live session the request's cookie names, with its account's phone;
    None, and the session deleted, after thirty idle days."""
    token = request.cookies.get(COOKIE)
    if not token:
        return None
    s = st.row("SELECT s.id, s.account_id, s.seen_at, a.phone FROM sessions s "
               "JOIN accounts a ON a.id = s.account_id WHERE s.token_sha256 = ?", (_sha(token),))
    if s is None:
        return None
    now = st.now()
    if now - int(s["seen_at"]) > SESSION_IDLE_S:
        st.execute("DELETE FROM sessions WHERE id = ?", (s["id"],))
        return None
    if now - int(s["seen_at"]) > SEEN_EVERY_S:
        st.execute("UPDATE sessions SET seen_at = ? WHERE id = ?", (now, s["id"]))
    return s


class PhoneIn(BaseModel):
    phone: str = Field(min_length=1, max_length=40)


class LoginIn(BaseModel):
    phone: str = Field(min_length=1, max_length=40)
    code: str = Field(min_length=1, max_length=12)


@router.get("/api/account/status")
def account_status() -> dict:
    """Whether a seller can log in on this deployment, and if not which part
    is missing. Nothing in it is a secret or is derived from one."""
    url = os.environ.get("DATABASE_URL", "").strip()
    store = "off"
    if url:
        try:
            open_store(url, migrate=False).close()
            store = "on"
        except StoreError:
            store = "unusable"
    return {"store": store, "sms": sms.state()}


@router.post("/api/account/code", dependencies=[Depends(same_origin)])
def send_code(body: PhoneIn, request: Request, st: Store = Depends(the_store)) -> dict:
    """Sends a code to a mobile number. The answer is the same for a number
    with an account and one without."""
    provider = sms.provider()
    if provider is None:
        raise _off("SMS_OFF")
    phone = phone_09(body.phone)
    if phone is None:
        raise HTTPException(422, PHONE_FA)
    pk, ak = st.key("phone", phone), st.key("address", client_address(request))
    tries = (("code_phone", pk), ("code_address", ak), ("code_all", "all"))
    code = None
    with st.transaction():
        st.lock("code")
        waits = [w for kind, who in tries if (w := st.blocked(kind, who, LIMITS[kind])) is not None]
        if not waits:
            for kind, who in tries:
                st.record(kind, who)
            st.execute("DELETE FROM login_codes WHERE phone_key = ?", (pk,))
            code, now = f"{secrets.randbelow(10 ** 6):06d}", st.now()
            st.insert("INSERT INTO login_codes (phone_key, code_key, created_at, expires_at) "
                      "VALUES (?, ?, ?, ?)", (pk, _code_key(st, pk, code), now, now + CODE_SECONDS))
    if waits:
        raise too_many(max(waits))
    if not provider.send(phone, TEMPLATE.format(code=code)):
        st.execute("DELETE FROM login_codes WHERE phone_key = ?", (pk,))
        raise HTTPException(503, SMS_FAILED_FA)
    return {"sent": True, "seconds": CODE_SECONDS}


@router.post("/api/account/login", dependencies=[Depends(same_origin)])
def login(body: LoginIn, request: Request, response: Response,
          st: Store = Depends(the_store)) -> dict:
    """The code answered: a session, and an account if the number had none."""
    phone = phone_09(body.phone)
    if phone is None:
        raise HTTPException(422, PHONE_FA)
    typed = body.code.strip().translate(_DIGITS)
    pk, ak = st.key("phone", phone), st.key("address", client_address(request))
    token, created = None, False
    with st.transaction():
        st.lock(f"login:{pk}")
        wait = st.blocked("wrong_address", ak, LIMITS["wrong_address"])
        if wait is None:
            row = st.row("SELECT id, code_key, expires_at, wrong_tries FROM login_codes "
                         "WHERE phone_key = ? ORDER BY id DESC", (pk,))
            now = st.now()
            if (row is not None and int(row["expires_at"]) > now and re.fullmatch(r"\d{6}", typed)
                    and hmac.compare_digest(row["code_key"], _code_key(st, pk, typed))):
                st.execute("DELETE FROM login_codes WHERE phone_key = ?", (pk,))
                account = st.row("SELECT id FROM accounts WHERE phone = ?", (phone,))
                if account is None:
                    aid, created = st.create_account(phone), True
                else:
                    aid = account["id"]
                token = secrets.token_urlsafe(32)
                st.insert("INSERT INTO sessions (account_id, token_sha256, created_at, seen_at) "
                          "VALUES (?, ?, ?, ?)", (aid, _sha(token), now, now))
            else:
                st.record("wrong_address", ak)
                if row is not None and (int(row["expires_at"]) <= now
                                        or int(row["wrong_tries"]) + 1 >= CODE_TRIES):
                    st.execute("DELETE FROM login_codes WHERE id = ?", (row["id"],))
                elif row is not None:
                    st.execute("UPDATE login_codes SET wrong_tries = wrong_tries + 1 WHERE id = ?",
                               (row["id"],))
    if wait is not None:
        raise too_many(wait)
    if token is None:
        raise HTTPException(401, WRONG_FA)
    _cookie(response, token)
    return {"phone": phone, "created": created}


@router.get("/api/account/me")
def me(request: Request, st: Store = Depends(the_store)) -> dict:
    s = session_of(request, st)
    if s is None:
        raise HTTPException(401, NO_SESSION_FA)
    return {"phone": s["phone"]}


@router.post("/api/account/logout", dependencies=[Depends(same_origin)])
def logout(request: Request, response: Response, st: Store = Depends(the_store)) -> dict:
    token = request.cookies.get(COOKIE)
    if token:
        st.execute("DELETE FROM sessions WHERE token_sha256 = ?", (_sha(token),))
    _cookie(response, None)
    return {"ok": True}


@router.post("/api/account/delete", dependencies=[Depends(same_origin)])
def delete_account(request: Request, response: Response, st: Store = Depends(the_store)) -> dict:
    """«حذف حساب»: the account, and by the store's cascade every session and
    listing under it, at once."""
    s = session_of(request, st)
    if s is None:
        raise HTTPException(401, NO_SESSION_FA)
    st.execute("DELETE FROM accounts WHERE id = ?", (s["account_id"],))
    _cookie(response, None)
    return {"deleted": True}
