"""The seller listings' store: one module for SQLite and Postgres.

docs/SELLER_LISTINGS.md, «The store», sets it out, and this is step 1 of its
build: the storage and nothing else. The login, a listing's rules and the
operator's view are the steps after it, and each reads and writes through
`Store`.

Four properties, and each of them is a decision rather than an accident.

**No store is assumed.** `DATABASE_URL` names it -- `sqlite:///<path>` or
`postgresql://...` -- and without it `open_store()` gives None and the seller
pages are off. A default file would be the inbox's mistake again (D68): on a
serverless function a listing written to a local file is gone at the next
cold start, and the seller was told it was kept.

**One SQL for both.** The statements are the part the two databases share.
Where they differ -- the id column, how a parameter is written, how a write
transaction begins, how a new row's id comes back, what keeps two processes
from migrating at once -- is `DIALECTS` in `caro/sql.py`, which the catalog
of published runs uses too, and nothing outside it knows which database it
has. The driver for Postgres is imported only for a Postgres address, so the
suites and a laptop need nothing beyond Python.

**Migrations only add.** Each is a numbered list of CREATE TABLE, CREATE
INDEX and ALTER TABLE ... ADD COLUMN, applied in order, each in a
transaction, and recorded in `schema_migrations`. Nothing renames, drops or
changes a column, so the code from before a migration still works on the
database after it, and a deployment never has to stop to change one.
`tests/test_store.py` holds every statement to that.

**Nothing personal in clear but an account's number.** A login code, a phone
number that asked for one and an address the limits count are kept only as
keyed hashes (`Store.key`, HMAC-SHA256 under `CARO_STORE_SECRET`), so a copy
of the database gives none of them. The number in `accounts` is in clear
because it is shown when its seller chooses, and an account exists only once
its owner has answered a code. Deleting an account deletes everything under
it, by the database's own cascade.
"""

from __future__ import annotations

import hashlib
import hmac
import importlib
import os
import re
import time
from typing import Any, Callable

# Named here as well as in caro/sql.py: the seller store's suite and its
# callers import them from the store.
from caro.sql import DIALECTS, Database, Dialect, connect, sqlite_path, to_driver  # noqa: F401

MIN_SECRET_CHARS = 32
PHONE = re.compile(r"09\d{9}")
_DIGITS = str.maketrans("۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩", "01234567890123456789")
# Attempts older than this are deleted as new ones are written: the longest
# window a limit has is a day.
ATTEMPTS_KEPT_S = 2 * 86400


class StoreError(RuntimeError):
    """The store is configured and cannot be used. Its message never holds
    the address (which can carry a password) or the secret."""


# Times are seconds since the epoch, BIGINT. Money is toman and a distance is
# km, and the unit is in the column's name, so a rial is never read as a toman
# (ACCOUNTS_AND_PAYMENT, «Payment»). {id} is the dialect's id column.
MIGRATIONS: tuple[tuple[int, tuple[str, ...]], ...] = (
    (1, (
        """CREATE TABLE IF NOT EXISTS accounts (
            id {id},
            phone TEXT NOT NULL UNIQUE,
            created_at BIGINT NOT NULL)""",
        """CREATE TABLE IF NOT EXISTS sessions (
            id {id},
            account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            token_sha256 TEXT NOT NULL UNIQUE,
            created_at BIGINT NOT NULL,
            seen_at BIGINT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS sessions_account ON sessions(account_id)",
        """CREATE TABLE IF NOT EXISTS login_codes (
            id {id},
            phone_key TEXT NOT NULL,
            code_key TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            expires_at BIGINT NOT NULL,
            wrong_tries INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS login_codes_phone ON login_codes(phone_key)",
        """CREATE TABLE IF NOT EXISTS attempts (
            id {id},
            kind TEXT NOT NULL,
            who_key TEXT NOT NULL,
            at BIGINT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS attempts_kind_who ON attempts(kind, who_key, at)",
        """CREATE TABLE IF NOT EXISTS listings (
            id {id},
            account_id BIGINT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
            created_at BIGINT NOT NULL,
            ends_at BIGINT NOT NULL,
            live_version BIGINT,
            held INTEGER NOT NULL DEFAULT 0)""",
        "CREATE INDEX IF NOT EXISTS listings_account ON listings(account_id)",
        """CREATE TABLE IF NOT EXISTS listing_versions (
            id {id},
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            created_at BIGINT NOT NULL,
            make TEXT,
            model TEXT,
            trim TEXT,
            year_jalali INTEGER,
            mileage_km INTEGER,
            price_toman BIGINT,
            negotiable INTEGER NOT NULL DEFAULT 0,
            city TEXT,
            gearbox TEXT,
            fuel TEXT,
            color TEXT,
            body TEXT,
            description TEXT,
            show_phone INTEGER NOT NULL DEFAULT 0,
            review TEXT NOT NULL DEFAULT 'pending',
            reviewed_at BIGINT,
            reason TEXT)""",
        "CREATE INDEX IF NOT EXISTS listing_versions_listing ON listing_versions(listing_id)",
        "CREATE INDEX IF NOT EXISTS listing_versions_review ON listing_versions(review)",
        """CREATE TABLE IF NOT EXISTS reports (
            id {id},
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            reason TEXT NOT NULL,
            who_key TEXT NOT NULL,
            created_at BIGINT NOT NULL,
            UNIQUE (listing_id, who_key))""",
        """CREATE TABLE IF NOT EXISTS reveals (
            id {id},
            listing_id BIGINT NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
            who_key TEXT NOT NULL,
            at BIGINT NOT NULL)""",
        "CREATE INDEX IF NOT EXISTS reveals_listing ON reveals(listing_id)",
    )),
    # The province, chosen from the 31 (caro/ingest/persian.py); the city
    # stays as the seller wrote it, and is never read for the province.
    (2, (
        "ALTER TABLE listing_versions ADD COLUMN province TEXT",
    )),
)

TABLES = ("accounts", "sessions", "login_codes", "attempts", "listings",
          "listing_versions", "reports", "reveals")


def phone_09(raw: object) -> str | None:
    """A mobile number as the store keeps it, "09" and nine digits, from the
    ways people write one: Persian or Arabic-Indic digits, spaces, dashes,
    dots and brackets, +98 or 0098 in front, or the leading 0 left off. None
    for anything else, a landline included."""
    if not isinstance(raw, str):
        return None
    s = re.sub(r"[\s\-.()\u200c]", "", raw.translate(_DIGITS))
    for prefix in ("+98", "0098"):
        if s.startswith(prefix):
            s = "0" + s[len(prefix):]
            break
    if re.fullmatch(r"(98)?9\d{9}", s):
        s = "0" + s[-10:]
    return s if PHONE.fullmatch(s) else None


class Store(Database):
    """The seller store: `caro.sql.Database`, with the store's limits, its
    keyed hashes and its accounts."""

    def __init__(self, conn: Any, dialect: Dialect, secret: str,
                 clock: Callable[[], float] = time.time):
        super().__init__(conn, dialect, clock)
        self._secret = secret.encode("utf-8")

    # ---- the limits ----------------------------------------------------------
    def blocked(self, kind: str, who: str,
                limits: tuple[tuple[int, int], ...]) -> int | None:
        """The seconds until `who` may try `kind` again, under limits given as
        (how many, in how many seconds); None when no limit is reached."""
        now, wait = self.now(), None
        for most, window in limits:
            got = self.rows("SELECT at FROM attempts WHERE kind = ? AND who_key = ? AND at > ? "
                            "ORDER BY at DESC", (kind, who, now - window))
            if len(got) >= most:
                # open again when the attempt that filled the window leaves it
                w = int(got[most - 1]["at"]) + window - now
                wait = max(wait or 0, max(1, w))
        return wait

    def record(self, kind: str, who: str) -> None:
        now = self.now()
        self.execute("INSERT INTO attempts (kind, who_key, at) VALUES (?, ?, ?)", (kind, who, now))
        self.execute("DELETE FROM attempts WHERE at < ?", (now - ATTEMPTS_KEPT_S,))

    # ---- keyed hashes ------------------------------------------------------
    def key(self, kind: str, value: str) -> str:
        """HMAC-SHA256 of a value under the store's secret, with its kind in
        it, so a phone and an address that are the same text get different
        keys."""
        msg = f"{kind}\x00{value}".encode("utf-8")
        return hmac.new(self._secret, msg, hashlib.sha256).hexdigest()

    # ---- the schema --------------------------------------------------------
    def version(self) -> int:
        return self.schema_version("schema_migrations")

    def _migration_lock(self) -> None:
        if self.dialect.migration_lock:
            self.execute(self.dialect.migration_lock)

    def migrate(self) -> list[int]:
        """Applies the migrations this database does not have, in order, and
        gives their numbers. A second call applies nothing. Each runs under
        the dialect's lock, so two processes starting at once apply it once.
        `MIGRATIONS` is read when this runs, not when it was defined."""
        return self.apply_migrations(MIGRATIONS, table="schema_migrations",
                                     lock=self._migration_lock)

    # ---- accounts ----------------------------------------------------------
    def create_account(self, phone: str) -> int:
        """An account for a number written as 09 and nine digits; anything
        else is a caller's fault and never reaches the database."""
        if not isinstance(phone, str) or not PHONE.fullmatch(phone):
            raise ValueError("a phone number is 09 and nine digits")
        return self.insert("INSERT INTO accounts (phone, created_at) VALUES (?, ?)",
                           (phone, self.now()))


def open_store(url: str | None = None, secret: str | None = None, *,
               clock: Callable[[], float] = time.time,
               importer: Callable[[str], Any] = importlib.import_module,
               migrate: bool = True) -> Store | None:
    """The store `DATABASE_URL` names, migrated, or None when it names none.
    A store that is named and cannot be used raises StoreError."""
    url = (url if url is not None else os.environ.get("DATABASE_URL", "")).strip()
    if not url:
        return None
    secret = secret if secret is not None else os.environ.get("CARO_STORE_SECRET", "")
    if len(secret or "") < MIN_SECRET_CHARS:
        raise StoreError(f"CARO_STORE_SECRET is not set or is shorter than "
                         f"{MIN_SECRET_CHARS} characters")
    conn, dialect = connect(url, setting="DATABASE_URL", what="the store",
                            error=StoreError, importer=importer)
    store = Store(conn, dialect, secret, clock)
    if migrate:
        store.migrate()
    return store
