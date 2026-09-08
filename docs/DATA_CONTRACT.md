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

## The estimand

> CARO's appraisal estimand is **conditional**, not a population-weighted
> model-level market statistic. Trim-stratified acquisition does not receive
> population weights because trim inclusion probabilities are unknown. Any
> model-level aggregate is out of scope unless sampling sensitivity is
> reported.

### The frozen principle

> A conditional appraisal may only be served when the estimator does not
> **materially extrapolate** across thin or unrepresented trims, and when no
> downstream aggregate assumes sampling weights.

That principle is what is frozen. The rule below is its current
*operationalisation*, and may be replaced by a better one — a properly
benchmarked hierarchical or shrinkage estimator would change what counts as
"material extrapolation" without changing the principle. Freezing the
threshold instead of the principle would make the contract an obstacle to
improving the estimator, which is not what it is for.

**Current operationalisation** (`stratification.conditional_scope`,
`appraisal.AggregateOutOfScope`):

1. trim is present as a conditioning value;
2. each trim carries at least `MIN_PER_TRIM = 5` observations of its own;
3. at least 70% of eligible listings sit in such trims;
4. nothing downstream aggregates across trims without a sampling span.

**On the 2026-09-07 corpus, (3) fails at 55%.** So the conditional defence
does not currently cover it. The consequence is precise, and narrower than it
first appears:

> The span does **not** demonstrate that the estimate is biased. It shows the
> estimate is sensitive to the sampling design that is assumed. Because
> `P(inclusion)` is unknown, none of the candidate designs may be called the
> correct weighting — so the span cannot be read as precision either, and a
> model-level aggregate is out of scope without it.

That is a measured reason to keep W1 closed, not a judgement call.

## Three uncertainties, never merged

D8 required two; D29 adds a third, and it is different in kind.

| quantity | what it measures | shrinks with more data? |
|---|---|---|
| `estimate_confidence` | how well we know this model's market | yes |
| `information_completeness` | how much *this listing* disclosed | no — ask the seller |
| `sampling_sensitivity` | how much the answer depends on how we sampled | **no** — not while the design is unchanged |

Folding the third into a confidence band would tell a user their uncertainty
is reducible by collecting more, when collecting more the same way cannot
reduce it. Any served estimate carries `estimate + confidence + sampling
sensitivity`.

## When a gate refuses

> **The fix is a corpus that can judge, not a tuning pass that makes the
> question go away.**

Every threshold in this document is either arithmetic (`MIN_SLICE_N = 58` is
2.5 binomial standard errors on a 15-point coverage deviation) or a recorded
policy with its reasoning. Lowering one to obtain a verdict does not buy
information; it buys the appearance of one, and the appearance is what a
reader will act on.

Three statements can be true at once, and the benchmark prints them together
so the flattering one cannot travel alone:

    estimator quality                  promising
    evidence for conditional serving   insufficient
    decision                           do not serve

## The publishable corpus artifact

Added after D46, which found that the corpora behind every published number
were never in the repository and are not recoverable. Nothing above this
section is relaxed by it: this is a contract for a stage that did not
previously exist, not a threshold moved to let a run pass.

**Two directories, because there are two lifecycles and conflating them is
what went wrong.**

```
data/
├── snapshots/    operational. Working output of a collection run. Ignored by
│                 git. May hold whatever the run needed, including
│                 seller-authored prose. Never published.
└── corpora/      publication-grade. Committed. The only path a README, a
                  benchmark or a replay command may point at.
```

A file does not move between them by hand. **Promotion is a deterministic,
validated, redacting step**, and it is the only writer of `data/corpora/`.
Copying a snapshot across manually is the failure mode this section exists to
remove: everything D46 records was process failure, not a missing `.gitignore`
line, and a rule a person has to remember is the same failure waiting again.

### What a published corpus artifact must be

| | |
|---|---|
| **deterministic** | replaying it reproduces the run's reported numbers exactly |
| **immutable by run identity** | one artifact per run id; a changed artifact is a new run, never an edit of the old one |
| **free of seller-authored text** | see below — this is the semantic rule, not a field list |
| **free of contact identifiers** | no phone number, no messaging handle, no address, in any field |
| **free of credential material** | no cookies, tokens, session state, salts, or headers carrying any of them |
| **bounded and addressable** | an artifact too large for the repository is a storage decision, not a reason to weaken replayability or retention — see below |

**Storage medium is an implementation choice.** What must hold is that the
artifact stays immutable, addressable and independently replayable; where the
bytes physically live does not. An artifact too large for the repository must
either be reduced by a **pre-declared** sampling policy — declared before the
run, not chosen after seeing which rows are inconvenient — or stored in an
immutable, content-addressed artifact store, with the repository holding the
reference and the expected digest. Either satisfies D46. What does not satisfy
it is an artifact that exists only on the machine that made it.

For CARO at its current size, `data/corpora/` in git is the default, and the
external-store path is not yet exercised.

### The seller-text rule is semantic, not a field list

> **No free-form seller-authored text may appear in a published corpus
> artifact.**

The fields that carry it today are `description`, `desc`, `title` and
`km_line`. Those are **instances, not the definition** — a rename does not
create an exemption, and a new adapter that introduces `notes` or `summary`
is covered from the day it is written.

The reason is narrow and specific. `caro/ingest/base.py` states that raw phone
numbers must not reach CARO or disk, and no redaction step has ever enforced
it: `salted_fingerprint()` protects the seller identifier and nothing protects
the prose. D45 records the one time this was noticed in passing — `km_line`
picking up dealer ad copy on listings with no odometer, "the one place a phone
number could have ridden along". Bama masks the number it renders; a seller
typing one into a description is not masked by anyone.

### What is explicitly allowed

The rule is about seller-authored prose, **not about identifiers as a
category**, and it must not drift into the second thing:

- `seller_fingerprint` — a salted hash, used only for dedup. Allowed.
  `salted_fingerprint()` already refuses to run without `CARO_SELLER_SALT`,
  because an unsalted hash of a phone number is a phone number.
- `payload_sha` — a content hash for traceability. Allowed.
- `image_phashes` — perceptual hashes for repost identity. Allowed.
- Structured extracted fields — price, mileage, year, make, model, trim,
  colour, province, body condition, dealer badge. Allowed; these are what a
  corpus is for.

A guard that flags any identifier-shaped string would flag all four and be
switched off within a week. The line is authorship: a value the seller wrote
in prose is out, a value the pipeline derived is in.

### Two guards, because one is not enough

**Schema guard.** A published artifact may not contain a key drawn from the
forbidden set, at any nesting depth. Cheap, exact, and evadable by renaming —
which is why it is only the first of two.

**Content guard.** No personal contact identifier may occur anywhere in a
published corpus artifact, *regardless of field name*. A field called `notes`,
`raw`, `meta` or `text` gets the same scan as `description`.

Three properties the content guard must have, each because the obvious
implementation would miss something:

- It runs on the **serialized artifact after it is written**, not on the
  object before serialization. A serializer that flattens a nested structure,
  or a field added downstream of the check, defeats an in-memory scan.
- It **normalises before matching** — Persian and Arabic digits to ASCII,
  ZWNJ and NBSP removed, `ك→ک` and `ي→ی` — so `۰۹۱۲…` is caught as readily as
  `0912…`. `normalize_persian_digits()` already does exactly this.
- It **fails the suite**, not a log line. A warning about a file that is about
  to be committed to a public repository is not a control.

### What these guards cannot check

Stated plainly, because an unstated limit reads as a covered one.

- **A contact written in words or deliberately obfuscated.** `صفر نه یک دو…`,
  a number split across a sentence, or one spelled with letters substituted
  for digits will pass both guards. The guards raise the cost of an accident;
  they do not defeat an intent, and the seller-text rule is what actually
  carries the guarantee. The guards exist to catch the case where prose was
  admitted by mistake — which is the case that has actually happened.
- **Whether the artifact reproduces the run.** Determinism is asserted by
  replaying it, not by inspecting it. That is a separate check and it belongs
  to the replay path.
- **Anything about a corpus that was never promoted.** A run whose artifact
  does not exist has no evidence in this repository, whatever its transcript
  says (D46).

### The replay path points here, and only here

`--replay` reads a published artifact from `data/corpora/`, validates it
against this schema, and parses it. It does not read `data/snapshots/`.
Documentation that says otherwise is describing an architecture in which the
operational area and the published evidence are the same thing — which is the
arrangement this section replaces, and the one under which D46 happened.

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
- **Trim-level market shares — and therefore population weighting.** The
  sample is stratified by the source's published trim facets, each of which
  has its own listing ceiling. Trim-level market shares are unknown, so
  estimates are **not population-weighted across trims**. A trim's listing
  count reflects that page's ceiling at least as much as its share of the
  market, so no weight is derived from it (D29). What IS reported, per model,
  is the concentration (HHI, normalised entropy, effective n) and a
  reweighting sensitivity span. Per-vehicle conditional estimates are in
  scope; market-level aggregates across trims are not, unless they carry that
  span.
- **Trim-level conditional coverage above 63% (Pride).** Measured directly
  from all 34 published Pride trim pages on 2026-09-07: 135 listings, 22 of
  34 trims holding fewer than five. With *complete* acquisition of everything
  the source publishes, at most 63% of listings sit in trims with 5+
  observations — below the 70% the conditional estimand requires, and an
  upper bound before eligibility is applied. The market's trim distribution
  is long-tailed; no acquisition strategy changes that (D31). Trim-level
  pagination does not exist and its URLs silently serve the generic feed, so
  it is not a route to more depth either.
- **Geographic representativeness.** Not measured at all yet.
- **Truthfulness.** A plausible odometer is not a verified one. Every claim
  in the corpus is the seller's, and the system's job is to say so.
