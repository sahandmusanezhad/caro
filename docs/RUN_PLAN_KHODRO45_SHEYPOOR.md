# Khodro45 and Sheypoor — the first reads, offline then live: plan and predictions

Written 2026-10-29, **before either read**, from what the owner's probes of that
day showed (Khodro45 `/buy-car/`, 577,043 bytes; Sheypoor `/s/iran/car`,
600,924 bytes; both plain GETs, both saved on his machine). The adapters were
built offline against the shapes the probe printed and nothing else
(`caro/ingest/khodro45.py`, `caro/ingest/sheypoor.py`). A prediction that turns
out wrong is reported as wrong, with its number; this file is not edited after
the reads, and what they show goes in the next D-entry
([WORKING_AGREEMENT](WORKING_AGREEMENT.md)). The runs are the owner's: a
session does not start a request to a source.

## Step 0 — offline, on the pages already saved (no request at all)

```
python3 scripts/first_run.py --source khodro45 --page ~/caro-probes/20261029T023237Z-khodro45/01-385b5b1f.html
python3 scripts/first_run.py --source sheypoor --page ~/caro-probes/20261029T024503Z-sheypoor/01-6c76758a.html
```

No network, no salt, nothing written. Each prints the inventory, the funnel
and its page report (counts and categories only: no title, no id, no
listing's price but the smallest, the middle and the largest). Read it before
sending it, as always.

What they should print, from the predictions locked before the code
(sha256 `04631165…` for Khodro45, `fb47646e…` for Sheypoor):

- **Khodro45.** 12 listings from 12 results and 12 cards; the cards show ONE
  of the two price fields on all 12 (which one is not known — the survey masked
  the card's digits — and the line `card shows` answers it); 11 prices and one
  without (`price_type 4`); asking prices between 1.19 and 8.59 billion toman;
  12 odometers agreeing with the cards; 12 years, one Gregorian; the site's
  count 1812; the next page `/api/v#/car_listing/?limit&offset&ordering`.
- **Sheypoor.** At most 26 listings (fewer if a promoted card repeats); about
  one in five «توافقی» or with no figure; prices in toman, from tens of
  millions to a few billion; a year from the title on under a third and an
  odometer on fewer, so the funnel's eligible count is 0 to 3. That is the
  finding, not a fault: the list's cards give no year and no odometer.

## Before the live runs

1. The review the ROADMAP names (the product gaps, item 1) for each site: its
   terms and its robots directives for the car list, read by the owner, and
   the finding recorded whatever it says. If the terms forbid this use, that
   site's run does not happen.
2. `git status` clean on `divar-page-round`; `python3 tests/run_all.py` green.
3. A salt that lives outside the repository:
   `export CARO_SELLER_SALT="$(head -c 24 /dev/urandom | base64)"`.

## The live runs

```
python3 scripts/first_run.py --source khodro45 --pages 2
python3 scripts/first_run.py --source sheypoor --pages 2
```

Khodro45: `robots.txt`, `/buy-car/`, and the page its `next` names — a page of
the site's API, what its own list loads when a visitor scrolls — only if it is
on khodro45.com and robots.txt allows it. If not, the run keeps page 1 and
prints `stopped early: the next page (…) is not requested`. Sheypoor:
`robots.txt`, `/s/iran/car`, and the page its `rel=next` names
(`?page_num=2`). A pause of two to five seconds, now and then longer, after
every request. No login, no click, no contact. A page that does not answer
ends the run; **do not retry harder, change the User-Agent, or wait less.** A
block is a result and goes in the record.

## What to send back

The two `… PAGE READ` blocks, the COLLECTION FUNNEL and any `stopped early`
line of each run, and the result of a search for phone-shaped strings in what
was written:

```
grep -rcE '09[0-9]{9}|\+98[0-9]{10}' data/snapshots/*/khodro45-*.json data/snapshots/*/sheypoor-*.json
```

(the search Divar's plan uses), which should print 0 for each file: no adapter
reads a seller field, and none is on either list. A number-like string in a
snapshot is a leak: stop, tell the session, publish nothing.

## Predictions for the live runs, written before them

- **L1.** Khodro45's page 1 reads as the saved page did, and `card shows`
  names the same field.
- **L2.** Khodro45's API page is either asked for and read — twelve listings
  more, priced by the field the cards showed (`structured_only`), with an
  address by the rule the cards' links followed — or not asked for, with the
  reason printed. Which one is not known here: robots.txt has nine rules this
  session has not read.
- **L3.** Sheypoor's page 2 holds other listings than page 1; a promoted card
  shown again is counted under `duplicates`, not as new.
- **L4.** Sheypoor's eligible count stays at 0 to 3 for the two pages: the
  list cannot price a car.

## The next probe: one Sheypoor listing page

The year and the odometer are on the listing page, which nothing here has
read. Two links from the page already saved, then one probe and a survey:

```
grep -o 'href="/v/[^"]*"' ~/caro-probes/20261029T024503Z-sheypoor/01-6c76758a.html | head -2
python3 scripts/page_probe.py --source sheypoor --origin https://www.sheypoor.com \
    --url "https://www.sheypoor.com<the first href>" --url "https://www.sheypoor.com<the second>"
python3 scripts/page_probe.py --survey ~/caro-probes/<the new run>/01-….html
```

## Decisions that are the owner's, and are not made here

- **Khodro45's role.** D15 names three sources with a role each; Khodro45 has
  none, and `cross_source` has no profile for it.
- **`price_type` 4.** One of the 12; its listing carries no price until such a
  card has been read on the site.
- **Khodro45's API pages.** robots.txt decides in code whether they may be
  asked for; whether they should be, beyond that, is the owner's call. With
  `--pages 1` nothing past `/buy-car/` is requested.
- **Sheypoor's corner image.** An image at the top right of some cards' photo,
  all of them titled «فروش سازمانی» or «فروش دولتی» on the saved page: a shop's
  logo, perhaps. Counted, and `seller_type` stays unknown (D26). The optional
  branch carries the rule that reads it as a dealer, for the owner to take or
  leave.
- **Divar.** What a NewCondition car is in a used-car corpus (counted since
  this round), and what «paintless-dent-removal» is (the optional branch maps
  it to `minor_paint`, as the prose table reads «صافکاری»).

## Addendum — 2026-10-29, after the offline reads

The sections above are as they were written before the reads; this one says
what the reads found and what that changes for the live runs. The full
record goes in the D-entry after the owner's push.

- **Khodro45.** The page holds 24 results in two lists of 12, not 12, and 24
  cards (the survey shows one list of each size). Its `slug` is not the code
  the card's link ends in, so the first read joined no card and priced
  nothing; joined by odometer and year, all 24 matched, the cards show
  `final_price` on all 24, and 23 are eligible (one is `price_type` 4). The
  shapes say the code is «cla-» and the slug in another case, and the adapter
  now joins by that and learns the address rule from the cards. The next page
  is given as `http://khodro45.com/api/v2/car_listing/?limit=12&offset=24&…`
  and is asked for over `https://`, the same host, path and query.
- **Sheypoor.** 26 listings from the list, 24 with a price, none with an
  odometer; the listing page, probed since, holds the year, the odometer, the
  gearbox, the fuel, the colour, the condition and a price with its currency
  code in its JSON-LD. A live run now asks for the listing page of each new
  listing, up to `--limit` (50 by default), so the first one should be small.

Before the live Sheypoor run, the owner's three saved pages read offline, the
list and the two listing pages (no request):

```
python3 scripts/first_run.py --source sheypoor --page ~/caro-probes/20261029T024503Z-sheypoor/01-6c76758a.html ~/caro-probes/20261029T162509Z-sheypoor/01-ca72f8d7.html ~/caro-probes/20261029T162509Z-sheypoor/02-f3f9c8ea.html
```

It should print 26 listings, the two listing pages merged into their cards,
one currency code on both (which one is not known: IRR, IRT or TOMAN, else
«unrecognised currency» and the card's price stands) and the unit code KMT
(sha256 `f782aa9b…`, written before the code).

The live runs, as they are now:

```
python3 scripts/first_run.py --source khodro45 --pages 2
python3 scripts/first_run.py --source sheypoor --pages 1 --limit 10
```

Khodro45: robots.txt, `/buy-car/` (24 listings) and the API page at offset 24
(12 more) if robots.txt allows `/api/`; three requests. Sheypoor: robots.txt,
`/s/iran/car` and ten listing pages; twelve requests, the pause after each.

