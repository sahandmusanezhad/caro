# Data contract

**Frozen 2026-09-07, after the second live run. Do not move these definitions
to make a run pass.**

The point of writing them down is that they are the only thing standing
between "the collection worked" and "the collection is sufficient". A
threshold that gets relaxed because the demo needs to move is not a threshold;
it is a formality. If a future corpus exposes a genuine semantic failure these
definitions do not cover, change them *and record why* — but not to unblock a
number.

---

## The chain

Each stage is a strictly narrower claim than the one before it. Nothing here
lets a listing skip a stage.

```
source
  ↓                       what the site published
raw observation           kept verbatim: price_raw, price_currency_raw
  ↓                       what it means in our units
normalisation             asking_price_toman, mileage_km, year_jalali
  ↓                       whether the value can be true
quality judgement         price_status, mileage_status
  ↓                       whether the record describes a car coherently
usable listing
  ↓                       whether it can inform an estimate
appraisal-eligible
  ↓                       whether a MODEL has enough varied evidence
comparable support
  ↓
W1
```

"Parsed successfully" is stage 3 of 8. It has never meant "safe for the
model", and the funnel report exists so nobody can read it that way.

---

## Definitions

**fetched** — an HTTP response came back. A transport fact only; a 200 can be
a soft-404, a challenge page, or a partial render (D19).

**parsed** — the page yielded a `CarListing`. Says nothing about the quality
of its fields.

**usable** — the record describes a car coherently: it has a model, a year,
and an odometer reading that is not `suspicious` or `impossible`.

**appraisal-eligible** — usable, *and* it can inform an estimate:

| requirement | why |
|---|---|
| `asking_price_toman` present | nothing to price against without it |
| `price_status` not `ambiguous` / `negotiable` / `absent` | an instalment deposit is not a cash asking price |
| `year_jalali` present | the strongest single predictor |
| `mileage_km` present and `plausible` | 999,990 km is present, in range, and false |
| `model` present | a comparable set has to be *of* something |

**comparable support** — a model is ready to price against only when **both**
hold:

1. **count** — at least **30** appraisal-eligible listings; and
2. **variation** — the set is not degenerate, meaning no more than **80%**
   share a single model year or body condition, and the mileage
   interquartile range is at least **15%** of the median.

The 40 records that fall out between *parsed* and *appraisal-eligible* are
not "bad data". They are evidence with insufficient properties for this
particular downstream task: they still count toward supply, toward
time-on-market, and toward what the source publishes.

---

## Why variation is a gate and not a nice-to-have

This is the part most easily talked out of, so the reasoning is recorded
rather than assumed.

The appraiser fits price on year, mileage and condition. A coefficient is
identified only if its predictor varies in the sample. Thirty listings that
are one narrow slice produce:

- a mileage term fitted on almost no spread — noise wearing a number;
- an output very close to the slice mean, presented as a conditional
  estimate; and
- **narrower** prediction intervals, because residuals inside a homogeneous
  slice are small.

So degeneracy manufactures confidence instead of destroying it, and W1's
acceptance gate would see a well-calibrated model. No metric computed on the
same slice can detect this, because the held-out half is degenerate in
exactly the same way. It has to be checked structurally, on the inputs,
before anything is fitted — which is what `caro/ingest/coverage.py` does.

What this licenses, and what it does not. A failing slice establishes
*"this sample is not evidence of a varied market"*. It does **not** establish
*"more pages cannot help"* — a later page could hold different sellers,
conditions and prices, and claiming otherwise would be a statement about
pages nobody has fetched. The gate fails the sample; the next run tests
whether a different retrieval strategy fixes it, with these thresholds held
fixed while the sampling varies (`scripts/run3_matrix.py`).

## seller_type is a diagnostic, never a feature

`seller_type` answers "is this comparable set one forecourt's inventory?" —
a question about *our sampling*, not about the car. Feeding it to the
estimator would let CARO learn that fair value depends on who is selling,
from a correlation that is real and an inference that is not; every metric
would improve, because dealer listings genuinely are priced differently.

The boundary is enforced rather than documented:
`caro.ingest.quality.DIAGNOSTIC_ONLY_FIELDS` lists it alongside the other
provenance fields, and `Row.__post_init__` raises `DiagnosticLeakedIntoModel`
if any of them reaches the design matrix.

---

## What this contract cannot check

Stated plainly, because an unstated limit reads as a covered one.

- **Seller independence.** CARO never reads a phone number, so there is no
  seller identity to count. `seller_type` is inferred from a dealership block
  the page publishes about *itself* — a trade badge, a showroom address. It
  is coarse: thirty listings from thirty different dealers pass as diverse,
  and a small dealer posting like an individual reads as `unknown`. Absence
  of a badge is never recorded as `private`.
- **Whether the unit is right across the whole corpus.** The price magnitude
  check cannot see a uniformly tenfold-wrong corpus. Only the cross-check
  against the buyer-facing price can (D20), and only on pages that display
  one.
- **Geographic representativeness.** Not measured at all yet.
- **Truthfulness.** A plausible odometer is not a verified one. Every claim
  in the corpus is the seller's, and the system's job is to say so.
