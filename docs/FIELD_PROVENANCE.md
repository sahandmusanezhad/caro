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
may show it — that is the separate **UI eligibility** column, and the two are
kept apart deliberately. A schema may carry an optional field long before any
renderer is allowed to draw it.

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

| field | status | filled | distinct | UI eligible | note |
|---|---|---|---|---|---|
| `listing_id` | `SOURCE_BACKED` | 76/76 | 76 | key only | not shown; identity |
| `source_url` | `SOURCE_BACKED` | 76/76 | 76 | yes | the source's own statement of where the listing lives |
| `make` | `SOURCE_BACKED` | 76/76 | **1** | display yes, filter **no** | one value on this corpus — see *coverage is not variety* |
| `model` | `SOURCE_BACKED` | 76/76 | 3 | yes | |
| `trim` | `SOURCE_BACKED` | 76/76 | 22 | yes | |
| `year_jalali` | `SOURCE_BACKED` | 76/76 | 18 | yes | |
| `color` | `SOURCE_BACKED` | 75/76 | 7 | yes | |
| `asking_price_toman` | `SOURCE_BACKED` | 74/76 | 55 | yes | 2 listings carry no price and must render as such |
| `price_status` | `SOURCE_BACKED` | 76/76 | 3 | yes | what is known about the number, not only the number |
| `price_kind` | `SOURCE_BACKED` | 76/76 | 2 | yes | cash · negotiable · financing_total · absent (D52) |
| `price_kind_source` | `SOURCE_BACKED` | 76/76 | 2 | detail only | |
| `mileage_km` | `SOURCE_BACKED` | 73/76 | 59 | yes | 3 listings carry none |
| `mileage_status` | `SOURCE_BACKED` | 73/76 | 1 | yes | travels with the number or neither is shown |
| `mileage_line_canonical` | `SOURCE_BACKED` | 73/76 | 59 | detail only | canonicalised, not the source's prose |
| `condition` | `SOURCE_BACKED` | 74/76 | 5 | yes | the body-condition block (D45) |
| `condition_source` | `SOURCE_BACKED` | 74/76 | 1 | detail only | `field` here — never `description` on this corpus |
| `product_class` | `SOURCE_BACKED` | 76/76 | 2 | filter yes | a حواله is not a used car at any price (D52) |
| `product_class_source` | `SOURCE_BACKED` | 76/76 | 1 | no | |
| `dealer_badge` | `SOURCE_BACKED` | 76/76 | **1** | no | `false` on every row; carries no information here |
| `document_issue` | `SOURCE_BACKED` | **1/76** | 1 | **no** | one row in seventy-six is not a field a screen can use |
| `seller_type` | `PENDING_LIVE_VALIDATION` | **0/76** | 0 | no | inferred only from a business badge, never from a person (D26) |
| `province` | `PENDING_LIVE_VALIDATION` | — | — | no | empty on all 76 snapshot records, so promotion dropped the key; reading it off the page landed in `8e34dba`, after this corpus |
| `gearbox` | `PENDING_LIVE_VALIDATION` | — | — | no | crosses the boundary since `2ddbc72`; never promoted into a corpus |
| `fuel` | `PENDING_LIVE_VALIDATION` | — | — | no | as above |
| **title** | `DERIVED` | — | — | yes | composed from `make + model + trim + year_jalali` |
| **image** | `UNAVAILABLE` | — | — | no | see below |
| **listing age** | `EVIDENCE_ONLY` | — | — | see below | `data/observations/date_watch.jsonl`, under D58's scope |

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
`asking_price_toman` (55) and `mileage_km` (59), and excludes `make`,
`dealer_badge`, `condition_source`, `mileage_status` and `product_class_source`
from being filters — several of which are still worth showing.

## The three fields that are not corpus fields

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

**listing age — `EVIDENCE_ONLY`.** No corpus field carries a posting date. The
only channel that reads one is `scripts/date_watch.py`, whose observations are
operational and unpublished; `data/derived/date_watch_summary.json` carries the
four fields that may leave it. D58 applies **at its own scope and no wider**:
in that corpus, with extractor v4, `phrase_days` was never observed at 7 or
above and was absent in all 34 observations of age 7 to 29. It is not a general
rule about the source. A screen that shows an age therefore shows it for
listings inside that window, says what it does not know outside it, and never
converts the absence into a number.

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
