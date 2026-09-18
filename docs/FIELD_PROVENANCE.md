# Field provenance — what a screen is allowed to show, and why

Field → source → evidence → coverage → UI eligibility, for every field a card
or a detail page might want.

Written 2026-09-18, before any of those screens exist. That order is the point.
A card designed first and sourced afterwards has spaces in it that nothing
fills, and the usual repair is to fill them with something plausible. This file
is what makes that repair visible instead of easy.

It decides nothing about product or layout. It states what is there.

## The five statuses

A status says where a value would come from. It does not say whether a screen
may show it — that is the separate `card` / `detail` / `gate` / `facet`
columns, and the two are kept apart deliberately. A schema may carry an optional field long
before any renderer is allowed to draw it.

| status | meaning |
|---|---|
| `SOURCE_BACKED` | the published corpus carries it, measured below |
| `DERIVED` | computed by CARO from `SOURCE_BACKED` fields; never copied from a source |
| `EVIDENCE_ONLY` | it exists, but in an operational channel outside the corpus, under that channel's own scope |
| `UNAVAILABLE` | no published field carries it today |
| `PENDING_LIVE_VALIDATION` | the code path exists, and no real run has produced a value yet |

`PENDING_LIVE_VALIDATION` is not a weaker `SOURCE_BACKED`. A field whose
extractor has never returned anything on a real page is a field whose extractor
has never been tested against the thing it extracts from. D45 is the entry
about a field that went out in a rewrite and was not noticed for a whole
pre-registered run; a field that has never arrived at all is the same class of
ignorance with less excuse.

## What was measured, and how to measure it again

One artifact: `data/corpora/run11.json` — 76 Bama listings, collected
2026-09-10, `schema: caro.corpus/1`, the run the API serves by default and the
only publication-grade corpus in the repository (D57).

A value counts as filled when it is not null, empty, `"unknown"` or `"none"`.
Distinct counts the filled values.

```python
import json
from pathlib import Path
rows = json.loads(Path("data/corpora/run11.json").read_text(encoding="utf-8"))["listings"]
EMPTY = {None, "", "unknown", "none"}
for k in sorted({k for r in rows for k in r}):
    nn = [r.get(k) for r in rows if r.get(k) not in EMPTY]
    print(f"{k:<26}{len(nn):>4}/{len(rows):<3}"
          f"{len({json.dumps(x, ensure_ascii=False) for x in nn}):>6}")
```

## The table

`filled` and `distinct` are that script's output on run11, unedited.

| field | status | filled | distinct | card | detail | gate | facet | reason |
|---|---|---|---|---|---|---|---|---|
| `listing_id` | `SOURCE_BACKED` | 76/76 | 76 | no | no | no | no | identity; keyed on, never drawn |
| `source_url` | `SOURCE_BACKED` | 76/76 | 76 | yes | yes | no | no | the source's own statement of where the listing lives |
| `make` | `SOURCE_BACKED` | 76/76 | 1 | yes | yes | no | no | one distinct value here; a filter over it offers one choice |
| `model` | `SOURCE_BACKED` | 76/76 | 3 | yes | yes | no | yes |  |
| `trim` | `SOURCE_BACKED` | 76/76 | 22 | yes | yes | no | yes |  |
| `year_jalali` | `SOURCE_BACKED` | 76/76 | 18 | yes | yes | no | yes |  |
| `color` | `SOURCE_BACKED` | 75/76 | 7 | no | yes | no | yes |  |
| `asking_price_toman` | `SOURCE_BACKED` | 74/76 | 55 | yes | yes | no | yes | 2 listings carry no price and must render as carrying none |
| `price_status` | `SOURCE_BACKED` | 76/76 | 3 | yes | yes | no | no | extraction quality, NOT plausibility — see below |
| `price_kind` | `SOURCE_BACKED` | 76/76 | 2 | yes | yes | no | no | what the number means (D52); own namespace, see below |
| `price_kind_source` | `SOURCE_BACKED` | 76/76 | 2 | no | yes | no | no |  |
| `mileage_km` | `SOURCE_BACKED` | 73/76 | 59 | yes | yes | no | yes | 3 listings carry none |
| `mileage_status` | `SOURCE_BACKED` | 73/76 | 1 | yes | yes | no | no | travels with the number or neither renders |
| `mileage_line_canonical` | `SOURCE_BACKED` | 73/76 | 59 | no | yes | no | no | canonicalised, not the source's prose |
| `condition` | `SOURCE_BACKED` | 74/76 | 5 | no | yes | no | yes | the body-condition block (D45); `unknown` is a value, not an absence |
| `condition_source` | `SOURCE_BACKED` | 74/76 | 1 | no | yes | no | no | `field` here — never `description` on this corpus |
| `product_class` | `SOURCE_BACKED` | 76/76 | 2 | no | yes | yes | no | the grid gate: only `vehicle` renders as a car (D52) |
| `product_class_source` | `SOURCE_BACKED` | 76/76 | 1 | no | yes | no | no |  |
| `dealer_badge` | `SOURCE_BACKED` | 76/76 | 1 | no | no | no | no | `false` on every row; carries no information here |
| `document_issue` | `DERIVED` | 1/76 | 1 | no | no | no | no | one row in seventy-six, and derived — see below |
| `seller_type` | `PENDING_LIVE_VALIDATION` | 0/76 | 0 | no | no | no | no | inferred only from a business badge, never from a person (D26) |
| `province` | `PENDING_LIVE_VALIDATION` | — | — | no | no | no | no | empty on all 76 snapshot records, so promotion dropped the key; reading it off the page landed in `8e34dba`, after this corpus |
| `gearbox` | `PENDING_LIVE_VALIDATION` | — | — | no | no | no | no | crosses the boundary since `2ddbc72`; never promoted into a corpus |
| `fuel` | `PENDING_LIVE_VALIDATION` | — | — | no | no | no | no | as above |
| `derived_title` | `DERIVED` | — | — | yes | yes | no | no | composed from `make + model + trim + year_jalali` |
| `observed_at` | `DERIVED` | — | — | yes | yes | no | no | the artifact's `collected_on`, carried onto every row — see below |
| `listing_age` | `EVIDENCE_ONLY` | — | — | yes | yes | no | no | only where the evidence exists; absence renders no claim — see below |
| `image` | `UNAVAILABLE` | — | — | no | no | no | no | see below |

`card`, `detail`, `gate` and `facet` are the whole vocabulary of those four
columns: `yes` or `no`, nothing else. A guard has to read this table, and a
parser that has to interpret "see below" is a guard that will one day interpret
it wrongly.

**`gate` and `facet` are two different things and the table keeps them apart.**
A `facet` is a choice a reader makes — a brand, a year, a price range. A `gate`
is applied by the query before anyone sees a row, and nobody chooses it:
`product_class` is the only one, and only `vehicle` passes it (D52). Both are
"filters" to a query engine and neither is the same act, so they get a column
each rather than one column and a paragraph explaining which is which. A field
may be both; none is today.

**None of these four columns is derived from `filled` and `distinct`.**
Coverage and variety are inputs to the judgement, not the judgement: `make` is
filled on every row and is still `facet: no`, because one distinct value is not
a choice. `filled: 76/76` on its own authorises nothing — and `product_class`,
with two values, would fail the variety condition as a facet while being a
gate, which is the clearest case of why the two are not one column.

A dash means the field is not a key in run11 at all. `promote_corpus.py` ends
with `{k: v for k, v in out.items() if v is not None}`, so a key with no value
does not reach the artifact — and absence here therefore has three different
upstream causes, which the table keeps apart rather than flattening into
"missing":

- `province` — a key the parser produced, empty on all 76 records, dropped by
  that comprehension.
- `gearbox`, `fuel` — not produced by the parser at all on that date. The
  repair that carries them across the boundary is `2ddbc72`, later.
- `seller_type` — a key that survived, because its value is the string
  `unknown` on every row, which this file counts as unfilled. It is published
  precisely so that a car with no business badge is never published as
  `private` (D26).

## Coverage is not variety

`make` is filled on every one of the 76 rows and has exactly **one** value.
A brand filter over this corpus offers the reader a single choice, and a
ranking term computed from it moves nothing. D41 found four of six scoring
terms constant on a real corpus and the gate refusing; the same arithmetic
applies to a filter.

So UI eligibility has two conditions, not one: enough coverage to be honest,
and enough distinct values to be useful. On run11 that admits `model` (3),
`trim` (22), `year_jalali` (18), `color` (7), `condition` (5),
`asking_price_toman` (55) and `mileage_km` (59) as facets, and excludes
`make`, `dealer_badge`, `condition_source`, `mileage_status` and
`product_class_source` — several of which are still worth showing.

The variety condition applies to `facet` and not to `gate`. A gate exists to
remove rows the reader should never have been offered, so two values is all it
needs.

## Price: extraction quality is not plausibility

`price_status` and `price_kind` are two vocabularies about one number and
neither is about whether the number is believable.

`PriceStatus` — `display_confirmed`, `structured_only`, `displayed_only`,
`label_corrected`, `ambiguous`, `negotiable` — grades the extraction. The
strong case, `display_confirmed`, means the site's structured data and the
number rendered to buyers agree, so the currency label was checked rather than
trusted (D20). It is a statement about **consistency between two places on one
page**. It says nothing about whether the amount is possible for the car.

`price_kind` — `cash`, `negotiable`, `financing_total`, `absent` — says what
the number means (D52). A financing total can be display-confirmed and is
still not what anyone is asking for the car.

So a card renders an asking price only when **both** gates pass, and the rule
has to name its fields with their vocabularies, because `negotiable` is a
member of `PriceStatus` *and* a member of `price_kind` and the same word means
two different things:

    price_status ∈ {display_confirmed, …}     AND     price_kind == cash

On run11 that gate costs nothing: the two rows whose `price_kind` is not
`cash` are exactly the two rows that carry no number. Which is the reason to
write the rule now rather than when it first matters — a rule checked only
against this corpus looks complete.

**There is no `price_validity`, and mileage has one.** `Validity` grades an
odometer `plausible`, `suspicious`, `impossible` or `unknown`, and its own
docstring keeps the last two apart on purpose: a missing odometer is the seller
declining to say, a suspicious one is the seller saying something untrue.
Nothing equivalent exists for price. A row can be `vehicle`, `cash`,
`display_confirmed` and `plausible` — every gate in this file — and still
carry a number an order of magnitude away from its neighbours. `run11` contains
one such row. Whether that is a fault, and what a plausibility state for price
would have to be, belongs in `caro/ingest/quality.py` and is not settled by
observing it here. What this file fixes is narrower: nothing may read
`display_confirmed` as "plausible".

## The fields that are not corpus fields

**title — `DERIVED`.** `caro/ingest/corpus.py` lists `title` and `description`
in `FORBIDDEN_KEYS`: the source's own sentence does not enter a published
artifact. So the title on a CARO card is CARO's, composed from four fields the
corpus does carry. That is a constraint and also an improvement — Torob's
equivalent is one glued string, `پراید 131 مدل 1392 ا SE`, which cannot be
filtered, sorted or corrected.

**image — `UNAVAILABLE`.** The snapshot behind run11 carries `image_phashes` on
76 of 76 records and no image address anywhere. Perceptual hashes identify a
photograph; they do not display one. Nothing in the published corpus can render
a picture, and this file does not decide whether that should change — storing
addresses, fetching and re-hosting, and showing no photographs are three
different decisions with different consequences, and none of them belongs in a
schema. It is recorded here as a gap so that a design cannot assume its way
past it.

**observed_at — `DERIVED`.** When CARO last looked, which is a different
question from how old the listing is, and the only one of the two that can be
answered for every row. The artifact states `collected_on` once — `2026-09-10`
for run11 — and every row inherits it, so `observed_at` is available on 76 of
76 while `listing_age` is available on one. It is CARO's record of its own
looking, never the source's statement, and a screen that shows it is telling
the reader how stale the page is rather than how old the car's advertisement
is. The equivalent on Torob is the date in the page title, stated once for
several thousand listings.

**listing age — `EVIDENCE_ONLY`.** No corpus field carries a posting date. The
only channel that reads one is `scripts/date_watch.py`, whose observations are
operational and unpublished; `data/derived/date_watch_summary.json` carries the
four fields that may leave it. D58 applies **at its own scope and no wider**:
in that corpus, with extractor v4, `phrase_days` was never observed at 7 or
above and was absent in all 34 observations of age 7 to 29. It is not a general
rule about the source. A screen that shows an age therefore shows it for
listings inside that window, says what it does not know outside it, and never
converts the absence into a number. Of the 76 rows, 20 are in the watch panel
at all — `date_watch` samples twenty with `seed 0` — and one still carries an
age today.

**document_issue — `DERIVED`, and weaker than it reads.** The corpus carries a
value on one row in seventy-six; the other 75 are null. `promote_corpus.py`
takes the structured field when there is one and otherwise falls back to
`has_document_issue(desc)`, so a `false` means *the parser read the prose and
found no phrase* — not that the seller stated there is no issue. Converting a
null into a third vocabulary member (`not_reported`) is a derivation performed
by the mapping layer, not a value the corpus supplies, and that is why this
row's status is `DERIVED` rather than `SOURCE_BACKED`. Two states must never
collapse into one on a screen: `false` is a weak negative finding, null is the
absence of any finding, and neither is the seller's assurance.

## What this file does not decide

Card layout, detail layout, which fields share a row, the image question, and
whether a field with a `PENDING_LIVE_VALIDATION` status is worth a run. It also
does not close a schema: an optional field may exist in a schema while no
renderer is allowed to draw it, and that is the intended state for `province`
and `gearbox` until a real run records a coverage number here.

Nothing above is evidence about Divar, Sheypoor or Khodro45. Divar's
`CarListing` is a richer shape — it carries `city`, `gearbox`, `fuel` and
`image_urls` — and its live path has never been run, so its real coverage is
unknown rather than zero. The other two have no adapter. Any screen element
that depends on more than one source is unbacked today.

## Refreshing this file

Re-run the snippet against whichever corpus a screen is served from, and
replace the numbers. A field moves out of `PENDING_LIVE_VALIDATION` when a
real run puts a coverage number in the table beside it — not when its code is
merged, and not when a test passes over a fixture.
