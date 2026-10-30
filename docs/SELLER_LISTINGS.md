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
| city | one of the cities the site knows; the province from it, said to be from the city |
| gearbox, fuel, colour, body | the site's own classes |
| description | the seller's text, up to 1,000 characters, no link and no number in it (a number in prose is how a phone escapes the reveal) |
| show the number | yes or no, no by default |

**Photos — decide.** A photo needs a file store (Vercel Blob, S3 or the
like) and a check that it is a car and not a face or a number written on
card. Proposed: none in the first version.

## Before a listing is seen

- **Every listing waits for the operator.** New and edited listings are
  «در انتظار تأیید» until approved in the admin view (which opens with the
  token and the code, O1); a rejection carries its reason, which the seller
  sees. **Decide:** approval for every listing (proposed), or only for the
  first of each account.
- **One active listing per number** for a private seller. **Decide:** whether
  dealers get more, and how a dealer is told apart (proposed: the operator
  marks the account; no badge from anything the seller writes, as D26 has it).
- **A listing lives 30 days**, renewable by its seller, and is deleted 90 days
  after it ends. Its seller can delete it at any time, and then it is gone.
- **«گزارش آگهی»** on every listing: a reason from a short list; three
  reports take it down until the operator looks.

## What the owner gives

| Choice | What it is | Proposed |
|---|---|---|
| **decide** the store | where accounts and listings live in production | Postgres (Neon or Vercel Postgres), `DATABASE_URL`; SQLite, from Python's own library, on a laptop and in the suites |
| **decide** the SMS provider | who sends the codes | any with an HTTP API and a template (Kavenegar, SMS.ir, Ghasedak); the code talks to one interface and a fake one in the suites |
| the template | the text the provider approves | «کد ورود کارو: {code}» |
| the session secret | signs nothing but the cookie's hash | `CARO_SESSION_SECRET`, made locally, set by the deploy holder |
| a privacy page | what is kept, for how long, how it is deleted | drafted by a session, approved by the owner |

No key is written into the repository or a chat; the code reads each from the
environment, and the suites run with made-up ones.

## The order of the build

Each step a round of its own: predictions first, its tests, mutants, its own
commits, a delivery.

1. **The store** -- tables for accounts, sessions, codes, listings, reports and
   reveals; migrations that only add; SQLite and Postgres behind one module.
2. **The login** -- send a code, check it, the session, logout, «حذف حساب»,
   with the fake provider; the limits in the store.
3. **The listing** -- the form's rules on the server, the seller's list,
   edit, renew, delete; the reveal and its limit.
4. **The operator** -- pending, approve, reject with a reason, the reports.
5. **The site** -- «ورود», «آگهی‌های من», «ثبت آگهی», the public list, the
   section on a model's page, «نمایش شماره», «گزارش آگهی».
6. **The provider** -- the one the owner chose, behind the same interface,
   tried by the owner on the owner's own number before anyone else's.

The corpus guards stay as they are and gain one: no first-party listing, and
no phone number, ever reaches `data/corpora/` or an answer of the decision
API.
