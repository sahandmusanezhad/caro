# Roadmap — the honest gap list

## Against the challenge brief

The brief asks for: **crawl offers → normalize messy data → rank by user
intent → explain the best choice**.

| Requirement | State |
|---|---|
| crawl offers | ⚠️ **built, not yet run.** `DivarCarAdapter` collects public car listings with enforced politeness and stop-on-block; `CsvAdapter` ingests an external scraper's output. Parsing is tested offline against realistic fixtures. The live network path has not been exercised. |
| normalize messy data | ✅ **built.** Persian numerals and amount words, prices in toman and rial, mileage, Jalali and Gregorian years, make/model aliases, trim, gearbox, fuel, colour — and body condition from free text, severity-ordered so the worse disclosed claim wins. |
| rank by user intent | ✅ **built** (`caro/ranking.py`). Persian intent parsing, hard filters, relaxation ladder, inspectable scoring, diversity — and a win-rate benchmark against sort-by-price. |
| explain the best choice | ✅ built, and the strongest part of the system. |

**Read that table honestly: the deepest work sits on the last row, and the
first three are where the remaining work is.** The decision layer is only
useful once something feeds it a ranked candidate set.

## Next, in order

### 1. Ingest — run it
`DivarCarAdapter` exists and its parsing is tested. What remains is a first
live run, which is a decision rather than a build:

- Review Divar's terms and robots directives for the car category, and record
  the finding in the run log whatever it says.
- Start with one city and a handful of pages. Volume is not the point.
- Set `CARO_SELLER_SALT` in the environment. The hash helper refuses to run
  without it, because an unsalted hash of a phone number is a phone number.
- Expect to be blocked eventually. The adapter halts and says so; that is the
  designed behaviour, not a bug to work around.

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
