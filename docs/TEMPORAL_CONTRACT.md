# The TrackedListing → corpus row contract

**Status: PROPOSAL. Nothing here is implemented.**
Written to be argued with before any code moves, because every defect this
project has paid for was a boundary that was crossed before it was described.

Run 11 is frozen at `UNJUDGEABLE — missing_temporal_axis`. The reason is not
that the benchmark is too strict; it is that a corpus promoted from ONE
snapshot has no time in it, and `rows_from_corpus` says so honestly by
setting `first_seen_ordinal=0` on every row. W0 has held the missing axis
since the beginning and has never been connected to W1.

This document is that connection, and only that. It does not propose a
model, a metric, or a number.

---

## 0. What each side already is

```
W0  TrackingState { tracking_id -> TrackedListing }
        first_observed_at : date          ← when WE first saw it
        observed_appearance : bool        ← did we WATCH it appear
        observations : [Observation]      ← present / absent / unknown, per day
        source_listing_ids : [str]        ← the repost chain, one physical car
        last_signals : FetchOutcome       ← what it looked like most recently

W1  Row
        cluster_id : str                  ← one physical car
        first_seen_ordinal : int          ← the split key
        asking_price_toman : float        ← the target. AN ASKING PRICE.
```

The two types were designed for each other and were never joined. The join
is not a function call; it is four decisions, below, and each one can be got
wrong in a way that produces a clean-looking number.

---

## 1. The unit of a row

**Proposed: one corpus row per TrackedListing, carrying the FIRST observed
asking price.**

A car relisted three times at three prices is one car, not three
observations. Publishing three rows would weight the corpus toward
long-lived, repeatedly-reposted cars — which are precisely the overpriced
ones — and `cluster_temporal_split` would keep them together without ever
reporting that it had done so.

Between the first ask and the last ask, the first is the observation of the
market. **A reduced price is conditioned on the car not having sold**, which
is a selection effect and not an independent draw from the price
distribution W1 estimates.

The alternative — the last observed ask — answers a different and genuinely
interesting question: *what do sellers end up asking after the market has
refused them?* That is a second corpus with a second name, never a flag on
this one. Per D55, a flag would let one number be produced under either
meaning and quoted under whichever suits.

    row.asking_price_toman  := first observed ask
    row.cluster_id          := tracking_id      (NOT listing_id)
    row.listing_id          := source_listing_ids[0]

### 1a. This requires a change to `TrackedListing`

`TrackedListing` keeps `last_signals` and does not keep the first. The first
ask is recoverable from the `appeared` event, but the **evidence that ask was
eligible** — `price_status`, `price_kind`, `product_class`, `condition_source`
— is not. It exists only in the `FetchOutcome` that has since been
overwritten.

    + first_signals : FetchOutcome | None    set once at appearance, never
                                             overwritten

Minimal, bounded, and it makes "the first ask, with its own provenance" a
first-class fact rather than something the projection reconstructs. Without
it, eligibility for a row would be judged on evidence from a different day
than the price it publishes — which is D51 in a new place.

---

## 2. The ordinal is DERIVED, never stored

**A corpus row must not carry `first_seen_ordinal`.**

An ordinal is relative to an origin. The same listing in a different corpus
gets a different ordinal, and two stored corpora are then **incomparable
while looking comparable** — the exact failure mode of a number that travels
without its question.

    row carries        first_seen_on : date
    corpus carries     tracking_began_on : date
    the split derives  ordinal = (first_seen_on - tracking_began_on).days

Derived from the corpus constant, not from `min()` over the rows in hand.
Otherwise filtering the corpus (Prides only) shifts the origin and moves the
printed `cutoff_ordinal`, and a printed number that changes with a filter is
a number someone will eventually quote.

Under this rule `ordinal = 0` means *the day tracking began*, in every corpus
of the series, forever.

---

## 3. Left truncation is safe in exactly one direction

`observed_appearance=False` means the listing already existed when tracking
began. Its true first-appearance is **at or before** what we recorded, so
`first_observed_at` is an **upper bound** on the truth.

The temporal split orders clusters by first-seen and calls the late ones the
future. For a left-truncated cluster the recorded date can only be too late,
never too early. Therefore:

| placement | left-truncated cluster | consequence |
|---|---|---|
| **train** | always sound | true first-seen is even earlier, still the past |
| **test**  | **never sound** | it may in truth predate the training cars |

    INVARIANT — a left-truncated cluster is eligible for TRAIN and is never
    placed in TEST.

This is not a preference and not conservatism. It is provable from what
`observed_appearance` means, and it must be mechanical in
`cluster_temporal_split` rather than a paragraph anyone can be in a hurry
past.

### 3a. The guard the invariant needs

The proof above assumes left truncation implies `first_observed_at ==
tracking_began_on`. That holds because `apply_snapshot` sets
`observed_appearance = not is_first`, and `is_first` is true only for the
first fold. But `is_first` is a **caller-supplied flag**: restart tracking
from an empty state on day 50 and every listing is left-truncated at day 50,
where train-placement is no longer sound.

    ASSERTED AT PROJECTION TIME, not assumed:
        first_seen_left_truncated  ⟹  first_seen_on == tracking_began_on

A violation is a broken projection, not awkward data. It raises.

### 3b. What this does to the corpus composition, said out loud

Day 1 contributes a block of left-truncated rows, all at ordinal 0, all in
train. Later days contribute genuinely-observed appearances, and the test set
is drawn only from those.

So train and test are not samples of one population. Train over-represents
long-lived listings by length-biased sampling — a cross-section of a market
over-represents slow-moving cars in proportion to how long they sit. Test is
fresh arrivals.

That is arguably the honest deployment condition: you appraise fresh
listings. But it must be **reported, not discovered**. `distribution_shift()`
already exists for this, and:

    a severe shift between a truncation-heavy train and a fresh test set
    downgrades the verdict to UNJUDGEABLE, never to REJECTED.

Under D54 and the `ReasonKind` split, that is `EVIDENCE_MISSING`: the corpus
could not answer. It is not a measured failure of the estimator, and calling
it one would retire a model for a fault in the sampling.

---

## 4. Straddling becomes structurally impossible — say so

`cluster_temporal_split` drops clusters where `lo < cutoff <= hi`, computed
over the `first_seen_ordinal` of a cluster's rows.

Under this projection **every row of a cluster shares one first-seen**,
because first-seen is a property of the car and not of the observation. So
`lo == hi` always, and `dropped_straddling` is **structurally 0**.

A check that can only ever report 0 is a check nobody can trust, and a green
line that cannot go red is worse than no line. So:

    the invariant is declared:  all rows of a cluster share first_seen_on
    the split ASSERTS it;       a violation raises rather than drops
    the report states that straddling is impossible here, not that it was 0

Dropping a straddling cluster is an answer about awkward data. Here it would
be hiding a broken projection — the same distinction as D54, one level down.

---

## 5. What a row must never carry

Everything W0 knows that is conditioned on the listing's fate:

| field | why it is forbidden as a feature |
|---|---|
| `status` (active/absent) | disappeared ≠ sold — tracking invariant 1. A model that learns "cars that vanish are worth X" has learned about our crawler. |
| `observed_span_days` | conditioned on not having sold; and structurally ~0 for the fresh listing being appraised |
| `repost_count` | same, and **always 0 in deployment** — train/serve skew wearing the costume of a signal |
| `price_changes` | the outcome leaking into the predictor of its own first term |
| `first_seen_on` / the ordinal | the split key. A model that reads its own split key is scoring itself. |

These join `DIAGNOSTIC_ONLY_FIELDS` and are enforced by `assert_not_features`
at fit time, not promised here. A type error at a boundary is a boundary; a
table in a design document is a hope.

They remain fully available to W0's own reporting and to the ranking layer's
risk terms. Forbidden as *predictors of price*, not forbidden.

---

## 6. Comparability across days: the salt

`seller_fingerprint` is the corpus's only seller-independence signal (D53
records that Run 11 has none at all). A fingerprint is a salted hash, so:

    INVARIANT — CARO_SELLER_SALT is constant for the life of a tracking
    series. A rotated salt makes day 12 incomparable with day 11 in a way
    that is invisible: every seller simply appears to be new.

The corpus publishes `salt_id = sha256(salt)[:8]` in its provenance block —
enough to prove two corpora share a salt, never enough to reveal one. Merging
two corpora with different `salt_id` values is refused rather than warned
about.

---

## 7. The proposed corpus row

Added to `caro.corpus/1`, all optional so existing artifacts stay valid and a
reader can tell a tracked corpus from an untracked one by their absence:

```
    tracking_id                str    the physical car (→ Row.cluster_id)
    source_listing_ids         [str]  the repost chain that produced it
    first_seen_on              date   OUR first sighting, never the ad's date
    first_seen_left_truncated  bool   true ⟹ first_seen_on is an UPPER BOUND
```

corpus-level provenance:

```
    tracking_began_on          date   the origin every ordinal is relative to
    snapshot_ids               [str]  every snapshot folded in, in order
    salt_id                    str    sha256(seller salt)[:8]
```

`first_seen_left_truncated`, not `first_seen_left_censored`. The project's
existing vocabulary already gives `censored` a meaning — right censoring, a
listing still active when we last looked — and `duration_stats` reports
`n_excluded_left_truncated` today. One word, one meaning.

---

## 8. What this does NOT unlock

Stating it here so no one has to infer it from silence:

- **No time-on-market claim.** `duration_stats` still needs ≥30 observed
  disappearances and still refuses below that.
- **No sale, ever.** No field named `sold`, `days_to_sale`, or `age`.
- **No retroactive rescue of Run 11.** Run 11 remains
  `UNJUDGEABLE — missing_temporal_axis`. A corpus built under this contract
  is a NEW corpus with a new run id and a new sha256. Any change that made
  Run 11 judgeable would be the forbidden move.
- **No benchmark until the axis is real.** Two snapshots on one day is one
  day. The gate will keep answering UNJUDGEABLE until several distinct
  `first_seen_on` values exist, and that answer is correct.

---

## 9. The prerequisite that is not code

All three existing snapshots are dated `2026-09-10`. `first_observed_at` is a
`date`. Building this projection today would produce a flat axis — the same
flat axis as Run 11, more expensively made and hidden under one more layer of
abstraction.

The projection is worth nothing until the collection runs on more than one
day, with:

- the same sampling pin (`--categories`, `--makes`, `--seed`), so day-to-day
  differences are the market and not the sampler;
- a stable `CARO_SELLER_SALT` (§6);
- `is_first=True` on exactly one fold, ever (§3a).

Design first, then the clock, then — only then — implementation.

---

## Open questions for approval

1. **First ask or last ask** (§1). Proposed: first. The alternative is a
   separate corpus, not a flag.
2. **`first_signals` on `TrackedListing`** (§1a). This changes a W0 type.
3. **Left-truncated rows in train** (§3), versus excluding them entirely —
   which is what `duration_stats` already does for W0 statistics. Proposed:
   keep in train, mechanically barred from test, composition reported.
4. **Severe shift ⟹ UNJUDGEABLE** (§3b), not REJECTED.
