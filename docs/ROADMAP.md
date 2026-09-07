# Roadmap — the honest gap list

## Against the challenge brief

The brief asks for: **crawl offers → normalize messy data → rank by user
intent → explain the best choice**.

| Requirement | State |
|---|---|
| crawl offers | ⚠️ **adapter contract only.** `caro/ingest` defines the boundary and ships a working CSV adapter. No live marketplace crawler is in this repo. |
| normalize messy data | ⚠️ **partial.** Identity normalisation, repost clustering and integrity handling are built. Persian free-text extraction (paint, replacement, documents, insurance) is not. |
| rank by user intent | ✅ **built** (`caro/ranking.py`). Persian intent parsing, hard filters, relaxation ladder, inspectable scoring, diversity — and a win-rate benchmark against sort-by-price. |
| explain the best choice | ✅ built, and the strongest part of the system. |

**Read that table honestly: the deepest work sits on the last row, and the
first three are where the remaining work is.** The decision layer is only
useful once something feeds it a ranked candidate set.

## Next, in order

### 1. Ingest — connect a real source
Write one `SourceAdapter` per source against `caro/ingest/base.py`. An external
scraper needs no rewrite: emit rows to CSV and `CsvAdapter` consumes them.

Obligations are in the module docstring — terms of use, salted seller hashes,
and honest failure classification. That last one matters most: misclassifying a
403 as absence silently fabricates disappearances.

### 2. Ranking + intent — DONE, see `caro/ranking.py`
Built as described below. Kept here because the shape is worth reading:

```
Persian query → IntentSpec (budget, use case, deal-breakers, weights)
              → candidate retrieval + hard filters
              → relaxation ladder when < 3 survive, with a report of what loosened
              → score = value − risk − running cost + liquidity …
              → diversity pass
              → top N, each already carrying a Verdict
```

Two requirements worth stating up front: the weights must be **visible and
adjustable** by the user, and the relaxation must **say what it loosened**
rather than silently widening the net.

The number that decides whether this is a product: **win-rate against
sort-by-price on realistic queries.** Currently 100% win-rate, +22% uplift on
the synthetic corpus — and getting there required fixing a real bug the
benchmark exposed (risk normalised instead of priced). On real data this
needs the blind human panel, not a ground-truth utility function.

### 3. Real-data evaluation
Corpus inventory first — row count, date range, models, missingness, repost
candidates, tier coverage — then run the existing gate:

```
GlobalQuantiles → ComparableQuantiles → LogLinearQuantiles → LightGBM
```

Report whichever wins. If it is the baseline, ship the baseline and say why.

### 4. Longitudinal collection
Time-dependent and unrecoverable: a day not collected is gone. Price-change and
repost signals are dense within days; disappearance-as-transaction-proxy is
sparse and should not be claimed on a short window.

### 5. Calibrate the confidence policy
Bands are currently judgement. With real data they should be revisited against
observed decision quality and relabelled — or kept, and honestly described as
policy.

## Deliberately not planned

TCO / maintenance-cost estimates. No Iranian maintenance dataset exists, so
every component would be an invented number wearing a confidence label — the
exact fake precision this system exists to avoid. Corpus-derived reliability
signals (engine-replacement rate per model, and similar) are the grounded
substitute.
