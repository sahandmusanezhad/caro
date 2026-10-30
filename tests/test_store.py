"""The seller listings' store keeps what it says, deletes what it says, and only adds.

    Run: PYTHONPATH=. python3 tests/test_store.py

WHY THIS SUITE EXISTS

`webapp/api/store.py` is where accounts, sessions, login codes and the
listings sellers post will live (docs/SELLER_LISTINGS.md, «The store»). Three
of its promises are the kind that fail silently: that deleting an account
deletes everything under it, that a migration never takes anything away, and
that a store named by DATABASE_URL and unusable says so instead of quietly
working on something else. Each has a row here.

It needs nothing beyond Python: the store is SQLite here, in a temporary
file. The same rows run against Postgres when CARO_TEST_STORE_URL names an
empty database made for them, with psycopg installed; that is how Postgres is
tried by hand, and the suite refuses a database that already holds anything.
"""
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import webapp.api.store as store_mod  # noqa: E402
from webapp.api.store import (  # noqa: E402
    DIALECTS, MIGRATIONS, TABLES, Store, StoreError, open_store, phone_09, sqlite_path, to_driver)

FAILS = []
HEAD = MIGRATIONS[-1][0]


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def raises(fn, kind=Exception):
    """The exception `fn` raised, or None."""
    try:
        fn()
    except kind as e:          # noqa: BLE001
        return e
    return None


SECRET = "made-up-for-the-suites-0123456789abcdef"
_tmp = tempfile.TemporaryDirectory()
URL = os.environ.get("CARO_TEST_STORE_URL") or f"sqlite:///{_tmp.name}/store.sqlite3"
ST = open_store(URL, SECRET, migrate=False)
if raises(lambda: ST.row("SELECT 1 AS one FROM accounts")) is None:
    print("CARO_TEST_STORE_URL names a database that already has an accounts table; "
          "give it an empty one made for this suite")
    raise SystemExit(2)
print(f"\nthe store, on {ST.dialect.name}")


def count(table, where="", params=()):
    return ST.row(f"SELECT COUNT(*) AS n FROM {table} {where}", params)["n"]


# ---------------------------------------------------------------------------
# What opens, and what refuses
# ---------------------------------------------------------------------------
os.environ.pop("DATABASE_URL", None)
os.environ.pop("CARO_STORE_SECRET", None)
check("S1: no DATABASE_URL, no store: the seller pages are off rather than writing somewhere",
      open_store() is None and open_store("") is None and open_store("   ", SECRET) is None)

_e1 = raises(lambda: open_store("mysql://u:hunter2-pw@db.example/x", SECRET), StoreError)
_e2 = raises(lambda: open_store("hunter2-pw-and-nothing-else", SECRET), StoreError)
check("S2: an address the store does not know is refused, naming its scheme and no part of the address",
      _e1 is not None and "«mysql»" in str(_e1) and "hunter2" not in str(_e1)
      and _e2 is not None and "scheme: none" in str(_e2) and "hunter2" not in str(_e2),
      str((_e1, _e2)))


def _no_driver(name):
    raise ImportError(f"No module named {name!r}")


_e3 = raises(lambda: open_store("postgresql://u:hunter2-pw@db.example/x", SECRET, importer=_no_driver),
             StoreError)
check("S3: a Postgres address without the driver is refused, naming psycopg and not the address",
      _e3 is not None and "psycopg" in str(_e3) and "hunter2" not in str(_e3), str(_e3))

_short = "s" * 31
_e4 = [raises(lambda s=s: open_store("sqlite:///:memory:", s), StoreError) for s in (None, "", _short)]
_ok4 = raises(lambda: open_store("sqlite:///:memory:", "t" * 32).close())
check("S4: a secret that is not set or is under 32 characters is refused, and the refusal holds no part "
      "of it; 32 characters open",
      all(e is not None for e in _e4) and all(_short not in str(e) for e in _e4) and _ok4 is None,
      str((_e4, _ok4)))

_mem = open_store("sqlite:///:memory:", SECRET)
check("S5: sqlite:///<path> is under the repository, sqlite:////<path> is absolute, sqlite:///:memory: "
      "is in memory, and the last opens migrated",
      sqlite_path("data/store/caro.sqlite3") == str(ROOT / "data" / "store" / "caro.sqlite3")
      and sqlite_path("/var/x.sqlite3") == "/var/x.sqlite3" and sqlite_path(":memory:") == ":memory:"
      and _mem.version() == HEAD, str(_mem.version()))
_mem.close()

# ---------------------------------------------------------------------------
# Migrations
# ---------------------------------------------------------------------------
_v0 = ST.version()
_applied = ST.migrate()
_tables_ok = all(raises(lambda t=t: count(t)) is None for t in TABLES + ("schema_migrations",))
check("S6: migrating an empty database applies every migration in order and makes the eight tables and "
      "schema_migrations, at the last version",
      _v0 == 0 and _applied == [n for n, _ in MIGRATIONS] and _tables_ok and ST.version() == HEAD,
      str((_v0, _applied, _tables_ok)))

_a7 = ST.create_account("09100000007")
_again = ST.migrate()
check("S7: a second migration applies nothing, and what was written in between stays",
      _again == [] and ST.version() == HEAD and count("accounts", "WHERE id = ?", (_a7,)) == 1, str(_again))

_ADDS = re.compile(r"\s*(CREATE TABLE IF NOT EXISTS|CREATE (UNIQUE )?INDEX IF NOT EXISTS"
                   r"|ALTER TABLE \w+ ADD COLUMN)\s", re.I)
# DELETE and UPDATE are not here: a statement that is one does not start as
# _ADDS asks, and inside one they are a key's ON DELETE CASCADE.
_TAKES = re.compile(r"\b(DROP|RENAME|ALTER\s+COLUMN|TRUNCATE)\b", re.I)
_bad = [s.split("(")[0].strip()[:60] for _, stmts in MIGRATIONS for s in stmts
        if not _ADDS.match(s) or _TAKES.search(s)]
_numbers = [n for n, _ in MIGRATIONS]
check("S8: every statement of every migration only adds, and the migrations are numbered 1, 2, … in order",
      not _bad and _numbers == list(range(1, len(_numbers) + 1)), str((_bad, _numbers)))

# ---------------------------------------------------------------------------
# Accounts, and what deleting one takes with it
# ---------------------------------------------------------------------------
_before9 = count("accounts")
_bad9 = ("9123456789", "+989123456789", "۰۹۱۲۳۴۵۶۷۸۹", "0912345678", "091234567890", "", None)
_e9 = [raises(lambda p=p: ST.create_account(p)) for p in _bad9]
check("S9: an account's phone is 09 and nine digits; anything else is refused before the database",
      all(isinstance(e, ValueError) for e in _e9) and count("accounts") == _before9, str(_e9))

ST.create_account("09100000010")
_e10 = raises(lambda: ST.create_account("09100000010"))
check("S10: a second account with the same number is refused by the database",
      _e10 is not None and count("accounts", "WHERE phone = ?", ("09100000010",)) == 1, str(_e10))


def seller(phone, listings=1):
    """An account with a session, and listings each with two versions, a
    report and a reveal."""
    a = ST.create_account(phone)
    ST.insert("INSERT INTO sessions (account_id, token_sha256, created_at, seen_at) VALUES (?, ?, ?, ?)",
              (a, ST.key("test", f"token-{phone}"), 1, 1))
    ls = []
    for i in range(listings):
        lid = ST.insert("INSERT INTO listings (account_id, created_at, ends_at) VALUES (?, ?, ?)", (a, 1, 2))
        for n in range(2):
            ST.insert("INSERT INTO listing_versions (listing_id, created_at, make, price_toman) "
                      "VALUES (?, ?, ?, ?)", (lid, 1 + n, "Peugeot", 1500000000))
        ST.insert("INSERT INTO reports (listing_id, reason, who_key, created_at) VALUES (?, ?, ?, ?)",
                  (lid, "spam", ST.key("address", f"addr-{phone}-{i}"), 1))
        ST.insert("INSERT INTO reveals (listing_id, who_key, at) VALUES (?, ?, ?)",
                  (lid, ST.key("address", f"addr-{phone}-{i}"), 1))
        ls.append(lid)
    return a, ls


def under_account(a):
    """What lies under account `a`, table by table."""
    sub = "SELECT id FROM listings WHERE account_id = ?"
    return {"sessions": count("sessions", "WHERE account_id = ?", (a,)),
            "listings": count("listings", "WHERE account_id = ?", (a,)),
            "listing_versions": count("listing_versions", f"WHERE listing_id IN ({sub})", (a,)),
            "reports": count("reports", f"WHERE listing_id IN ({sub})", (a,)),
            "reveals": count("reveals", f"WHERE listing_id IN ({sub})", (a,))}


def under_listing(lid):
    return {t: count(t, "WHERE listing_id = ?", (lid,)) for t in ("listing_versions", "reports", "reveals")}


_A, _A_ls = seller("09100000011", listings=2)
_B, _ = seller("09100000012")
_b_before = under_account(_B)
_A_ids = tuple(_A_ls)
_del11 = raises(lambda: ST.execute("DELETE FROM accounts WHERE id = ?", (_A,)))
_gone = {t: count(t, f"WHERE listing_id IN ({', '.join('?' * len(_A_ids))})", _A_ids)
         for t in ("listing_versions", "reports", "reveals")}
check("S11: deleting an account deletes its sessions, its listings and their versions, reports and reveals, "
      "and nothing of another account's",
      _del11 is None and count("accounts", "WHERE id = ?", (_A,)) == 0 and set(under_account(_A).values()) == {0}
      and set(_gone.values()) == {0} and under_account(_B) == _b_before
      and _b_before == {"sessions": 1, "listings": 1, "listing_versions": 2, "reports": 1, "reveals": 1},
      str((_del11, under_account(_A), _gone, under_account(_B))))

_C, (_L1, _L2) = seller("09100000013", listings=2)
_l2_before = under_listing(_L2)
_del12 = raises(lambda: ST.execute("DELETE FROM listings WHERE id = ?", (_L1,)))
check("S12: deleting a listing deletes its versions, reports and reveals, and leaves its account and the "
      "account's other listing",
      _del12 is None and set(under_listing(_L1).values()) == {0} and under_listing(_L2) == _l2_before
      and _l2_before == {"listing_versions": 2, "reports": 1, "reveals": 1}
      and count("accounts", "WHERE id = ?", (_C,)) == 1 and count("sessions", "WHERE account_id = ?", (_C,)) == 1,
      str((_del12, under_listing(_L1), under_listing(_L2))))

# ---------------------------------------------------------------------------
# What the database itself refuses
# ---------------------------------------------------------------------------
_k = ST.key("address", "addr-13")
_rep = "INSERT INTO reports (listing_id, reason, who_key, created_at) VALUES (?, ?, ?, ?)"
_r1 = raises(lambda: ST.insert(_rep, (_L2, "spam", _k, 5)))
_r2 = raises(lambda: ST.insert(_rep, (_L2, "fake", _k, 6)))
_r3 = raises(lambda: ST.insert(_rep, (_L2, "spam", ST.key("address", "addr-14"), 7)))
check("S13: one address reports a listing once; another address can",
      _r1 is None and _r2 is not None and _r3 is None
      and count("reports", "WHERE listing_id = ? AND who_key = ?", (_L2, _k)) == 1, str((_r1, _r2, _r3)))

_sess = "INSERT INTO sessions (account_id, token_sha256, created_at, seen_at) VALUES (?, ?, ?, ?)"
_t = ST.key("test", "one-token")
_s1 = raises(lambda: ST.insert(_sess, (_C, _t, 1, 1)))
_s2 = raises(lambda: ST.insert(_sess, (_C, _t, 2, 2)))
check("S14: a session's token hash is held once",
      _s1 is None and _s2 is not None and count("sessions", "WHERE token_sha256 = ?", (_t,)) == 1,
      str((_s1, _s2)))

# ---------------------------------------------------------------------------
# The keyed hashes, the transaction, the SQL each driver gets, the ids
# ---------------------------------------------------------------------------
_other = open_store("sqlite:///:memory:", "another-made-up-secret-0123456789abcdef")
_kp = ST.key("phone", "09123456789")
check("S15: a keyed hash is the same for the same value, 64 hex characters, different by kind and by secret, "
      "and the value is not in it",
      _kp == ST.key("phone", "09123456789") and re.fullmatch(r"[0-9a-f]{64}", _kp) is not None
      and _kp != ST.key("address", "09123456789") and _kp != _other.key("phone", "09123456789")
      and "09123456789" not in _kp and "123456789" not in _kp, _kp)
_other.close()

_n16 = (count("accounts"), count("listings"))


def _half_written():
    with ST.transaction():
        a = ST.create_account("09100000016")
        ST.insert("INSERT INTO listings (account_id, created_at, ends_at) VALUES (?, ?, ?)", (a, 1, 2))
        raise RuntimeError("the second half fails")


_e16 = raises(_half_written, RuntimeError)
check("S16: a transaction that raises leaves nothing it wrote",
      _e16 is not None and (count("accounts"), count("listings")) == _n16
      and count("accounts", "WHERE phone = ?", ("09100000016",)) == 0, str((_n16, count("accounts"))))

_pg, _sq = DIALECTS["postgres"], DIALECTS["sqlite"]
_sql = "SELECT id FROM accounts WHERE phone = ? AND created_at > ?"
check("S17: Postgres gets %s where the SQL says ?, SQLite gets it as written, and SQL with a % in it is "
      "refused for both",
      to_driver(_sql, _pg) == "SELECT id FROM accounts WHERE phone = %s AND created_at > %s"
      and to_driver(_sql, _sq) == _sql
      and all(raises(lambda d=d: to_driver("SELECT 1 WHERE 'a' LIKE '%a'", d), ValueError) for d in (_pg, _sq)))

_i1 = ST.create_account("09100000018")
_i2 = ST.create_account("09100000019")
check("S18: an insert gives the new row's id, and the next one is larger",
      isinstance(_i1, int) and _i2 > _i1 > 0
      and ST.row("SELECT phone FROM accounts WHERE id = ?", (_i2,)) == {"phone": "09100000019"}, str((_i1, _i2)))

# ---------------------------------------------------------------------------
# A phone's form, and the limits, which are rows here and not a process's memory
# ---------------------------------------------------------------------------
_same = ("۰۹۱۲ ۳۴۵ ۶۷۸۹", "+98 912 345 6789", "0098-912-345-6789", "9123456789", "٠٩١٢٣٤٥٦٧٨٩",
         "989123456789", "(0912) 345.67.89")
_not = ("02112345678", "+98 21 1234 5678", "0912345678", "09123456789012", "", None, "abc")
check("S19: seven ways of writing one mobile number are 09123456789; a landline, ten or fourteen digits, "
      "empty, None and letters are not a number",
      [phone_09(x) for x in _same] == ["09123456789"] * len(_same) and [phone_09(x) for x in _not] == [None] * len(_not),
      str(([phone_09(x) for x in _same], [phone_09(x) for x in _not])))

_now = [1_700_000_000]
LS = Store(ST.conn, ST.dialect, SECRET, clock=lambda: _now[0])
_who = LS.key("phone", "09100000020")


def _try(kind, who, limits):
    with LS.transaction():
        LS.lock(f"{kind}:{who}")
        w = LS.blocked(kind, who, limits)
        if w is None:
            LS.record(kind, who)
    return w


_w20 = []
for _ in range(4):
    _w20.append(_try("s20", _who, ((3, 900),)))
    _now[0] += 60
_others = (LS.blocked("s20-other", _who, ((3, 900),)), LS.blocked("s20", LS.key("phone", "09100000021"), ((3, 900),)))
_now[0] += 900 - 4 * 60 + 1
_open = LS.blocked("s20", _who, ((3, 900),))
check("S20: under a limit nothing waits; at it the wait is what is left of the window; another kind or "
      "another key is not counted; when the oldest attempt leaves the window it opens",
      _w20 == [None, None, None, 720] and _others == (None, None) and _open is None, str((_w20, _others, _open)))

_now[0] = 1_800_000_000
_who = LS.key("address", "203.0.113.21")
_L = ((3, 900), (6, 86400))
_short = [_try("s21", _who, _L) for _ in range(4)]
_now[0] += 901
_day = [_try("s21", _who, _L) for _ in range(4)]
_n_before = count("attempts", "WHERE kind = ?", ("s21",))
_now[0] += 2 * 86400 + 1
LS.record("s21-later", _who)
check("S21: with 3 in 15 minutes and 6 in a day, the short window blocks first and the day's after it; "
      "an attempt older than two days is deleted when the next is written",
      _short[:3] == [None] * 3 and 0 < _short[3] <= 900 and _day[:3] == [None] * 3 and _day[3] > 900
      and _n_before == 6 and count("attempts", "WHERE kind = ?", ("s21",)) == 0,
      str((_short, _day, _n_before, count("attempts", "WHERE kind = ?", ("s21",)))))

# ---------------------------------------------------------------------------
# A database the code before migration 2 made, under the code after it
# ---------------------------------------------------------------------------
_old = open_store(f"sqlite:///{_tmp.name}/older.sqlite3", SECRET, migrate=False)
_all = store_mod.MIGRATIONS
try:
    store_mod.MIGRATIONS = _all[:1]
    _old.migrate()
    _o_acc = _old.create_account("09100000022")
    _o_l = _old.insert("INSERT INTO listings (account_id, created_at, ends_at) VALUES (?, ?, ?)", (_o_acc, 1, 2))
    _V1 = "INSERT INTO listing_versions (listing_id, created_at, make, price_toman) VALUES (?, ?, ?, ?)"
    _old.insert(_V1, (_o_l, 1, "Saipa", 400000000))
    _v_before = _old.version()
finally:
    store_mod.MIGRATIONS = _all
_up = _old.migrate()
_e22 = raises(lambda: _old.insert(_V1, (_o_l, 2, "Saipa", 410000000)))
_p22 = raises(lambda: _old.execute("UPDATE listing_versions SET province = ? WHERE listing_id = ?", ("قم", _o_l)))
check("S22: on SQLite, a database at version 1 holding a listing gets version 2: the province column is there, "
      "every row is there, and an INSERT written for version 1 still works",
      _v_before == 1 and _up == [2] and _old.version() == 2 and _e22 is None and _p22 is None
      and _old.row("SELECT COUNT(*) AS n FROM listing_versions WHERE listing_id = ? AND province = ?",
                   (_o_l, "قم"))["n"] == 2
      and _old.row("SELECT COUNT(*) AS n FROM accounts")["n"] == 1, str((_v_before, _up, _e22, _p22)))
_old.close()

ST.close()
print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
