# Field provenance — what a screen is allowed to show, and why

Field → source → evidence → coverage → UI eligibility, for every field a card
or a detail page might want.

Written 2026-09-18. **Correction, 2026-09-21:** this line first said the file
came before any of the screens it governs, and that the order was the point.
It did not come first. `CarDetail.tsx` already drew `gearbox`, `fuel`,
`province` and `seller_type` — the four rows then `PENDING_LIVE_VALIDATION` —
under «آنچه از آگهی استخراج شد», rendering the three empty ones as «ثبت‌نشده»
and seller type's `unknown` as «نامشخص — نشان کسب‌وکاری روی آگهی نبود». The
repair the next paragraph describes had already been made.

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

One artifact: `data/corpora/run16.json` — 73 Bama listings, collected
2026-10-15, `schema: caro.corpus/1`, the run the API serves by default, and
the first whose every location line was read before it was published (D80).
Three earlier runs on the same pin stay published: `run14.json` — 77
listings, collected 2026-10-11, served until run16 — `run13.json` — 74
listings, collected 2026-10-06, served until run14 — and `run11.json` — 76
listings, collected 2026-09-10 (D57): this file was first measured on it,
the decision record cites it, and its assignment is the non-vehicle the
suites follow by name. Where a row below says what run11, run13 or run14
held, it names it.

A value counts as filled when it is not null, empty, `"unknown"` or `"none"`.
Distinct counts the filled values.

```python
import json
from pathlib import Path
rows = json.loads(Path("data/corpora/run16.json").read_text(encoding="utf-8"))["listings"]
EMPTY = {None, "", "unknown", "none"}
for k in sorted({k for r in rows for k in r}):
    nn = [r.get(k) for r in rows if r.get(k) not in EMPTY]
    print(f"{k:<26}{len(nn):>4}/{len(rows):<3}"
          f"{len({json.dumps(x, ensure_ascii=False) for x in nn}):>6}")
```

## The table

`filled` and `distinct` are that script's output on run16, unedited.

| field | status | filled | distinct | card | detail | gate | facet | reason |
|---|---|---|---|---|---|---|---|---|
| `listing_id` | `SOURCE_BACKED` | 73/73 | 73 | no | no | no | no | identity; keyed on, never drawn |
| `source_url` | `SOURCE_BACKED` | 73/73 | 73 | yes | yes | no | no | the source's own statement of where the listing lives |
| `make` | `SOURCE_BACKED` | 73/73 | 1 | yes | yes | no | no | one distinct value here; a filter over it offers one choice |
| `model` | `SOURCE_BACKED` | 73/73 | 3 | yes | yes | no | yes |  |
| `trim` | `SOURCE_BACKED` | 73/73 | 22 | yes | yes | no | yes |  |
| `year_jalali` | `SOURCE_BACKED` | 73/73 | 20 | yes | yes | no | yes |  |
| `color` | `SOURCE_BACKED` | 70/73 | 7 | no | yes | no | yes |  |
| `asking_price_toman` | `SOURCE_BACKED` | 69/73 | 50 | yes | yes | no | yes | 4 listings carry no price and must render as carrying none |
| `price_status` | `SOURCE_BACKED` | 73/73 | 4 | yes | yes | no | no | extraction quality, NOT plausibility — see below |
| `price_kind` | `SOURCE_BACKED` | 73/73 | 3 | yes | yes | no | no | what the number means (D52); own namespace, see below |
| `price_kind_source` | `SOURCE_BACKED` | 73/73 | 3 | no | yes | no | no |  |
| `price_currency_raw` | `SOURCE_BACKED` | 70/73 | 1 | no | no | no | no | the structured block's currency label, `IRR` wherever there is one; diagnostic only — `assert_not_features` refuses it as a predictor |
| `mileage_km` | `SOURCE_BACKED` | 70/73 | 56 | yes | yes | no | yes | 3 listings carry none, all of 1405 |
| `mileage_status` | `SOURCE_BACKED` | 70/73 | 2 | yes | yes | no | no | travels with the number or neither renders |
| `mileage_line_canonical` | `SOURCE_BACKED` | 70/73 | 56 | no | yes | no | no | canonicalised, not the source's prose |
| `condition` | `SOURCE_BACKED` | 64/73 | 5 | no | yes | no | yes | the body-condition block (D45); `unknown` is a value, not an absence |
| `condition_source` | `SOURCE_BACKED` | 64/73 | 1 | no | yes | no | no | `field` here — never `description` on this corpus |
| `product_class` | `SOURCE_BACKED` | 73/73 | 1 | yes | yes | yes | no | the gate: only `vehicle` renders as a car (D52), and search applies it (D60). `card` because compare shows a non-vehicle row labelled with its class instead of dropping it — the class drawn as a fact about the row. run16 holds no non-vehicle, run14 one assignment, `bama:ktawd8le`; the suites follow run11's by name |
| `product_class_source` | `SOURCE_BACKED` | 73/73 | 1 | no | yes | no | no |  |
| `dealer_badge` | `SOURCE_BACKED` | 73/73 | 2 | no | no | no | no | `true` on two rows, the two `seller_type` reads as dealers, and `false` on the rest |
| `document_issue` | `DERIVED` | — | — | no | no | no | no | not a key in run16: no row's text names a phrase the parser knows; run14 carried it on one row — see below |
| `seller_type` | `SOURCE_BACKED` | 2/73 | 1 | no | no | no | no | inferred only from a business badge, never from a person (D26): `dealer` on the two rows that carry one, the first value a real run has produced |
| `province` | `SOURCE_BACKED` | 73/73 | 23 | yes | yes | no | yes | read off the page by position (D74); the car page and the lists draw it with how it was known. `facet` because «در تهران» is a constraint a buyer states and the search judges it against this field (`webapp/api/constraints.py`, D82) — see below |
| `province_source` | `SOURCE_BACKED` | 73/73 | 2 | yes | yes | no | no | `stated` or `city`: whether the line names the province or a city sharing its name gave it — 42 and 31 here. Drawn beside the province, never apart from it. Not a key in run13, which predates it |
| `gearbox` | `SOURCE_BACKED` | 73/73 | 2 | no | no | no | yes | the structured block's transmission, on every row since `72c2573` carried it across the boundary; `automatic` on one row of run16, a Quik, and `manual` on the rest. `facet` because «اتومات» is a red line a buyer states and the search checks against it (`webapp/api/constraints.py`) — see below |
| `fuel` | `SOURCE_BACKED` | 73/73 | 3 | no | no | no | no | on every row; nothing reads it yet |
| `model_key` | `DERIVED` | — | — | yes | yes | no | no | make, model and trim joined into one key, rendered through `modelLabel`. Drawn by the detail page and by all three card surfaces — the evidence grid, `ListingCard` and `CompareTable` — which is why `card` is `yes`: `derived_title`, which this table meant for the card, is not a key in any published corpus and is not on the payload |
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
Coverage and variety are inputs to the judgement, not the judgement: `make`
is filled on every row and is still `facet: no`, because one distinct value
is not a choice. `filled: 73/73` on its own authorises nothing — and
`product_class`, one value on run16 and on run13 and two on run14 and on
run11, is a gate on all four and would fail the variety condition as a facet
on run16 and run13, which is the clearest case of why the two are not one
column.

A dash means the field is not a key in run16 at all. `promote_corpus.py` ends
with `{k: v for k, v in out.items() if v is not None}`, so a key with no value
does not reach the artifact — and absence has more than one upstream cause,
which the table keeps apart rather than flattening into "missing":

- `model_key`, `derived_title`, `observed_at` — CARO's own, composed after the
  artifact is read, never in it.
- `document_issue` — a dash again: a value the parser writes only where the
  seller's text has a phrase it knows, an issue or a clean title, and no
  text in run16 had one. run14 carried it on one row, and run13 on none.
- `seller_type` — not a dash: the key survives on every row, `unknown` where
  the page carried no business badge, which this file counts as unfilled,
  and `dealer` on the two rows of run16 that carry one. It is published
  precisely so that a car with no business badge is never published as
  `private` (D26).

run11 had three more dashes, for causes since repaired: `province` was read
from a label the page does not render, and `gearbox` and `fuel` were dropped at
the snapshot boundary until `72c2573` carried them across. run13 is the first
corpus promoted after both repairs, and run14 the first to carry
`province_source`.

## Coverage is not variety

`make` is filled on every one of the 73 rows and has exactly **one** value.
A brand filter over this corpus offers the reader a single choice, and a
ranking term computed from it moves nothing. D41 found four of six scoring
terms constant on a real corpus and the gate refusing; the same arithmetic
applies to a filter.

So UI eligibility has two conditions, not one: enough coverage to be honest,
and enough distinct values to be useful. On run16 that admits `model` (3),
`trim` (22), `year_jalali` (20), `color` (7), `condition` (5),
`asking_price_toman` (50), `mileage_km` (56) and `province` (23) as facets, and excludes
`make`, `dealer_badge`, `condition_source`, `mileage_status` and
`product_class_source` — several of which are still worth showing.

`gearbox` has two values on run16 — `automatic` on one row, a Quik, and
`manual` on the rest — and stays a facet for the reason its row gives. The
variety condition exists because a filter offering one choice tells a reader
nothing. «اتومات» is not a choice offered: it is a red line a buyer states,
checked against every row. On run16 one listing meets it; on run14, with one
value, none did, and the answer was that no listing met it — which a reader
who asked should be told. On run13 it had two values, and D72 made it a
facet there.

The variety condition applies to `facet` and not to `gate`. A gate exists to
remove rows the reader should never have been offered, so two values is all it
needs.

## Province: on 73 of 73

run16, collected on 2026-10-15, is the corpus served and the first read by
the rule below as it stands since `f82efec`: a province on all 73 rows, 42
stated and 31 by the city. تهران is on 20, 17 of them by the city, and
اصفهان on 12, 9 by the city, and there are twenty-three provinces in all.
Three rows are a capital named as its province standing alone — «قزوین»,
«زنجان», «کرمان» — and are by the city. run14, collected on 2026-10-11 and
served until run16, was the first collection the rule read at all: a
province on 76 of its 77 rows, 44 stated and 32 by the city, read before
`f82efec`, so that a capital alone counts among its stated rows — «زنجان»
and «کرمان» on two of them at least, drawn again in run16 (D80) — and its
one row without a province names it as Bama spells it,
«کهکیلویه و بویراحمد», read since `d12c592` (D75).

The rule. `province` is read off the page by position, in the four lines
after the odometer line — «کارکرد … کیلومتر», or a new car's «صفر کیلومتر».
A province the line states is read in any part after the city; a line whose
city is one of the thirteen capitals that share their province's name, with
its district — «تهران، آذری», «اصفهان، کهندژ» — or alone — «کرمان» — gives
that province, recorded as `province_source` `city`, never as stated (D74).
Since 2026-10-30, by the owner's choice, so does a line whose city is one of
the eighteen other capitals — «کرج» gives البرز, «شیراز» فارس — and no other
city gives one (`persian.OTHER_CAPITALS`).
The city stands alone because Bama leaves out a province named as its city;
the rule read such a line as stated until the lines a collection kept on
2026-10-14 showed the shape, and run14 was read by that rule — how many of
its 44 stated rows are such a line, the lines it did not keep cannot say. On
the nineteen listings whose lines date_watch stored (read 2026-10-10), the
rule run13 was read by found eight; this one finds all nineteen.

run13 was read by the narrower rule of `8e34dba` — the last comma-separated
part of a line, after «کارکرد … کیلومتر» only — and carries a province on 34
of 74. Ten of its pages were read by hand on 2026-10-06 — eight without a
province, two with — and every miss was empty, none wrong. The misses were
lines that rule could not read:

    «شهر، استان»            منوجان، کرمان                 read
    «شهر، محله»             تهران، آذری                   5 of the 8
    «شهر، استان، محله»      مشهد، خراسان رضوی، فلسطین     2 of the 8
    no «کارکرد … کیلومتر»   a 1405 Quik with no reading    1 of the 8

So run13's 34 lean to small towns. Its pages were not kept, and its numbers
stay as they are.

The car page draws it, and says how it was known: «تهران» where the listing
names its province, «تهران — از روی نام شهر» where the city gave it, and
«ثبت‌نشده» where there is none; and since D81 so do the lists an ungated
corpus serves, search's two tables and compare's evidence rows, in the same
words. That is `detail` and `card`. On run13 every flag was `no` for
coverage — a value missing where the market is largest is not one a filter
may offer — and on run14 that no longer held. What held them after that was
the first hazard below, measured on the lines of run16, the corpus served.
In a list a misread is one row among others, labelled with how it was read;
a search that reads «در تهران» would drop a misread car from its answer
without a word. So `facet` is `yes` since D82, after that search was built
and measured: the buyer chooses it by writing it; a listing whose province
is known only from its city's name meets it, and the table says so; and a
listing with no province is held apart and named, never dropped — which is
run13, where 40 of 74 rows carry none and «پراید در تهران» finds 3 and holds
31 apart. `gate` stays `no`: a gate is applied to every query, and this one
only to the query that states it.

Two hazards stand. A district named like a province, after the city, is read
as that province, stated, because a stated province wins: «تهران، گلستان»
would give گلستان. The line a province is read from crosses to the
operational snapshot as `location_raw`, and the corpus guard refuses it in a
published row, so the hazard is read on the lines themselves. run15,
collected on 2026-10-14 and not published, is the first collection that kept
them, and run16 the second: none of run15's 48 stated rows stands on such a
district, and none of run16's 42 — on 22 the line's first part is the
capital of the province read, and the other 20 were read by hand — and no
district on either's lines is named as a province is (D79, D80). Since D82
the search judges the province, so such a row would meet «در گلستان» and be
left out of «در تهران»; none is known. And a new car's mileage is still not
read from its line.

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

So a card, and the car page, renders an asking price only when **both** gates
pass, and the rule has to name its fields with their vocabularies, because
`negotiable` is a member of `PriceStatus` *and* a member of `price_kind` and
the same word means two different things:

    price_status ∈ {display_confirmed, …}     AND     price_kind == cash

On run16 that gate costs nothing: the four rows whose `price_kind` is not
`cash` — three negotiable, one financing total — are exactly the four rows
that carry no number, as run14's three, run13's four and run11's two were.
Which is the reason to write the rule now rather than when it first matters
— a rule checked only against this corpus looks complete.

**There is no `price_validity`, and mileage has one.** `Validity` grades an
odometer `plausible`, `suspicious`, `impossible` or `unknown`, and its own
docstring keeps the last two apart on purpose: a missing odometer is the seller
declining to say, a suspicious one is the seller saying something untrue.
Nothing equivalent exists for price. A row can be `vehicle`, `cash`,
`display_confirmed` and `plausible` — every gate in this file — and still
carry a number an order of magnitude away from its neighbours. `run11` contains
one such row — 65 million toman beside a Pride median of about 612 million;
run13, run14 and run16 have none as far from their models' medians,
run16's lowest being a 1380 Pride at 240 million against a median of 650,
and its highest a 1394 Pride at 1.8 billion. Whether that is a
fault, and what a plausibility state for price would have to be, belongs in
`caro/ingest/quality.py` and is not settled by observing it here. What this
file fixes is narrower: nothing may read `display_confirmed` as "plausible".

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
answered for every row. The artifact states `collected_on` once —
`2026-10-15` for run16 — and every row inherits it, so `observed_at` is
available on 73 of 73, while `listing_age` comes from a channel that covers
a handful (below).
It is CARO's record of its own looking, never the source's statement, and a
screen that shows it is telling the reader how stale the page is rather than
how old the car's advertisement is. The equivalent on Torob is the date in the
page title, stated once for several thousand listings.

**listing age — `EVIDENCE_ONLY`.** No corpus field carries a posting date.
Khodro45's list states one, `created_time`, and since 2026-10-30 it reaches the
snapshot as `listed_at` and stops there: an audit of our own first sighting
(TEMPORAL_CONTRACT §11, the owner's decision), never a feature, never shown.
For a published listing, the only channel that reads one is
`scripts/date_watch.py`, whose observations are operational and unpublished; `data/derived/date_watch_summary.json` carries the
four fields that may leave it. D58 applies **at its own scope and no wider**:
in that corpus, with extractor v4, `phrase_days` was never observed at 7 or
above and was absent in all 34 observations of age 7 to 29. It is not a general
rule about the source. A screen that shows an age therefore shows it for
listings inside that window, says what it does not know outside it, and never
converts the absence into a number. The panel is twenty of run11's listings —
`date_watch` samples them with `seed 0` — and none of run16's 73 rows is among
them, nor of run14's 77; one of run13's 74 was.

**document_issue — `DERIVED`, and weaker than it reads.** run16 carries
none, so the key is absent from it; run14 carried one value in
seventy-seven, a `false`, on `bama:bwfgrup6`; run11 one in seventy-six, also
a `false`; run13 none. `promote_corpus.py` takes the structured field when
there is one and otherwise falls back to `has_document_issue(desc)`, which
answers `true` where the prose holds a phrase it knows for an issue, `false`
where it holds one of three phrases for a clean title — «سند آزاد»,
«سند تک برگ», «سند دست اول» — and null where it holds neither. So a `false`
is the seller's own sentence about the title, found by a three-phrase list,
and not a check of the title. This paragraph said from 2026-09-18 that a
`false` meant the parser had read the prose and found no phrase; the
function, unchanged since `4a16962`, has never answered `false` for that.
Converting a null into a third vocabulary member (`not_reported`) is a
derivation performed by the mapping layer, not a value the corpus supplies, and
that is why this row's status is `DERIVED` rather than `SOURCE_BACKED`. Two
states must never collapse into one on a screen: `false` is a seller's claim
that a short list recognised, null is the absence of any finding, and neither
is a check of the title.

## What this file does not decide

Card layout, detail layout, which fields share a row, the image question, and
whether a field with a `PENDING_LIVE_VALIDATION` status is worth a run. It also
does not close a schema: an optional field may exist in a schema while no
renderer is allowed to draw it. That is where `gearbox` and `fuel` stay for
every surface but the one `gearbox` is judged for.

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
