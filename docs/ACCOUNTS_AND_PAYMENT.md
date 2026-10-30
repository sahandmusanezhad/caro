# Accounts, payment and the way to the seller — the options

Written 2026-10-30, before anything of it is built. The owner asked for the
parts a site like Torob has: a page per product, the cheapest offer first,
something a buyer keeps, an account, a payment. This document says what of
that exists, what each remaining part would be, what it needs that only the
owner can give, and which option a session recommends. Nothing below is built
until the owner has chosen (ROADMAP, the product gaps, item 4), and every
choice the owner makes becomes a D-entry once it is pushed.

**Chosen on 2026-10-30:** B1 and O1, both built the same day -- the page
`/before-buying`, with the draft's text, and the operator's second step in
`webapp/api/totp.py`. A0 and P0 stand: no account and no payment.

## What exists now

- **A page per model** (`/models`, `/model/[make]/[model]`, from
  `GET /api/models` and `GET /api/model`): every listing of a model in the
  corpus being served, the priced ones cheapest first; the range of asking
  prices; the middle by year; and the middle in every published run, given
  only where three priced listings stand behind it. Each listing links to its
  file and to the source it was read from.
- **Listings a person keeps** (`/saved`, `webapp/web/lib/saved.ts`): ids in
  the browser's own storage, under one key, sent nowhere. No account, no
  server, nothing personal leaves the device. A second device does not see
  them, and clearing the browser forgets them; that is the price, and the page
  says so.
- **The way to the seller** ends at the source. CARO stores no seller's phone
  number and shows none (DATA_CONTRACT); «دیدن در منبع ↗» opens the listing
  where it was published, with `rel="noopener noreferrer nofollow"`, and the
  buyer contacts the seller there. This is how a comparison site works: it
  sends the buyer to the shop; it does not stand between them.
- **No account and no payment.** The one login is the operator's: the admin
  view opens with `CARO_ADMIN_TOKEN`, fails closed when it is unset, and
  counts failed tokens per address (`webapp/api/security.py`).
- **No store that keeps anything on the deployed site.** A serverless
  function's disk keeps nothing, which is why the contact inbox is off there
  (`CARO_INBOX=off`, D68). Every option below that remembers a person needs
  that store first.

## The way to the seller

| | What it is | Needs | Recommended |
|---|---|---|---|
| **B0** | As now: the source's own page, by link. | nothing | ✅ keep |
| **B1** | B0, and a page «پیش از خرید» — what to check before paying, in plain steps (the text is at the end of this document). | the owner's wording; it is a statement about buying a car in Iran, so it is the owner's | ✅ chosen and built, 2026-10-30 |
| **B2** | Booking an inspection through a partner. | a partner, a contract, and a way to pay them | ❌ not now |

CARO does not take a buyer's money for a car, and none of the options below
changes that. A car changes hands at a notary with its documents; a site that
held the price in between would be holding sums it cannot insure, under rules
this project has not read. If the owner ever wants it, it is a business of
its own, and a document of its own.

## Accounts

What an account would give that the browser does not: the saved listings on
every device, and — once collection runs over time (ROADMAP, step 5) — saved
searches and an alert when a model at a price appears. Until that collection
exists, an alert has nothing to watch: the corpus is a handful of published
runs, not a feed.

| | Login | Needs from the owner | For | Against |
|---|---|---|---|---|
| **A0** | none — as now | nothing | nothing personal is kept; nothing to leak | one device; no alerts |
| **A1** | phone number and a code by SMS | an SMS provider's account, an approved message template, its key in the deploy's environment; the store | what Iranian buyers already use on Divar and Torob | a cost per message; phone numbers are personal data, kept and guarded |
| **A2** | a link by e-mail | a mail provider's account and its key; the store | cheap; no SMS cost | e-mail is not how most buyers here sign in |
| **A3** | a passkey (WebAuthn) | the store | no third party, no code to intercept, no cost | unfamiliar; a lost device needs a way back, which is A1 or A2 again |

**Recommended: A0 until alerts can exist, then A1.** An account that only
moves a list between devices is not worth the phone numbers it would keep.

If A1 is chosen, it is built under these rules, each with its test:

- A code is six digits, lives two minutes, is kept only as an HMAC under a
  server secret, and dies after five wrong tries.
- Codes are limited per phone and per address in a **shared** store (Redis or
  the database). The limiter in `security.py` is per process and says so; on
  a serverless deployment it does not hold, so it is not what guards a
  message that costs money.
- The answer to «send me a code» is the same whether the number has an
  account or not, so the endpoint cannot be used to learn who is a member.
- A session is a random 256-bit token in an `HttpOnly`, `Secure`,
  `SameSite=Lax` cookie, kept only as a hash on the server, renewed on login,
  deleted on logout, and expired after thirty idle days. The site and the API
  share an origin in production, so CORS stays without credentials.
- Every request that changes something is a `POST` whose `Origin` must be the
  site's own.
- The account keeps the phone number and what the person saved, nothing
  else: no name, no national code. «حذف حساب» deletes all of it at once.
- Nothing in an account ever holds a seller's number. That rule is the
  corpus's, and an account does not get around it.

The OTP rule in the working agreement is about the sources: CARO never logs
into a source's account, by OTP or otherwise. A code CARO sends its own users
is a different thing, and the owner's choice.

## The operator's login

ROADMAP's product gap 4 asks for a login by authenticator, and leaves its
design to the owner.

| | What it is | Needs | Recommended |
|---|---|---|---|
| **O0** | As now: one token in the environment. | nothing | — |
| **O1** | The token **and** a six-digit code from an authenticator app (TOTP, RFC 6238), the shared secret in the environment beside it. | one more secret for the deploy holder to set; an app on the owner's phone | ✅ chosen and built, 2026-10-30 |
| **O2** | O1 for several operators, each with their own secret. | the store | when there is a second operator |

O1 needs no store, no third party and no cost: the code is computed from the
secret and the clock on both sides. The failed-attempt count that guards the
token today guards the code too, and a code is accepted once.

## Payment

Payment is for something CARO itself sells. The candidates, none of which
exists yet:

- a report on one car: its listings over the runs, the model's range, and
  what the file shows and does not show;
- alerts, once there are alerts (A1 and collection over time);
- a dealer's listing shown first — which a comparison site that ranks by
  evidence should not sell, and this document does not recommend.

| | What it is | Needs from the owner | Recommended |
|---|---|---|---|
| **P0** | none | nothing | ✅ until there is a product |
| **P1** | an Iranian payment gateway (a PSP on Shaparak, or a bank's own) for one product | a merchant account; the site's eNamad and whatever else the gateway asks; a domain of its own registered with it; and an answer to two questions first — whether the gateway answers a server hosted outside Iran, and whether the hosting's terms allow it | when a product is chosen |

If P1 is chosen, it is built under these rules:

- The card is typed on the gateway's page, never on CARO's. CARO receives a
  reference, not a card number, and keeps no card data at all.
- The amount is computed on the server from the product, never taken from the
  browser, and stored in **one** unit with that unit in its name. The
  corpus's own history is the reason: a rial read as a toman is a tenfold
  error, and it happened (the Divar page's prices are rials).
- An order is written before the buyer is sent to the gateway; on the way
  back the payment is verified server to server, and only a verified payment
  delivers anything. The gateway's reference is unique in the store, so a
  callback that arrives twice delivers once.
- Every step is logged with the order, and the day's orders are reconciled
  against the gateway's own report. Refunds are by hand, by the operator.
- The suites test it against a fake gateway, offline; the gateway's sandbox
  is the owner's to run, on the owner's machine, like every other live request.

## What the owner gives, for each choice

| Choice | The owner | The deploy holder |
|---|---|---|
| B1 | approves the checklist's text | — |
| O1 | chooses O1; installs an authenticator app | sets `CARO_ADMIN_TOTP_SECRET` |
| A1 | chooses a provider and opens its account; gets the template approved | creates the store; sets `DATABASE_URL`, `CARO_SMS_API_KEY`, `CARO_SESSION_SECRET` |
| P1 | chooses the product and the gateway; the merchant account, eNamad and domain | sets `CARO_PAYMENT_MERCHANT_ID`; adds the callback domain |
| the store (A1, A2, A3, O2, and the inbox) | chooses where it lives | creates it and sets its address |

No key is ever put in the repository, sent in a chat, or given to a session:
the code reads each from the environment, and its tests run with made-up
values.

## The order, if everything is chosen

1. **The store**, with migrations that only add. It also turns the contact
   inbox on where the site is deployed (the product gaps, item 5).
2. **O1** — small, and independent of the rest.
3. **A1**: send a code, check it, the session, logout, «حذف حساب»; the saved
   listings move from the browser into the account at the first login, and
   the browser keeps working for whoever does not log in.
4. **Saved searches and alerts**, after collection over time exists.
5. **P1** for the one product chosen.

Each step is its own round: predictions first, its tests, its own commits, and
its D-entry after the push.

## A draft for B1 — «پیش از خرید»

The owner approved it on 2026-10-30, and `/before-buying` draws it word for
word (`components/BeforeBuying.tsx`; the screens suite holds the two to one
text). It is written in the site's spelling, «ه‌ی» for the ezafe.

> ۱. قیمت را با آگهی‌های همان مدل و همان سال مقایسه کن؛ صفحه‌ی هر مدل در کارو
> آگهی‌ها را از ارزان به گران نشان می‌دهد.
>
> ۲. پیش از دیدن خودرو بیعانه نده.
>
> ۳. خودرو را پیش کارشناسی ببر که فروشنده معرفی نکرده است، برای فنی و بدنه.
>
> ۴. سند و کارت خودرو را ببین و شماره‌ی شاسی و موتور را با خود خودرو تطبیق
> بده.
>
> ۵. خلافی، بیمه‌نامه و معاینه‌ی فنی را استعلام کن.
>
> ۶. قرارداد را بنویس، سند را در دفترخانه منتقل کن و پول را از راه بانکی
> بپرداز تا ردش بماند.
>
> ۷. کارو شماره‌ی فروشنده را نگه نمی‌دارد و نشان نمی‌دهد؛ با فروشنده در خود
> سایتی که آگهی را منتشر کرده تماس بگیر.
