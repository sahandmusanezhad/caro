# Listings sellers post themselves — the design, before the code

Written 2026-10-30. The owner wants a buyer who finds a car on CARO to be able
to reach its seller. CARO does not collect sellers' numbers from the sources
and will not (DATA_CONTRACT: no contact identifier in any field; the sources
show them only behind their own login), and the link to each listing on its
source now says that the seller is reached there. The other way, the one this
document designs, is a seller who posts a car on CARO itself and chooses to
show a number. The owner chose to build it alongside the first live runs (A1
in [ACCOUNTS_AND_PAYMENT](ACCOUNTS_AND_PAYMENT.md)).

Every default below is a session's proposal; the ones marked **decide** are
the owner's, and the code waits for nothing but them.

**Chosen on 2026-10-30:** no photos in the first version; the operator
approves every listing and every edit; Postgres in production and SQLite on
a laptop and in the suites; the SMS provider later, so the login is built
against a fake one. Still the owner's: dealers, and the Postgres driver
(below, «The store»).

## What it is, and what it is not

- **A second kind of listing, kept apart.** A listing a seller posts is
  written by its owner for publication. It is not the corpus: it never enters
  `data/corpora/`, is never scored by the estimator, and is never evidence in
  a decision. It is drawn under its own heading, «آگهی‌های ثبت‌شده در کارو»,
  on its own page and beside a model's corpus listings, never mixed into them.
- **Its contact is its seller's choice.** The number is the one the seller
  logged in with, verified by the code it received; it is shown only where the
  seller ticked «نمایش شماره», and then only to a visitor who presses «نمایش
  شماره» -- never in the page's HTML, its JSON or its structured data, where a
  crawler would read it. Each reveal is counted and limited per address.
- **Not a marketplace.** No payment, no escrow, no messaging between buyer
  and seller (P0 stands). The buyer calls; the deal is theirs.

## Login (A1)

As [ACCOUNTS_AND_PAYMENT](ACCOUNTS_AND_PAYMENT.md) set it out: a phone number
and a six-digit code by SMS, the code alive two minutes, kept only as an HMAC,
five wrong tries and it dies; limits per phone and per address in the store,
not in a process; the same answer whether the number has an account or not; a
session in an `HttpOnly`, `Secure`, `SameSite=Lax` cookie, kept only as a hash,
renewed at login, gone at logout, expired after thirty idle days; every change
a `POST` whose `Origin` must be the site's. An account holds the number and
the seller's listings, nothing else. «حذف حساب» deletes both.

## A listing

| Field | Rule |
|---|---|
| make, model, trim | the site's table of names, or the seller's own words, kept as written |
| year | Jalali, 1300 to next year |
| mileage | km, 0 to 2,000,000; «کارکرد صفر» only with a year this year or next |
| price | toman, cash, or «توافقی»; the same floor the corpus gate has |
| province and city | the province one of the 31 (`caro/ingest/persian.py`); the city as the seller writes it, kept verbatim and never read for the province -- the code holds no city list, on purpose |
| gearbox, fuel, colour, body | the site's own classes |
| description | the seller's text, up to 1,000 characters, no link and no number in it (a number in prose is how a phone escapes the reveal) |
| show the number | yes or no, no by default |

**Photos — chosen: none in the first version.** A photo needs a file store
(Vercel Blob, S3 or the like) and a check that it is a car and not a face or
a number written on card.

## Before a listing is seen

- **Every listing and every edit waits for the operator** (chosen). New
  and edited listings are «در انتظار تأیید» until approved in the admin view
  (which opens with the token and the code, O1); a rejection carries its
  reason, which the seller sees. An edit is a new version of the listing:
  the approved version stays public while the edit waits, is replaced when
  the edit is approved, and stays when it is rejected. So an edit cannot
  put unreviewed words on a page.
- **One active listing per number** for a private seller. **Decide:** whether
  dealers get more, and how a dealer is told apart (proposed: the operator
  marks the account; no badge from anything the seller writes, as D26 has it).
- **A listing lives 30 days**, renewable by its seller, and is deleted 90 days
  after it ends. Its seller can delete it at any time, and then it is gone.
- **«گزارش آگهی»** on every listing: a reason from a short list; three
  reports take it down until the operator looks.

## The store

Production keeps it in Postgres and a laptop and the suites in SQLite, from
Python's own library; one module, `webapp/api/store.py`, speaks to both, and
the SQL is the part of it the two share. Where they differ -- the id column,
how a parameter is written, how a write transaction begins -- is one table in
that module, and nothing else in the code knows which one it has.

- **No store is assumed.** It is `DATABASE_URL`: `postgresql://…` or
  `sqlite:///<path>`. Without it the seller pages are off and say so, the
  way the inbox is off where a disk keeps nothing (D68): a deployment that
  took a listing into a file a serverless function forgets would be handing
  out a receipt for nothing.
- **Migrations only add.** Each is a numbered list of `CREATE TABLE`,
  `CREATE INDEX` and `ALTER TABLE … ADD COLUMN`, recorded in
  `schema_migrations` when applied; nothing renames, drops or changes a
  column, so the code before a migration works on the database after it. The
  suites hold every statement to that.
- **What is kept, and how.**

  | Table | Holds |
  |---|---|
  | `accounts` | the phone number, written as `09…`, and when the account was made; nothing else |
  | `sessions` | the SHA-256 of the session's token, never the token; its account; when it was made and last used |
  | `login_codes` | a keyed hash of the phone and one of the code, never either in clear; when it dies; the wrong tries |
  | `attempts` | for the limits: what was tried, by whom as a keyed hash of a phone or an address, and when |
  | `listings` | its seller; when it ends; which version is public; whether reports have taken it down |
  | `listing_versions` | each version's fields, in the units their names say (`price_toman`, `mileage_km`, `year_jalali`), and the operator's verdict on it with its reason |
  | `reports` | a listing, a reason from the short list, and the keyed hash of the address that sent it |
  | `reveals` | a listing, the keyed hash of the address that pressed «نمایش شماره», and when |

  A phone number in clear is in `accounts` alone, and only after its owner
  answered the code. Deleting an account deletes its sessions, its listings
  and everything under them, by the database's own cascade.
- **The keyed hashes** are HMAC-SHA256 under `CARO_STORE_SECRET`, so a copy
  of the database gives no code, no phone number that asked for one, and no
  address. The session's token needs no key: it is 256 random bits.
- **The Postgres driver -- decide.** Python reaches Postgres through a
  driver, which is a new dependency and so the owner's. Proposed:
  `psycopg[binary]` 3, the maintained one, added to `webapp/requirements.txt`
  only when chosen. Until then the module imports it only when
  `DATABASE_URL` is a Postgres address. The suites run on SQLite. Postgres
  is tried by hand, against a server on the session's own machine, before a
  change to the store is handed over, and the change's commit says what that
  showed.

## What the owner gives

| Choice | What it is | Chosen or proposed |
|---|---|---|
| the store | where accounts and listings live in production | chosen: Postgres (Neon or Vercel Postgres), `DATABASE_URL`; SQLite on a laptop and in the suites |
| **decide** the driver | how the API reaches Postgres | proposed: `psycopg[binary]` 3 |
| the SMS provider | who sends the codes | later; meanwhile a fake one. Any with an HTTP API and a template (Kavenegar, SMS.ir, Ghasedak); the code talks to one interface |
| the template | the text the provider approves | «کد ورود کارو: {code}» |
| the store's secret | the key of the keyed hashes above | `CARO_STORE_SECRET`, made locally, set by the deploy holder |
| the site's address | the Origin every change must come from | `CARO_SITE_ORIGINS`, set by the deploy holder; unset, the host a request came to |
| a privacy page | what is kept, for how long, how it is deleted | drafted by a session, approved by the owner |

No key is written into the repository or a chat; the code reads each from the
environment, and the suites run with made-up ones.

## The order of the build

Each step a round of its own: predictions first, its tests, mutants, its own
commits, a delivery.

1. **The store** -- tables for accounts, sessions, codes, listings, reports and
   reveals; migrations that only add; SQLite and Postgres behind one module.
   *Built 2026-10-30:* `webapp/api/store.py`, held by `tests/test_store.py`,
   whose rows were also run by hand against PostgreSQL 16.
2. **The login** -- send a code, check it, the session, logout, «حذف حساب»,
   with the fake provider; the limits in the store. *Built 2026-10-30:*
   `webapp/api/accounts.py` and `webapp/api/sms.py`, held by section 22 of
   `tests/test_api_contract.py`. The limits are proposals the owner can move:
   per phone 3 codes in 15 minutes and 6 a day; per address 6 an hour, 20 a
   day and 20 wrong codes an hour; 500 codes a day in all.
3. **The listing** -- the form's rules on the server, the seller's list,
   edit, renew, delete; the reveal and its limit. *Built 2026-10-30:*
   `webapp/api/listings.py`, held by section 23 of `tests/test_api_contract.py`,
   with migration 2 adding the province. The reveal's limit is a proposal: 10
   an hour and 30 a day per address, every press counted, a number found or
   not. A listing renewed and then left alone ends the day its seller's
   session does (both are 30 days), so renewing it after that takes a new
   login.
4. **The operator** -- pending, approve, reject with a reason, the reports.
   *Built 2026-10-30:* `webapp/api/review.py`, held by section 24 of
   `tests/test_api_contract.py`, behind the inbox's own door (the token, and
   the code where a TOTP secret is set). A report's reasons are sold, wrong,
   fake, spam, offensive and other; one address counts once for a listing,
   three take it down, and an address has 20 reports a day -- a proposal.
   Released, a listing's reports are cleared; removed, its public version is
   rejected with the reason, which its seller reads.
5. **The site** -- «ورود», «آگهی‌های من», «ثبت آگهی», the public list, the
   section on a model's page, «نمایش شماره», «گزارش آگهی».
6. **The provider** -- the one the owner chose, behind the same interface,
   tried by the owner on the owner's own number before anyone else's.

The corpus guards stay as they are and gain one: no first-party listing, and
no phone number, ever reaches `data/corpora/` or an answer of the decision
API.
