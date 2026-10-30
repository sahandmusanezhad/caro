"""What the operator decides about listings sellers post, and what the public
reports: step 4 of docs/SELLER_LISTINGS.md.

**Every listing and every edit waits here.** The operator sees each pending
version, oldest first, marked as a listing's first or as an edit of one, and
approves it -- it becomes the public version, and the one before it is
superseded -- or rejects it with a reason, which the seller reads in
«آگهی‌های من». A rejected edit leaves the approved version where it was.

**Three reports take a listing down until the operator looks.** A report is
one reason from a short list, from the site, one per address and listing, 20
a day per address. At three the listing is held: off the public list, its
number not revealed. The operator releases it, and its reports are cleared,
or removes it with a reason, which rejects its public version; the seller
can edit, and the edit comes back through the queue.

**The operator's door is the inbox's.** The token, and the code where a TOTP
secret is set, through `contact.require_operator` and its failure count. No
Origin check: nothing here reads a cookie, and a page on another site cannot
put the token in a header. No answer here holds a seller's number; reviewing
a listing does not need it.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from webapp.api.accounts import same_origin, the_store
from webapp.api.contact import require_operator
from webapp.api.listings import FIELDS, LIVE_FROM, LIVE_WHERE, NOT_FOUND_FA
from webapp.api.security import client_address, too_many
from webapp.api.store import Store

router = APIRouter()

HOLD_AT = 3
REPORT_LIMITS = ((20, 86400),)       # per address; a proposal
REPORT_REASONS = ("sold", "wrong", "fake", "spam", "offensive", "other")
NOT_PENDING_FA = "این نسخه دیگر در انتظار تأیید نیست."
REASON_FA = "دلیل را بنویس؛ فروشنده آن را می‌بیند."
REPORT_REASON_FA = "یکی از دلیل‌های فهرست را انتخاب کن."


def operator(request: Request, x_admin_token: str | None = Header(default=None),
             x_admin_code: str | None = Header(default=None)) -> None:
    require_operator(request, x_admin_token, x_admin_code)


class ReasonIn(BaseModel):
    reason: str = Field(max_length=300)


class ReportIn(BaseModel):
    reason: str = Field(max_length=40)


def _reason(body: ReasonIn) -> str:
    r = body.reason.strip()
    if not r:
        raise HTTPException(422, REASON_FA)
    return r


def _version(v: dict) -> dict:
    return {k: v[k] for k in FIELDS}


@router.get("/api/admin/listings/pending", dependencies=[Depends(operator)])
def pending(st: Store = Depends(the_store)) -> dict:
    rows = st.rows("SELECT v.*, l.live_version FROM listing_versions v "
                   "JOIN listings l ON l.id = v.listing_id "
                   "WHERE v.review = 'pending' ORDER BY v.created_at, v.id")
    return {"pending": [{"version": r["id"], "listing": r["listing_id"], "created_at": r["created_at"],
                         "kind": "edit" if r["live_version"] is not None else "first",
                         "fields": _version(r)} for r in rows]}


@router.post("/api/admin/listings/versions/{vid}/approve", dependencies=[Depends(operator)])
def approve(vid: int, st: Store = Depends(the_store)) -> dict:
    now = st.now()
    with st.transaction():
        v = st.row("SELECT id, listing_id, review FROM listing_versions WHERE id = ?", (vid,))
        if v is None:
            raise HTTPException(404, NOT_FOUND_FA)
        if v["review"] != "pending":
            raise HTTPException(409, NOT_PENDING_FA)
        live = st.row("SELECT live_version FROM listings WHERE id = ?", (v["listing_id"],))["live_version"]
        if live is not None:
            st.execute("UPDATE listing_versions SET review = 'superseded' WHERE id = ?", (live,))
        st.execute("UPDATE listing_versions SET review = 'approved', reviewed_at = ? WHERE id = ?", (now, vid))
        st.execute("UPDATE listings SET live_version = ? WHERE id = ?", (vid, v["listing_id"]))
    return {"approved": vid, "listing": v["listing_id"]}


@router.post("/api/admin/listings/versions/{vid}/reject", dependencies=[Depends(operator)])
def reject(vid: int, body: ReasonIn, st: Store = Depends(the_store)) -> dict:
    reason, now = _reason(body), st.now()
    with st.transaction():
        v = st.row("SELECT review FROM listing_versions WHERE id = ?", (vid,))
        if v is None:
            raise HTTPException(404, NOT_FOUND_FA)
        if v["review"] != "pending":
            raise HTTPException(409, NOT_PENDING_FA)
        st.execute("UPDATE listing_versions SET review = 'rejected', reason = ?, reviewed_at = ? WHERE id = ?",
                   (reason, now, vid))
    return {"rejected": vid}


@router.get("/api/admin/listings/held", dependencies=[Depends(operator)])
def held(st: Store = Depends(the_store)) -> dict:
    out = []
    for lst in st.rows("SELECT id, live_version FROM listings WHERE held = 1 ORDER BY id"):
        live = st.row("SELECT * FROM listing_versions WHERE id = ?", (lst["live_version"],))
        reasons = st.rows("SELECT reason, COUNT(*) AS n FROM reports WHERE listing_id = ? GROUP BY reason",
                          (lst["id"],))
        out.append({"listing": lst["id"], "fields": _version(live) if live else None,
                    "reports": {r["reason"]: r["n"] for r in reasons}})
    return {"held": out}


@router.post("/api/admin/listings/{lid}/release", dependencies=[Depends(operator)])
def release(lid: int, st: Store = Depends(the_store)) -> dict:
    with st.transaction():
        if st.row("SELECT id FROM listings WHERE id = ?", (lid,)) is None:
            raise HTTPException(404, NOT_FOUND_FA)
        st.execute("UPDATE listings SET held = 0 WHERE id = ?", (lid,))
        st.execute("DELETE FROM reports WHERE listing_id = ?", (lid,))
    return {"released": lid}


@router.post("/api/admin/listings/{lid}/remove", dependencies=[Depends(operator)])
def remove(lid: int, body: ReasonIn, st: Store = Depends(the_store)) -> dict:
    """Off the public list for a reason the seller reads: its public version
    rejected. The listing stays the seller's, to edit or delete."""
    reason, now = _reason(body), st.now()
    with st.transaction():
        lst = st.row("SELECT live_version FROM listings WHERE id = ?", (lid,))
        if lst is None:
            raise HTTPException(404, NOT_FOUND_FA)
        if lst["live_version"] is not None:
            st.execute("UPDATE listing_versions SET review = 'rejected', reason = ?, reviewed_at = ? WHERE id = ?",
                       (reason, now, lst["live_version"]))
        st.execute("UPDATE listings SET live_version = NULL, held = 0 WHERE id = ?", (lid,))
        st.execute("DELETE FROM reports WHERE listing_id = ?", (lid,))
    return {"removed": lid}


@router.post("/api/listings/{lid}/report", dependencies=[Depends(same_origin)])
def report(lid: int, body: ReportIn, request: Request, st: Store = Depends(the_store)) -> dict:
    """«گزارش آگهی». One address counts once for a listing; three take it
    down until the operator looks."""
    if body.reason not in REPORT_REASONS:
        raise HTTPException(422, REPORT_REASON_FA)
    ak, now, seen = st.key("address", client_address(request)), st.now(), None
    with st.transaction():
        st.lock(f"report:{lid}")
        wait = st.blocked("report_address", ak, REPORT_LIMITS)
        if wait is None:
            st.record("report_address", ak)
            seen = st.row(f"SELECT l.id {LIVE_FROM} WHERE {LIVE_WHERE} AND l.id = ?", (now, lid))
            if seen and st.row("SELECT id FROM reports WHERE listing_id = ? AND who_key = ?", (lid, ak)) is None:
                st.insert("INSERT INTO reports (listing_id, reason, who_key, created_at) VALUES (?, ?, ?, ?)",
                          (lid, body.reason, ak, now))
                if st.row("SELECT COUNT(*) AS n FROM reports WHERE listing_id = ?", (lid,))["n"] >= HOLD_AT:
                    st.execute("UPDATE listings SET held = 1 WHERE id = ?", (lid,))
    if wait is not None:
        raise too_many(wait)
    if seen is None:
        raise HTTPException(404, NOT_FOUND_FA)
    return {"reported": True}
