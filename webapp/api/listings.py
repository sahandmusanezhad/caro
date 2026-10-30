"""A listing a seller posts on CARO: step 3 of docs/SELLER_LISTINGS.md.

**Not the corpus.** Nothing here is read by the estimator, the search or a
model's page of corpus listings, and nothing here writes to data/corpora/. A
listing a seller posts is written by its owner for publication; a listing in
the corpus was read from a source as evidence. They meet only on the site,
under different headings.

**The rules are the server's.** Whatever the form in the browser lets
through, `faults()` decides: a year from 1300 to next year; an odometer from
0 to 2,000,000 km, and 0 only on this year's or next year's car; a cash price
at or above the corpus's floor or «توافقی», one of the two; the province one
of the 31 and the city as the seller writes it, never read for the province
(caro/ingest/persian.py holds no city list, on purpose); gearbox, fuel,
colour and body condition the site's own classes or not stated; no link in
any text, no run of five digits however spaced in the names, and no digit at
all in the description -- a number in prose is how a phone escapes the
reveal.

**What the public sees** is a listing's approved version, while it is live
and not taken down by reports, and never its seller's number. The number is
given only by `reveal`, only where the seller ticked «نمایش شماره», only to a
POST from the site, counted per address in the store, and never cached.

**Every listing and every edit waits for the operator.** A new listing is a
pending version; an edit is another, and the approved one stays public until
the operator decides (step 4); a second edit replaces the first. One active
listing per account. A listing lives 30 days, its seller can renew it, and it
is deleted 90 days after it ends; its seller can delete it at any time.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from caro.ingest.divar_car import BODY_CONDITION, COLORS, FUEL, GEARBOX
from caro.ingest.persian import PROVINCES, normalize
from caro.ingest.quality import CURRENT_JALALI_YEAR, classify_price_value
from webapp.api.accounts import NO_SESSION_FA, same_origin, session_of, the_store
from webapp.api.security import client_address, too_many
from webapp.api.store import Store

router = APIRouter()

LIFE_S = 30 * 86400
KEPT_AFTER_END_S = 90 * 86400
REVEAL_LIMITS = ((10, 3600), (30, 86400))       # per address; proposals, like the login's
PAGE_MAX = 50
NAME_MAX = 40
DESCRIPTION_MAX = 1000
MAX_KM = 2_000_000
BODIES = tuple(label for label, _ in BODY_CONDITION)
FIELDS = ("make", "model", "trim", "year_jalali", "mileage_km", "price_toman", "negotiable",
          "province", "city", "gearbox", "fuel", "color", "body", "description", "show_phone")
PUBLIC_FIELDS = tuple(f for f in FIELDS if f != "show_phone")

_PROVINCE = {normalize(p): p for p in PROVINCES}
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
_LINK = re.compile(r"https?://|www\.|\.(?:ir|com|net|org|me|io)\b|@|t\.me|telegram|instagram|"
                   r"whatsapp|تلگرام|اینستاگرام|واتساپ|ایتا|روبیکا", re.I)
_RUN_OF_FIVE = re.compile(r"\d(?:[\s\-.()/_]*\d){4}")

NAME_FA = "این بخش باید نوشته شود، تا ۴۰ حرف، بدون پیوند و بدون شماره‌ی تلفن."
YEAR_FA = f"سال ساخت باید بین ۱۳۰۰ و {CURRENT_JALALI_YEAR + 1} باشد."
KM_FA = "کارکرد باید بین ۰ و ۲٬۰۰۰٬۰۰۰ کیلومتر باشد."
ZERO_KM_FA = "کارکرد صفر فقط برای خودروی امسال یا سال بعد پذیرفته است."
PRICE_ONE_FA = "یا قیمت را بنویس یا «توافقی» را بزن؛ هر دو یا هیچ‌کدام پذیرفته نیست."
FLOOR_FA = "این قیمت کمتر از کف قیمت هر خودرویی است."
PROVINCE_FA = "استان را از فهرست انتخاب کن."
CLASS_FA = "از گزینه‌های فهرست انتخاب کن."
DESCRIPTION_FA = "توضیح تا ۱۰۰۰ حرف است و پیوند یا عدد ندارد؛ شماره را فقط «نمایش شماره» نشان می‌دهد."
ONE_FA = "هر شماره یک آگهی فعال دارد. آگهی فعلی‌ات را حذف کن یا بگذار تمام شود."
ENDED_FA = "این آگهی تمام شده است. اول تمدیدش کن."
NOT_FOUND_FA = "این آگهی پیدا نشد."


def province_of_choice(raw: str | None) -> str | None:
    return _PROVINCE.get(normalize(raw or ""))


def faults(x: "ListingIn") -> dict[str, str]:
    """Every rule the listing breaks, by field, in the seller's language."""
    f: dict[str, str] = {}
    for name in ("make", "model", "trim", "city"):
        v = (getattr(x, name) or "").strip()
        if (not v and name in ("make", "model")) or len(v) > NAME_MAX:
            f[name] = NAME_FA
        elif _LINK.search(v.translate(_DIGITS)) or _RUN_OF_FIVE.search(v.translate(_DIGITS)):
            f[name] = NAME_FA
    if not 1300 <= x.year_jalali <= CURRENT_JALALI_YEAR + 1:
        f["year_jalali"] = YEAR_FA
    if not 0 <= x.mileage_km <= MAX_KM:
        f["mileage_km"] = KM_FA
    elif x.mileage_km == 0 and x.year_jalali < CURRENT_JALALI_YEAR:
        f["mileage_km"] = ZERO_KM_FA
    if x.negotiable == (x.price_toman is not None):
        f["price_toman"] = PRICE_ONE_FA
    elif x.price_toman is not None and not classify_price_value(x.price_toman).usable:
        f["price_toman"] = FLOOR_FA
    if province_of_choice(x.province) is None:
        f["province"] = PROVINCE_FA
    for name, allowed in (("gearbox", GEARBOX), ("fuel", FUEL), ("color", COLORS), ("body", BODIES)):
        v = getattr(x, name)
        if v is not None and v not in allowed:
            f[name] = CLASS_FA
    d = x.description.translate(_DIGITS)
    if len(x.description) > DESCRIPTION_MAX or _LINK.search(d) or re.search(r"\d", d):
        f["description"] = DESCRIPTION_FA
    return f


class ListingIn(BaseModel):
    # Generous bounds on what is read at all; faults() holds the real ones,
    # so that every rule answers in one shape.
    make: str = Field(max_length=200)
    model: str = Field(max_length=200)
    trim: str | None = Field(default=None, max_length=200)
    year_jalali: int
    mileage_km: int
    price_toman: int | None = None
    negotiable: bool = False
    province: str = Field(max_length=200)
    city: str | None = Field(default=None, max_length=200)
    gearbox: str | None = Field(default=None, max_length=40)
    fuel: str | None = Field(default=None, max_length=40)
    color: str | None = Field(default=None, max_length=40)
    body: str | None = Field(default=None, max_length=40)
    description: str = Field(default="", max_length=4000)
    show_phone: bool = False


def _values(x: ListingIn) -> tuple:
    def text(v):
        v = (v or "").strip()
        return v or None
    return (text(x.make), text(x.model), text(x.trim), x.year_jalali, x.mileage_km,
            x.price_toman, int(x.negotiable), province_of_choice(x.province), text(x.city),
            x.gearbox, x.fuel, x.color, x.body, x.description.strip(), int(x.show_phone))


def _add_version(st: Store, lid: int, x: ListingIn, now: int) -> int:
    return st.insert(
        f"INSERT INTO listing_versions (listing_id, created_at, {', '.join(FIELDS)}) "
        f"VALUES (?, ?, {', '.join('?' * len(FIELDS))})", (lid, now, *_values(x)))


def _seller(request: Request, st: Store) -> dict:
    s = session_of(request, st)
    if s is None:
        raise HTTPException(401, NO_SESSION_FA)
    return s


def _own(st: Store, lid: int, s: dict) -> dict:
    row = st.row("SELECT * FROM listings WHERE id = ? AND account_id = ?", (lid, s["account_id"]))
    if row is None:
        raise HTTPException(404, NOT_FOUND_FA)
    return row


def _another_active(st: Store, account_id: int, now: int, besides: int | None = None) -> bool:
    sql, params = "SELECT COUNT(*) AS n FROM listings WHERE account_id = ? AND ends_at > ?", [account_id, now]
    if besides is not None:
        sql += " AND id <> ?"
        params.append(besides)
    return st.row(sql, tuple(params))["n"] > 0


def _check(x: ListingIn) -> None:
    f = faults(x)
    if f:
        raise HTTPException(422, {"faults": f})


def _fields(v: dict | None) -> dict | None:
    if v is None:
        return None
    out = {k: v[k] for k in FIELDS}
    out["negotiable"], out["show_phone"] = bool(out["negotiable"]), bool(out["show_phone"])
    return out


def purge(st: Store, now: int) -> None:
    """A listing is deleted 90 days after it ends, and its versions, reports
    and reveals with it."""
    st.execute("DELETE FROM listings WHERE ends_at < ?", (now - KEPT_AFTER_END_S,))


# Public: the approved version of a live listing that reports have not taken
# down. The only place that says which listings anyone may see; the list, a
# listing and the reveal are all built from it.
LIVE_FROM = "FROM listings l JOIN listing_versions v ON v.id = l.live_version"
LIVE_WHERE = "l.held = 0 AND l.ends_at > ?"
_PUBLIC_COLS = "l.id AS listing_id, l.ends_at, " + ", ".join(f"v.{c}" for c in FIELDS)


def _public(r: dict) -> dict:
    out = {"id": r["listing_id"], "ends_at": r["ends_at"],
           **{k: r[k] for k in PUBLIC_FIELDS}, "has_phone": bool(r["show_phone"])}
    out["negotiable"] = bool(out["negotiable"])
    return out


@router.post("/api/listings", dependencies=[Depends(same_origin)])
def create(body: ListingIn, request: Request, st: Store = Depends(the_store)) -> dict:
    s = _seller(request, st)
    _check(body)
    now = st.now()
    with st.transaction():
        st.lock(f"listings:{s['account_id']}")
        if _another_active(st, s["account_id"], now):
            raise HTTPException(409, ONE_FA)
        lid = st.insert("INSERT INTO listings (account_id, created_at, ends_at) VALUES (?, ?, ?)",
                        (s["account_id"], now, now + LIFE_S))
        _add_version(st, lid, body, now)
    return {"id": lid, "review": "pending", "ends_at": now + LIFE_S}


@router.get("/api/listings/mine")
def mine(request: Request, st: Store = Depends(the_store)) -> dict:
    """The seller's listings: what the public sees, what waits for the
    operator, and the operator's last word with its reason."""
    s = _seller(request, st)
    now, out = st.now(), []
    for lst in st.rows("SELECT * FROM listings WHERE account_id = ? ORDER BY id DESC", (s["account_id"],)):
        versions = st.rows("SELECT * FROM listing_versions WHERE listing_id = ? ORDER BY id", (lst["id"],))
        live = next((v for v in versions if v["id"] == lst["live_version"]), None)
        pending = next((v for v in reversed(versions) if v["review"] == "pending"), None)
        # the operator's last word: the version reviewed last, whichever it is
        last = max((v for v in versions if v["reviewed_at"] is not None),
                   key=lambda v: (v["reviewed_at"], v["id"]), default=None)
        out.append({
            "id": lst["id"], "ends_at": lst["ends_at"], "ended": lst["ends_at"] <= now,
            "held": bool(lst["held"]), "live": _fields(live), "pending": _fields(pending),
            "last_review": ({"review": last["review"], "reason": last["reason"]} if last else None),
            "reveals": st.row("SELECT COUNT(*) AS n FROM reveals WHERE listing_id = ?", (lst["id"],))["n"]})
    return {"listings": out}


@router.post("/api/listings/{lid}/edit", dependencies=[Depends(same_origin)])
def edit(lid: int, body: ListingIn, request: Request, st: Store = Depends(the_store)) -> dict:
    s = _seller(request, st)
    lst = _own(st, lid, s)
    now = st.now()
    if lst["ends_at"] <= now:
        raise HTTPException(409, ENDED_FA)
    _check(body)
    with st.transaction():
        # a pending version was never public: the new one takes its place
        st.execute("DELETE FROM listing_versions WHERE listing_id = ? AND review = 'pending'", (lid,))
        _add_version(st, lid, body, now)
    return {"id": lid, "review": "pending"}


@router.post("/api/listings/{lid}/renew", dependencies=[Depends(same_origin)])
def renew(lid: int, request: Request, st: Store = Depends(the_store)) -> dict:
    s = _seller(request, st)
    now = st.now()
    with st.transaction():
        st.lock(f"listings:{s['account_id']}")
        lst = _own(st, lid, s)
        if lst["ends_at"] <= now and _another_active(st, s["account_id"], now, besides=lid):
            raise HTTPException(409, ONE_FA)
        st.execute("UPDATE listings SET ends_at = ? WHERE id = ?", (now + LIFE_S, lid))
    return {"id": lid, "ends_at": now + LIFE_S}


@router.post("/api/listings/{lid}/delete", dependencies=[Depends(same_origin)])
def delete(lid: int, request: Request, st: Store = Depends(the_store)) -> dict:
    s = _seller(request, st)
    _own(st, lid, s)
    st.execute("DELETE FROM listings WHERE id = ?", (lid,))
    return {"deleted": True}


@router.get("/api/listings")
def public_list(make: str | None = Query(None, max_length=NAME_MAX),
                model: str | None = Query(None, max_length=NAME_MAX),
                limit: int = Query(20, ge=1), offset: int = Query(0, ge=0),
                st: Store = Depends(the_store)) -> dict:
    now = st.now()
    purge(st, now)
    limit = min(limit, PAGE_MAX)
    sql, params = f"SELECT {_PUBLIC_COLS} {LIVE_FROM} WHERE {LIVE_WHERE}", [now]
    for col, v in (("make", make), ("model", model)):
        if v and v.strip():
            sql += f" AND v.{col} = ?"
            params.append(v.strip())
    sql += " ORDER BY v.reviewed_at DESC, l.id DESC LIMIT ? OFFSET ?"
    rows = st.rows(sql, (*params, limit, offset))
    return {"listings": [_public(r) for r in rows], "limit": limit, "offset": offset}


@router.get("/api/listings/{lid}")
def public_one(lid: int, st: Store = Depends(the_store)) -> dict:
    r = st.row(f"SELECT {_PUBLIC_COLS} {LIVE_FROM} WHERE {LIVE_WHERE} AND l.id = ?", (st.now(), lid))
    if r is None:
        raise HTTPException(404, NOT_FOUND_FA)
    return _public(r)


@router.post("/api/listings/{lid}/reveal", dependencies=[Depends(same_origin)])
def reveal(lid: int, request: Request, st: Store = Depends(the_store)) -> dict:
    """The seller's number, where the seller chose to show it. Every press is
    counted against the address, a number found or not, so that asking for
    one listing after another is slowed like any other guessing."""
    ak = st.key("address", client_address(request))
    now, phone = st.now(), None
    with st.transaction():
        st.lock(f"reveal:{ak}")
        wait = st.blocked("reveal_address", ak, REVEAL_LIMITS)
        if wait is None:
            st.record("reveal_address", ak)
            r = st.row(f"SELECT v.show_phone, a.phone {LIVE_FROM} JOIN accounts a ON a.id = l.account_id "
                       f"WHERE {LIVE_WHERE} AND l.id = ?", (now, lid))
            if r is not None and r["show_phone"]:
                phone = r["phone"]
                st.insert("INSERT INTO reveals (listing_id, who_key, at) VALUES (?, ?, ?)", (lid, ak, now))
    if wait is not None:
        raise too_many(wait)
    if phone is None:
        raise HTTPException(404, NOT_FOUND_FA)
    return {"phone": phone}
