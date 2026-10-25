# Design record

Each entry: the decision, what it replaced, and what being wrong would cost.

---

## D1 — A failed fetch is not an absence

`403 / 429 / 5xx / timeout` classify as `UNKNOWN`. Only a definitive 404 or an
explicit removal page is `ABSENT`.

**Cost of the alternative:** a crawler throttled on day 3 records hundreds of
"disappearances" on one date, and the entire time-on-market analysis becomes
garbage — discovered at the demo, not before.

## D2 — Snapshot integrity guard

A snapshot whose disappearance rate exceeds 20% is `SUSPECT` and excluded from
all longitudinal inference. **A block looks exactly like a mass disappearance.**

A first version applied the rate check at any sample size, so with three
tracked cars one ordinary disappearance was a 33% rate and tripped the guard on
every clean snapshot. Rate checks now require n ≥ 20; below that the counts are
reported and no rate is computed.

## D3 — There is no `sold` field

A listing disappearing may be a sale, an expiry, a manual delete, a platform
removal, a duplicate cleanup or a repost. The schema stores the **observation**
and never the interpretation. Any transaction-flavoured reading is a derived,
explicitly named proxy.

Rejected: a flat `{active, disappeared, reappeared, price_changed}` enum — it
conflates a *state* with an *event*, and a listing can be active and have just
changed price. Split into `status` + an `events` log.

## D4 — Unknown days are counted as unknown

Four durations, none named "age": `observed_span`, `confirmed_present`,
`confirmed_absent`, `unknown` — with `span + 1 == present + absent + unknown`.

An earlier version computed "active days" as a span and folded blocked days
into it. A listing observed on day 0 and day 3, unknown between, was reported
as 3 days active when we had seen it on 2. In a system whose whole thesis is
"never claim more than you observed", that was the worst possible bug. The old
test asserted the wrong value and passed, because code and test shared the
mistake.

## D5 — Repost linking: blocking → veto → score → ambiguity gate

Candidate generation is generous (four keys of decreasing tightness); the
decision is strict.

- **Vetoes** are only facts that cannot be a renormalisation artefact: make,
  model, year, and a mileage that ran backwards. Trim and colour are *not*
  vetoes — `206 Type 5` / `206 تیپ ۵` and `سفید` / `سفید صدفی` are one car
  described twice, and a single composite key would have put them in different
  blocks so the pair never reached the scorer.
- **Ambiguity gate:** if the top two candidates score within 0.10, link
  neither. An arbitrary pick fabricates history.

Precision over recall throughout: a false link invents a vehicle's past.

## D6 — Cluster-temporal split, and long-lived listings are kept

The unit of splitting is the physical car, so no repost of one vehicle can sit
on both sides. Clusters straddling the cutoff are dropped and counted.

An earlier version also dropped clusters observed for more than 60 days.
**That was a selection bias, not a leakage control:** the cars that sit longest
are the overpriced ones, so excluding them flatters every metric while making
the model worst on exactly the listings a buyer most needs help with. Long-span
clusters are now counted and reported, never removed.

## D7 — Rank on a lower quantile, not a scaled mean

`adjusted_opportunity = quantile(estimate, α) − asking_price`, with α from the
risk profile.

Rejected: `delta × confidence`. It shrinks the delta toward zero, which encodes
"uncertain ⇒ smaller opportunity" when the truth is "uncertain ⇒ riskier bet" —
and it does not even fix the pathology it was meant to fix. A wide-interval
car with a large nominal delta still wins under multiplication; under a lower
quantile it correctly goes negative.

`risk_tolerant = 0.50` is the median, i.e. plain expected value, and that is
correct: someone buying one car plays once, so a lower quantile is rational;
a flipper buying many plays repeatedly, so expected value is.

## D8 — Two uncertainties, never one number

`estimate_confidence` (how well we know this model's market) widens the
interval. `information_completeness` (how much this listing discloses) raises
the risk penalty and gates the top rank.

Merged into one score, a car with 400 comparables but no chassis information
and a car with 3 comparables and a full description both read "medium" — while
requiring **opposite** user actions. One is our limitation; the other means
*go inspect it*.

## D9 — Confidence is a published policy

Named bands with stated rationales, printable via `ConfidencePolicy.explain()`.
"Why 0.65?" answers *"that is the published band for 3–4 days of confirmed
observation, and here is the table"*.

Fixing this surfaced a real ordering bug: tier and count were **added**, so a
strict match with 5 comparables (0.65) scored below a relaxed match with any
count (0.75). Tier now sets a **ceiling** and count earns a fraction of it.

## D10 — The adversarial reviewer is deterministic

An LLM reviewer can be talked out of a finding, can invent one, and is
non-reproducible. For the component that polices overclaiming, none of those
are acceptable. Consequence: the system runs with no API key.

## D11 — Refusal is a product state

`MarketEstimator.predict()` raises `NotBenchmarked` until the gate passes; the
orchestrator returns `INSUFFICIENT_EVIDENCE` with reasons and a fallback offer.
The honesty rule is a type error, not a README promise.

## D12 — Ship the baseline if the baseline wins

`AcceptanceGate` rejects any estimator that does not beat comparable quantiles
on pinball, and the rejection message says "ship the baseline instead".
No model is kept because the project has "AI" in the description.

## D13 — Risk is priced, not scored

`opportunity = conservative_estimate − asking − risk × estimate × DAMAGE_COST_FACTOR`,
every term in tomans, subtracted before any normalisation.

**The win-rate benchmark caught this.** The first ranker normalised risk to
[0,1] across the candidate set and blended it as a weighted term. That is
scale-free: a 20% defect probability scored identically on an 800M car and a
2B one, though it costs the buyer roughly 2.5× more on the second. The ranker
kept selecting expensive, moderately damaged cars — and **lost** to sorting by
price (−4.0% uplift, despite winning 64% of individual queries: narrow wins,
occasional heavy losses).

Pricing risk in currency took it to a 100% win-rate and +22.0% uplift.

The lesson is not the constant. It is that the ranker had quietly stopped
implementing the product thesis — `value = estimate − asking − risk_discount` —
and no unit test would have noticed, because every component was individually
correct. Only an end-to-end benchmark against the baseline the product claims
to beat could see it.

`DAMAGE_COST_FACTOR = 0.60` is policy, not a fitted parameter. In the test
world the true cost is 0.85, and the ranker still wins with the wrong
constant — which is the robustness result worth having, since on real data
the true factor is unknown.

## D14 — Intent parsing is where an LLM belongs

The one place in CARO where a language model genuinely earns its keep:
Persian free text is exactly what deterministic code is bad at.

`IntentParser` is a Protocol. The shipped `RuleIntentParser` is deterministic,
runs offline and never hallucinates; an LLM parser can replace it by producing
the same frozen `IntentSpec`. Everything after parsing stays deterministic,
because ranking must be reproducible, inspectable term by term, and
recomputable client-side when a user drags a weight.

Two rules the parser holds regardless of implementation: every inference goes
into `assumptions` so the user can correct it, and text it could not map goes
into `unparsed` rather than being silently dropped.

## D15 — Three sources, each with a role

Bama `primary_offers`, Divar `breadth`, Sheypoor `independent_cross_check`.

The third role was called `corroboration` until D18 established that several
sites carrying one seller's car is the opposite of corroboration — one
observer publishing in several places. The word was doing real damage in a
role name, because it says the thing D18 forbids. What Sheypoor actually
supplies is a second source whose *coverage* can be compared with Bama's:
evidence about what each site publishes, never a second witness to a price.

Specs and
price-guide sites are `taxonomy_only` and never enter the corpus as offers —
a price-guide page is not something anyone is asking, and letting one in
teaches the appraiser from a number that does not exist in the market.

Three, not ten. The claim worth making is "I reconciled independent sources
into one canonical market", and a fourth site does not strengthen it.

## D16 — robots.txt was read, not assumed

Fetched 2026-09-07.

**Divar** allows category browsing (`/s/{city}/light`) and listing pages
(`/v/...`), and **disallows search urls** (`/s/*/*?*q=*`). So "just search for
پژو ۲۰۶" is not available; we browse categories and filter locally.
`assert_allowed()` raises on a violating url at the call site, because a rule
that lives only in a comment gets violated the first time someone adds a
feature.

**Bama** publishes a car **sitemap** and disallows nothing relevant. That
changed the design rather than merely permitting the old one: sitemap
discovery means coverage is knowable instead of estimated, needs far fewer
requests for the same result, and needs no browser. Crawling search pages
when the site hands you an index is both ruder and worse.

One consequence worth naming: a 404 on a sitemap-advertised url is the one
place an `ABSENT` is genuinely earned. The listing was there when the index
was built and is gone now — that is an observation, not an inference.

## D17 — Cross-source matching is a different problem, and needs a different matcher

`repost_match_score` leans on `seller_fingerprint` for 0.35 of its score.
That signal is worthless across sites, because a seller has a different
account and therefore a different salted hash on each. Reusing it would have
pushed nearly every genuine cross-site pair below threshold and silently
found nothing.

So `cross_source_match_score` reweights: images dominate at 0.50, because
photos are the one artefact copied verbatim between sites. **Price is not
scored at all** — across sites, price differing is expected of the *same*
car, so using it as identity evidence would systematically reject exactly the
clusters worth finding.

The threshold is higher (0.80 vs 0.70), and the direction is deliberate. A
false same-source merge fabricates one car's history; a false cross-source
merge destroys a genuine independent market observation and shrinks the
sample the appraiser learns from. The second error costs more.

## D18 — Several sites listing one car is not corroboration

The tempting UI copy is "confirmed by 3 sources". It is wrong, and
`claim_fa()` is tested to never say «تأیید».

Corroboration needs independent *observers* of one fact. Here there is one
observer — the seller — publishing to several places. When the prices differ,
the finding is the opposite of confirmation: it is inconsistency. Three things
follow, all more useful than agreement would be:

> An earlier version of that sentence read "when the prices differ, which
> they usually do". How often they differ is a market fact CARO has never
> measured — the cross-source path has only ever run on fixtures. It is the
> fifth instance of the pattern in **D36**, found while adding a pointer to
> D36 from this entry. Read D36 before writing anything user-facing here.

1. **A price gap, stated as an observation.** The lowest public ask is the
   least the seller is *advertising* — not a price they have accepted. An
   earlier draft of this file said they "cannot credibly refuse it
   elsewhere", and that was an overclaim: a published price can be stale,
   specific to one channel, or already raised. `price_gap_fa()` reports the
   spread and lets the buyer draw the inference; it is tested to never say
   the seller would accept the lower number.
2. **A supply correction.** Counting listings without cross-source dedup
   overstates how many cars are for sale, and liquidity feeds the ranker — so
   an uncorrected count does not merely look wrong, it moves recommendations.
3. **A seller-behaviour signal.** Systematic cross-site price gaps say
   something about who you are dealing with.

## D19 — Extraction reads the site's structured data, not its rendered text

Bama publishes a schema.org `["Product", "Car"]` block on every detail page:
identifier, brand, model year, odometer with a unit code, colour,
transmission, fuel, and an offer with a price and a currency. CARO parses
that block and treats it as authoritative.

The switch was forced by a live failure. The site's navigation renders above
the article and contains real prices («قیمت روز خودرو»). The previous
heuristic — find «تومان», take the preceding line — cannot distinguish that
block from the car, and a mis-anchored price is undetectable downstream:
every comparable, estimate and «ارزش» claim inherits it silently.

Three properties follow, and each is tested:

1. **A currency the parser does not recognise yields `None`.** It is never
   coerced. A price off by a factor of ten is the most destructive error this
   codebase can make, and it is invisible; a missing price is visible in the
   inventory and excluded from fitting.
2. **When the structured block exists, its verdict is final** — including its
   verdict that there is no usable price. Letting the text heuristic overrule
   the authority is precisely how the navigation number gets in.
3. **The extraction path is recorded per page.** `ParseTrace` counts how many
   rows came from the structured block versus the text fallback, and the run
   report prints the split. Without it, the site dropping its JSON-LD would
   leave fill rates looking healthy while quality collapsed.

`وضعیت بدنه` — body condition — is deliberately *not* taken from JSON-LD.
The block's `itemCondition` is `UsedCondition` on every car on the site and
says nothing about paint, replacement or accident history. The field the
risk layer actually needs lives in the spec table, so the parser stays
hybrid: structured for the spine, text for the condition.

## D20 — Bama's declared currency is wrong, and the fix is a cross-check

Every Bama detail page declares `"priceCurrency": "IRR"` and publishes a
**toman** figure. Verified 2026-09-07 against the number rendered to buyers on
the same page:

    JSON-LD   "price": "850000000", "priceCurrency": "IRR"
    page      ۸۵۰,۰۰۰,۰۰۰ تومان

Reading the label literally divides every price by ten. This is the worst
shape a bug can take here, because the currency whitelist added in D19 cannot
catch it: `IRR` *is* a recognised code, so nothing raises, nothing is counted,
and the whole corpus is uniformly wrong by an order of magnitude — a state in
which every model still fits, every metric still looks reasonable, and every
recommendation is nonsense.

Three parts to the decision.

1. **The observed convention overrides the declared one.** `BAMA_TO_TOMAN`
   maps `IRR → 1.0` for this source, with the evidence and date in the
   comment. `_TO_TOMAN` keeps the ISO-correct reading for everyone else.
2. **The override is continuously verified, not trusted.** `reconcile_price()`
   compares the structured price against the price rendered on the page, and
   the run report prints the agreement counts. On the 2026-09-07 corpus: 66
   `agree`, 0 `label_wrong_*`. If Bama ever fixes the label, those 66 flip to
   `label_wrong_ld_10x_high` on the very next run and the report says so.
3. **An unexplained disagreement yields no price.** One listing in 100 was an
   instalment offer whose only visible numbers were a deposit (400M) and a
   monthly payment, against a JSON-LD price of 580M. Neither displayed number
   is a cash asking price, so the row carries `price=None` rather than a
   deposit dressed up as a valuation.

The general lesson, and the reason this is a design record rather than a bug
fix: a structured source is more *reliable* than scraped text, not more
*true*. Its self-description is still a claim. The number a buyer sees is the
one they act on, so that is the ground truth the metadata gets checked
against — and the disagreement between two sources is itself the signal.

## D21 — Mileage is checked for plausibility, not just for range

The 2026-09-07 corpus contained three odometer readings that are present,
in-range, and false:

    999,990 km on a 1384 Pride     the 999999 placeholder
          1 km on a 1385 Pride     "ask me", typed as a digit
      6,000 km on a 1385 Pride     a 21-year-old car at ~300 km/year

A min/max check passes all three. Left uncounted they enter the appraiser as
genuine low-mileage cars and drag the mileage coefficient toward zero — the
cheapest available way to make a model confidently wrong, and one that no
error metric on the same corpus would reveal, because the corrupted rows are
in both the training and the test half.

`_garbage()` therefore flags anything at or above 900,000 km, and anything
under 1,500 km/year sustained over a car at least three years old. Genuinely
unused cars say «صفر» and are almost always current-model-year. The rate is
reported as garbage rather than dropped silently: 4% of this corpus.

## D22 — Validity is a field on the record, not a line in a report

The first version of the mileage plausibility check (D21) lived in
`first_run.py`. It printed an accurate garbage rate and protected nothing:
the listing still carried `mileage_km = 999_990`, and W1 was still free to
consume it as a fact. A check that only the report can see is a check the
pipeline does not have.

So `caro.ingest.quality` owns the judgement, the parser applies it, and the
status travels on `CarListing`:

    mileage_status   plausible | suspicious | impossible | unknown
    price_status     display_confirmed | structured_only | displayed_only
                     | label_corrected | ambiguous | negotiable | absent

Three properties this buys, each of which the previous shape lacked.

**Status, not deletion.** A suspicious value is kept and labelled. Dropping
it would erase the evidence that the source publishes placeholders at all,
which is a fact about the source worth having. `eligibility()` filters; the
inventory reports the rate; nothing is quietly thrown away.

**Suspicious is not impossible.** 1 km on a twenty-year-old car is
implausible, not physically impossible — an odometer may have been replaced.
−5,000 km cannot be a reading at all. Collapsing the two would either discard
real edge cases or admit corrupt ones, so the caller decides.

**Unknown is not suspicious.** A missing odometer is the seller declining to
say, which is information about the *listing*; a false one is the seller
saying something untrue, which is information about the *seller*. Counting
them together would hide both.

The report now calls the same functions the parser does, so the number a
reader sees and the flag the appraiser filters on cannot drift apart.

## D23 — Four counts, because "listings scraped" means four different things

The run report separates:

    fetched             the page came back
    parsed              the page yielded a listing
    usable              the listing describes a car coherently
    appraisal-eligible  it can actually inform an estimate

On 2026-09-07: **100 → 100 → 94 → 60**.

The gaps are the whole point, because they call for opposite responses. A
wide fetched→parsed gap is an extraction bug. A wide usable→eligible gap is
a market-coverage problem, and no amount of parser work fixes it. Collapsing
them into "100 listings collected" invites the reader — including the
author, later — to assume the best of all four.

Source integrity stays separate from these counts. An HTTP 200 is a
transport fact; the D19 soft-404 check exists precisely because it is not a
semantic one.

The same reasoning moved the readiness gate: model support is counted in
appraisal-eligible listings, not parsed ones. Ten parsed Tibas of which
eight can be priced is eight. Reading the threshold off the parsed count is
how a corpus passes a gate it does not meet.

## D24 — The price field is named for the unit it holds

`price_irr` held toman. The name was left over from Divar's structured field
and survived the currency work in D20 unchanged, which made it a live trap:
a later component reading `price_irr` and dividing by ten to "normalise" it
would be doing exactly the right thing to the wrong data, and every test
would still pass.

Renamed to `asking_price_toman`, with the inputs kept alongside it:

    price_raw               verbatim from the source
    price_currency_raw      what the source *claimed*
    price_displayed_toman   what the buyer actually sees
    price_status            how much the result is worth believing
    price_provenance        which path produced it

`asking_price_toman` is a conclusion — it may have been corrected against
the displayed price when the source's label disagreed. Without the inputs, a
corrected price is indistinguishable from a raw one, and the correction is
neither auditable nor replayable after the rule changes.

## D25 — A comparable set must be varied, not merely large

Thirty appraisal-eligible listings unlock the estimator mechanically. Thirty
listings that are the same car thirty times unlock nothing, and this failure
is worse than having no data, because it points the wrong way.

The appraiser fits price on year, mileage and condition, and a coefficient is
identified only if its predictor varies in the sample. In a degenerate slice:

- the mileage term is estimated from almost no spread — noise wearing a
  number;
- the output is close to the slice mean but is presented as a *conditional*
  estimate; and
- residuals inside a homogeneous slice are small, so the prediction interval
  comes out **narrower**.

Degeneracy therefore manufactures confidence rather than destroying it, and
`AcceptanceGate` would see a well-calibrated model. **No metric computed on
the same corpus can catch this**, because the held-out half is degenerate in
exactly the same way — the same structural blindness as D6's selection bias
and D21's placeholder odometers, and the third time this project has met it.
It has to be checked on the inputs, before fitting.

`caro/ingest/coverage.py` therefore gates readiness on count **and** spread:
no more than 80% sharing one model year or body condition, and a mileage IQR
of at least 15% of the median. Policy constants, in the same sense as
`DAMAGE_COST_FACTOR` — they encode how homogeneous is too homogeneous to
price against, which is a judgement about what a buyer is owed rather than a
quantity estimable from data.

The 2026-09-07 corpus already fails it at n=5–8: Saina's eligible listings are
100% `intact` with an asking-price IQR of **3%** of the median, which is not a
market, it is one narrow slice.

What that licenses, stated carefully. The evidence supports *"this sample is
not evidence of a varied market"*. It does **not** support *"deeper pagination
cannot fix it"* — a later page could perfectly well introduce different
sellers, conditions and prices, and asserting otherwise would be a claim about
pages nobody has fetched. An earlier draft of this entry made the stronger
claim; it was wrong, and the kind of wrong that is easy to attack precisely
because it sounds like a finding.

So the gate fails the current sample and the next run tests whether changing
the retrieval strategy fixes it — pagination depth and query variation as
separate arms, with the thresholds held fixed while the sampling changes. If
the constants moved to accommodate whatever the next run produced, the gate
would be measuring the run rather than the market.

## D26 — Seller type is inferred from the business, never from the person

`coverage` needs some signal of sample independence: thirty listings from one
dealer are not thirty observations of a market. The obvious key is the phone
number, and CARO does not read it — not hashed, not masked, not at all
(D-privacy, `salted_fingerprint`).

So `seller_type` is inferred only from what the page states about the
*business*: Bama's own tenure badge («فعالیت مداوم در باما»), dealers' union
membership, agency-sales language. Two consequences are deliberate:

- absence of a badge yields `unknown`, never `private` — small dealers post
  like individuals, and asserting otherwise would invent a fact; and
- the signal is coarse enough that thirty listings from thirty different
  dealers still pass as diverse. That limit is written into
  `docs/DATA_CONTRACT.md` rather than left for a reader to discover.

A weaker signal that touches no personal data is the right trade here. The
alternative is not a better feature — it is a phone number in a model.

## D27 — Sampling diagnostics are barred from the model, in code

`seller_type`, `price_status`, `mileage_status` and the provenance fields
describe how a corpus was *collected*. They are listed in
`quality.DIAGNOSTIC_ONLY_FIELDS`, and `Row.__post_init__` raises
`DiagnosticLeakedIntoModel` if any of them appears in a row's features.

The failure this prevents would look like a result. Dealer listings really
are priced differently, so an estimator given `seller_type` would find a
genuine correlation, improve on every metric, and encode *fair value depends
on who is selling*. What the corpus actually establishes is only that this
sample may be dominated by a particular seller population. The model would
then quote a lower fair value for a private seller's otherwise identical car,
and nothing in the evaluation would object.

The signal is also a coarse proxy built from a trade badge (D26), so part of
what it would learn is badge-availability rather than anything about cars.

A guard in code rather than a paragraph in a design doc, for the same reason
`NotBenchmarked` is an exception rather than a README promise (D11): the
boundary that matters is the one that fails loudly.

## D28 — The pre-flight fired, and it changed the experiment

Run 3's pre-flight ran against the live site before any collection. Two of
three candidate retrieval routes were wrong, and one was wrong in the exact
way the check was written to catch.

**`?page=N` — invalid.** It answers `200`, redirects to page 1, and returns
the identical ten listings. The tell is `finalUrl`; the status code says
nothing. Four "pages" fetched this way yield forty rows that dedupe to ten —
and a run that then reported *"enough listings, too homogeneous"* would have
blamed the Iranian used-car market for a bug in our crawler. This is the
laundering that the `INVALID_ACQUISITION` outcome exists to prevent, and it
was a live hazard, not a hypothetical one.

**`/car/<slug>-page-N` — valid, then saturates.** Page 2 is genuinely new
(zero overlap with page 1), then it runs out. New listings per page:

    pride     10, 10, 3, 1, 0, 0    →  24 distinct across six pages
    peugeot   10,  8, 0, 0, 0, 0    →  18 distinct
    tiba      10, 10, 0, 0, 0       →  20 distinct

Pride is the most common car in Iran. Twenty-four is not its inventory; it is
this route's ceiling. **The depth arm therefore cannot reach 30 eligible
listings for any model** — which answers the arm's question, but with a fact
about the access route rather than about the market. It is reported as
`INVALID_ACQUISITION`.

That distinction is the whole value of having run the pre-flight first. Had
the depth arm simply been executed, it would have produced ~20 rows per
model, failed the count gate, and invited the conclusion that Iranian
used-car supply is thin. It is not; our route is.

**`/car/<model>-<trim>` — the real vocabulary.** The sitemap publishes 1,862
plain category pages, and they are trim-level: 34 under `pride`, 61 under
`peugeot`, 16 under `quick`, each its own page with its own ceiling, plus a
published `?mileage=0|1` split of every one.

So the variation arm uses the site's own faceted browse rather than a guessed
filter parameter. One caveat is recorded with it, because it is the obvious
way to fool ourselves next: that arm is varied **by construction** — different
trims are different cars — so its diversity is a property of the query, not
evidence of a varied market. The degeneracy gate still has to pass on the
pooled, deduplicated result.

## D29 — Measure the sampling design; do not invent weights for it

The variation gate (D25) asks *are the cars sufficiently different?* It does
not ask *are they present in the right proportions?* Run 3 made the gap
concrete.

Bama publishes ~34 trim-level category pages under `pride`, each with its own
ceiling of roughly twenty listings. Sampling all of them produced 48 eligible
Prides that are genuinely varied — and gave `pride-111-se` roughly the same
weight as `pride-131-sl`, whatever their real shares of the market. The result
is a sample **stratified by the source's published facets, with unknown and
non-proportional weights**.

Why this is dangerous rather than merely imprecise: if rare trims are
systematically dearer or cheaper, the price distribution shifts, and
`AcceptanceGate` cannot see it — train and test are drawn from the same skewed
design, so both carry the same bias and the model calibrates beautifully
against the wrong population. The fourth appearance of the same structural
blindness, after D6, D21 and D25.

**No weighting is applied.** A valid design weight is `w ∝ 1/P(inclusion)`,
and `P(inclusion)` is not known. Three listings under one trim slug do not
imply that trim is 3% of the market — the count reflects the page's ceiling at
least as much as the market's composition. Deriving a weight from the sample's
own shape would launder an assumption into a number, which is the failure this
project keeps refusing.

So `caro/ingest/stratification.py` measures and reports:

    model         elig  trims  top-trim   HHI  entropy  n_eff
    Saipa Pride     48     17      12%   0.07     0.95   33.3
    Saipa Quik      38     11      18%   0.12     0.92   23.6
    Saipa Tiba      38      7      24%   0.19     0.90   18.1
    Saipa Saina     29      6      31%   0.22     0.91   17.7

and runs a **reweighting sensitivity analysis** — none of whose weightings
enters the estimator — because the spread is itself the finding:

    Saipa Pride   observed 0.54B   equal-trim 0.54B   span  1.9%
    Saipa Quik    observed 1.15B   equal-trim 1.16B   span  8.5%
    Saipa Tiba    observed 0.78B   equal-trim 0.84B   span 11.5%  ⚠
    Saipa Saina   observed 1.15B   equal-trim 1.24B   span 13.7%  ⚠

That differentiates three models the ladder had reported identically. Pride's
median is robust to how the trims are weighted; Tiba's and Saina's are not.
"The model says 1.5B" and "the model says 1.5B, and stays between 1.47B and
1.53B under reasonable sampling assumptions" are different products — and when
the span is wide, the uncertainty is coming from the acquisition design rather
than from residual model error, which is a thing the user is owed and a
confidence interval will not say.

### The decision among the three options

**(B) applies: inclusion probability is not inferable**, so no population
weighting is performed, and `docs/DATA_CONTRACT.md` records the limitation
verbatim rather than leaving it to be discovered.

**(C) also applies, and narrows the damage.** CARO's product is a *conditional*
statement — "what is this car worth, given its trim, year, mileage and
condition" — not "the market value of Pride". Trim is a conditioning variable
in the estimator, not something averaged over. Under that target, uneven trim
sampling costs **precision within each trim**, which the count gate already
governs; it does not bias the conditional estimate. The bias enters only when
something aggregates across trims, and the sensitivity span above is exactly
how much.

Consequences, stated so they cannot be quietly forgotten:

1. Any CARO output phrased as a per-vehicle estimate is within scope.
2. Any output phrased as a market-level aggregate — "Pride is up 8% this
   month", a model-level median — is **out of scope** on this sampling
   design, and must either carry the sensitivity span or not be published.
3. The span is a reportable quantity alongside the estimate, not a footnote.

## D30 — The conditional defence has preconditions, and one of them fails

D29 concluded that uneven trim sampling costs precision *within* a trim
rather than biasing a conditional estimate. That is true, and it is not free.
It holds only if trim genuinely conditions the estimate rather than being
extrapolated around, so the conditions are checked rather than asserted:

1. trim is present as a conditioning value;
2. each trim carries at least `MIN_PER_TRIM = 5` observations;
3. at least 70% of eligible listings sit in such trims;
4. nothing downstream aggregates across trims assuming sampling weights.

**Condition 3 fails on the 2026-09-07 corpus at 55%.** Nearly half the
eligible listings sit in trims of one or two, so their prices come from the
pooled distribution — exactly the extrapolation the conditional argument
assumes is not happening.

The consequence, stated precisely, because an earlier draft of this entry
overstated it. The span does **not** demonstrate bias. What it shows is that
the estimate is *sensitive to the sampling design being assumed*; and since
`P(inclusion)` is unknown, there is no standing to nominate any one of those
designs as the correct weighting. So the span cannot be read as precision
either — it is design sensitivity, reported and unresolved. W1 stays closed
for that measured reason rather than a cautious one.

What is frozen in the contract is the **principle** — *a conditional
appraisal may only be served when the estimator does not materially
extrapolate across thin trims* — not the number 5. A properly benchmarked
hierarchical or shrinkage estimator would change what counts as material
extrapolation, and should be able to do so without breaking the contract.
Freezing the threshold rather than the principle would turn the contract into
an obstacle to improving the estimator.

The first three are checkable on data; the fourth is about what a caller does
with the output, so it is enforced where the output is used.
`MarketEstimator.aggregate()` raises `AggregateOutOfScope` unless a
`SamplingSensitivity` accompanies the number. It refuses rather than warns,
because a warning printed beside a market-level median is read as a caveat:
the number gets quoted and the caveat does not.

`SamplingSensitivity` is deliberately a third quantity rather than a
contribution to `estimate_confidence`. D8 established that two uncertainties
must stay apart because they demand opposite user actions; this one is
different again — it is a property of the **acquisition design**, and no
volume of further listings collected the same way will shrink it. A
confidence band that absorbed it would tell the user their uncertainty is
reducible when it is not.

One thing deliberately not done: `MIN_PER_TRIM`, the 30-eligible floor and
the variation thresholds were all left alone. Tiba clears the gates with 38
observations and carries an 11.5% sampling span. That span is a reportable
fact about Tiba, not evidence that a gate is mis-set — moving a threshold to
make a model look better is the exact failure this contract was frozen to
prevent.


## D31 — Deeper inside the trims we have, not more trims

Run 3's remaining failure is condition 3 of D30: 55% of eligible listings sit
in trims with five or more observations, against a 70% requirement. The
obvious response is the wrong one. Adding models, category pages or new trims
raises the count and *lowers* this share, because each new facet arrives with
one or two listings of its own — it would make the number worse while looking
like progress.

So Run 4 goes the other way:

    existing model
      └── existing, already-populous trim facet
            └── deeper valid acquisition
                  └── more independent listings in trims we already have

The question, fixed in advance:

> Can the share of genuinely conditional observations be raised from 55% to
> the 70% threshold, **without changing any gate and without constructing a
> weight**?

Both outcomes are informative, which is the point of stating it this way.

*If yes* — the D30 preconditions are re-evaluated and, if they pass, W1's
estimand gate opens for the models that qualify.

*If no* — that is a finding rather than a setback: this acquisition design
cannot support a conditional appraisal at this granularity, and the response
is to change the **estimator or the design** — a hierarchical model that
borrows strength across trims honestly, or a coarser conditioning level with
its own benchmark — and never to move the threshold.

The standing rule from D28 carries over: the route's own ceiling is measured
before anything is concluded from a shortfall. A trim page that saturates at
twenty listings cannot supply thirty, and reporting that as market thinness
would repeat the mistake the pre-flight exists to prevent.

## D31 (result) — the ceiling is the source inventory's shape, not our route

Run 4's pre-flight answered D31 without needing the collection, and the
answer is stronger than a shortfall: the ceiling is provable.

**Trim-level pagination does not exist, and pretending it does is dangerous.**
`/car/pride-131-se-page-2` answers 200, redirects to page 1, and returns the
identical ten listings. `/car/quick-manualr-page-2` is worse: it answers 200,
redirects to `/car/quick-manualr-page`, and serves **Tara, Dignity, Renault
and Toyota** — the generic feed. Nine of its listings looked "new". None was
that trim.

That is `/car/saipa` from Run 1, exactly, third occurrence. Without the
pre-flight those nine would have been collected as trim depth, and the run
would have reported *higher* conditional coverage manufactured entirely by a
crawler bug — an acquisition failure dressed as progress on the precise
metric the experiment exists to move.

**The real ceiling, measured directly.** Because conditional coverage is a
function of listing counts per trim, it can be measured without fetching a
single detail page. All 34 published `pride` trim pages, on-target slugs
only:

    11, 10, 9, 8, 8, 7, 6, 6, 5, 5, 5, 5,
     4,  4, 4, 4, 3, 3, 3, 3, 3, 3, 2, 2, 2, 2, 2, 1, 1, 1, 1, 1, 1, 0

    135 listings · 22 of 34 trims hold fewer than 5
    MAXIMUM ACHIEVABLE COVERAGE = 63%

That is with **complete** acquisition of everything Bama publishes for Pride.
63% < 70%, and it is an upper bound: eligibility ran ~85% in Run 3, so the
attainable figure is lower still.

So D31's answer is **no**, and for the most useful possible reason. The
shortfall is not our sampling and not the route — it is the shape of what
this source publishes. **Bama's published Pride inventory** is long-tailed
across trims on the snapshot measured, and no acquisition strategy makes
`pride-151-sl` have more than the two cars listed there.

That distinction is not pedantry. We have seen one source on one day. Whether
the Iranian Pride *market* is long-tailed is a different claim, about a
population we have never observed, and nothing in this run bears on it. See
D36.

### What follows, per the options fixed in advance

Option (3) — change the estimator or the estimand — is now the only live one,
and the choice between them is a real design decision rather than a
formality:

- **A hierarchical / shrinkage estimator** that borrows strength across trims
  and benchmarks the extrapolation it performs. This keeps trim-level
  conditioning and makes the borrowing explicit and measurable, which is what
  the current design does implicitly and unmeasurably.
- **A coarser conditioning level** — model plus body style, say, rather than
  full trim — chosen so the coverage condition is met, with its own
  benchmark. Cheaper, and it gives up genuine resolution: `pride-131-se` and
  `pride-131-sl` are not the same car to a buyer.

Neither is a threshold change, and the 70% is not revisited. What is revised
is what the estimator claims to condition on — which is the honest response
when the data cannot support the granularity the estimand assumed.

`docs/DATA_CONTRACT.md` gains the measured ceiling so a later reader does not
re-run this experiment hoping for a different answer.

## D32 — Partial pooling that shows its work

D31 closed acquisition: the trim tail is the shape of what this source
publishes, and no crawling fixes it. The remaining honest option is to keep trim-level conditioning and
make the borrowing across trims **explicit, measured and visible**, instead of
implicit and unmeasurable as pooling already is.

The trap is specific and worth naming, because the fix looks like the
failure. A hierarchical model trained only on this corpus can learn

    thin trim → parent mean

and then present exactly the extrapolation the pooled estimator was already
doing, in Bayesian clothing, with a better-looking average error. Three
structural defences:

**1. Shrinkage is computed, not chosen.** `λ_t = τ²/(τ² + σ²/n_t)` —
empirical Bayes, where the between-trim and within-trim variances decide how
much a trim speaks for itself. Nothing is hand-tuned toward a nicer answer,
and when the trims are statistically indistinguishable `τ² = 0` sets λ to
zero everywhere, which is the correct refusal.

**2. Every prediction carries a `PoolingTrace`** — the trim's observation
count, how much of the estimate came from the trim versus the parent, and
whether that is material extrapolation. A thin-trim estimate and a
well-observed one are different claims, and the difference is not visible in
the number.

**3. The gate stresses the tail separately.** `held_out_trim_split` holds out
**entire trims**, not rows: a trim the model has never seen must be priced
from its parent alone and must admit it. A row-level split cannot ask that
question, because every trim appears on both sides. Mean error over a corpus
dominated by fat trims cannot see a model that is useless on 45% of it.

### What the tests forced

The first version flagged extrapolation on λ alone, and a **one-listing trim
came out at λ = 0.58** — above the threshold, so it passed as a normal
conditional estimate. Empirical Bayes was not wrong: when between-trim
variance is genuinely large, one observation *is* informative. But λ measures
how much the model should weight the trim; it does not measure whether a
buyer should be told the number rests on a single advert.

So the flag now fires on either trigger, and the observation floor is
literally the same constant the data contract uses — `MIN_PER_TRIM_FLOOR`,
moved into `quality.py` and imported by both. Two constants meaning "too few
to speak for itself" would have drifted, and the drift would have surfaced as
a confident estimate the contract says is out of scope.

### Borrowing strength is not a sampling weight

The distinction that makes this legitimate where D29's weighting was not:
using Pride to inform `Pride 131 EX` claims that **Prides are informative
about Prides**. It never claims to know 131 EX's share of the market. That is
why partial pooling is available here and `1/P(inclusion)` weighting is not —
the first is a statement about similarity, the second about composition, and
only the second needs a quantity we do not have.

W1 stays locked. D32 supplies the estimator; it does not benchmark it on the
real corpus, and until `AcceptanceGate` is run with the thin-trim and
held-out-trim slices reported alongside the aggregate, nothing here is
evidence that the approach works on Bama data rather than on a fixture.

## D33 — What writing the gate's tests changed about the estimator

Three real defects, each found by a test rather than by review, and each
worth recording because the pattern repeats.

**1. λ is not evidence sufficiency.** The extrapolation flag first fired on
shrinkage alone, and a one-listing trim came out at λ = 0.58 — above
threshold, passing as an ordinary conditional estimate. Empirical Bayes was
right: with large between-trim variance one observation *is* informative. But
λ says how much the model should weight a trim; it says nothing about whether
a buyer should be told the number rests on a single advert. The flag now
fires on either trigger, sharing `MIN_PER_TRIM_FLOOR` with the data contract.

**2. The intervals were sized for trims we had seen.** Training residuals are
computed *after* each trim's offset is applied, so they describe within-trim
scatter. For an unseen or heavily-shrunk trim the offset itself is unknown
and its variance belongs in the band:

    predictive variance ≈ σ²_within + (1 − λ_t)² · τ²

Held-out-trim coverage was **12% against a nominal 70%** before this. The
point estimate correctly fell back to the parent while the band stayed as
tight as if the trim were fully observed — textbook "more confident and less
right", and the gate caught it.

**3. The gate repeated a mistake W1 had already fixed.** It judged slice
coverage on raw deviation. On an 18-listing slice the coverage estimate
carries about 11 points of standard error, so a 19-point miss is under two SE
and means nothing; judging several slices that way picks the noisiest one
every time. Significance testing at 2.5 SE was added — the same correction,
for the same reason, as W1's `significant_coverage_error`. Third time this
project has met the winner's curse.

That correction exposed the honest constraint underneath. To detect a
15-point coverage deviation at 2.5 SE requires **n > 58**, so `MIN_SLICE_N`
is derived rather than chosen. Slices below it cannot support a calibration
verdict, and the gate treats a required-but-unjudgeable slice as a failure
with a distinct message: *not a model failure — the corpus cannot judge this
slice*. Passing there would accept a model precisely where it was never
tested.

**The consequence for the real corpus is direct.** Run 3's 221 listings split
into thin and held-out slices of roughly 14–44 rows. None reaches 58. So the
2026-09-07 corpus **cannot calibrate a hierarchical estimator per slice at
all** — which is a fact about the data, stated as a verdict, and another
measured reason W1 stays locked.

### Two adversarial fixtures that failed to break it

Worth recording because the passes were informative. A uniform thin-trim
premium does not break calibration: it inflates τ² and the bands widen
correctly. Nor does a highly dispersed tail, because τ² is estimated over all
trims including the thin ones. The estimator is better behaved than either
guess assumed.

What does break it is narrower: **held-out trims drawn from somewhere the
training trims never went.** τ² then measures the variation we saw, the bands
are sized for it, and the model is confident exactly where it has no
information. The gate rejects that and accepts the on-distribution twin, so
it discriminates rather than always refusing — a gate that always fails being
exactly as useless as one that always passes.

## D34 — The benchmark ran. The verdict is UNJUDGEABLE, and that is a result.

Partial pooling against the Run 3 corpus, 155 appraisal-eligible listings
across 43 trims, held-out-trim split:

    slice                   n          MAE     cover   err  shrink  extrap
    well-observed trim     75   64,072,026      69%    1%    0.93      0%
    thin trim              54   63,738,855      70%    0%    0.84    100%
    held-out trim          26  115,525,217      77%    7%    0.00    100%

    MAE 63,932,559 vs parent-median baseline 133,372,093   (−52.1%)

    VERDICT: UNJUDGEABLE_SLICE

The numbers look good. **That is exactly why the verdict matters.** A 52%
improvement over the baseline, coverage within a point of nominal on the
slices we can measure, shrinkage behaving as designed — and none of it
licenses serving a conditional appraisal, because the two slices the claim
depends on carry n = 54 and n = 26 against the 58 a calibration verdict
requires. Their coverage figures are real measurements — what is missing is
enough of them to turn a measurement into a calibration verdict.

The distinction matters and an earlier draft got it wrong, calling those
figures "noise that happens to look reassuring". They are not noise. They are
observations with an interval too wide to decide anything, which is a
different and more honest complaint: we measured, and the measurement cannot
settle the question.

Publishing on this would have been easy and defensible-sounding: the
aggregate is genuinely strong. It is also the precise inference D30 refused —
concluding from a corpus-wide number that a *conditional* claim holds, when
the conditioning is exactly where the evidence runs out.

Three separate, measured reasons W1 is locked, none of them a judgement call:

1. **D30** — conditional-scope condition 3 fails at 55% against 70%.
2. **D31** — the acquisition ceiling is 63%, proved from the source's own
   trim census. No crawling reaches 70%.
3. **D34** — the corpus cannot calibrate the estimator that would have made
   trim-level conditioning defensible anyway.

The third subsumes neither of the others and is not implied by them. A corpus
could satisfy D30 and still be too small to calibrate; this one fails both,
independently.

### What would change the verdict

Not tuning. `MIN_SLICE_N = 58` is arithmetic — 2.5 binomial standard errors
on a 15-point coverage deviation — so lowering it does not buy information,
it buys the appearance of one. What is needed is a thin-trim slice of ~58 and
a held-out-trim slice of ~58, i.e. roughly 400–500 eligible listings rather
than 155. Run 3's route can supply that: 1,862 published trim pages at ~10
listings each, well beyond what four model families were sampled for here.

That is a straightforward, bounded collection job with a known cost, and it
is the honest next step. What it is not is a modelling problem.

### The property this establishes

CARO reports uncertainty about prices. It now also reports **uncertainty
about its own ability to assess uncertainty** — and refuses on it. The
distinction between "the model is wrong" and "we cannot tell whether the
model is wrong" is the one a benchmark normally erases, and it is the one an
appraisal product most needs to keep.

## D35 — Acquisition and estimator do not change in the same run

From here the two are separated, and the separation is the decision.

The next run is **mechanical**:

    bounded acquisition  →  ≥ required eligible corpus
                         →  the SAME frozen estimator
                         →  the SAME frozen AcceptanceGate
                         →  judge thin + held-out slices

and explicitly not:

    more data → tune model → change threshold → rerun → keep the nicer result

The second loop is not a worse version of the first; it answers a different
question. Every free parameter it touches is one the verdict depends on, so
whatever comes out is a statement about the search, not about the market.
D34 would have been quietly relocated rather than answered.

This also means a failure after the next acquisition is **still a result**.
If 450 eligible listings arrive and the gate returns REJECTED, that is the
honest finding that partial pooling does not support trim-level conditional
appraisal on Bama data — and it is a finding worth having, not a state to
tune out of.

The rule is deliberately stricter than it needs to be. There will be a
legitimate reason to change the estimator eventually; the point is that it
must not happen in the same step as changing the corpus, because then
neither change can be attributed.

## D36 — A mechanism is not a market fact

Three text fixes in a row turned out to be one error wearing three
costumes. Writing this entry found a fourth in the test suite and a fifth in
the very paragraph of D18 the entry was being cross-referenced from. Running
this entry's test for the first time found three more, including one in the
shipped package. A later review found a ninth, in the synthetic benchmark.
Nine is enough to stop calling it a proofreading miss.

The count is worth stating in that order, because the order is the argument.
Careful reading found two. A twenty-line regression test found three more in
one second, one of which had survived being read past twice in the same
week. Review then found a ninth that the test could not have — it was
phrased in words no catalogue held. Neither method subsumes the other, and
the entry ends by saying which one is load-bearing for what.

**The pattern.** A mechanism the design supports gets restated as an
observed fact about the market.

    supported by the design   "sorting by price can systematically favour
                               damaged cars"
    promoted to market fact   "the cheapest listing is usually the most
                               damaged one"

The promoted version is shorter, more useful, more quotable, and reads
like the kind of thing a product person is supposed to say. It is also a
claim about Iranian used-car prices that this project has never measured.
Nothing in the corpus, the benchmark or the estimator establishes it.

**Where it has appeared.**

                                                                    found by
    1  price_gap_fa()    "the seller has already accepted this      review
                          price, so there is room to negotiate
                          above it"
    2  D18               "cannot credibly refuse it elsewhere"      review
    3  README            "the cheapest listing is usually the       review
                          most damaged one"; "a number the seller
                          has already accepted"
    4  test_ingest.py    "minimum ask is the negotiation floor"     reading
    5  D18               "when the prices differ, which they        reading
                          usually do"
    6  README            the same sentence as (5), copied           TEST
    7  README            the retired Persian copy of (1), still     TEST
                          printed as a sample of CARO's output
    8  caro/ranking.py   "the cheapest listing is usually the       TEST
                          most damaged one" — the module docstring
    9  test_appraisal    the Oracle described as "the upper bound   review
                          on performance"

Five of these are worth more than a note.

(4) is the mildest and the same inference: `min(prices)` is the lowest
number the seller has *published*, and calling it a floor asserts they will
not go below it — the retired claim exactly, in a test label nobody thought
of as a claim.

(5) sits in the paragraph of D18 that already corrects (2), written by
someone who had just finished being careful about this. How often
cross-site prices differ is a market frequency CARO has never measured; the
cross-source path has only ever run on fixtures. It was found while adding
a pointer from D18 to this entry — the pattern reproducing inside the act of
documenting the pattern.

(7) is the most instructive. When (3) was fixed, the corrected paragraph sat
four lines above a fenced block printing the *retired Persian copy* as an
example of what CARO says. The prose was fixed; the sample output beneath it
was read past. Fixing a claim in one register leaves it standing in another,
and the register nobody re-reads is the one showing output.

(8) is the most serious. It was not in a document at all — it was the
opening docstring of `caro/ranking.py`, stating the market fact as the
module's stated thesis, which makes it the version a reader of the code
meets first. Three rounds of documentation review never opened that file.

(9) is the pattern in its synthetic form, and the most dangerous shape it
has, because it is *almost* true. The Oracle reads quantiles out of the
fixture's own generating formula, so within the fixture nothing can beat it
— which is exactly why calling it "the upper bound on performance" reads as
harmless. It is a ceiling for one data-generating process and three
features. Unscoped, it licenses putting D34's real MAE beside a synthetic
number and calling the difference headroom, and that comparison has no
meaning at all. The synthetic tier exists in the table below for this.

**What does not belong in this catalogue.** The same review flagged
`ComparableQuantiles` for saying its comparable count "IS the confidence
signal". That sentence is wrong and was fixed in the same commit — but it is
not this pattern, and filing it here would make D36 a bin for every
inaccurate sentence in the project. It is a docstring that predates its own
correction: D9 records finding that tier and count were being *added*, so a
strict match on five comparables scored below a relaxed match on any number;
tier became a ceiling, count a fraction of it, and W2 later widened
confidence to six dimensions (D8). The docstring simply never caught up.

The distinction is worth holding. D36 is about claims that outrun their
evidence. A stale docstring is about a claim that outran its own codebase.
Both are real; only one of them is a pattern, and a decision that covers
everything constrains nothing.

**Why prose alone did not stop it.** CARO already owns a machine for this.
`EvidenceLedger.unsupported_claims()` refuses to let W2 tell a buyer
anything the ledger cannot source, and `tests/test_agents.py` asserts the
list is empty for every generated response. It works. All nine instances
landed just outside its scope: assembled template copy, a design record, a
README, a test label, a design record again, the README twice more, a module
docstring.

So the failure is not an absent mechanism. It is a mechanism with a boundary
and nine recurrences on the far side of it. That is the finding worth
keeping, and it is not specific to this project: the
surface where a system speaks to its users tends to be governed carefully,
and the surface where it explains *itself* tends not to be governed at
all.

**The rule.** Five tiers, kept distinct in anything a reader sees:

    mechanism            the design supports it    "can", "is designed to",
                                                   "responds to"
    hypothesis           believed, untested        "we expect", "if"
    synthetic property   built into the fixture    "in the generating
                                                   process"
    observed corpus      measured in a real run    "we observed, in N
                                                   listings on <date>"
    transaction fact     someone paid this         only with transaction
                                                   evidence

The bottom tier is currently empty and that is not an oversight. CARO
observes asks, never settlements; there is no `sold` field and a
disappearance is not a sale (D3). No sentence anywhere in this project may
sit in that tier today.

A mechanism does not become an empirical claim by being plausible, by
being load-bearing, or by recurring in the architecture until it feels
settled. The last is how all nine happened — each was true as a mechanism
somewhere upstream and lost its qualifier on the way down.

**Sourced is not the same as tiered, and the ledger only checks the first.**
`EvidenceLedger` asks whether a claim can be traced to an observation. D36
asks whether the claim says no more than that observation supports. They are
different questions and both can fail alone:

    evidence   38 comparable listings, tier=strict, observed 2026-09-07
    claim      «۳۸ آگهی مشابه»                      sourced ✓   tiered ✓
    claim      "so this car is worth 1.4B"          sourced ✓   tiered ✗

The second claim passes the ledger. Its evidence id resolves, the count is
real, the observation happened. What fails is the *step* from a count of
asks to a statement about worth — and no provenance check can see a step,
because provenance is about where a number came from and tiering is about
what a sentence does with it. So the two mechanisms sit side by side, and
neither is redundant.

**The check.** `tests/test_claims.py` asserts the retired phrasings do not
return, across every surface a reader meets — the README, the design record,
the data contract, the package, the scripts, the other suites — plus the
Persian copy the shipped functions actually emit, generated rather than
grepped, because instance (1) was assembled at run time from fragments no
file contains.

It enforces one rule, and the rule is what makes it mechanical at all: **a
retired claim may appear only in quotation marks.** Every sentence in the
catalogue has to stay quotable, or this entry could not list them and D18
could not correct itself. What is forbidden is the phrase asserted in the
project's own voice. Cite the mistake; do not commit it. "Is this an
overclaim?" is semantic and cannot be tested. "Is this inside quotation
marks?" is not.

The rule has one consequence worth knowing before it surprises someone: a
*denial* is not an exemption. The first replacement for (9) read "it is not
an upper bound on performance" and the test rejected it, correctly by its
own rule and annoyingly in the moment. Writing it as "an earlier docstring
called it `the upper bound on performance`, which it is not" passes. That is
the right outcome for a reason worth more than the inconvenience: a reader
skimming a denial and a claim sees the same words, and the quotation marks
are what tell them which one they are looking at.

**Patterns and instances are different counts.** This entry numbers
*instances* — one claim, one place, one time. The test holds *patterns*, and
one pattern covers several instances whenever the same sentence turned up
twice: (1) and (3) are one regex, so are (3) and (8), so are (5) and (6).
Nine instances, seven patterns, permanently. A reader comparing the two
counts and finding them unequal is looking at the design, not a gap.

Neither count is written down twice. The suite prints both from its own
catalogue, and reads the instance numbers straight out of *this file* to
assert the two agree in both directions — a D36 entry with no pattern fails,
and a pattern for an instance never recorded here fails too. The parse is
strict and returns nothing if the catalogue's format changes, which the
first assertion turns into a loud failure; a cross-file check that passes
silently once it can no longer see one of the files is worse than no check,
because it reads as coverage. This project has lost that bet before —
`MIN_PER_TRIM_FLOOR` was two constants meaning one thing, and a renamed
field survived in EVAL.md for a week.

**Two things are retired, and a hit means different things.** A `claim`
entry approximates one sentence: a match is that sentence returning. A
`vocabulary` entry retires a *term* from own-voice copy in every sentence,
denials included — "negotiation floor", "upper bound on performance". A
vocabulary hit is a policy violation, not a finding that the surrounding
sentence overclaims. The regex does not read sentences and the catalogue
says so per entry, because a guard that quietly implies more precision than
it has is the failure this whole entry is about.

The quotation exemption has been narrowed twice, both times because the
safe direction for a heuristic here is to exempt *less*: a missed exemption
is a false alarm someone clears in a minute, an over-broad one retires the
guard silently.

First, long single-quoted runs, so that `'an ordinary python string'` no
longer counts as a citation. That was measured rather than argued — across
every surface and every pattern the narrow and wide rules returned identical
verdicts, so it bought nothing and could only have hidden something.

Second, and this one was not free. **In prose, quotation marks mean
citation; in source code they mean "this is a string"** — often a string a
user will read: a Persian template, a printed label, an error message.
Exempting those turns the guard off exactly where output lives. Python
surfaces are now split with `tokenize`: citations count in comments and
docstrings, and code gets no exemption at all. That split immediately found
"negotiation floor" in a `check(...)` label in `tests/test_ingest.py` —
retired vocabulary, printed on every run, in the very file whose label had
been corrected for instance (4). The correction had kept the term and
rearranged the sentence around it.

That is the tenth occurrence and it is not numbered, because it is the same
term as (4) in the same file rather than a new claim. It is recorded here
because of what found it: not review, not the catalogue, but narrowing an
exemption and re-running.

**Unknown is as loud as a hit.** A Python file the scanner cannot tokenize
fails the pattern it was being checked for, rather than falling back to the
prose rule or returning no hits. Both of those misrepresent something: the
fallback presents a weaker rule's verdict as a policy scan, and an empty
result makes the file read as *clean* while leaving the whole surface
resting on one summary assertion — weaken that later and the hole is silent.
The honest verdict on a surface that could not be read is not "clean", it is
"unknown", and this suite treats the two differently on purpose.

**The scan set is verified, not declared.** The suite says it covers
`caro/**/*.py`; an independent `os.walk` enumeration is compared against
what the glob actually produced, and compared for *equality* — a subset
check would only catch the glob missing a file, while a scope that picked
up something os.walk does not see has also stopped matching its own
description. Two ways of listing the same files, compared: the same move as
reading the instance numbers out of this file rather than copying them.

The scope is also stated at its real size. It is "every reader-facing
surface currently in the scan set", not "everywhere a reader looks" — a
`CHANGELOG.txt` or a `.rst` added tomorrow falls outside it and this guard
would say nothing. Widening the set is one line when a surface appears;
describing it as already general would be the entry's own pattern, in the
entry.

Two limits are named rather than closed. The quotation exemption is
**syntactic** — quote marks are not evidence that the quoted text is a
historical citation, so a sentence asserting a retired claim while quoting
it goes free. And the Python split is a statement-level string heuristic,
not AST docstring detection; `tokenize` cannot tell a docstring from any
other bare string in those positions. Both could be closed by making this a
parser, and neither is worth becoming one.

The shipped demo is checked separately and differently. `demo/index.html`
and `demo/demo_data.json` are *generated* — written once and committed, so
`tests/test_agents.py`, which guards live orchestrator output, cannot see
them. Add a guard after an export and the committed artefact keeps the old
words while every test still passes. They are therefore scanned as files,
against the tiers rather than the catalogue: «قیمت واقعی», «ارزش واقعی»,
«کف بازار», «فروخته», «قبول می‌کند», «می‌ارزد», «قطعاً». All clean today;
the point is that this is now checked rather than believed.

Those words are **not** D36 entries and must never be cited as such. They
carry no instance numbers and take no part in the pattern/instance
accounting — they are a standing wordlist enforcing the same boundary, kept
in the same file for convenience and labelled apart from the catalogue on
purpose.

There are in fact three lists in that file, doing three jobs, and conflating
them is the obvious way to misread it: the **catalogue** (nine instances,
seven patterns, scanned across every surface), the **demo wordlist** above
(seven Persian terms, scanned against the two committed artefacts), and a
handful of **fixture probes** on the cross-source strings instance (1) lived
in — «پذیرفته», «قبول کرده», «تأیید», «قطعاً», «حتماً» — which run against
live output from `cluster_across_sources()` and nothing else. Only the first
is D36.

The catalogue's own accounting has one wrinkle worth recording. Instance (3)
maps to two patterns, because that one README paragraph carried two separate
claims. Repeats like that are legitimate and are declared in the suite
rather than inferred; an undeclared repeat, or the same number listed twice
inside one entry, fails. Without that the set-based coverage checks would
swallow a typo silently. This decision is worth something because it is narrow. A decision
that absorbs every adjacent good idea ends up asserting nothing, and the
temptation to grow this one will be constant, since almost any careless
sentence in the project is *adjacent* to it.

Its limits, stated here rather than discovered later: it is a regression
test, not a lint. It knows the nine claims that have already been caught.
It cannot recognise a tenth overclaim phrased in new words, and no
reasonable test can, because the judgement is semantic. What it buys is
that the specific failure this decision is about — **recurrence** — is now
mechanical instead of depending on who reads the file next.

The tier vocabulary is the part a human still has to apply. Instance (9) is
the proof: it was phrased in words no catalogue held, and only a reader
noticed. The test prevents recurrence; a reader is still what finds the
first one.

One last thing this entry does **not** claim. `tests/test_claims.py` does not
govern what CARO says to a buyer — `EvidenceLedger` does, and the section
above explains why both are needed. Reading D36 as "overclaiming is now
handled" would be a mechanism restated as a guarantee, which is the pattern
this entry is about, applied to the entry itself.

### D36 — frozen

Reviewed and closed at `4d95b7d`. Nine instances, seven patterns, 47
assertions, inside a suite that totalled 603 at that moment (the project
total moves; this is a freeze-time snapshot, not a current count). Reopen it
for a real recurrence, a
real bug, or a genuinely new surface — not to improve it. Its value now is
that it is finite, and every addition costs some of that.

Three standing rules, written here because they are the ways it will
plausibly be widened by someone acting in good faith:

1. **A new claim earns one pattern, not a category.** Semantic review
   decides it is a retired claim; then one explicit pattern, one instance
   mapping, one test. Adding synonyms to future-proof a pattern is how a
   regression guard becomes a vocabulary lint, and no synonym goes in until
   a recurrence has actually used it.
2. **`NEVER_IN_OUTPUT` is not D36.** A phrase added to the demo wordlist is
   an output policy, not a historical instance. The three lists stay three.
3. **D36 is not a reason to collect data.** D35 is unchanged: bounded
   acquisition → required eligible corpus → the SAME frozen estimator → the
   SAME frozen gate → judge thin and held-out. Claim discipline improving
   does not make the corpus more able to answer, and no acquisition starts
   without an explicit decision to run that experiment.

The reason it belongs in this record at all is that it turned out to be the
same decision the rest of the project keeps making, one level up:

    D1    a failed fetch is not an absence
    D3    a disappearance is not a sale
    D8    confidence is not completeness
    D11   insufficient evidence is a product state, not a silent guess
    D22   suspicious is not deleted
    D30   an unsupported aggregate is out of scope, not approximated
    D34   uncalibrated is UNJUDGEABLE, not passable
    D36   an unscanned surface is not a clean one

Every one refuses the same move: turning *we do not know* into *it is
fine*. D36 applies it to the project's own prose, which was the last place
still doing it.

## D37 — A sample-size multiplier is not an acquisition strategy

Found while pre-registering Run 5, before any request was sent, and recorded
here because it is a fact about **our own gates' arithmetic** — not an
observation about the market, and not a result. Under D36's tiers it is a
derivation from frozen constants; it would be true of a corpus that does not
exist yet, which is precisely why it could be established on paper.

D34 left two slices short, and the obvious reading was "collect about twice
as much". That reading is wrong, and not by a margin:

    thin slice   rows in TRAINING trims with 4 or fewer listings  (needs 58)
    coverage     share of eligible rows in trims with 5 or more   (wants 70%)

These are complements. Every listing that lifts a trim from four to five
raises coverage and removes that trim's rows from the thin slice. So the two
gates the project already froze pull in **opposite directions on acquisition
strategy**, and neither pure strategy satisfies both:

    strategy   eligible  trims  thin  held  cover
    deepen            —      —     —     —      —   UNREACHABLE
    broaden         229     74   107    62    40%   fails D30
    mixed           312     62    60    76    76%   ok

Deepening being *unreachable* rather than merely expensive is the part worth
keeping. D31 chose to deepen existing trims specifically to raise coverage
from 55% toward 70%. It does — and past a point the thin slice is empty, so
the benchmark that decides whether thin-trim estimates can be trusted has
nothing left to judge. A strategy chosen to satisfy one gate destroys the
other's ability to run at all.

**The consequence: a corpus target is a shape, not a count.** Run 5 needs 312
eligible listings across ~62 trims, every well-observed trim at five or more,
and enough trims under the floor to put 58 rows in the thin slice. The same
312 collected the obvious way — deepest models first — satisfies neither
gate, while the count alone reads as success.

**Why this had to be found before collecting, not during.** Halfway through a
run, this arrives as pressure to relax 5, or 70%, or 58. Each of those makes
the shortfall disappear without answering anything, and each would be
proposed in good faith by someone who has just spent two weeks collecting.
D34's verdict is only worth what it cost if the threshold that produced it
survives contact with the inconvenience. The cheapest moment to fix a number
is before anyone is invested in it.

`scripts/run5_target.py` derives all of this from the Run 3 snapshot and
disagrees with `docs/RUN5_SPEC.md` if either the corpus or a frozen constant
moves. The 640-request cap is the one number it does *not* derive: that is
registered, and the script checks the derivation against it, because a budget
recomputed from its own formula grows with the formula.

## D38 — Run 5 rejected the estimator, and the registration was blind

The run executed as registered: 615 of 640 requests, the frozen estimator,
the frozen gate, no constant touched. `HierarchicalGate` returned
**REJECTED** — MAE 606,996,397 against a parent-median baseline of
526,344,633, 15.3% worse. That failure is judgeable and does not depend on
any slice being large enough, so the held-out slice landing at 51 does not
soften it into UNJUDGEABLE.

**D12 is now live, not hypothetical.** It has said since the beginning that
if the baseline wins, the baseline ships and we say so. On this corpus the
baseline wins. The README leads with that.

Three numbers stay separate and none of them is the verdict:

    thin slice        87   MET — judgeable for the first time in the project
    held-out slice    51   short of 58; not a model failure, an unanswered
                           question about that slice
    coverage         47%   D30's precondition still fails, by more than Run 3

**D37 has an empirical result now.** It predicted that thin-slice size and
conditional coverage are complements and that no single acquisition strategy
buys both. Reaching a judgeable thin slice took 100 trims where D37's model
assumed 62, and coverage fell from Run 3's 55% to 47% doing it. The tension
was real and it went the predicted way.

**The finding worth more than the verdict.** `RUN5_SPEC.md` §2 constrained
the trim-size distribution in detail — counts, floors, slice sizes — and said
nothing about price heterogeneity or make composition. Run 3 was four Saipa
models; Run 5 spans 44 makes and a 143× price range. Both satisfy the
registered shape. They are not comparable estimation problems.

What Run 5 established, stated at the level the evidence reaches: **a regime
exists in which this estimator's cross-trim borrowing costs more than it
buys** — a corpus of 44 makes across a 143× asking-price range, on which the
parent-median baseline did better. That the shrinkage is *what* caused it is
a mechanism I find convincing and did not measure. Isolating it would need
the error decomposed against the other candidates the same corpus carries:
missing prices, missing odometers, dealer and current-model-year
concentration, and extrapolation into unseen trims. None of that was done, so
the mechanism stays a hypothesis (D36's second tier) and the regime stays an
observation.

Nothing was violated. The registration was blind, in advance, to the variable
that decided the outcome — which is the only way that could have been
established at all. **A shape specification is not sufficient to make two
corpora comparable**, and any future registration in this project has to say
what it holds constant about the *problem*, not only about the sample.

**The pre-flight over-read its own sample, and that is the same error class
as D36 at smaller scale.** Seven detail pages from one thin trim came back
6-of-7 usable, and §10 recorded that as "nothing suggests the tail converts
worse", keeping 0.701. The real rate was **0.566**. At n=7 the interval spans
roughly half the range and one trim is one trim; the honest record would have
been "this sample cannot speak to the tail's conversion rate". D36 is about a
mechanism promoted to a market fact — this is evidence promoted past what its
sample size supports. Different sentence, same failure: a claim outrunning
what is behind it. D36 stays frozen and does not absorb this; the two sit
side by side.

**Run 6 is not a rematch.** Constraining price band, constraining make
composition, or comparing estimators on a narrower corpus are all legitimate
experiments and none of them is a continuation of this one. Each needs its
own registration and has to name the question it answers, because it is not
this question. D35 is unchanged and now bites in the other direction: after
an estimator loses, changing the corpus and re-running is the single most
natural way to manufacture a win, and it is the loop this project exists to
refuse.

## D39 — The REJECT does not survive its own uncertainty

Raised in review, measured immediately, and it changes what Run 5 is allowed
to claim.

`HierarchicalGate` rejects when model MAE exceeds baseline MAE by more than
10%. Run 5 tripped it at +15.3% and the gate returned REJECTED. **That
criterion is a bare comparison of two point estimates.** A paired bootstrap,
resampling *trims* rather than rows because rows inside a trim share a price
level and a parent:

    model MAE               606,996,397
    baseline MAE            526,344,633
    observed                +80,651,765   (+15.3%)

    95% CI on the difference   [-323,924,724, +435,581,962]
    95% CI on the ratio        [0.59x, 2.18x]
    P(model worse)                  68.0%
    P(worse by more than 10%)       58.1%

The interval straddles zero by a wide margin. At 177 rows in 75 trims across
a 143× price range, a handful of expensive cars moves the mean absolute error
further than the effect being measured. **58% is barely distinguishable from
a coin flip**, and that is the probability attached to the exact statement
the gate rejected on.

**This is the fourth time this project has met this error, and the first
three are in D33.** A max over 48 noisy slice estimates rejected a perfect
Oracle; `MIN_SLICE_N` rose to 58 so a coverage deviation counts only past 2.5
binomial SE. Both fixes put significance testing on the **calibration**
criterion. Neither was applied to the **MAE** criterion — one field away, in
the same gate, in the same dataclass, with a bare `>`. I wrote the second fix
and did not look sideways.

**What Run 5 may now say, in full:**

> The frozen gate returned REJECTED under its registered criterion. That
> criterion has no uncertainty control, and the difference it rejected on
> cannot be distinguished from sampling noise on this corpus. The estimator
> is not shown to be better than its baseline; it is also not shown to be
> worse.

Both halves are required. Quoting the first alone overstates the finding in
exactly the direction D36 is about; quoting the second alone would be reading
a failed rejection as support, which is worse.

**The verdict is not retroactively changed.** The gate ran as registered and
returned what it returned; editing that after seeing this would be the tuning
D35 forbids, run backwards. `mae_tolerance` stays as it is. The next
registration decides whether a criterion without an interval belongs in a
gate at all — and the honest answer is probably not, which makes this a
finding against my own design rather than against Run 5.

**One thing the MAE comparison structurally cannot see.** The baseline emits
a point; the estimator emits a distribution with a traced shrinkage. Leading
on Q50 MAE compares them only where they overlap and silently discards the
interval — the part D8 and D32 exist for. A comparison that judged both on
what each is *for* would need pinball loss and interval width beside it, and
the baseline would have to forfeit those columns rather than win them. That
is a gap in how this benchmark reports, not a result.

## D40 — Fix the criterion before running another experiment

D39 showed the gate's MAE criterion is a bare comparison of point estimates.
Running Run 6 against it would produce a second result with the same defect,
so the criterion is registered first, in `docs/EVAL_CONTRACT_V2.md`, and Run
6 is registered against that afterwards — separate documents, separate
commits, in that order, so the corpus cannot be shaped to the criterion.

    primary       ΔMAE on Q50, paired cluster bootstrap, 95% CI
                  CI below 0 → beats · CI above tolerance → loses ·
                  spans either → UNJUDGEABLE
    diagnostics   mean pinball loss; interval coverage AND width, as a pair
                  reported every run, gating nothing

**The timing is the problem and it has to be argued, not asserted.** A rule
rewritten after a loss is the exact move D35 forbids. The defence is
structural: **v2 is strictly harder than v1 in both directions.** v1 accepted
anything within 1.10× of the baseline; v2 accepts only when the interval lies
entirely below zero. Applied to Run 5's own numbers, v2 returns UNJUDGEABLE
— it does not hand the previous run a win. A rule written to rescue an
estimator would loosen acceptance; this one tightens it. And what would
falsify that claim is written into the contract: if a later version loosens
acceptance, it is the thing it says it is not.

Run 5's verdict is untouched. It stands as REJECTED under v1, with D39's
interval attached. v2 governs Run 6 onward and is not retroactive.

**Why the diagnostics do not gate.** Three gates give a 2-of-3 vote, and a
candidate losing the primary criterion can be declared a winner by two
diagnostics — choosing the metric after seeing the result, one step removed.
Coverage and width are also reported only as a pair, because coverage alone
is gameable by widening the interval until it contains everything.

**Recorded against my own design, from the same review.** The strongest
objection raised was not about statistics: *this project may have spent more
effort proving the estimator is scientific than establishing that the
estimator is a necessary part of the product.* CARO's thesis is a decision
engine — normalisation, intent-aware ranking, priced risk, an evidence
ledger, and a refusal state. The market estimate is one input to that. If
parent-median turns out to be the best available estimate, the product is not
diminished; only the ML pricing model is. Those two have been allowed to
blur, and the README's framing is where that shows.

## D41 — The evidence is concentrated on the component the thesis needs least

D40 recorded the review's strongest objection: this project may have spent
more effort proving the estimator is scientific than establishing that the
estimator is a necessary part of the product. That was accepted as a framing
problem. It is worse than a framing problem, and pointing the decision path
at Run 5's own listings for the first time is what showed it.

    measured on real Bama data     the estimator. Twice. Against a real
                                   baseline, under a pre-registered gate,
                                   with a bootstrap interval attached.
    measured on synthetic data     the ranking. `winrate_vs_price_sort`
                                   is called in exactly one place —
                                   tests/test_ranking.py — over a corpus
                                   this repository generates, against a
                                   utility function this repository writes.
    measured on nothing            retrieval, relaxation, refusal, the
                                   evidence ledger, the adversarial pass.

Five live runs, two registrations, forty entries above this one, all aimed at
the component the thesis calls one input among several. The component the
thesis says *is* the product has never been evaluated on data the project did
not create. `scripts/rank_run5.py` is the audit, and it deliberately prints no
win-rate: on real data there is no ground truth for what a buyer gains, and
the honest substitute is a blind panel over shuffled unlabelled shortlists,
which is a person, not a script.

**Three things the audit found, none of which a passing suite could show.**

*Four of six ranking terms are constant on real data.* `risk`,
`ownership_risk` and `liquidity` are absent on all 228 eligible rows;
`first_seen_ordinal` is 0 for every one of them. Only value and mileage vary.
A constant term contributes an identical amount to every score, so it cannot
change an ordering — the weight slider over it moves nothing. Four of the six
sliders the product offers are inert on Bama data. This is a W4 ingest gap:
the fields exist in the Row and nothing populates them.

*The gate refuses even the baseline class here.* `comparable-quantiles` fails
on this corpus at a coverage error of 0.206 against a 0.07 limit. Run 5
rejected the conditional estimator; this says the thing D12 promised to ship
in its place does not clear the gate either. So on real Bama listings today,
every shortlist refuses. The refusal path is not a demonstrated feature of
the product — it is currently the *only* path that runs.

> **Corrected by D43.** The sentence above reads as a fact about the
> baseline's quality and it is not one. Under a held-out-TRIM split the
> comparables estimator has no comparables and becomes bit-identical to the
> global estimator, and the held-out trims are a different price population
> from the training trims. The refusal stands; the 0.206 simply carries no
> information about how good this baseline is. This was my own overclaim, of
> exactly the kind D36 catalogues, written into the entry that opened D36 one
> level up — and D43's own first draft then overclaimed in the other
> direction. Both corrections are left visible there.

*Retrieval matched a bare slug against a full `make|model|trim` key*, so
every model-constrained query returned zero while matching cars sat inside
the stated budget, and the relaxation ladder then explained a trade-off it
had not made. Fixed in its own commit. The reason it survived 611 assertions
is the general lesson: every ranking test builds its corpus with `model_key`
already set to the parser's own slug. W3 was tested against its own
vocabulary and had never been run against W4's.

**Why this is the same error as D36, one level up.** D36 is about a mechanism
the design supports being narrated as an observed market fact. This is a
mechanism the *tests* support being read as a working product. The nine D36
instances were sentences; this one is an architecture. And it was invisible
for the same reason: nothing failed. Six hundred and eleven assertions passed
over corpora shaped to the code that consumes them.

**What this changes about the demo, and it is the reason the entry exists.**
The review's recommendation — centre the video on the decision, with ranking,
refusal and the evidence ledger as its parts, and the estimator as one input
— is right about the product and cannot be filmed against real data today.
On Bama listings the shortlist refuses, four sliders are inert, and the only
number that says ranking beats price-sort was measured on a corpus this
project generated. A video centred there would move the submission's weight
from a claim that was measured and lost onto a claim that has not been
measured at all. So the demo does both and says which is which, on camera:
what runs on real listings, what runs on synthetic, and what has no evidence
yet. `docs/DEMO_SCRIPT.md` is rewritten to that shape.

**And it reorders the next experiment.** Run 6 is another estimator
comparison, and after D39 and EVAL_CONTRACT_V2 it is a well-designed one. It
is also not the most valuable thing this project could do next, because it
adds a sixth measurement to the component that already has five. The cheaper
and more informative work is upstream of it: populate the risk, ownership and
liquidity fields from data Bama actually publishes, so the ranking has more
than two live terms; and find out why the baseline class fails the gate on
real listings, because a product that cannot serve an estimate at all is a
larger problem than which estimator it would have served. EVAL_CONTRACT_V2
stays frozen and Run 6 stays registered against it whenever it happens. It
just stops being next.

### D41 addendum — the four dead terms are a collection gap, not a source limit

D41 said the constant ranking terms are "a W4 ingest gap: the fields exist in
the Row and nothing populates them". That was true but not specific enough to
act on, because it did not say *why* nothing populates them. There were two
possibilities and they have opposite consequences: Bama does not publish this,
or Bama publishes it and Run 5 did not record it.

The snapshot said where to look. `data/snapshots/run5/listings.json` carries a
`COND` field — body condition — in its eleven-field record, and it is the
empty string on **all 403 records**. `DESC` is empty too, but deliberately:
descriptions carry masked phone numbers and are excluded on purpose. `COND`
was not excluded on purpose. It is a field the format reserves and the run
never filled. And `parse_detail_page` reads it correctly: it looks for a
labelled «وضعیت بدنه» in the page text, because JSON-LD does not carry it.

Two live Bama detail pages, opened through the browser and read (not crawled),
settle it. Both publish a condition block above the description:

    وضعیت بدنه     بدون رنگ
    رنگ بدنه       (a colour)
    رنگ داخل       (a colour)
    گیربکس         اتوماتیک

and the city sits in the header beside the date. One was a zero-kilometre car
where «بدون رنگ» is trivially true; the other a 2018 import at 26,000km, where
it is not. The block is on the page either way.

**So the answer is the second possibility.** Bama publishes body condition,
both colours, gearbox and city on the detail page CARO already fetches. Run
5's detail extractor recorded the price/kilometre/year spine and dropped the
condition block beside it.

> **Sharpened by D45.** This understates it. Run 3's snapshot fills COND on
> 214 of 221 records with five real condition classes. The capability existed
> and was lost in Run 5's mid-run extractor rewrite, beside a deliberate and
> correct decision to drop descriptions. It is a regression, not a gap. That is why `risk` and `ownership_risk` are absent
on all 228 eligible rows — not because the market does not publish the
evidence, but because the run did not keep it.

Three things follow.

*The cost of fixing it is zero additional requests.* The condition block is on
pages the crawl already downloads. This is a change to what gets written into
the snapshot, not to what gets fetched — which matters, because D35 governs
acquisition changes and this is not one.

*It changes what the ranking demo is waiting on.* Four inert sliders were the
strongest argument that the decision layer is unfinished. They are not
unfinished; they are unfed, from a source that publishes the feed.

*And it is the same error as the retrieval bug, in the other direction.* There
the code compared two vocabularies that had never met. Here the snapshot
format and the crawl that fills it had never been checked against each other:
a reserved field, silently empty, on every record, through a full
pre-registered run. Nothing failed. `tests/test_ingest.py` has 272 assertions
and none of them assert that a field the format reserves is ever non-empty on
real data.

What is *not* claimed: that populating these fields would make the estimator
clear the gate, or make the ranking better. Those are separate questions and
neither is answered here. The claim is narrower and checkable — the evidence
Bama publishes is richer than what Run 5 kept, and the gap is ours.

## D42 — When outcome validity is unavailable, measure construct validity

D41 ended on an open question and it was the real one: with no blind human
panel, is there any evidence for ranking quality on real listings that does
not rest on disappearance-as-sale, and does not collapse back into a utility
function this project wrote for itself?

The answer is no, and it is worth stating flatly because the temptation runs
the other way. Three substitutes suggest themselves and all three fail:

    "the listing vanished, so the car sold"     D2. Disappearance is not a
                                                sale, and building the
                                                ranking's ground truth on the
                                                inference this project exists
                                                to refuse is worse than
                                                having no ground truth.
    "I will write a rubric and label 50 cars"   That is the synthetic utility
                                                function with a clipboard.
                                                Same author, same assumptions,
                                                fewer samples.
    "an LLM judges which shortlist is better"   The most seductive one, and
                                                the emptiest. It does not
                                                obtain ground truth from
                                                anywhere; it moves the utility
                                                function from code into a
                                                prompt, where it is harder to
                                                inspect.

So **"ranking quality on real listings is not validated" is the ceiling of
what this submission may claim**, and the README's status table says exactly
that rather than filling the cell with a weak criterion.

**But a different claim is available, and it needs no ground truth at all.**
Instead of *was this car really the better choice*, ask: *are the inputs the
ranking says it uses actually present, observable and traceable in real
listings?* That is construct validity rather than outcome validity, and it is
measurable today. `decision_ledger()` records, per candidate, which of the
scoring function's inputs existed — and for each one that did not, the reason.

On Run 5's 58 candidates the answer is 38% mean completeness: the hard filter,
mileage and year are present; the price delta, the risk score, the running-cost
and reliability proxies and the observation history are all absent, each with
a named cause. The ledger runs without a gated estimator on purpose — a ledger
that refused when the estimator refuses would hide the most informative line
it has.

**Three reasons this is worth having rather than a consolation prize.**

*It is the first thing the decision layer can show on real Bama listings
beyond a refusal.* D41 left the real-data section of the demo with nothing but
a `NotBenchmarked`. Now it has a table of what the decision actually had.

*It makes a specific class of overclaim structurally hard.* An absent input is
recorded as absent with its reason, never as a zero. A term scored at zero and
a term with no input are indistinguishable in a weighted sum and completely
different facts about the product — this is D4's UNKNOWN-vs-ABSENT rule turned
on the ranker's own inputs instead of a listing's fields.

*And the number is unflattering, which is the point.* 38% is a low figure to
publish. It is also the honest description of a ranking layer that has been
tested only against corpora built to feed it.

**What it is not, and this belongs in the record because the failure mode is
obvious.** A ledger showing every input present would say the ranker is well
fed. It would not say the ordering is right. Construct validity is a
precondition for outcome validity, never a substitute, and quoting a
completeness figure as though it were a quality figure would be D36's error
with a new number attached.


## D43 — The gate was not measuring the estimator

D41 said the baseline class fails the acceptance gate on Run 5's corpus at a
coverage error of 0.206, and read that as a fact about the baseline. Checking
it produced the opposite conclusion, and two facts settle it.

**The two estimators are the same estimator under this split.**
`ComparableQuantiles` and `GlobalQuantiles` produce *bit-identical*
predictions on the held-out set — max absolute difference 0.0. The reason is
structural: the split holds out whole trims, so of 75 training trims and 25
test trims the overlap is zero, and only 6 of 21 test parents appear in
training at all. A comparables ladder with no comparables falls through to
`global` on every row. The gate could not have distinguished them, and did
not: both reported the same 0.206.

**And the held-out trims are a different price population.**

    train   n=177   median 2,300,000,000   p15   876,000,000   spread 143x
    test    n= 51   median 3,200,000,000   p15 1,440,000,000   spread  53x

    share of test rows below the train p15       0.000
    share of test rows below the train median    0.294

Those two shares *are* the coverage failure, arithmetically:

    tau 0.15   empirical 0.000   error −0.150
    tau 0.50   empirical 0.294   error −0.206      ← the number the gate quoted
    tau 0.85   empirical 0.824   error −0.026

The gate reported the calibration of a distribution fitted on one price
population against a disjoint one. That is not a property of any estimator.

**What this changes.** The refusal is correct and stands — CARO still may not
serve a market estimate on this corpus. What was wrong is the *reason* D41
gave: the 0.206 is not a fact about the baseline's quality, it is the
arithmetic of a price-shifted test set applied to an estimator that has
collapsed to the global distribution.

> **The first draft of this paragraph overclaimed and it is worth leaving the
> correction visible.** It said *no better model clears this gate, because the
> model is not what is being measured.* The first half does not follow from
> the second. What is established is that `ComparableQuantiles` and
> `GlobalQuantiles` are the same estimator here; an estimator using other
> available signal — parent, model family, year, mileage, price band, the
> observed market structure — could in principle predict the held-out
> distribution better and cover it better. That this baseline degenerates is
> not evidence that every estimator must. Writing it that way turned a
> diagnostic finding into an alibi, which is the exact move D43 exists to
> refuse, made inside D43.

The narrower true statement, and it is worth stating as a property of the
*gate* rather than of any model:

> This split is so far out of support that it collapses the comparable and
> global baselines into a single predictor, and as a consequence the gate had
> no power to distinguish models in Run 5 at all.

That is stronger and more useful than "the number says nothing about this
baseline", because it names what was lost: discriminating power. A gate that
cannot separate two estimators it was built to compare is not returning a
verdict about either of them. What would restore that power is a corpus where
held-out trims share a price world with the training ones, or an evaluation
that conditions on price level. Both are registration questions.

**What this does not change.** It does not rescue the estimator. Run 5's
REJECT stands as registered with D39's interval attached, and nothing here is
evidence that partial pooling would have passed under a kinder split.
Choosing a kinder split now, having seen this, is precisely the D35 move —
so `held_out_trim_split`, the fraction and the seed are untouched, and this is
recorded rather than acted on. The next registration decides.

**Third appearance of the same blind spot.** D38 recorded that Run 5's
registration constrained trim counts, floors and slice sizes and said nothing
about price heterogeneity. That blindness decided the benchmark (D38), then
explained the thin-slice tension (D37), and now turns out to have decided
whether a market estimate can be served at all. A registration is blind to
what it does not name, and the same unnamed variable has now produced three
different results.

**And a note on how this was found, because it is the point of D36.** D41 is
the entry that named the project's tendency to let a mechanism be read as a
fact — and it contained one. "The baseline does not clear the gate" was a
plausible reading of a true number, written without checking what the number
measured. The catalogue in D36 does not catch new instances and says so; this
is one, in the entry that extended D36, written by the same author in the same
session.

## D44 — Stop here: the evidence ceiling, not the finish line

Three things could have come next: a fresh collection that records the
condition block (raising the ledger's 38%), more diagnosis of the gate, or
neither — record the video and submit. The decision is the third, and the
reason is worth stating precisely because "we ran out of time" and "we reached
the limit of what this evidence can support" are different claims and only the
second one is true.

**More diagnosis has nothing left to find.** The question was *why is coverage
0.206*, and D43 answers it: not estimator-specific; comparable collapses to
global because support vanishes under the frozen split; and the coverage
failure tracks the train/test price-distribution shift. Another pass produces
the same three lines.

**A fresh collection is the dangerous one, and it is dangerous precisely
because it is attractive.** It costs no extra requests, it would light up two
dead ranking terms, and it would make the demo's real-data section look
better. But it starts a chain with no natural stopping point:

    collect → parser fix → corpus changes → benchmark changes →
    ranking changes → new failure → new interpretation

Every link is reasonable on its own. Together, in the last hours before a
submission, they replace a coherent record with a half-rebuilt one, and the
final claim rests on a corpus assembled after seeing which corpus produced the
unwelcome result. That is D35's loop with better manners.

**And the gap is worth more open than closed, for this submission.** COND is
a named, reproducible, zero-cost defect with a guard that fails the moment
someone fixes it. A slightly higher completeness figure would say less about
how this project works than the gap plus the guard does.

**What the ceiling actually looks like, and it is the closing slide.**

    real data     ingestion                     VALIDATED
                  extraction contracts          VALIDATED / AUDITABLE
                  snapshot completeness         AUDITABLE
                  ranking inputs                AUDITABLE
                  appraisal                     NOT VALIDATED
                  ranking quality               NOT VALIDATED
                  ground truth for ranking      NO GROUND TRUTH

    synthetic     pipeline behaviour            observable
                  ranking mechanics             runnable
                  decision ledger               observable
                  explanation / evidence path   demonstrable

**The line that makes this a product decision rather than an apology.** On
real data CARO does not quietly fail in the video. It reaches the appraisal
boundary and says *I do not have enough evidence to make this claim* — and a
system that can say that is worth more than a shortlist that cannot. Every
other row above is what earns that sentence the right to be believed.

Remaining work is the recording. The technical record stops here on purpose.

**One amendment, and the reasoning that changed it.** The review revised its
own advice after reading D43, and the revision is better than the position it
replaced — including better than mine. It separates the collection I rejected
into two different things that I had merged:

    an estimator rescue          collect until the gate passes.   Forbidden.
    an ingestion observation     collect to find out whether the
                                 condition block records, and what
                                 the natural overlap is.          Registerable.

The second is not the D35 loop, and the difference is not sincerity but
permission: an ingestion observation **may not feed a benchmark**. Its success
criterion is `COND: empty → populated`, which is an ingestion fact that stands
or falls independently of every appraisal question.

So `docs/SNAPSHOT2_PROTOCOL.md` is written and frozen, and **not executed**.
It carries the stop conditions, the positive conditions a future benchmark
design would have to meet, the rule that the two snapshots are not merged
before their five geometry numbers are published, and a hard stop that does
not depend on the result: if the collection does not fit the time available,
the benchmark is not touched again and the video gets recorded.

Registering it without running it is the correct output here for a reason
worth naming: **the decision about whether there is time belongs to the
project owner, not to me or to a reviewer.** What I can do is make sure that
if it is ever run, it is run against rules written before the data existed.
D44's stop stands until that decision is made.

## D45 — The condition block is not a missing capability, it is a lost one

The D41 addendum established that Bama publishes «وضعیت بدنه» and Run 5 did
not record it, and treated that as a gap to be closed by a future collection.
Checking the earlier snapshot before spending a single request on that
collection produced a sharper and less comfortable fact.

    snapshot          COND non-empty       through the parser
    run3 (221 rows)   214 / 221            intact 108 · minor_paint 45 ·
                                           multi_paint 37 · replaced_part 12 ·
                                           accident 4 · unknown 15
    run5 (403 rows)     0 / 403            —

Same eleven-field format. Same field index. Same `parse_detail_page`, which
reads the label correctly and always did. **Run 3 collected body condition and
Run 5 did not.** This is a regression in the collection, not a limitation of
the source and not an unexplored corner.

**Where it was lost.** Run 5's detail extractor was rewritten mid-run to fix a
real bug: `kmLine` was picking up dealer ad copy on listings with no odometer,
which is the one place a phone number could have ridden along. The fix
validated the mileage line against a pattern and dropped descriptions
entirely. Dropping `DESC` was deliberate and correct. Dropping `COND` was not
deliberate at all — it went out beside it, in the same edit, for no stated
reason, and nothing in the repository noticed for an entire pre-registered
run.

**Three consequences, and the middle one is the useful one.**

*The D41 addendum understates it and is amended.* "Bama publishes it and we
did not record it" is true. "We recorded it, then a bug fix removed the
capability and 272 ingest assertions did not see it go" is the same fact with
the part that matters left in.

*The risk term can be fed today, from data already on disk.* Run 3's corpus
carries condition on 206 of 221 parsed listings across five real classes. The
first objective of `SNAPSHOT2_PROTOCOL.md` — demonstrate that a dead ranking
term can be brought to life from what Bama publishes — is therefore
demonstrable **offline, at zero request cost, before the collection runs**.
That is the right order: prove the capability on data we have, then collect.
A protocol whose first objective is already met by existing data is a cheaper
and better-specified protocol.

*And the guard added under the D41 addendum is the test that would have caught
it.* That is not a happy coincidence; it is the only reason to write such a
guard. It is also worth being precise about what it would and would not have
done: it fires on a field that is empty across a whole snapshot, so it would
have caught this the moment Run 5's snapshot was written. It would not have
caught a partial loss — condition recorded on half the rows — and nothing in
the repository would.

**The pattern this belongs to.** D36 is about a claim outrunning its evidence.
D41 is about tests supporting a mechanism being read as a working product.
This one is smaller and more ordinary and probably more common than either: a
correct fix for a real bug quietly removed an unrelated capability, in a
codebase with 629 assertions, during a run whose registration nobody violated.
Nothing failed. The only thing that would have surfaced it is a test that
asserts a field the format reserves is ever populated — which is exactly the
class of test that feels redundant to write.

## D46 — The corpus was never in the repository, and those numbers are not reproducible

The README tells a reader to run `scripts/benchmark_run3.py` and calls it "the
benchmark above, from the stored corpus". `DEMO_SCRIPT.md` opens by saying
every number in the script is "in the repository and reproducible with no
network" and names five scripts. On a clean clone, all six fail:

    scripts/benchmark_run3.py        FileNotFoundError  data/snapshots/run3/listings.json
    scripts/benchmark_run5.py        FileNotFoundError  data/snapshots/run5/listings.json
    scripts/run5_significance.py     FileNotFoundError
    scripts/rank_run3.py             FileNotFoundError
    scripts/rank_run5.py             FileNotFoundError
    demo/export_ranking.py           FileNotFoundError

`.gitignore` line 8 is `data/snapshots/`. The raw corpora were never committed,
so no clone has ever had them, and the sentence describing them as stored was
never true for anyone but the machine that collected them.

**The search, and what it settles.** Every place that could hold them was
checked before this entry was written:

    git history, all refs        92 commits · 262 blobs · 0 paths under data/
    working tree                 one file: data/snapshots/2026-09-07/
                                 bama-2026-09-07.json — 231 bytes,
                                 integrity "suspect", counts.total 0
    git stash                    no refs/stash
    every bundle on the machine  ancestors of that same history, which holds
                                 no blob under data/ — so none can carry it
    both repo tarballs           0 entries under data/
    the run-output directory     summaries and reports only
    Downloads / Desktop /        64 CARO artifacts, all bundles, archives,
    Documents                    docs and summaries; no listings.json

**The cause is not established, and does not need to be.** Several accounts
fit the evidence; none is confirmed, and the engineering decision is the same
under all of them. This entry records the state, not a story about how it
arose.

**What survives, and what it is worth.** The verbatim output of every run is
committed and stays committed: `RUN3_2026-09-07.txt`, `RUN5_2026-09-07.txt`,
`BENCHMARK_2026-09-07.txt`, `BENCHMARK_RUN5_2026-09-07.txt`,
`RUN5_SIGNIFICANCE_2026-09-07.txt`, `RANK_RUN3_2026-09-08.txt`,
`RANK_RUN5_2026-09-08.txt`, `GATE_DIAGNOSIS_2026-09-08.txt`. These are
**evidence that the runs executed and what they printed**. They do not, by
themselves, establish that the committed code, inputs, and environment would
produce those outputs again. A transcript fixes what one execution printed; it
cannot close the loop from *committed code + exact input corpus + exact
configuration* back to that output, and without the corpus nothing else in the
repository closes it either. `demo/ranking_data.json` is committed and inlined
into `demo/index.html`, so the decision panel still renders without the missing
corpus.

**What may no longer be claimed.** Three phrasings are now retired, and the
files carrying them are wrong until they are changed:

- "from the stored corpus" — `README.md:138`
- "629 assertions, no API key, no network" is fine; "reproducible with no
  network" applied to the *run* scripts is not — `DEMO_SCRIPT.md:7-10`
- any frame implying a clean clone can re-derive Run 3 or Run 5, including
  filming `scripts/rank_run5.py` running live — `DEMO_SCRIPT.md:124`

The replacement is a status, not a deletion. The numbers stay; what changes is
the grade attached to them, and the grade has five rows rather than one,
because "not reproducible" collapses distinctions this project needs:

    execution evidence          ✓   the run happened, on a dated corpus
    result transcript           ✓   committed, verbatim, in docs/
    repository replay           ✗   the input is not in the repository
    independent reproduction    ✗   no third party can re-derive the numbers
    full provenance             ✗   code + input + configuration → output
                                    cannot be closed from what is committed

**Re-collection is not recovery, and calling it that would be D35.** The
collection path still works and `RUN5_SPEC.md` is frozen, so a new run under
the same specification is possible. It would be a **new run with new numbers**.
Run 5's corpus was a particular 403 listings observed on a particular day;
nothing collected later reconstitutes it. Publishing a fresh collection as
though it re-derived Run 5's figures would be relabelling a second experiment
as the first — the exact move D35 exists to refuse, and it would be worse here
than in the case D35 was written for, because the original could no longer be
consulted to catch it.

Rebuilding a corpus from the reported summaries is barred under a separate and
stricter rule: **a corpus reconstructed from reported aggregates or outputs
cannot be treated as the original experimental input, even if it reproduces the
same headline numbers.** Matching figures would establish that the
reconstruction was fitted well, not that it is the corpus the experiment ran
on. Corpus identity is not inferable from agreement of results.

**What follows.** The requirement is on the artifact, not on the storage
mechanism: *any run whose numbers are published must have an immutable,
repository-addressable input artifact sufficient for independent replay.* For
this project, at this size, that artifact should be committed under
`data/snapshots/` unless a stronger versioned artifact mechanism is introduced
— a content-addressed store or artifact registry would satisfy the requirement
equally, and would be the better answer once a corpus outgrows a git object.
The ignore rule is therefore the current remedy rather than an architectural
invariant, and changing it is worth more than this entry: a decision record can
say the corpus should have been retained, and only the rule can stop the next
one from going the same way.

**The pattern this belongs to.** D36 is a claim outrunning its evidence. D41 is
tests for a mechanism read as a working product. D45 is a correct fix quietly
removing an unrelated capability. This one is the same family and the most
consequential member of it, because the broken claim concerns the project's
central reproducibility promise: everything here is built to stop a number from
being asserted beyond what supports it, and the README invited a reviewer to
verify the headline numbers with a command that has never worked for them.

Nothing in the existing suites failed, because no existing test exercised the
repository's own replay commands against a clean clone. The suites pass because
they build their own corpora, which is exactly why they are silent about a
corpus that is missing. The missing check was not a property of the model; it
was a repository-integrity check: run the commands the documentation tells a
reviewer to run, from a clean clone, with network disabled.

## D47 — Two stores, and the projection between them runs one way

The platform needs a database. Introducing one puts the corpus at risk, because
a table is the obvious place to put listings and the corpus is made of
listings. This entry fixes which store owns what, before the first migration
makes the answer implicit.

**Product state lives in PostgreSQL.** Users, saved searches, saved
comparisons, contact messages, the event log — mutable rows with a lifecycle,
which is what a relational store is for.

**Evidence state lives in the artifact.** `data/corpora/<run>.json` remains the
source of truth for anything a published number depends on. Not the corpus in
a table, not appraisal results in a table, not provenance in a table.

The reason is mechanical rather than aesthetic. The content guard runs over the
**serialized bytes** of the artifact, deliberately, because a guard that only
inspects the in-memory object is defeated by renaming a field or by a
serializer that flattens a structure. `promote_corpus.py` is the only writer of
that directory and writes nothing at all when either guard fails. A Postgres
row has none of those properties: it is not immutable, it is not addressable by
content, there is no single writer, and `UPDATE` leaves no trace. Moving the
corpus into a table would replace the mechanism D46 exists to protect with one
that has no equivalent.

**Listings do go into Postgres, as a read model.** Serving a search over a
growing corpus wants an index. The rule is the direction:

    scrape → snapshot → promote → artifact → Postgres read model → API

and never

    scrape → Postgres → somehow corpus

The scraper does not write to Postgres. Nothing projects into Postgres that has
not first survived promotion. Two consequences follow and both are the point:
if Postgres is lost, the artifacts rebuild it; if the Postgres schema changes,
provenance does not.

**V1 has no cache and no job queue.** Not "not yet configured" — absent, on
purpose, because each of them can break the property above in a way that is
invisible.

A cached shortlist is the sharper of the two. It can outlive the corpus it was
computed from, and at that moment the `SYNTHETIC` / `REAL` label travelling
with it is false — the one thing the label exists to prevent. If a cache is
ever added, its key must carry `corpus_sha256`, the gate state, the ranking
version, the normalized intent and the weights. A key of the shape
`search:pride` is a provenance bug with a cache in front of it.

A queue is the softer one, and the risk is cultural. D35 makes an acquisition
run a deliberate event with its own transcript. Infrastructure that makes
firing a run cheap and unattended erodes that without changing a line of the
rule. When a queue is warranted the choice is Arq over Celery — the work is
async (Playwright is), the job set is small, and Celery's process model fights
asyncio for benefits this project does not need — and every run it starts still
writes its own transcript.

**What this freezes.** Next.js + TypeScript + Tailwind; FastAPI with Pydantic
response contracts; CARO as an imported package, not a service; Python
acquisition with bounded adapters; PostgreSQL for product state; the file
artifact for evidence; Docker Compose; no Kubernetes; anonymous-first auth.
A new feature is now required to show it does not cross these lines, and the
line most worth watching is the projection arrow.

## D48 — SorinFlow is ported from, not vendored

A working Persian scraper already exists in the owner's other project
(`Tecso-Dev/SorinFlow-DaTA-mAmager`, MIT). The obvious move is to vendor it and
write a car adapter on top, and the obvious move is wrong. This entry records
why, because the pressure to reuse working code is highest exactly when a
deadline is near, and "we already have a scraper" is the sentence that would
undo it.

**Most of that scraper is forbidden by an obligation this repository already
carries.** `caro/ingest/base.py` binds every adapter:

> Build no anti-bot evasion — if a source blocks you, stop and record it.
> Raw phone numbers must not reach CARO or disk.

`app/scraper/` contains, measured rather than assumed:

    captcha_solver.py      PuzzleCaptchaSolver — an OpenCV slider-CAPTCHA
                           solver with a confidence threshold. Not a stub.
    stealth.py             StealthConfig — browser fingerprint, locale,
                           timezone, geolocation. Anti-detection by name.
    contact_extractor.py   988 lines. "Extracts phone numbers from a Divar
                           listing page", including click-to-reveal.
    auth.py, otp_store.py, divar_session.py
                           login, SMS codes, session rotation.

Vendoring these would put a CAPTCHA solver and a phone-number extractor in a
repository whose own site tells a reviewer, in Persian, that it does neither.
The cost is not that a rule is broken quietly; it is that the reviewer who
finds it has grounds to disbelieve every other claim in the project, and most
of those claims are load-bearing.

**It is also not a library.** `app/main.py` is 969 lines, `crm.py` is 2395, and
the tree carries its own routes for SMS, GCP and proxies, plus `init.sql`,
`migrations/`, `k8s/` and a second `docker-compose.yml`. Reuse here means
carrying a second product, and that product's deployment opinions would arrive
with it.

**The portable core was already written.** `caro/ingest/persian.py` is 153
lines — `normalize`, `parse_price` with toman/rial disambiguation,
`parse_mileage_km`, `parse_year_jalali` — under 281 assertions in the ingest
suite. The advice "do not rewrite it" is sound in general and describes, here,
a decision that was made and executed some time ago.

**What is actually worth porting is five functions, and not the obvious ones.**
From `parsers.py` (1111 lines, 24 functions):

    panel_says_agency · decide_advertiser_type · is_personal_value
    agency_name_from_panel · _norm_value

These decide agency-versus-private from the **rendered panel rather than from
free text**, which is structurally the rule CARO already states for
`seller_type`: business badges only. The Persian cues differ — «مشاور املاک»
becomes «نمایشگاه» / «اتوگالری» — and the semantics convert
`agency / personal → dealer / individual`, but the shape of the decision
transfers exactly. Each arrives with attribution and its own test.

The remaining nineteen functions are real-estate domain — `detect_corner_type`,
`extract_rooms_from_text`, `extract_amenities`, `enrich_price_from_features` —
and do not transfer to vehicles.

**Python stays; Go is not introduced.** The value in this layer is Persian
heuristics, not throughput, and the binding constraint is the politeness delay,
which is deliberately slow. Go would speed up the one part of the pipeline that
is supposed to wait.

## D49 — A REAL failure must never become a SYNTHETIC success

`webapp/api/corpus.py` chooses a corpus: the published artifact if one exists,
the generated one if not. The fallback is correct and deliberate — a checkout
with no corpus should still run the product — and the way it was written made
one specific failure invisible.

`_real()` caught `(CorpusUnavailable, ValueError)` and returned `None`, which
`active()` reads as "no real corpus, use the synthetic one". Two very different
situations arrive at that same `None`:

    the artifact is ABSENT       → synthetic is the honest answer
    the artifact EXISTS and we   → synthetic is a false answer, delivered
    could not load it              under a truthful-looking label

The second is the dangerous one, and D46 is why. A corpus that fails
`validate()` raises ValueError; a mounted volume that `relative_to` cannot
express raises ValueError; a truncated file, a permission error, a schema
violation, a tampered artifact — all of them landed in the same `except` and
all of them produced a working site serving generated data. The
`SYNTHETIC` badge would be displayed, correctly, in every one of those cases.
Nothing lies. Nobody is told that a real corpus is sitting on disk being
refused, and there is no error anywhere to notice.

This is worse than a crash, and the ranking is not close. A crash is loud,
dated, and gets fixed. A silent downgrade produces a site that looks healthy,
labels itself honestly, and quietly stops being about the data it was built
for — which is the failure mode this entire project is organised against, in
the one place where the evidence grade is chosen rather than reported.

**The rule.** Absence is a fallback. Failure is not.

    corpus_path does not exist   → synthetic, silently, as designed
    anything else goes wrong     → a third state that serves nothing and
                                   says what broke

The third state is a corpus with `kind="UNUSABLE"`, no rows, no listings and
`gated=False`. Every endpoint refuses on it exactly as it refuses on an
ungated real corpus, and the fault travels in the envelope so the site can
show it rather than leaving it in a log nobody is reading. Serving nothing is
a product state this codebase already has and already renders; reaching it by
a new route costs no new mechanism.

**Why a state and not an exception.** Raising on startup would satisfy the
invariant and is defensible. It is rejected because the operator who needs to
see this is looking at the site, not at a terminal — and because a 500 tells a
visitor that the site is broken, when the truth is narrower and more useful:
the site works, one specific artifact will not load, and here is what it said.

**What this does not change.** The synthetic corpus stays a first-class,
deliberate mode with its own label and its own note on every screen. Nothing
here makes it second-rate. What is forbidden is *arriving* at it by accident.

## D50 — The API may not be more informative than the evidence behind it

Every rule in this project so far constrains what CARO computes. This one
constrains what it *serialises*, because a JSON boundary is the easiest place
in the system to acquire a fact nothing supports. A field is added because a
client is awkward without it; the value has to come from somewhere; and the
somewhere is a default.

Three instances, stated as prohibitions:

    corpus identity is null   → no field anywhere names an evidence id
    nothing is appraisable    → no estimate, no opportunity, no damage cost
    the corpus is UNUSABLE    → no rows are presented as real results

None of these is hypothetical. The second nearly shipped: `Ranker.score`
returns `[]` for an empty candidate set before it reaches the estimator, so a
real corpus produced `served: true` with an empty list — a *shape* that says a
ranking happened. One field of aggregate summary on that response and the
project would have been publishing a ranking claim over zero evidence.

**Enforced by the types first, and tested second.** The ordering matters
because a check can be deleted and a type cannot be ignored.

    a refusal returns a model with NO estimate fields, so a refusal that
    carried an estimate would not be a valid response — it is unrepresentable
    rather than merely wrong

    `identity` is one nullable object, not four nullable scalars, so
    "there is no evidence identity" is expressible exactly once and cannot be
    half-answered

    `_unusable()` constructs its corpus with no rows and no listings, so
    there is nothing for a serialiser to reach for

The contract suite then asserts the invariant across every endpoint in every
corpus state, which is what catches the fourth instance — the one not
anticipated here.

**Absence is a value.** `null` is the answer, not an omission and not a
placeholder. A missing key and a key whose value is null read identically to
a careless client, and a placeholder digest beside a corpus that has none is
worse than either: it renders exactly like a real one.

**Why this is not just D36 again.** D36 forbids restating a mechanism as an
observed market fact, in prose. This forbids a *schema* from implying evidence
the system does not hold — no sentence is written and no number is invented;
the shape alone does the claiming. The two failures need different guards
because they are found in different places: one by reading, one by serialising.

## D51 — A value is not collected until it survives to where it is read

`parse_detail_page` extracted a body condition from every Bama page it read.
`first_run.py` printed the distribution. Every ingest test asserting on that
value passed. And a corpus promoted from the snapshot that same run wrote
carried `condition: "unknown"` on every row, because `to_fetch_outcome` — one
function, four lines below the parse — did not carry the field.

Three more fields died on the same line or the one after it:

    document_issue    re-derived at promotion from a description a snapshot
                      does not contain → absent on every row, which every
                      consumer reads as "the papers are clean"
    seller_type       D26's business-badge inference, and the corpus's only
                      proxy for sample independence → an entire dealer's
                      inventory weighted as independent evidence
    body_condition    read back at promotion under the corpus's spelling
                      (`condition`) rather than the snapshot's
                      (`body_condition`), so it was dropped a second time
                      even after the first two boundaries were fixed

**The fourth one is the point.** It was introduced *by the commits fixing the
first three* and it passed every assertion those commits added, because those
assertions stopped at the FetchOutcome boundary — one step short of the place
the value was still being lost. A boundary that no test crosses is a boundary
where forgetting is free, and each fix creates the next one until a test walks
the whole distance.

**What this forbids.** A test that asserts a parser produced a value is not
evidence that the value is collected. The claim "CARO records body condition"
is only supported by an assertion that runs

    parse → FetchOutcome → JSON on disk → promoted row → the object a
    consumer reads back

through the production serialiser and a real file. `tests/test_field_survival.py`
is that assertion; the in-memory version of it would have passed throughout the
entire period the field was being lost.

**And what it requires.** Every field on the parsed record is now either
declared as crossing — under the name it crosses as, since `city` becomes
`province` and `seller_raw` becomes a salted fingerprint — or named as lost
with the reason. Silence is not an option the table offers. A field that
starts or stops crossing fails the suite until someone decides which it should
be, which is the difference between a loss that was chosen and a loss that was
merely never noticed.

Two are recorded there as undecided rather than fixed in passing: `gearbox`
and `fuel`, parsed on every page and read from a corpus by nobody; and
`price_currency_raw`, which `promote_corpus` publishes and the snapshot path
cannot fill at all. That last one is D50's shape one level down — the corpus
schema advertising a field no live run can populate — and it is written here
rather than repaired quietly, because the repair is a decision about what the
artifact promises.

**Why this is not D46.** D46 is about an input that was never committed: the
evidence existed and was not kept. This is about evidence that was never
collected in the first place while every instrument said it had been. D46 is
found by trying to replay a run. This is found only by following one value all
the way to the consumer, and the cost of not following it is a risk term that
is constant across every car — which cancels out of
`value = estimate − asking − risk` and removes the product's whole thesis
without failing anything.

## D52 — Eligible means a used car with a cash asking price, not a row we could parse

Run 9 collected 74 listings from bama and reported 65 appraisal-eligible. The
number was arithmetically correct and it meant something other than what it
was about to be used for. `eligibility` asked whether a price and a mileage
had been extracted and whether the extraction was sound. It could not ask
whether the record was a used car, or whether the number was an asking price,
because nothing in the schema carried either fact.

Two rows in that corpus, read by hand:

    detail-x20klg7t   30,000,000 toman, model year 1405, «حواله کوییک»
                      an ASSIGNMENT — a claim on a car not yet built. Not a
                      mispriced car; not a car.

    detail-jy04yagr   1,830,000,000 toman, the corpus MAXIMUM, a Pride
                      600M down, a second instalment of 150M, sixty months
                      at 18M. The total cost of a financing plan.

**Every check passed and every check was right.** `price_status` on the second
was `display_confirmed`; D20's cross-check compared the structured figure
against the displayed one and they agreed. The extraction was flawless. The
estimator would have learned that a 1404 Pride is worth 1.83B toman and that
a 1405 Quik can be had for 30M.

**Why a threshold is the wrong repair.** The obvious fix is to raise
`MIN_PLAUSIBLE_PRICE_TOMAN` or to condition it on model year. Both would be
tuning a number until two rows disappear, and both would leave the actual
defect in place: a حواله priced at 900M is still not a used car, and a
financing total that lands inside the plausible band is still not an asking
price. So the repair is classification, not filtering.

    product_class   vehicle | assignment | unknown
    price_kind      cash | negotiable | financing_total | absent

**Read, with the evidence kept.** `product_class` comes from the product
NAME and never from `description`: bama's schema.org `name` is the site's own
string — «پراید،  151» against «حواله کوییک،  دنده ای S» — while the
description is the seller's. `price_kind` comes from «جزئیات اقساط», a
section heading bama renders, and not from «قسط», which appears in ordinary
ad copy. Both carry a `_source` beside them, and `cash` states honestly that
its source is `no_contrary_evidence`: there is no positive marker for a cash
price, and a provenance string that admits that is worth more than one
implying a check happened.

**Fail closed, in the shape D1 already established.** `unknown` never decays
to `vehicle`; an unrecorded class or kind is refused exactly as an unrecorded
price provenance is. The alternative is not a smaller corpus — it is an
estimator that prices an assignment as the cheapest car of its model.

**What is NOT claimed.** Four semantic classes were observed on one source on
one day and are modelled correctly. That is the whole claim. `ASSIGNMENT_CUES`
holds one entry and the suite asserts that it does, because widening a cue
list by imagination is how a parser learns to see what it was told to find. A
class this gate cannot recognise stays `unknown`, which costs a row.

Nor is the financing check complete: it does not verify the structured price
against the plan total. On the observed page that arithmetic holds — 600 +
150 + 60x18 = 1,830 — but checking it needs the schedule table parsed, which
is more machinery than one observation justifies. A cash listing that
happened to carry a schedule block would be read as financing and excluded.
That is the fail-closed direction and it is written down rather than
discovered later.

**The consequence for the benchmark, stated before the number exists.** Run
9's 65 eligible rows are not 65 comparable cash asks until they are counted
again under this definition. Whatever that count turns out to be is the
honest one, and D35 forbids preferring the larger.

**And a pointer, so this can be done again.** `source_url` is read from the
`url` bama publishes in the same block as the price. It is provenance, never
evidence: nothing appraises it and nothing claims on it. Its only job is to
let a person open the page behind a row — which is exactly what D46 records
the absence of, and exactly what turned two anomalous numbers into two
diagnosed classes here.

## D53 — On the corpus we would benchmark, there is no seller-independence signal at all

`seller_type` exists for one reason, stated in `caro/ingest/quality.py`:
thirty listings from one dealer are not thirty observations of a market. It is
the corpus's only proxy for sample independence, and `caro.ingest.coverage`
uses it to ask whether a comparable set is one forecourt's inventory wearing
the shape of a market.

On the Pride slice it is not there.

    run 7   imports and luxury, 49 listings      seller_type   22%
    run 9   pride / quick / tiba, 74 listings                   1%
    run 10  the same pin, 75 listings                           0%

**It is the source, not the classifier.** Run 9's single badged listing was
opened beside two unbadged ones. The badge was on the first page and the
other two carry no dealership block of any kind — no tenure badge, no
showroom address, no union membership. `DEALER_MARKERS` fires correctly on
what bama publishes; bama publishes it on almost no domestic listing.

That distinction decided what happens next. A classifier bug is fixed by
adding a marker. A source limitation is recorded, because adding a marker
that fires on something else would not be reading the page — it would be
teaching the parser to see what it was told to find.

**There is no second signal either.** `seller_fingerprint` is a salted hash of
`seller_raw`, and on bama `seller_raw` is always `None`: the phone number is
partially masked and CARO does not read it, masked or not. So the Pride corpus
carries neither a badge nor a fingerprint, and two listings from one forecourt
are indistinguishable from two independent observations by anything in the
artifact.

**What follows, before any benchmark number exists.** A benchmark on this
corpus may report an error and may not report it as an error over N
independent observations. Every interval derived from it assumes independence
that nothing in the evidence establishes, and D34's floor — 58 for a
calibration verdict — is a count of rows, not of sellers. `coverage`'s
dealer-concentration check runs and returns nothing, which is the failure mode
this project is built to name rather than let pass: a check that is silent
because it is blind reads exactly like a check that passed.

**What would establish it, and is not being done now.** Nothing in the
repository can recover seller identity from bama without reading a contact
detail, which the ingest contract forbids outright. A second source that
publishes a seller handle would, and so would repeat observation over time —
`caro.tracking`'s repost linking already scores identity across snapshots
without any identifier — but both are collection work, not a parser change,
and neither is a reason to hold the current corpus hostage.

So the limitation is recorded and the corpus is used with it stated. The
alternative on offer was to say nothing and let a reader assume the sample is
independent, which is the same class of silence D36 exists to forbid.

## D54 — Fail-closed is an answer about the source, never about a boundary

`eligibility` reads `price_status` and `mileage_status`. `to_fetch_outcome`
did not carry them. `corpus_reader` set both to `None` and said so in a
comment that read as a deliberate choice:

    # Parse-time provenance the artifact cannot carry. None means "not
    # recorded", and eligibility() fails closed on it.

Measured: **no row read back from a published corpus has ever been
appraisal-eligible.** Not one, in the whole life of the artifact. The corpus
cannot feed the layer it exists to feed, and nothing said so — because Run 3
and Run 5 produced their numbers by re-parsing rebuilt pages, so the artifact
path was never the thing under test.

The comment was not wrong about the mechanism. It was wrong about what the
mechanism meant.

**The rule, as stated:**

> هر فیلدی که eligibility به آن وابسته است و parser آن را برای تصمیم‌گیری
> تولید کرده، باید در artifact حفظ شود؛ fail-closed نباید جای فیلدی را بگیرد
> که صرفاً در مرز publish گم شده است. `None`/`unknown` فقط وقتی معتبر است که
> منبع واقعاً آن مقدار را ارائه نکرده یا parser نتوانسته آن را با provenance
> معتبر استخراج کند. این قاعده شامل seller-authored prose یا هر داده‌ای که
> corpus contract صراحتاً انتشارش را ممنوع کرده، نمی‌شود.

In English: any field `eligibility` depends on, which the parser produced in
order to decide, must be preserved in the artifact. Fail-closed must not
stand in for a field that was merely lost at the publish boundary.
`None`/`unknown` is valid only when the source genuinely did not supply the
value, or the parser could not extract it with sound provenance. **This rule
does not extend to seller-authored prose, or to any data the corpus contract
explicitly forbids publishing.**

That last clause is load-bearing and is the reason the rule is written down
with it rather than without. Without it, the sentence reads as "publish
everything the parser produced" — and the parser also produces `توضیحات`.
The corpus contract's rule is about AUTHORSHIP, not about volume, and nothing
here touches it. `price_provenance` and `mileage_note` stay behind for the
other reason: no gate reads them. The test is which fields a DECISION depends
on, not which fields exist.

**No new vocabulary.** `PriceStatus` and `Validity` already existed and are
the contract. Adding an enum here would have been inventing a second way to
say what the codebase already says.

**And nothing is reconstructed.** `corpus_reader` does not derive a status
from the presence of a price. A reader that inferred `display_confirmed`
because a number was there would manufacture exactly the provenance the gate
exists to check, and the artifact would pass its own examination by writing
its own answers.

**The third instance of one shape.** D51 was a field dropped at a boundary.
D52 was two facts the schema could not express. This is a DECISION that could
not survive the boundary, which is worse than either: the fields were all
present and the verdict computed from them was still lost. The survival
suite now asserts the decision end to end, not only the fields —

    the parse admits this row  →  it is still admitted after a round trip
    remove either status on disk  →  the refusal comes back, by name

— and the negative controls run against the real serializer, because a chain
that only ever says yes proves nothing.

**What this does NOT license.** A benchmark number is now derivable from a
published artifact, which it was not before. It is not thereby more true.
D53's limitation stands unchanged: the rows carry no seller-independence
signal, so an error may be reported and may not be reported as an error over
N independent observations.

**And the historical numbers stay historical.** Run 3 and Run 5 were produced
by `scripts/replay_run3.py` and `scripts/benchmark_run5.py`, which rebuild a
page and re-parse it. Those two are no longer a source of new benchmark
numbers: a benchmark is now computed from a published artifact or it is not
computed. The existing figures are not rewritten and are not regenerated
against a new corpus — D46 already records what they are and what cannot be
re-derived from this repository, and reproducing them through a different
path would replace a documented limitation with a fresh number that answers a
different question.

## D55 — A result carries the question it answers, or it is not a result

Run 11's artifact holds 71 appraisal-eligible rows and cannot be benchmarked.
`rows_from_corpus` sets `first_seen_ordinal = 0` on every row, because a
published corpus has no per-listing first-seen date and nowhere to get one.
The temporal split then has no axis, puts the whole corpus on one side, and
reports:

    train / test    0 / 70
    leakage         0   (must be 0)

Both lines are true. The second is not evidence of anything: a training set
of nothing cannot leak into anything, so zero leakage is a consequence of the
failure rather than a check that passed.

**The obvious repair is the one that must not be made.** A cluster-aware
random split inside the one snapshot would produce a number immediately. It
would also answer a different question. The temporal protocol asks whether
the estimator holds up on listings separated IN TIME; a within-snapshot split
asks whether it generalises to other listings in the same collection. The
second is not weaker evidence of the first — it is evidence of something
else, and substituting it would leave every downstream sentence about
"generalisation" quietly false.

So a single snapshot yields `UNJUDGEABLE: missing_temporal_axis`, and time
comes from collecting across snapshots, which is what W0 is for.

**What this decision actually fixes.** A bare `MAE = 63,900,000` in a
transcript is a number with no question attached, and six months later it is
quoted as "CARO's accuracy". So every exit from the benchmark — including
the successful one, which is the case nobody thinks to check — emits:

    EVALUATION
      protocol   temporal
      status     unjudgeable
      reason     missing_temporal_axis
      run_id     run11
      sha256     …

`PROTOCOL` is a module constant and there is deliberately no flag to switch
it. A flag would let one number be produced under either meaning and quoted
under whichever suited. A second protocol arrives as a second runner with its
own name, its own contract, and its own entry here.

The reason vocabulary is closed — eight values, asserted — because a status
line that reads `reason: <free text>` cannot be searched, and the point of
these lines is that a transcript can be interrogated months later by someone
who was not in the room.

**The assertions are worth more than the number would have been.** Four of
them stand between `0/70` and an MAE, and one counts `report()` calls against
exits in the AST so that an exit without a protocol is a test failure rather
than a discovery. That is the same rule as D35 and D36 applied one level up:
when the evidence does not answer the question, the system says so — and it
has to be able to say so precisely when the numbers look clean and
presentable, which is exactly when nobody asks.

**Run 11 is therefore not benchmarked.** Its verdict is
`UNJUDGEABLE: missing_temporal_axis`, and that is the whole claim.

## D56 — CARO stays one language, and the reason is a boundary, not a benchmark

Go was considered for CARO — as a fetcher, as a background worker, or as a
separate runner beside `date_watch.py`. The answer is no, for now, and this
records why so the question is not reopened from scratch in six months.

**The decision.** No Go service and no Go component is added. The API
contract, the fault vocabulary, the response envelope and every
interpretation of collected data stay in one language.

**The architectural reason, which outranks the performance one.**
`webapp/api/main.py` already records the opposite decision explicitly: the
backend is thin because CARO is a Python package, so the API imports it
rather than talking to it over a socket — "no service boundary, no
serialisation round-trip, no second place for a number to change on the way
past". A Go service is precisely that boundary.

And a second language boundary is not free here, because the first one is
already paid for. `tests/test_api_contract.py` check 7 exists solely to stop
`webapp/web/lib/api.ts` drifting from `webapp/api/schemas.py`, and that check
was found this month to have been blind to `export type` — the fault codes
and corpus kinds were never compared at all. A Python↔Go boundary would carry
the same risk over the same vocabulary: `FetchStatus`, `classify_http`, the
PRESENT / ABSENT_IN_SOURCE / UNREADABLE distinctions, and the fault codes that
D54 and D55 exist to keep honest. Those are product semantics, not plumbing,
and splitting them across runtimes is how two services come to disagree about
what "absent" means.

**The performance argument, measured rather than assumed.** Round 4 of the
watch, from the observation file:

    20 observations   15:21:09 → 15:23:03   =  114 s
      deliberate delay (2–5 s, 15% chance ×1.5–3)  ≈  79 s
      everything else — DNS, TLS, HTTP, parse, write  ≈  35 s

So the entire time budget any language could touch is about 31% of the round,
and getting below 79 s means raising the request rate, which is a change to
the politeness policy and not a change of language. `DELAY_MIN_S = 2.0` and
`DELAY_MAX_S = 5.0` are a product commitment; Go's advantage is throughput,
and throughput is the thing this project has capped on purpose.

**The limiting assumptions, recorded because they bound the claim.**

1. The 35 s is a residual, not a decomposition. It does NOT establish that
   any of it is removable, nor what share belongs to DNS, TLS, HTTP, parsing
   or writing. It bounds the fetcher's budget and nothing more.
2. Go does not force higher concurrency — a Go fetcher can be rate-limited to
   one request at a time exactly as this one is. The argument is that its
   advantage is unrealisable here, not that it would breach the policy.
3. "The numeric core is numpy, therefore C" is too clean. Array construction,
   dtype conversion, copies and Python-level loops around numpy calls are
   real costs, and CARO has no benchmark of its own hot path. Nothing here
   says the parser, canonicalisation or corpus comparison are fast — only
   that nobody has measured them.
4. This says nothing about Go. It says what CARO needs today.

**What would reopen it.** Any one of these, demonstrated rather than
anticipated:

1. Multi-domain scale — thousands of listings across several sources, where
   even at the permitted per-domain rate the crawl no longer finishes in its
   window. The relevant parallelism is BETWEEN domains; raising concurrency
   against one source is the policy change above, not this.
2. `duration_stats` genuinely running — at least 30 observed disappearances,
   with the censored and unexplained ones counted separately, and the
   processing or storage cost actually significant. One listing has been
   watched from present to gone (`xlyildqb`, 2026-09-14); that is the first.
3. A benchmark naming one stage as the bottleneck — parser, canonicalisation,
   corpus comparison, index build, serialisation or fetch orchestration — and
   showing the stage is transferable.

Until one of those is on the table, the shortest defensible sentence is the
one above: measure first, then add a boundary. Not the other way round.

## D57 — A digest nobody can check is a number about nothing

D46 records that the Run 3 and Run 5 corpora were never committed and are not
recoverable, so every figure derived from them is unreproducible. The repair
made after it was `CorpusIdentity`: a run id, a path, a byte count and a
sha256, travelling in every API response and printed on every screen.

That repair was half-finished, and a public repository is where the missing
half becomes visible. `CorpusBadge` shows the digest under «شناسه‌ی شواهد»
and tells the reader:

    همین عدد را با sha256sum روی خود فایل می‌گیری.

On a repository that does not contain the file, they cannot. The invitation is
unanswerable, and the digest verifies nothing to anyone except the operator
who already has the bytes — which is the one person who did not need it.

**So `data/corpora/run11.json` is committed.** 76 listings, collected
2026-09-10, sha256 `c7d00593…1c8be34`. It is the run the API serves by
default (D-run-selection, `DEFAULT_RUN`), the run the badge names, and the run
every screenshot in the docs was taken against.

**The guard passing is not the permission.** `validate(artifact, serialized)`
was run before committing and reported no violation: no forbidden key, no
seller-authored text, no contact identifier. That establishes one thing — the
file satisfies `docs/DATA_CONTRACT.md`. It does not establish that publishing
real market data is the right call; that is a separate judgement about
third-party listings on a public repository, and it was made deliberately
rather than derived from a green check. Recording the difference here because
a future reader will otherwise find a passing guard beside a published file
and conclude the first authorised the second.

**What is NOT published, and why the asymmetry is the point.** `run10.json`
sits beside it on disk and stays untracked. Nothing references it — not the
default, not the badge, not a benchmark, not a document. An artifact earns
publication by being the one a claim rests on, and symmetry is not a reason to
put more real listings into a public repository than the claims require.

**The scope of "validated" in that commit message.** It means the data
contract, and nothing about quality. No estimator has cleared the acceptance
gate on this corpus (D43); its benchmark verdict is frozen at `UNJUDGEABLE —
missing_temporal_axis` (D55). Publishing the artifact makes those refusals
checkable. It does not soften them.

**What this does not settle.** Whether future corpora are committed by default
is left open, because the answer depends on what they contain and what rests
on them — the same two questions asked here. The rule this decision does fix
is narrower and holds regardless: *a digest that is published as evidence must
be computable by the person it is shown to, or it should not be shown.*

## D58 — The relative phrase is censored at six days; absence is not an event

`scripts/date_watch.py` has run six rounds against the same twenty listings —
`data/corpora/run11.json`, `--sample 20 --seed 0`, the same ids every round —
from 2026-09-12T09:57Z to 2026-09-17T13:29Z. 120 observations over 123.5 hours.

Round 6 refuted a prediction written down before it ran, and the refutation is
why this entry exists.

**The prediction.** Nine listings carried a relative phrase at round 5,
«۵ روز پیش» or «۶ روز پیش». Each was expected to advance by the whole days
elapsed — 28.6 hours, so `+1` or `+2`. Seven listings with a title date and no
phrase were expected to stay without one; three unreachable urls to stay
unreachable; and `bama:l39y2bdi`, whose «۲۱ ساعت پیش» pinned its posting moment
to 2026-09-15T11:48Z, carried a point prediction of `d=2` with the title date
unchanged.

Eleven of the twenty held. `l39y2bdi` returned «۲ روز پیش», `d=2`, title
2026-09-15 — exactly. All nine ageing predictions failed, and none failed the
way a wrong prediction about ageing fails. The phrase did not advance
incorrectly; it ceased to exist. Nine listings, `http 200`, `extraction_status
PRESENT`, title date intact, `phrase_days` null.

**What the file shows.** 106 observations where an age is defined — the url
answered 200 and a title date is present. Every count below is recomputable
from `data/derived/date_watch_summary.json`, which carries all 120
observations in four fields; the observations themselves are operational and
stay out of the repository. Two tables, because the two date
fields do not always agree and the difference between them is the subject:

    age 0–6 days     phrase present 59    absent  0
    age 7–29 days    phrase present  3    absent 44

    d 0–6            phrase present 62    absent  0
    d 7–29           phrase present  0    absent 44

The first bins by the title-derived age, `observed_date − title_date_iso`. The
second bins by the phrase's own value, falling back to the age for rows where
no phrase is shown. They differ on exactly three observations — those whose
title-derived age is 7 while the phrase reads «۶ روز پیش» — and the second is
the one that shows a clean boundary, because the boundary sits on the phrase's
own value and the first table hides it.

Those three belong to the 29-of-61 disagreement between the two fields already
on record. `title_date_iso` is an independent reading, not a derivation from
the phrase, which is what makes crossing them informative and what makes the
two tables different tables rather than one table twice.

A third population, and it is not the 106: `max(phrase_days)` over all 64
phrase-bearing observations is 6. Seven has never been observed. 62 of those
64 sit inside the 106; the other two are `bama:l39y2bdi` at rounds 2 and 3,
carrying «امروز» while the extractor of the day recorded no title date, so
they have no age and cannot enter either table.

**Correction, 2026-09-17.** The first version of this entry — committed as
`1b5c11d`, and left in the history rather than amended away — carried one
table where there are two, and both of its right-hand cells were wrong. It
said `age 0–6 … present 62`, which is table B's figure printed under table
A's label; the number there is 59. And it said `age 7–29 … absent 34`, which
is a column read off a screen instead of added; the number is 44. As
published the four cells summed to 96 against a population of 106 — the
cheapest check available, and not done.

Neither error touches anything this entry concludes. `max(phrase_days)` is
still 6, the zero at `d ≥ 7` is still zero, the horizon still stands and the
point prediction still held. That is exactly why they survived: a wrong count
beside a right conclusion reads as corroboration, and two readers agreeing
about it is not a second check but the same check twice.

**What is claimed, and what is refused.** In this corpus, with extractor v4,
`phrase_days` has never been observed at 7 or above, and was absent in all 34
observations of age 7 to 29. That is the claim.

It is NOT the claim that the source deletes the phrase on the seventh day.
Twenty listings from one corpus over six days do not establish a rule about
bama.ir, and this file has already recorded the cost of that upgrade: D36
exists because nine mechanism descriptions had been written down as observed
market facts. A general claim needs a fresh corpus and listings watched across
the boundary from the other side.

Three competing explanations are ruled out by the data rather than by argument.
The page template did not change between rounds 5 and 6 — if it had,
`l39y2bdi` would have lost its phrase too, and it did not. The extractor did
not change — v4 on both sides, recorded per observation. And it is not
coincidence — the nine crossed on one calendar day, but `jmeyopyf` and
`lpsbyco6` crossed on 2026-09-14 and `mgctnyn9` on 2026-09-16, every one of
them at `d=7`.

**The consequence that matters.** `phrase_days` is not an ageing counter. It is
right-censored at 6. A null is not "this listing has no date information" and
not "time unknown": where the age is known from another channel it is a
predictable, computable absence, which is a different state from an absence
nobody can account for.

So the disappearance of the phrase is not an event about the listing. A tracker
reading a field going null as an edit, a repost or a removal would fire on every
listing in this panel on its seventh day — twenty spurious events from a source
that did nothing. This is `UNKNOWN ≠ ABSENT` again, in its stronger form: the
absence is derivable, so it can be separated from the unknown by arithmetic
instead of being merged into it.

**A gap this exposed, recorded and not repaired here.** The five-word extraction
vocabulary — PRESENT, PRESENT_BUT_UNPARSED, MALFORMED, ABSENT_IN_SOURCE,
UNREADABLE — is carried by one field, `extraction_status`, and that field
describes the TITLE channel. A listing that lost its phrase this round records
`extraction_status: PRESENT` with `matched_substring: 1405/6/19` beside
`phrase_raw: null`. Both are right: the title was found and parsed, the phrase
was not there. But the phrase channel carries no status of its own, so its null
is the one value in the record with no vocabulary behind it — the exact
condition the vocabulary was introduced to end. No field is added and no test is
written here. What to do about it is a separate decision.

Round 6 also produced a fourth `410`, `bama:4l0xpilj`, and no url has yet
returned from `410` to `200`. That changes nothing: an unreachable url is one
unreachable observation, not a removal and not a sale (D3).

**What this does not settle.** Whether the horizon is six days anywhere else,
whether it is a property of the source or of one page variant, and whether the
phrase should be consumed at all once censoring is known to be present. This
panel cannot answer the first two — nineteen of its twenty listings are now past
the boundary or unreachable, and only `l39y2bdi` still carries a phrase, because
it re-dated. That makes its next rounds a test: at `d=2` on 2026-09-17, with no
further re-dating, it should lose the phrase on or after 2026-09-22, and not
before.

## D59 — Round 7: a pre-registered table, tested, and one prediction refuted

D58 is not rewritten by this entry and its numbers are not restated. It was
computed over the 120 observations that existed on 2026-09-17 and is anchored
on `data/derived/date_watch_summary.json`. This one is computed over 140 and
anchored on `data/derived/date_watch_round7.json`. A later round adds
observations; it does not change what was true when an earlier claim was made,
and `--export` now requires a name and refuses to overwrite an anchor so that
the separation is a mechanism rather than a habit.

**The prediction, written before the round ran.** Fourteen listings to stay
without a phrase, four unreachable urls to stay unreachable, and
`bama:l39y2bdi` — anchored by «۲۱ ساعت پیش» on 2026-09-16 to a posting moment
of 2026-09-15T11:48:55Z — to read `d=3` with its title date unchanged.

Round 7 ran at 2026-09-18T21:39Z, 32.2 hours after round 6.

**Nineteen of twenty held.** `l39y2bdi` returned «۳ روز پیش», `d=3`, title
2026-09-15. The anchor has now predicted two independent observations exactly,
1.4 and 3.4 days out. A single hour-resolution phrase pins a posting moment
well enough to be checked twice.

**One was refuted, and it is the interesting one.** `bama:pfmvi6sb` answered
200 in all six earlier rounds, carrying the same title date 2026-08-24
throughout, and answered 410 in this one. The prediction said it would stay
reachable and carry no phrase; the second half was right and the first was
wrong.

**What that does and does not license.** Five of the twenty urls are now
unreachable and none has ever returned to 200:

    msy1ffh6  XXXXXXX   from round 1
    xlyildqb  ...XXXX   from 2026-09-14
    lpsbyco6  ....XXX   from 2026-09-16
    4l0xpilj  .....XX   from 2026-09-17
    pfmvi6sb  ......X   from 2026-09-18

That is an observation about seven rounds. It is not a demonstration that the
state is absorbing — a url that has not come back in six days looks exactly
like one that cannot come back, until one does — and it is not evidence of a
sale, a deletion or a date of removal (D3). What it does establish is that the
panel loses members at a rate the watch can measure, which bears on how long
any panel of this kind stays able to answer anything.

**The horizon survives the larger file.** Over 121 observations where an age
is defined — a title date is present and the url answered 200:

    age 0–6 days     phrase present 60    absent  0
    age 7–29 days    phrase present  3    absent 58

    d 0–6            phrase present 63    absent  0
    d 7–29           phrase present  0    absent 58

`max(phrase_days)` over all 65 phrase-bearing observations is 6. Seven has
still never been observed, now across two anchors and twenty-one more
observations than D58 had. The three rows at title-age 7 that carry a phrase
are the same three: their phrase reads «۶ روز پیش», which is why the boundary
sits on the phrase's own value and not on the title-derived age.

**What this does not settle.** Whether the horizon is a property of the source
or of one page variant; whether 410 is reversible; and what happens to
`l39y2bdi` when its own phrase reaches seven, which on the same anchor falls on
2026-09-22 and is the next thing this series can be wrong about.

## D60 — Search applies the gate, and `unknown` does not pass it

FIELD_PROVENANCE.md defines a gate as "applied by the query before anyone
sees a row", and names one: `product_class`, which only `vehicle` passes
(D52). Eligibility has applied it since D52, so a non-vehicle does not become
a Row and nothing that is not a car is scored. The query did not apply it. On
a corpus no estimator has cleared — every real corpus so far — search and
reweight answer from `_evidence`, which matched listings directly on model,
budget, year and mileage and never read the class.

**What that put on screen.** On run11 the Quik chip under the search box,
«یه کوییک اتومات کم‌کارکرد تا ۱.۵ میلیارد میخوام», at the k=8 the results
page asks for, showed `bama:hubymydi` as the eighth of its eight rows: an
assignment, a 1405 Quik at 90,000,000 toman, among cars at around a billion.
At k=24 it also reached the Snapp chip and the bare query «quik». It is the
kind of row D52 was written about, with a make, a model, a trim, a year and a
price like every row beside it, and the one field that says it is not a car
was the one field the query never looked at.

**The decision.** Strict: only `vehicle` passes, and `unknown` does not
(`79f7fcf`). A record whose class was never determined is not shown as a car.
The rule is not new. D52 already says `unknown` never decays to `vehicle`, and
eligibility has refused it since; the query was the one path by which rows
were offered to a reader without passing eligibility, and it now applies the
same test first, before any constraint the buyer stated.

**What it replaced, and why not those.** Two other fixes would have cleared
the defect that was seen.

Refusing only `assignment` removes that row. On run11 its results are the
strict gate's exactly, because the corpus holds one non-vehicle class and no
`unknown`; it is wrong on the day the classifier names a second, and it shows
`unknown` as a car.

Letting `unknown` through keeps search populated on an artifact that does not
carry the field. It does so by showing as a car a row nobody classified, which
is the confusion D52 exists to end.

**What being wrong costs, stated before it happens.** The published schema
does not require `product_class`, and `caro/corpus_reader.py` records a
missing class as `unknown`. So an artifact without the field now shows nothing
in search — an empty table under an honest heading instead of a full one under
a false one. That is the intended direction, and it is a real cost: a source
whose adapter does not classify produces a corpus that search will not show
until it does. On run11 it costs nothing — all 76 records carry a class — and
bama reserves `unknown` for a page with no product name at all.

**Scope.** Search and reweight only. The detail page reached by id, and
compare over ids someone chose, still answer for a non-vehicle:
`/api/listing/bama:hubymydi` returns the assignment, and its payload carries
`product_class: assignment` so that the renderer can know (section 9 of the
contract suite). Whether those two should refuse it — `200` with the class, or
a `NOT_A_VEHICLE` fault — is not decided here. Nor is the card surface:
`ListingCard` reads `model_key` while the declaration says `card=no`, and no
guard derives that surface from its source yet.

**How it is held.** Two guards in `tests/test_api_contract.py`, because
neither alone tells the strict gate from both of the wrong ones.

Section 10 (`0fc4bb2`) runs on the corpus that is shipped. It reads the gates
out of `eligibility.FIELDS` and fails on any gate but `product_class`, so a
second gate is not covered until someone writes what passes it. It sends every
example chip and one bare query per model through search and reweight at
k=24, and reads the class of each row shown from the ARTIFACT, by id — not
from the payload, because a guard that takes its verdict from what it guards
passes the day search labels its rows `vehicle`. A reach check requires each
non-vehicle to fall inside the first 24 rows of its own model's query, or the
guard could not see it leak.

Section 2 (`c8def22`) runs on a fixture that carries no class, as the schema
allows. All nine rows load as `unknown`, search shows none of them, and — the
control — the same nine rows declared `vehicle` are shown by the same query,
so «none shown» cannot be passing on a query that matches nothing.

Two commits before the fix moved the tests off the behaviour it changes.
Section 2 reaches detail and compare by the fixture's own ids (`062ae05`), and
sections 5 and 6 run on a fixture declared to hold vehicles (`45b03b2`): D50
is a claim about the evidence a refusal carries, and on the class-less fixture
there would be none, so its six key checks would pass on an empty payload.

**Measured.** Eleven mutations in twelve runs, each count written down before
its run. A run that crashed, or ended without the suite's own verdict, would
have counted as a failure and never as zero red.

                                                  §2   §10   elsewhere
    the gate as committed                          0     0
    refuses only `assignment`, run11 as it is      1     0
      the same, with a second non-vehicle class    1     6
    the gate, against that corpus                  0     0
    a second gate in the declaration               0     1
    the assignment moved to row 30 of «quik»       0     1
    no gate                                        1     6
    `unknown` passes                               1     0
    the loader records a missing class `vehicle`   2     0
    no gate, and search stamps `vehicle`           1     6
      the same, section 10 reading the payload     1     0
    nothing passes                                 1     0   §5 1 · §6 1 · §8 5

The loader case is also one red in the corpus suite, so section 2's first
check is this suite stating its own precondition, not the loader's only
guard. After the five commits the suites hold 1592 assertions, all green, and
the web build passes.

**What the guards cannot see, said rather than passed.** On run11 as it is,
section 10 cannot tell the strict gate from one that refuses only
`assignment`; section 2's class-less fixture is what does. And section 10 is
blind to a gate that refuses everything, because no row shown is no row past
the gate; section 2's control and sections 5, 6 and 8 go red on that.

**What this does not settle.** What detail and compare do with a non-vehicle.
The card surface. That the buyer's own constraints fail open where the gate
fails closed: `keeps()` lets a missing price, year or mileage through the
budget, year and mileage it was asked for, so a row whose mileage is unknown
passes «کم‌کارکرد». And that `/api/search` caps k at 24 while
`/api/search/reweight` takes any k.

## D61 — A rule the screen cannot apply is a rule nobody is keeping

FIELD_PROVENANCE.md governs two different things about a field. Four flags
say which surface may draw it, and for one number — the asking price — the
same file states a rule with its fields named. Neither was keepable. The card
surface had never been read, so `card` was a column nothing could contradict;
and the two fields the price rule names were not on the payload, so no screen
could apply the rule it is judged by. D60 was the same defect about the gate,
one surface over.

**The flag nothing could contradict.** `model_key` was `card=no`, and the
reason was written into the table beside it: nothing had judged the card
surface. `ListingCard` drew the field anyway. It is drawn by three components,
not one — the evidence grid in `SearchResults.tsx`, which is the table an
ungated corpus shows; `ListingCard.tsx` on a gated one; and `CompareTable.tsx`,
which has both — and all three render the heading from it through
`modelLabel`.

So the table moves to the renderers (`26ea4b5`). Not the reverse, because the
alternative it had in mind cannot be drawn: `derived_title` is `card=yes` in
the same table, is not a key in run11, and is not a field of `EvidenceItem`.
A flag kept `no` while three surfaces draw the field is not a judgement, it
is a note that nobody has looked.

**What the card draws is now read out of the card** (`318810f`), the way the
detail surface has been read out of `CarDetail.tsx`. Three kinds of field are
kept apart: one this table judges, which must be `card=yes`; a ranking output,
which only `ScoredItem` has and which D50 governs rather than this table; and
anything else, which fails — and which is also what stops a variable named
`r` elsewhere in a file from passing as a row.

Two judgements were made in writing it, and both are choices rather than
findings. Compare has no flag of its own: it is a grid of rows a reader is
shown, so it is held to the card's rules. And `id` and `url` are exempt by
name, because a card uses them to ADDRESS a row — a React key, the link to
/car/[id] — and not to say anything about the car.

Which components draw rows is derived too. A list of renderers is the
hand-kept `RENDERER_CONSUMES` one level up, and the renderer it would miss is
the one added tomorrow, so every .tsx importing a type that carries listings
must be a surface one of these guards reads.

**The rule nothing could apply.** The same table says a card renders an
asking price only when both gates pass:

    price_status ∉ UNUSABLE_PRICE     AND     price_kind == cash

The table writes that first half as `price_status ∈ {display_confirmed, …}`,
and the ellipsis is why the client needed a list rather than a sentence: the
set it elides is the complement of `UNUSABLE_PRICE`, which lives in Python.

Both fields are `card=yes` in that table. Neither was on the payload, so
every grid drew `toman(asking_price_toman)` with no way to know what the
number meant. Four commits make the rule applicable: the payload carries the
two fields (`e5ac6a4`); `lib/api.ts` carries the status list, checked member
for member against `quality.UNUSABLE_PRICE` rather than trusted (`c7501a5`);
`askingPrice` in lib/format.ts applies the rule in one place (`80b7c3d`); and
the card guard requires the fields wherever a surface draws a price
(`8df3c96`).

Both fields null means the row carries no price provenance at all, and that
is an appraisal row: eligibility applied these same two gates before it could
be scored, so the number stands. Two label maps, not one, because
`negotiable` is a member of `PriceStatus` and a member of `price_kind` and
means a different thing in each — which is why the rule above names its
fields.

**What changed on screen.** `bama:dn0taqsc` and `bama:gfgcipqb`, both in the
«پراید زیر ۳۰۰ میلیون» chip, stop reading «ثبت‌نشده» and read «توافقی».
Their number was never there — `price_status: absent` — so nothing is
hidden; what the reader gains is the difference between a seller who named
no price and a field this representation does not carry, which is the
distinction the rest of this project is built on.

**What being wrong costs.** A corpus whose rows carry a believable financing
total now shows a label where it used to show a figure, and that is the
intended direction: a total cost of instalments reads like a bargain beside
real asking prices, which is what D52 caught one layer down. The status half
costs the same way — an `ambiguous` extraction hides its figure — and on
run11 it costs nothing at all: 74 of 76 rows are `cash`, and the two that are
not carry no number.

**Measured.** Twelve mutations across the two suites, each count written
before its run, a crash counted as a failure and never as zero red:

    model_key declared card=no again                 corpus 3               one per surface
    a card draws a card=no field                     corpus 1
    a card reads a field in neither interface        corpus 1
    the row variable renamed, pattern finds nothing  corpus 1
    a new component imports a row type               corpus 1               no guard reads it
    a drawn field with no row in the table           corpus 1
    lib/api.ts forgets price_kind                    corpus 6 · contract 2  predicted 3, measured 6
    the grid stops drawing a price                   none                   the check is conditional
    price_status declared card=no                    corpus 3
    askingPrice drops the kind gate                  none                   the stated limitation
    the mirrored status list drops a member          contract 1
    the server stops filling price_kind              contract 2             zero before section 9 followed it

Two of those predictions were wrong and are corrected in place rather than
quietly adjusted. Removing a field from the interface gives six red in the
corpus suite and not three, because a field the renderer reads that is in
NEITHER interface fails the membership check as well, once per surface: the
guard is stricter than the prediction was. And the server no longer filling
`price_kind` was zero red everywhere — the guard asserted the fields are on
the model, nothing asserted they are FILLED — which is the hole section 9
now closes by following both fields from the artifact to the payload
(`d15e548`), as it already followed `product_class`.

**What the guards cannot see, said rather than passed.** `askingPrice`
dropping the kind gate is zero red. That function is TypeScript, these
suites are Python and run on numpy alone, and a text check over a function
body would be a spelling test. What is asserted is that the fields reach the
surface and carry the artifact's values; the behaviour is one indirection
away.

**What this does not settle.** `mileage_status` is `card=yes` and still not
on the payload: this file states no rule for an odometer the way it does for
a price, and a field sent for no stated rule is a field nobody has judged.
The buyer's own constraints still fail open where the gate fails closed
(D60). What detail and compare do with a non-vehicle is still open, as D60
left it. And the card surface is now derived from three renderers, which is
three more than yesterday and not a guarantee about the fourth.

## D62 — Round 9: the phrase went by its seventh day, and the one 5xx came back

D59 left one prediction open and named it: `bama:l39y2bdi`, anchored by
«۲۱ ساعت پیش» to a posting moment of 2026-09-15T11:48:55Z, should lose its
relative phrase once the phrase would read seven — on that anchor,
2026-09-22T11:48:55Z. This entry is computed over 180 observations and
anchored on `data/derived/date_watch_round9.json`. D58 and D59 keep their
own files and their own numbers, and neither is restated here.

**The round.** Round 9 ran at 2026-09-23T01:35Z, 7.57 days after the anchor
and 48.5 hours after round 8. The page answered 200, the title was `PRESENT`
with its date unchanged at 2026-09-15, and there was no phrase. That is the
prediction, exactly, and there was no re-dating to explain it away.

Under the one anchor, every v4 reading of the listing agrees with the floor
of the time elapsed since it:

    observed at          days since anchor    phrase_days
    2026-09-16T08:48Z    0.87                 0
    2026-09-17T13:28Z    2.07                 2
    2026-09-18T21:40Z    3.41                 3
    2026-09-21T01:03Z    5.55                 5
    2026-09-23T01:35Z    7.57                 none, title still 2026-09-15

A single hour-resolution phrase, read once, has now placed four later
observations over six and a half days.

**What the round does not show.** Nothing was observed between day 5.55 and
day 7.57. The round shows the phrase gone by the seventh day; it does not show
it surviving the sixth. For this listing that half rests on round 8's `d=5`
alone, and for the claim in general on the other listings, whose maximum is
still six.

**The horizon over the larger file.** Over 148 observations where an age is
defined — a title date is present and the url answered 200:

    age 0–6 days     phrase present 61    absent  0
    age 7–29 days    phrase present  3    absent 84

    d 0–6            phrase present 64    absent  0
    d 7–29           phrase present  0    absent 84

`max(phrase_days)` over all 66 phrase-bearing observations is 6. Seven has
still never been observed, now across three anchors and a file half again the
size of D58's. The three rows at title-age 7 that carry a phrase are the same
three, and for the same reason: their phrase reads «۶ روز پیش».

**Two facts about reachability.** They come from the observation file, which
the anchor does not carry — `http_status` is not one of its four fields.

`bama:tdlq3uyn` answered 502 at round 8 and 200 at round 9, title
2026-09-06: the first url in this series to come back, and the only one that
had ever failed with a 5xx. D1 says a 5xx is UNKNOWN and not ABSENT, and this
is the first time the panel has shown why — the listing was there throughout.

`bama:6mhsjxdd` and `bama:vm9bcghv` answered 410 for the first time. Seven of
the twenty now answer 410, and none of the seven has ever come back:

    msy1ffh6  XXXXXXXXX     pfmvi6sb  ......XXX
    xlyildqb  ...XXXXXX     6mhsjxdd  ........X
    lpsbyco6  ....XXXXX     vm9bcghv  ........X
    4l0xpilj  .....XXXX

As D59 said of five, that is an observation about nine rounds. It is not a
demonstration that the state is absorbing, and it is not a sale, a deletion or
a date of removal (D3).

**This panel is spent on the phrase.** `phrase_bearing_at_latest_round` in the
anchor is empty: at round 9, not one of the twenty carries a phrase.
`l39y2bdi` was the last, and only because it re-dated. Further rounds of this
panel can observe titles and urls; they can no longer be wrong about the
horizon. A further test needs listings watched across the boundary from the
other side — a fresh sample, observed from before its sixth day — and that is
a new panel and a separate decision.

**What this does not settle.** Whether the horizon belongs to the source or to
one page variant; whether a 410 is ever reversible; whether a url that failed
with a 5xx once will fail again; and D58's own open question, whether the
phrase should be consumed at all now that it is known to be censored.

## D63 — Detail and compare answer with the class; the screen says what it is

D60 left one question open by name: what detail and compare do with a
non-vehicle. Both answered for one. `/api/listing/bama:hubymydi` returned the
assignment, 200, with `product_class: assignment` on the payload, and compare
returned it too when it was asked about alone. Nothing in the client read the
field: in `webapp/web`, `product_class` appeared once, in the interface in
lib/api.ts.

**What that put on screen.** The detail page drew the assignment as a car:
«پرونده‌ی خودرو» over its id, the car file's cells, 90,000,000 toman under
«قیمت پیشنهادی», and a refusal headed
«برآوردی برای این خودرو سرو نمی‌شود».
Beside a real Quik's page it had the same structure. Compare was worse beside
a car. run11 holds 76 listings, 71 of them appraisal Rows, and the ungated
branch answered from the listings only when NO requested id was a Row. So the
assignment asked for beside any Row — `bama:oniy1maq`, a 1388 Pride, is the
first — came back as 200 with the Row alone, and the corpus-level
ESTIMATOR_NOT_GATED as the only fault. The four other listings that are not
Rows vanished the same way: the two Prides with no price, `bama:dn0taqsc` and
`bama:gfgcipqb`, and the two Quiks with no odometer, `bama:l39y2bdi` and
`bama:wmxsljsn`.

**Two contracts, measured before either was chosen.** Each was built as the
smallest edit that made it true, against a contract-neutral draft of the
guard — for each non-vehicle and each path, either refused with a fault that
says why, or delivered with its class to a component that reads it — and the
contract and corpus suites were run on each. The draft was five red on the
code as it was.

                        A: 200 with the class,       B: a NOT_A_VEHICLE fault,
                           the screens branch           the listing withheld
    the draft guard        0 red                        0 red
    everything else        1 — the card guard:          5 — §2 1, §3d 2, §9 2
                           compare draws a field
                           declared `card=no`
    the edit               3 files, +15/−1              3 files, +24/−6

Two partial versions were measured too. B refusing only the classes it knows,
and answering `unknown`, left the draft two red — `unknown` was drawn as a
car, D60's strictness lost one surface over — besides section 9's two. A on
detail alone left it three red, because compare needs its own fix.

**The decision.** A. Detail and compare answer 200 with the listing and its
`product_class`, and the screen is obliged to say, from the class, what the
listing is. `unknown` is held to the rule for any non-vehicle: it is never
drawn as a car. That is D52's rule — a class nobody determined does not decay
to `vehicle` — applied on the screen, as D60 applied it in the query.

The reasons, as they were given. The class is a fact the source states, not
an HTTP error. `bama:hubymydi` exists, and what it says can be shown. B set
the contract suite's HTTP doctrine against itself: section 3d has two cases,
200 when the fault is the source's and 404 when the resource is absent, and a
listing that is present and is not a car is neither; and section 9's claim
that the renderer receives the class became its opposite. A's danger is
different, and it was named with the choice: a renderer that ignores the
class draws a car with every API check green. So the guard was to measure
what a reader is shown — `assignment` and `unknown` are never drawn as a car
file on any path — and not that a component reads the field. D61 had already
recorded the limit of that second kind of check, for `askingPrice`.

**What changed.** Four commits.

Compare answers for every id it was asked about (`efbc210`): on an ungated
corpus, every requested listing the corpus holds, Row or not. That ends the
silent drop for all five listings above, not only the assignment.

`product_class` becomes `card=yes` (`c95a01b`). Compare is held to the card's
rules (D61) and now draws the class, as a fact about the row. Keeping `no`
while a surface drew the field would have been the defect D61 was written
against.

The detail page decides first (`727452b`). `ListingFile` draws the car file
for a vehicle, unchanged, and for anything else a listing file:
«پرونده‌ی آگهی» over the id; a heading that names the class,
«این آگهی خودرو نیست — حواله» or «نوع این آگهی تعیین نشده است»;
the sentence every surface uses, «به‌عنوان خودرو نمایش داده نمی‌شود»;
and the listing's own facts, with its amount called «مبلغ اعلام‌شده» and not an
asking price. No decision is requested for it, because an estimate of an
assignment is what D52 exists to prevent.

Compare's evidence table labels the row (`5e9f470`), with the class and the
same sentence in its first cell. The row stays, because compare was asked
about it.

One function decides all of it, `isVehicleClass` in lib/format.ts. A null
class is an appraisal Row, which only a vehicle becomes, so it is drawn as a
car — the null rule `askingPrice` already uses.

**How it is held.** In two halves, and two suites.

Section 11 of the contract suite (`5a0d865`) is the API half: every
non-vehicle the API is asked about is delivered with the class the artifact
records, by detail, by compare alone, and by compare beside a vehicle. It
follows two: the assignment in run11, and `unknown`. run11 records a class on
every listing, so `unknown` comes from section 2's fixture, an artifact that
carries no class, as the schema allows. The loader records the missing class
as `unknown`, and what `unknown` may never become is D52's rule. That fixture
is D52's case and not D50's: D50's checks run on a fixture declared to hold
vehicles, because they test paths that must work on valid vehicle evidence.

`tests/test_screens.py` (`c9f0132`) is the half that matters. It renders the
two components the pages draw with, `ListingFile` and `EvidenceRows`, with
what the API returns, through `tests/render_view.cjs`: the web app's own
TypeScript and its own react-dom, chosen over a browser or a new test
library, so the suite needs nothing the app does not already have. Its checks
are about the markup a reader gets. A non-vehicle carries none of the car
file's own claims, and does carry the sentence and its class label. The
vehicle, drawn the same way, must carry every claim; without that control the
negative checks could pass on a page whose wording had merely changed. Every
file is drawn WITH a decision's refusal, so a non-car cannot turn into a car
file because an estimate was asked for. The sentence and the labels are read
out of lib/format.ts at run time, never copied into the test.

It needs node, so it is a suite of its own, and two runner commits make that
safe. A declared need can be a program or a directory (`e3a7305`), and a
missing one skips the suite by name — never a pass. And the README's suite
count is checked as a word (`b90fcac`), because a fifteenth suite would
otherwise have left «fourteen» standing. Without node the runner prints
«skipped  needs node» against the suite and ends «across 14 of 15 suite(s)».

The guard came last, and that order was chosen. It draws components the fix
creates, so against the code before the fix it can be red only for a
structural reason — «components/CarDetail.tsx exports no component named
ListingFile», and the same for `EvidenceRows` — which is not the failure it
exists for. What it guards is shown by mutation instead.

**Measured.** Ten runs, each count written before its run. A suite that
crashed, or ended without its own verdict, would have counted as a failure
and never as zero red:

                                                        contract   screens
    as committed                                            0         0
    ListingFile ignores the class — the old page            0         4
    isVehicleClass lets `unknown` through                   0         3
    EvidenceRows loses the label                            0         3
    the car file's own claim renamed — the control          0         1
    the not-a-car file stops saying so                      0         2
    compare drops a non-Row beside a Row again              1         1
    the server stops sending the class                      7         7
    detail withholds a non-vehicle                          6         1
    no node_modules, the suite run by hand                  0         3

The corpus suite ran in every case and was never red. Against the code before
the chain, section 11 is one red: compare beside a vehicle. In the repository
the chain landed in, with its index identical entry for entry to the tree it
was built to produce, the suites hold 1667 assertions across 15, all green,
and the web build passes.

**Four commits in the chain are not this decision.** They were found while
closing the guard, and they are fixes, each explained in its own message. A
run narrowed to some suites no longer calls /about stale (`206e629`):
`run_all.py ranking`, which the README and the demo script tell a reader to
type, had exited 1 since the page's total was first checked. /about's suite
count is checked beside its assertion count (`06ba691`). setup.sh's no-root
message stopped counting ten suites (`4714ff8`). And setup.sh is executable
again (`512d115`): a commit of 2026-09-18 had carried its mode from 100755 to
100644, and on a fresh clone the README's first command answered «Permission
denied».

**What the guards cannot see, said rather than passed.** The wiring: the
pages fetch in `useEffect`, the suite draws the exported components with the
props the API would give them, and whether a page passes those props is one
step away. And the claims: a car file is recognised by three of its own
phrases, «پرونده‌ی خودرو», «برای این خودرو» and «قیمت پیشنهادی». The control
stops them from quietly leaving the car file; it does not catch a car drawn
under new words.

**What this does not settle.** Compare's gated branch. It still answers from
Rows, and a non-vehicle never becomes one (D52), so on a gated corpus A does
not hold. Measured on run11 with only the flag set: the assignment beside a
vehicle answers 200 with the vehicle alone, and the assignment alone answers
404 COMPARE_IDS_NOT_FOUND — a listing the corpus holds, reported as not in
it. No corpus is gated (D43), so neither case is reachable, and neither is
tested.

## D64 — Deployed as one Vercel project of two services; the inbox is off

The site has a public address, https://caro-rho.vercel.app. This records how
it is deployed and why, what the deployment was measured to do on the day,
and what was not measured. The platform is Vercel, the one the author
already deploys to. Whether the site can be reached from Iran was raised
before the choice and set aside; it was not measured.

**The decision.** One Vercel project, with the site and the API as two
services on one domain (`72daa23`). `vercel.json` at the repository root
sends `/api/*` to the API and everything else to the site. One domain keeps
the client's own paths: it writes `/api/...` in development and in production
alike. The API's root is the repository root, so its function carries
`caro/`, `data/corpora/` and `tests/` — the corpus fallback imports
`tests/test_ranking.py`. The package declares numpy as its one dependency
(`bfc8688`), and the API service installs the web requirements beside it.
Measured before deploying, with `vercel build`: the function is 97 MB of a
500 MB limit.

The contact inbox is off (`57bfd30`). A function's disk does not keep what is
written, so an inbox that accepted a message there would be losing it. With
`CARO_INBOX=off` — set for production and for previews — the contact page
draws no form. It says «صندوق پیام در این استقرار خاموش است», names the
repository's GitHub Issues instead, and says before anyone writes that Issues
are public. A server asked anyway answers 503, and so does one that cannot
write: never a 500, and never a tracking number for a message that was not
kept. `CARO_RUN` and `CARO_ADMIN_TOKEN` are unset, so the site serves run11
and the admin inbox does not open.

How to deploy is in webapp/README.md (`b545185`). The deployment settled one
thing that file could not: it is made with the CLI from a clean clone.
Connecting the repository so that a push deploys was refused with a 400 and
left, so every deployment is a pull and a `deploy --prod` by hand.

**Measured on the first deployment,** 2026-09-27, built from `b545185`, in a
browser not signed in to Vercel:

    /                        the corpus badge says REAL DATA
    /search                  the example query: 76 listings considered,
                             71 appraisable, 4 rows of evidence, NOT SERVED
    /car/bama:0hg8shef       the car file, and its refusal
    /car/bama:hubymydi       the listing file, headed as an assignment
    /compare                 two cars and the assignment: three rows, the
                             assignment's saying it is not a car
    /contact                 no form and no input; one link, to Issues
    /about                   63, 1673 and 15, the repository's numbers that day

The query was «پراید زیر ۳۰۰ میلیون», one of the search page's examples; the
refusal, «برآوردی برای این خودرو سرو نمی‌شود»; the assignment's heading,
«این آگهی خودرو نیست — حواله». The search's JSON was identical, key for key,
to the same query run locally on the same tree. `/api/contact/status`
answered `open: false` and `/api/admin/status` `configured: false`; a listing
the corpus does not hold came back 404 with the envelope, and a path the API
does not have 404. `x-vercel-id` put the function in iad1; the edge that
answered was fra1.

**What the deployment found.** A car opened from the search results showed
«پاسخی نرسید» and «هیچ چیزی نمی‌دانیم» where its file should have been. The
browser's log had the listing answered 200 and the request for its decision
failed with `net::ERR_NETWORK_CHANGED` — the network of the machine running
the browser changing under it, not the platform. Reloaded, the page was
right.

Measured next, locally, against a fresh build of the same tree and the real
API, with only the named request made to fail:

    the listing        its decision                     the page
    200                200, the refusal                 the file, and the refusal
    200                dropped, two kinds of error      no file; sentence A
    200                500, then 504, not the API's     no file; sentence A
    200                this API's own 404               no file; sentence B
    200                never answered, watched 8 s      the file, still deciding
    dropped            not asked                        sentence A, rightly
    200, assignment    not asked                        the listing file

A is «پاسخی نرسید» over «هیچ چیزی نمی‌دانیم»; B is
«این آگهی در پیکره‌ی جاری نیست». Every failure of the second request, once the
first had answered, took the file with it and said something the first
answer contradicted. The screen suite could not see it: the page decided
inside `useEffect`, and drawn the way the suite draws, it was
«در حال بارگذاری…» and nothing else.

It was fixed apart from this decision, in three commits, and is not reopened
here. The page's state became one pure function, with nothing a reader sees
changed: the nine cases gave the same screen and the same text before and
after (`199ea52`). The screen suite checks that function from real answers
(`ccae472`). And a failed decision is drawn where the decision would have
been, with the file kept (`e011af9`); the twelve checks that commit adds were
all red against the page before it.

The page still asks for its decision, once. On run11 the answer is, for all
75 listings drawn as cars, exactly the refusal the listing's own envelope
already carries. Not asking was measured and not chosen: it changes how the
page is built for a gain that lasts until the first gated corpus, and with
the file kept a dropped request no longer costs it anything. No retry either:
it would hide a failure instead of drawing it.

**Measured on the second deployment,** built from `e011af9`, the same day.
`/about` said 1707. The car page's ordinary path was unchanged: the file, the
refusal, the provenance. With `/api/compare` made to fail in the browser's
own tab — the request never sent, the listing fetched from the deployed API —
the file stayed and the decision's panel said «تصمیمی به این صفحه نرسید», with
neither A nor B on the page. And, by the same accident as before, a network
change dropped the listing's own request on one attempt: the page said A,
which is now the one case A is for.

**Not measured.** Cold start. The preview deployment, which was not opened.
The contact POST on the deployment: its 503 was not asked for there — the
status endpoint that answered `open: false` reads the same switch, and
section 12 of the contract suite sends the POST. Whether the Issues link
opens for a visitor not signed in to GitHub. And reachability from Iran, as
said above.

**What this does not settle.** The inbox is off, not replaced: a store that
keeps what is written would be a decision of its own. Deployments stay manual
while the repository is not connected. And compare's gated branch stays
where D63 left it, blocked by D43.

## D65 — A listing is a match only where every constraint stated was checked

D60 and D61 recorded it and left it open. On a corpus no estimator has
cleared, search answers from the listings directly, and its filter compared a
listing's price, year and odometer with the buyer's budget, year and mileage
only when the listing carried the value. A missing value passed.

**Measured first,** on run11, with the five examples under the search box at
the k=8 the results page asks for. Of the 36 rows drawn as
«آگهی‌های منطبق», 3 were there only because a value was missing: two of the
four answering «پراید زیر ۳۰۰ میلیون» — both «توافقی», and both accidents —
and one of the eight answering the Quik example, which has no odometer.
Across every match rather than the rows drawn, each of the three budget
examples held 2 such listings and the Quik example 2. Which of them were
drawn was decided by the corpus's order, not by anything the buyer said.

**The decision.** A constraint has three answers for a listing — met,
broken, unknown — and a listing is a match only when every constraint the
buyer stated is met (`bb9ec55`, `webapp/api/constraints.py`). One that
breaks any is left out. One that breaks none and lacks a value for some is
shown apart, saying which, in a field of its own, `evidence_unchecked`. Each
list is the first k of its kind and each has a total, so a page can say how
many there are in all. The budget is checked against the figure the card
draws as an asking price — the rule of `askingPrice()` — so a financing total
is unknown to it; run11 holds no such figure.

Leaving the unknown out was the other choice, and it was measured: 56, 2, 51,
69 and 7 matches, and nothing said about the listings removed. A count of
them was the third. Shown apart, a listing can be opened from its row; a
count cannot. And with the matches first, an unknown no longer takes the
place of one: the first row answering «پراید زیر ۳۰۰ میلیون» had been a
listing with no price.

**The red lines came with it** (`0aa8e07`). The roadmap item named budget,
year and mileage. But the parser also records four red lines, the intent
panel prints them under «خط قرمز» as understood, and the filter never read
them — so the table apart would have drawn the family example's two
accidents under «تصادفی نباشه». Each is judged from the one field that
answers it, silence unknown:

    accident           body condition `accident` breaks it — the ranked
                       path's own rule
    unclear_documents  a document issue breaks it — likewise
    manual             a manual gearbox breaks it, an automatic one meets
                       it; with none recorded, a trim word that is itself
                       one of the two answers it, and nothing else in a
                       trim does — `manualr` stays the artefact format.ts
                       calls it
    repaint            only `intact` meets «بدون رنگ»; every rung above
                       it on the severity ladder breaks it

The last two are judgements, written down so that they can be disagreed
with: a replaced panel is read as not a body without paint, and a trim is
read for a gearbox only where it says the word.

**On run11, after:**

                                     before   matched   apart   left out
    «پراید»                              56        56       0          0
    «پراید زیر ۳۰۰ میلیون»                 4         2       2          0
    the Snapp example                     53        51       2          0
    the family example                    71        67       2          2
    the Quik example                       9         0       8          1

The family example's two left out are the two accidents, which had been
passing for want of a price. The Quik example matches nothing: run11 records
no gearbox, so whether any of its listings is automatic is not known, and
one is left out because its trim is the word `manual`. That is the honest
answer to «اتومات» on this corpus, and the chip that asks it is kept.

**The page** (`6df2840`) draws two tables from `SearchEvidence.tsx`, a pure
view: the matches under the heading they always had, and the listings apart
under one of their own, the cell beside each name saying what is not
recorded — beside it, because a phone shows a table's first columns and
scrolls for the rest. A table says «۸ از ۵۱» when it is not all of them, and
the header counts matches and listings apart instead of rows drawn. And
reweight bounds k as search does (`e8602d7`): unbounded, «پراید» answered
k=0 with 200 and an empty table, and k=-1 with every match but the last.

**How it is held.** Contract §13 holds the rule on listings built for it,
then runs every example on run11 and reads each row's values from the
ARTIFACT by id: no match lacks a value, every row apart names exactly what
it lacks, nothing shown breaks a constraint, and both totals equal the
counts in the artifact — not the payload's own lists, which a total that
reported only the rows sent would agree with. §14 sends k over HTTP to both
endpoints. Screens §5 draws the view with search's real answers for the five
examples and three more queries, and checks which table each row lands in
and what it says is missing; its reach checks fail if no answer holds
listings apart, more of either kind than a table holds, or nothing matching.
The corpus suite's surface guard reads `SearchEvidence.tsx`; `unchecked` is
the API's verdict on the query, not a field FIELD_PROVENANCE.md judges.

**Measured.** Eleven mutations, each count written down before its run:

                                                     predicted      red
                                                     ctr   scr    ctr   scr
    as committed                                       0     0      0     0
    a missing price counts as met — the old filter     7     0      7     0
    any unknown leaves the listing out                16     3     16     3
    the red lines not judged                          13     1     13     1
    the budget reads the raw amount                    2     0      2     0
    «بدون رنگ»: a replaced panel, an accident unknown  1     0      1     0
    the trim not read for a gearbox                    4     0      4     0
    each total counts only the rows sent               3     1      3     2
    reweight takes any k again                         3     0      3     0
    the matched table also draws the rows apart        0     4      0     4
    the cell saying what is missing drawn empty        0     6      0     6

Ten exactly. The totals mutation cut both totals and the prediction counted
the matches' alone; the second red is the table apart no longer saying it is
cut. No other suite went red in any run. Each commit is green on its own —
1757, 1766, 1825, 1830 and 1830 assertions across 15 suites — with the web
build passing; the chain was applied to a fresh clone before it was sent;
and the search page was looked at, built, against the real API, at desktop
and phone width, with no horizontal scroll.

**Not measured.** The deployed site. The deploy of `bef900e` was refused on
2026-10-05 — the CLI, now 62.2.0, answered «Error: Not authorized» — and the
deploy clone had been at `a636ea6` until it pulled this chain, so none of it
is on the site yet.

**What this does not settle.** The ranked path keeps its own red lines: it
has no rule for `manual` or `repaint`, and lets an unknown through all four;
it ranks nothing on a real corpus yet (D43). The intent panel still lists
text the parser acted on under «نفهمیدیم», and prints a raw use-case token,
on two of the five examples. «اتومات» stays unanswerable until a corpus
carries a gearbox. And how an odometer's status travels with the number is
still D61's question: a suspicious odometer is checked like a plausible one.
All four are in docs/ROADMAP.md.

## D66 — The ranked path keeps its red lines until a real estimator is gated

D65 gave the evidence path four red lines, each judged from the field that
answers it, with an unknown held apart. The ranked path has its own:
`_passes` in `caro/ranking.py` reads `has_accident` and
`has_unclear_documents`, has nothing for `manual` or `repaint`, and lets an
unknown through. Whether it should take the evidence path's rules was
measured before anything was changed, on the one corpus where ranking is
served today, SYNTHETIC: the five examples under the search box at k=8, and
`tests/test_ranking.py`'s own win-rate benchmark, with the evidence rules
swapped in for the run alone.

**What SYNTHETIC can say.** Its rows carry none of the fields the four rules
read — no body condition, no documents, no gearbox, no trim. A row is a
model, a year, a mileage, a price and five features, so every rule answers
unknown on all 552 rows of the pool, and whether the rules keep the right
cars cannot be measured there. The one red-line signal the rows do carry is
the generator's `has_accident`, set where `risk > 0.45` (26 rows), which
today's rule reads and the evidence rule does not. Comparing the two like for
like would mean giving the generator a body condition — a change to the
benchmark's fixture made so that a measurement can run — and it was not
done.

**What it showed.** The three examples without a red line rank identically,
row for row and rank for rank — one of them, «پراید زیر ۳۰۰ میلیون», ranks
nothing either way, SYNTHETIC holding no Pride that cheap. The two with one,
«تصادفی نباشه» and «اتومات»,
rank nothing: every candidate is unknown — 329 and 28 under the constraints
as stated — so the ladder relaxes the budget, and for the Quik example the
odometer as well, for a shortfall neither caused, and the page says
«قیدها شل شد» over an empty shortlist. That is the statement D65 took out of
the evidence path. The 16 rows today's rule removes as accidents would not be
removed: they would be unknown.

The benchmark, as `test_ranking` calls it, k=3 over its twelve queries:

                    queries  win-rate          CARO    price-sort        random   uplift
    today                11      100%   −46,928,024   −60,165,712  −105,918,867   +22.0%
    with the rules        8      100%   −37,720,603   −49,513,942   −88,932,532   +23.8%

**The second uplift is not better than the first.** The eight queries both
rows count give the same numbers in both; the denominator changed. Three
queries drop out — the two that say «تصادفی نباشه», and «۲۰۷ اتومات», which is
today's most negative at −136.6 million — and two means over different sets
of queries are not a comparison. Eight is also the fewest queries
`test_ranking` accepts.

Measured, and not changed: «۲۰۷ اتومات» is counted in today's benchmark while
no gearbox is checked at all.

**The decision.** The ranked path is not changed. Swapping `_passes` alone
sends an unknown into budget and odometer relaxation and an empty result,
which is wrong in meaning, not only in number. What would make it right —
rows that carry the fields, a branch that holds an unknown apart, a ladder
that does not relax for an unknown red line — is not built for a corpus that
ranks nothing real (D43).

**What reopens it,** all three:

1. an estimator clears the acceptance gate on a real corpus;
2. the rows real ranking scores carry the evidence the four rules read;
3. this measurement is run again then: met, broken and unknown, the
   shortlist, the relaxation ladder, and the comparison with price-sort.

Until then no commit makes the ranked path evidence-aware.

## D67 — A number is an odometer reading only where its grade says so

D61 left it open and D65 named it. FIELD_PROVENANCE.md marks
`mileage_status` `card=yes` and says it "travels with the number or neither
renders", and the payload did not carry it: a card drew the number alone,
and the odometer constraint compared every number alike. Under that rule
D21's own examples went both wrong ways — 1 km on a 1385 Pride met
«کم‌کارکرد», and 999,990 km on a 1384 one broke it.

**Measured first,** on run11: 73 odometers graded `plausible` and 3
`unknown`, all three without a number; none `suspicious`, none
`impossible`. No rule about the last two can change what run11 answers, so
the contract was decided on what the grades mean, and it is reported below
as that.

**The decision.** Each grade of `caro.ingest.quality.Validity` (D21, D22)
answers the odometer constraint so:

    plausible    met or broken by the number
    unknown      unknown
    suspicious   unknown
    impossible   unknown

An unknown holds the listing apart, as D65 does with any constraint it
cannot check — unless another constraint breaks it, which still leaves it
out. Neither of D21's examples is a reading, so neither decides anything
now: both are held apart. Two things were ruled out with it: deleting an
impossible number, and reading a placeholder like 999,999 as a constraint
broken.

The status travels with its number (`f838cbd`): `EvidenceItem` carries
`mileage_status` beside `mileage_km`, and the number stays on the payload
whatever the grade. The constraint reads a number only where the grade is
`plausible` (`1a5fb76`, `odometer()` in `webapp/api/constraints.py`). The
page draws a number only where it is a reading, and says the grade where it
is not (`11eb434`) — «کارکرد ثبت‌نشده», «کارکرد مشکوک», «کارکرد ناممکن» —
in search's two tables, in compare, and in both places on the car page;
beside a listing held apart, the reason names the grade. D22's three are
never said as one.

Two choices beyond the table, written down so that they can be disagreed
with. A record that carries a number and no grade at all is not trusted: it
is unknown to the constraint and drawn «وضعیت کارکرد ثبت‌نشده», because the
number and its status are consumed together or not at all; run11 holds no
such record. And an appraisal row carries no grade and is drawn as a
number: on a real corpus eligibility admits only a plausible odometer before
a row is scored, and a generated row has no grade to give. The ranked
path's own odometer filter is not changed (D66).

**On run11, before and after** — the trees of `94c7500` and `11eb434`.
Search answered the same on all fifteen queries measured — the five examples
under the search box, the three the screens suite adds, and seven chosen to
reach the odometer, six of them with a cap — at k=8 and at k=24: 30 of 30
identical in matches, listings apart, what each lacks, and both totals.
What a reader sees changed only where the odometer is unknown. The cell
said «ثبت‌نشده» and says «کارکرد ثبت‌نشده»: on the car pages of the two Quik
listings that carry no odometer, in both places; in compare, for those two
and the assignment; and in their rows in five of the fifteen search tables.
The reason beside them was «کارکرد ثبت‌نشده» before and is now.

**This is a semantic contract, not a measured numeric effect.** Of its four
rows, run11 exercises two. `suspicious` and `impossible` are held by
listings built for the purpose, not observed.

**How it is held.** Contract §9: the payload carries the grade, and every
odometer reading in run11 states one. §13: `odometer()` on each grade. §15:
eight listings in a temporary artifact, searched with «۲۰۶ کم‌کارکرد» —
100,000 km graded plausible matches and 200,000 is left out; no number,
1 km on a 1385, 999,990, −5,000, 2,000,000, and 90,000 with no grade are
each held apart, keeping their number and grade. §7 holds the grade's
`Literal` to `Validity`, and the TypeScript union to the `Literal`. Screens
§7 draws each grade in search, compare and the car file and reads the exact
cell; the car file says «کیلومتر» nowhere for a grade that is not a
reading. The corpus suite fails any surface that reads `mileage_km` without
`mileage_status`.

**Measured.** Eleven mutations, each count written down before its run:

                                                    predicted        red
                                                   ctr  scr  cor  ctr  scr  cor
    as committed                                     0    0    0    0    0    0
    the constraint ignores the grade — the old rule  9    1    0    9    1    0
    suspicious read as plausible                     4    1    0    4    1    0
    impossible read as plausible                     3    1    0    3    1    0
    a number with no grade trusted                   2    1    0    2    1    0
    the API stops sending the grade                  7   11    0    7   11    0
    the page draws the number whatever the grade     0    6    0    0    6    0
    the reason apart drops the grade                 0    5    0    0    5    0
    compare draws the number without the grade       0    6    1    0    6    1
    the TypeScript union drops `impossible`          1    0    0    1    0    0
    the car file's heading draws the bare number     0    5    0    0    5    0

All eleven exactly, and no other suite went red in any run. The run11
comparison was predicted in writing too, and its predictions held; the
count they were written over did not — they said seventeen queries, and
there were fifteen — and «کوییک», which they did not name, changed on one
row. Each commit is green on its own — 1847, 1868, 1888 and 1888 assertions
across 15 suites — and the round was applied to a fresh clone before it was
sent. It was applied from `0ae74ac` with the six commits of the D66 round
ahead of it — 1888 across 15 suites, the web build green with its nine
routes — and pushed as `0ae74ac..139a29c`.

**Not measured.** The deployed site. Deploying is deferred — D65 records
the refusal — and none of this is on it.

**What this does not settle.** How many listings the contract moves on a
real corpus, until one carries a suspicious or impossible odometer. And the
car page draws a price with `toman()` where search and compare apply
`askingPrice()`: on run11 the two disagree on the two «توافقی» cars. That is
in docs/ROADMAP.md, measured and not decided.

## D68 — Issues where the code lives; unparsed is only what was not mapped

The D66 round carried four small changes the roadmap had listed, each
decided by the owner before it was written. Its roadmap commit (`94c7500`)
named them and nothing here did; this is their record, written after they
were pushed with the odometer round as `0ae74ac..139a29c`.

**Where to write.** With the inbox off (D64), the contact page sends a
person to GitHub Issues: `ELSEWHERE` in `webapp/api/contact.py`, which the
page, its 503s and `/api/contact/status` all read. It named the old
repository, on purpose, while Issues was taken to be off at Tecso-Dev/caro:
a fork starts with it off. The owner decided on 2026-10-05 that issues are
written where the code lives, and `cec587f` points there.

Seen signed out the same day, `https://github.com/Tecso-Dev/caro/issues`
is the repository's Issues page — titled «Issues · Tecso-Dev/caro · GitHub»,
searching `is:issue state:open`, with a sign-in link for writing one. The
repository's front page, seen signed out that evening, still drew no Issues
tab, and that was not explained. It is the sign the roadmap and `cec587f`
took for Issues being off, so it is not one: the Issues page is the check
that decides it.

**What writing takes** (`6b3700b`). The page said Issues are public. It did
not say that writing one needs a GitHub account, which a visitor would learn
only at GitHub's sign-in page, and that reading needs none. One sentence now
says both, `ACCOUNT_FA` in `ContactForm.tsx`. It is true only while any
GitHub account may open an issue: since 2026-06-29 GitHub lets a repository
restrict that to collaborators, and the setting cannot be read from outside.

**The use case by its name** (`50b7634`). The assumption that the weights
started from a use case's defaults printed the key — «وزن‌ها از پیش‌فرض
«ride_hailing» شروع شد» — a few lines under the same use case drawn in
Persian. `caro.ranking.USE_CASE_FA` carries the names the panel prints under
«کاربرد», and the assumption uses them.

**Only what was not understood** (`ac85c9b`). D14's `unparsed`, listed
under «بخش‌هایی که نفهمیدیم», also held text the parser had acted on: only
a budget clause and a year clause were taken out before the query was cut
into clauses. So «تصادفی نباشه» sat under «خط قرمز» and under «نفهمیدیم»
at once on the family example, and «ماشین برای اسنپ» and «کم مصرف» on the
Snapp one. The parser now keeps the cues that changed the spec, and a clause
holding one is understood whole, the way a clause naming a model always was.
Measured against the parser before it, on the 25 queries the site, the
benchmark and the suite parse: nothing but `unparsed` changed, and it
changed on 13; the win-rate line did not move. The owner kept the rule at
the clause rather than the word, for now, and its cost is pinned in the
ranking suite so that it changes only on purpose: «ماشین برای اسنپ با قطعات
ارزون» lists nothing.

**On the five examples under the search box,** between `0ae74ac` and
`139a29c`: three parse the same in every field. The Snapp and family
examples change in two fields and no others. The assumption names
«مسافرکشی (اسنپ/تپسی)» and «ماشین اول خانواده» instead of the key, and
«نفهمیدیم» lists «قطعاتش ارزون باشه» alone on the first and nothing on the
second, where it had listed three phrases and two.

**The demo keeps the old text.** `demo/ranking_data.json` and
`demo/index.html` still print the key, three times each. Neither can be
regenerated here: `demo/export_ranking.py` stops with `CorpusUnavailable`
for run3, which is not in the repository (D46). The roadmap had called
fixing the parser a decision about the demo; that was wrong, and `94c7500`
says so.

**How it is held.** Contract §12 holds the status and the 503s to
`ELSEWHERE`; screens §6 draws the closed inbox with it and checks its one
link and the sentence. Contract §7 holds the panel's names to the parser's,
name for name. The ranking suite checks that every use case the parser can
choose has a name, that the two examples say it, and seven `unparsed` cases,
the cost among them.

**Measured.** Ten mutations against the pushed tree, each count written
down before its run:

                                                predicted           red
                                              rnk ctr scr cor   rnk ctr scr cor
    as committed                                0   0   0   0     0   0   0   0
    ELSEWHERE back to the old repository        0   0   0   0     0   0   0   0
    the closed inbox drops the sentence         0   0   1   0     0   0   1   0
    the assumption prints the key again         2   0   0   0     2   -   -   -
    one name differs from the panel's           0   1   0   0     0   1   0   0
    a use case with no name                     1   1   0   0     1   -   -   -
    the cues acted on are not read              6   0   0   0     6   -   -   -
    a point between digits cuts a clause        0   0   0   0     0   0   0   0
    the floor after a year left as text         1   0   0   0     1   -   -   -
    a cue counts only inside one clause         1   0   0   0     1   -   -   -

Every count that could be read was predicted exactly. A dash is not a
zero. Each of the five mutations that turned a ranking check red also
stopped the contract, screens and corpus suites before a verdict of their
own: they reach SYNTHETIC through the API, and the API builds it by
importing `tests/test_ranking.py` (`_synthetic` in `webapp/api/corpus.py`),
which exits on a red check — traced in the contract suite, the SystemExit
comes out of `search`. run_all failed each time, so nothing went green that
should not have; but what those three suites would have said is unknown,
and the one count predicted there, the contract's for a use case with no
name, went unread.

Two rows are gaps, not checks. Nothing holds `ELSEWHERE` to the repository:
it is checked only against itself, so pointing it back at the old one turns
nothing red. And no case needs the decimal rule any longer: in every query
the suite parses, the point sits inside an amount the parser acted on, whose
span covers both halves. It would matter for a decimal outside an amount,
an engine size say, and nothing parses one.

Each commit was green on its own — 1830, 1833, 1837 and 1844 assertions
across 15 suites — and the round was applied to a fresh clone before it was
sent, then on the owner's machine with the odometer round after it: 1888
across 15 suites, the web build green with its nine routes.

**Not measured.** The deployed site. Deploying is deferred (D65), and the
site was last deployed at `a636ea6`, whose contact page names the old
repository.

**What this does not settle.** Whether issue creation is open to every
account, which cannot be seen from outside. The two gaps above. And that a
red ranking check hides three suites' verdicts, which is in
docs/ROADMAP.md.

## D68 (result) — issue creation is open to every account

D68 left one thing unsettled because it cannot be seen from outside. The
repository's own settings, as the owner showed them on 2026-10-06: Issues
is on at Tecso-Dev/caro, and «Issue permissions» reads «Creation allowed by:
All users». So `ACCOUNT_FA` is true as written: reading needs no account,
and writing needs a GitHub account and nothing more. Why the front page,
seen signed out, drew no Issues tab is still not known.

## D69 — The car page says a price by the rule search and compare use

FIELD_PROVENANCE.md states one rule for a price: a figure whose
`price_kind` is not `cash`, or whose `price_status` is unusable, is not an
asking price, and the page says what it is instead (D52). Search and compare
drew with it, `askingPrice()` in `lib/format.ts`, and the budget is checked
against the same figure (D65). The car page drew `toman()`, in its heading
and under «قیمت پیشنهادی», though it is sent both fields the rule reads
(`detail=yes`). It was found while drawing the odometer (D67) and recorded
in the roadmap, measured.

**Measured first,** on run11: the two surfaces disagreed on 2 of 75 cars.
The two whose price is «توافقی», with no amount, were «ثبت‌نشده» in both
places on their car page and «توافقی» in search and compare. run11 holds no
financing total and no unusable figure with an amount, so the rest of what
the rule decides was measured on listings built for it.

**The decision.** The car page uses `askingPrice()` in both places
(`8c47920`), and FIELD_PROVENANCE.md names the car page beside the card. A
figure that is not an asking price is said as what it is, and its amount is
drawn nowhere on the page; it stays on the payload, as an odometer's does
under D67. Drawing the amount under its own label — «قیمت کل اقساط: …» —
would be a second decision, and it was not taken. Two draws of the amount
stay as they were: a listing that is not a car shows its declared amount as
just that, and the scored panel's rows passed eligibility, which applies
the same two gates (D52).

**What the heading and «قیمت پیشنهادی» say,** before and after, on
listings built for each kind of price and served through the API:

- a cash price with a usable status — `display_confirmed`,
  `structured_only` — and an appraisal row, which carries neither field:
  the amount, as before;
- `negotiable`, with no amount: «ثبت‌نشده», now «توافقی»;
- `absent`: «ثبت‌نشده», now «قیمت اعلام‌نشده»;
- a financing total of 900,000,000: the amount, drawn as the asking price,
  now «قیمت کل اقساط»;
- a cash figure graded `ambiguous`: the amount, now «قیمت مبهم».

**On run11, before and after** — the trees of `3a52bc5` and `8c47920`: 2 of
76 car pages changed, the two «توافقی» listings, in both places. The
assignment's «مبلغ اعلام‌شده» is drawn as before. Search and compare were not
touched.

**How it is held.** Screens §8 draws the car file for six listings served
from a temporary artifact, one per kind of price, for an appraisal row, and
for run11's two «توافقی» listings beside a cash one, and reads the heading
and the cell; for the financing total and the ambiguous figure it checks
that the amount is nowhere on the page. The corpus suite fails a surface
that reads the amount without both of the rule's fields, the car page
included, and the car page's own derivation now holds both fields to
FIELD_PROVENANCE.md's `detail=yes`.

**Measured.** Six mutations, each count written down before its run:

                                                    predicted     red
                                                     scr  cor   scr  cor
    as committed                                       0    0     0    0
    the heading draws toman() again                    6    0     6    0
    the cell draws toman() again                       6    0     6    0
    both draw toman() — the code before                6    1     6    1
    an extra cell draws every amount                   2    0     2    0
    kind and status passed to askingPrice() swapped    8    0     8    0

All six exactly, and the ranking and contract suites stayed green in every
run. Each commit is green on its own — 1907 and 1907 assertions across 15
suites, 1489 across 12 without the extras — and the round was applied to a
fresh clone before it was sent, then on the owner's machine: 1907 across 15
suites, the web build green with its nine routes, pushed as
`3a52bc5..ed84d72`.

**Not measured.** The deployed site. Deploying is deferred (D65), and the
site was last deployed at `a636ea6`.

**What this does not settle.** Whether a figure that is not an asking price
should still be shown on the car page under its own label.

## D70 — Two rules nothing held are held, and the decimal rule stays

D68's mutations found two rules that no check held. `ELSEWHERE` was checked
only against itself: the status and the 503s must name it, whatever it
names, so pointing it back at the old repository turned nothing red. And
no query the suites parsed needed `unparsed`'s decimal rule — a point
between two digits is not a separator — because every point in them sat
inside an amount the parser acted on, whose span covers both halves.

**Where to write** (`7d5264e`). Contract §12 holds `ELSEWHERE` to the one
address D68 decided, `https://github.com/Tecso-Dev/caro/issues`: equal to
it, not merely a URL or anything naming GitHub. Issues is on there and
open to every account (D68, result).

**The decimal rule, measured first,** on the 25 queries the repository
parses — the examples under the search box, the benchmark's, every literal
the suites hand the parser, those of `scripts/rank_run5.py` — and a fixture
with a decimal outside an amount, «پراید، موتور ۱.۶، تا ۵۰۰ میلیون». With
the rule taken out, one of the 26 changes, the fixture, in one field,
`unparsed`: «موتور ۱.۶» is cut at the point to «موتور ۱». Ten others hold a
point between digits, each inside an amount, and parse the same; nothing
else changes on any of them.

**The decision.** The owner decided on 2026-10-06 that the rule stays. It
is narrow and it is needed: it changes nothing else the parser does, and
without it the panel would list a fragment as what was not understood —
evidence cut short and misleading. The ranking suite now holds the fixture
whole (`2d7d28b`), so the rule is a contract: changing it means changing
that check, on purpose. The parser itself was not changed.

**Measured.** Four mutations, each count written down before its run:

                                                 predicted          red
                                           rnk ctr scr cor    rnk ctr scr cor
    as committed                             0   0   0   0      0   0   0   0
    ELSEWHERE back to the old repository     0   1   0   0      0   1   0   0
    ELSEWHERE without /issues                0   1   0   0      0   1   0   0
    the decimal rule taken out               1   -   -   -      1   -   -   -

All four exactly, and the 26-query measurement, predicted in writing too,
held. With the rule taken out, the check reports `['موتور 1']`.
Its dashes were predicted as dashes: a red ranking check stops the contract,
screens and corpus suites before a verdict of their own (D68), which this
does not touch. Each commit is green on its own — 1908 and 1909 assertions
across 15 suites, 1489 and 1490 across 12 without the extras — and touches
only tests and the published counts. The round was applied to a fresh clone
before it was sent, then on the owner's machine: 1909 across 15 suites, the
web build green with its nine routes, pushed as `43d2720..2d7d28b`.

**What this does not settle.** That a red ranking check hides three suites'
verdicts, an architecture question of its own, to be measured before
anything changes.

## D71 — The site builds every corpus without the test suite

D68 found it while measuring something else: a red ranking check stopped
three other suites before a verdict of their own. Measured on 2026-10-06,
before anything was changed, it was more than a test harness problem. The
site built SYNTHETIC by importing `tests/test_ranking.py`, which ran every
check in that file and ended in `SystemExit` when one was red. Under
uvicorn the process lived, `/api/health` kept answering 200, and every
request that needed a corpus answered a bare 500, re-running the whole
suite each time. Not only in SYNTHETIC: both UNUSABLE states built the
synthetic corpus to borrow its pipeline, so the envelope that says
RUN_NOT_FOUND or CORPUS_INVALID — what those states exist to say — never
reached the client. REAL never touched the file. In the suites, one red
ranking check left 624 assertions unrun: all 238 of the contract suite's,
270 of corpus's 333, 116 of screens's 130.

Three predictions of that measurement were wrong, and are recorded: the
import was expected to cost seconds and costs 0.2–0.3 s; the 625
assertions run_all reported missing include the red check itself, so the
three suites lost 624, not 625; and RUN_NOT_FOUND was expected to be clear
of the suite, and was not.

**What the site used from the file,** measured next: three names, POOL,
PIPE and OK, all built by its first hundred lines. The other 483 lines
changed none of them, no line of the file ran at request time, and the two
UNUSABLE states used only the pipeline's parser.

**The decision.** The owner put it as two rules: production code does not
import and run the test suite to build a corpus, and a red ranking check
does not stop the suites that do not depend on it. The hundred lines moved,
unchanged, to `caro/synthetic.py` (`e5a34fa`), which the ranking suite now
imports. SYNTHETIC is built from it (`cb145fb`), and its `source` says
`caro/synthetic.py` — the one change a reader can see. REAL and both
UNUSABLE states share the pipeline REAL already built without any corpus
behind it, a parser and an estimator never benchmarked (`53afc1f`). Two
alternatives were weighed and set aside: a fixture file under `tests/`,
which leaves production importing from `tests/`, and catching `SystemExit`
in the site, which leaves it running the suite on requests.

**On the same measurements, after:** the corpus, the estimator and the
gate's verdict have the fingerprints they had; six calls in each of the
four states answer as before, but for SYNTHETIC's `source`; with one
ranking check red on purpose, run_all failed the ranking suite alone and
every other assertion ran and passed, 1917 of 1918; and under uvicorn
SYNTHETIC, RUN_NOT_FOUND and CORPUS_INVALID answered 200 with their
envelopes, with no `SystemExit` and the suite never imported. An UNUSABLE
state's first request now takes about 0.01 s, where building the synthetic
corpus made it 0.14–0.19 s. The win-rate line is unchanged.

**How it is held.** Contract §16 reads the eight modules under `webapp/`
for any import from `tests/`; builds each of the four states in a fresh
process, which reports that no test module was loaded; checks that
SYNTHETIC came from `caro.synthetic` and says so; and that REAL and the
UNUSABLE states build no synthetic corpus.

**Measured.** Five mutations, each count written down before its run:

                                                predicted           red
                                              rnk ctr scr cor   rnk ctr scr cor
    as committed                                0   0   0   0     0   0   0   0
    the site imports the ranking suite again    0   2   0   0     0   2   0   0
    RUN_NOT_FOUND borrows the synthetic one     0   1   0   0     0   1   0   0
    CORPUS_INVALID borrows the synthetic one    0   1   0   0     0   1   0   0
    one ranking check red                       1   0   0   0     1   0   0   0

All five exactly; the last row is the one that read 1 - - - before. Each
commit is green on its own — 1909, 1915, 1918 and 1918 assertions across
15 suites, 1490 across 12 without the extras — and the round was applied
to a fresh clone before it was sent, then on the owner's machine: 1918
across 15 suites, the web build green with its nine routes, pushed as
`9628920..84d293a`.

**Not measured.** The deployed site, where deploying is deferred (D65).
What Vercel's runtime does with a `SystemExit` inside a request is no
longer this code's question: nothing it imports can raise one.

**What this does not settle.** The corpus is not pinned by a fingerprint
in any test: numpy does not promise its distributions stay the same across
versions, and a pin could fail on an upgrade with nothing wrong. That it is
the same corpus was measured for this round instead.

## D72 — The site serves run13, and «اتومات» is checked against a field

run11 carries no gearbox, so a buyer who says «اتومات» was answered with
listings held apart: on the Quik example under the search box, nothing
matched and eight stood apart, unchecked. The owner chose a second Bama
run to change that, on 2026-10-06, measured first.

**Before the run,** read and run on the code at `f39cec1`: a row made today
carries exactly four keys run11 never has — `gearbox`, `fuel`, `province` and
`price_currency_raw` — measured by one listing taken through the shipped path,
from the parsed record to the reader. Four things were found on the way. The
red line in `webapp/api/constraints.py` already decided «اتومات» from `gearbox`
as soon as a corpus carried it: on a copy of run11 with the field written as
automatic on nine of its Quiks, six matched and two stayed apart, and written
as manual, none matched and none stayed apart — while the eligibility table
still called the field `PENDING_LIVE_VALIDATION`, gate and facet `no`. The
chain that holds that table to an artifact read `run11.json` by name.
`price_currency_raw` had no row in it. And nothing in Bama's fetch path reads
robots.txt, as recorded on 2026-09-11. Two hashes in the documents are not
commits of this repository: 2ddbc72, which FIELD_PROVENANCE.md cited where
`72c2573` is meant and which its rewrite below no longer cites, and 4d95b7d in
D36's freeze note, which stays as it was frozen. Two predictions were wrong:
six and two, not eight and none, because two of those Quiks were unchecked on
mileage as well; and every REAL answer carries the ESTIMATOR_NOT_GATED fault,
which is the state of a real corpus (D43), not an error.

**The run.** robots.txt was read by hand first: the same directives as on
2026-09-11, nothing disallowing `/car/`. Then run11's pin — pride, quick,
tiba · seed 0 · limit 90, digest `a07d10`: 90 links, 74 unique listings,
every page answered, the structured block on all 74. The target counts
links before they are de-duplicated, which is how 90 became 74 and how
run11 was drawn too, so it is left as it is. `gearbox` and `fuel` are on
74 of 74 at parse, snapshot and corpus, nothing lost;
`price_currency_raw` on 72. The run's report called two prices an
unexplained disagreement; both are instalment totals, which `price_kind`
had already named. Its last line says the corpus is ready to benchmark
on Saipa Pride. D55 says one snapshot is UNJUDGEABLE, and the same
function prints the same line on run11: the two have disagreed since
D55. Recorded, not changed.

**Read after the run,** on the owner's machine. The snapshot compared
with is the one run11 was promoted from, byte for byte. On the same pin 26
days apart, 3 of run11's 76 listings were drawn again, and none had
changed. `province` is on 34 of 74 — fifteen provinces, Tehran on five.
Ten pages were read once each: every miss was empty and none wrong, and
the misses are lines the rule cannot read — city and district, 5 of the
8; city, province and district, 2; a page with no odometer line, 1. The
Quik example found nothing at all: run13's three automatic Quiks ask
1.65, 1.68 and 1.75 billion. Three predictions were wrong: province on at
least 67, the Quik example matching at least one, and every example
finding something. A fourth claim was mine and false — that one Quik's
trim said manual while its field said automatic. The probe printed eleven
characters of «manualrplus at»; the page's structured block and its
displayed «گیربکس» line both say automatic.

**The decision.** The owner's: run13 is published, for the reason D57
published run11 — the site is to serve it — and served by default; the
Quik example asks up to 1.8 billion. On that, FIELD_PROVENANCE.md is
measured on run13 by its own procedure: `gearbox` and `fuel` are
`SOURCE_BACKED` on 74 of 74, and `gearbox` is a facet, because the search
checks «اتومات» against it; `province` is `SOURCE_BACKED` on 34 of 74 with
every flag `no`. The plan said it would stay pending, but the file moves a
field out of `PENDING_LIVE_VALIDATION` when a real run records a number,
and the flags, not the status, keep it off every screen.
`price_currency_raw` has a row of its own, diagnostic only. The sections
that follow a non-vehicle read run11's assignment by name, run13 holding
none; the §16 probe and the provenance chain read DEFAULT_RUN.

Nine commits: `f028dcc`, `38db406`, `b475ef9`, `db310e3`, `be9b871`,
`51ee6fa`, `868bad3`, `449b4d9` and `e4a32f6`. Two were not in the plan
the owner approved, `51ee6fa` and `868bad3`: making run13 the default
turned screens §5 red twice. A row held apart on a 4,200 km 1401, graded
suspicious, says «کارکرد مشکوک» (D67), and the check wanted
«کارکرد ثبت‌نشده»; and its case with nothing matched and nothing apart was
reached only while no Tiba lacked a price. Each is its own commit.

**Measured.** With run13 beside run11 and the default unchanged: 1918,
green. With run13 the default before the round: seven checks red in two
suites — the Quik example, a non-vehicle to follow in contract §11 and to
draw in screens §0, and the four of §16 — all predicted but the screens
one. With run13 served against run11's document, the new chain fails 25
checks: 24 rows' numbers, and no row for `price_currency_raw`. After the
round, matched and held apart:

                                         run11      run13
    «پراید»                              56, 0      54, 0
    «پراید زیر ۳۰۰ میلیون»                2, 2       2, 2
    the Snapp example                    51, 2      47, 4
    the family example                   67, 2      53, 11
    the Quik example, 1.8 billion         0, 8       1, 2

The one Quik match is a 1403 at 18,500 km for 1.68 billion; the two held
apart are held for their odometers. Each commit is green on its own —
1918, 1918, 1918, 1918, 1919, 1919, 1924, 1929 and 1929 assertions across
15 suites, 1490 to 1495 across 12 without the extras — and the round was
applied to a fresh clone before it was sent, then on the owner's machine:
1929 across 15 suites, the web build green with its nine routes, pushed as
`f39cec1..e4a32f6`.

**Not measured.** The deployed site, where deploying is deferred (D65): it
serves `a636ea6`, and run13 reaches it with the next deployment.

**What this does not settle.** run13 is one snapshot: an estimator is as
unjudgeable on it as on run11 (D55), and a second discovery run on the
same pin is a new sample, not a series. `province` waits for a rule that
reads the lines it misses now. robots.txt is read by hand for Bama, and
must be checked in code before any recurring collection.

## D73 — robots.txt is read in code, by a matcher of our own

D72 ended on it: robots.txt was read by hand for Bama, and had to be checked
in code before any recurring collection. The owner asked for the measurement
first, and chose on it.

**Before any code,** on `cafb893`. Divar's check is `assert_allowed`, which
`search_url` calls before every page: a transcription of robots.txt dated
2026-09-07, which nothing fetches, parses or keeps. Bama had none. Every
request it makes — the sitemap, a category, a listing, and every request of
the six scripts that build an adapter — goes through `BamaAdapter._get` to
the fetcher, and only `slice_probe2` asked for robots.txt, to print it.
Three mutations: `assert_allowed` returning at once turned the four refused
urls red; `search_url` no longer calling it turned nothing red; and a fake
Bama whose robots.txt disallowed `/car/` was asked for robots.txt zero
times, sent four of its five requests under `/car/`, and turned nothing red.
Two documents said more than the code did: `location_probe.py` promised "the
same robots check and the same sleep as a collection run", and RUN5_SPEC §9
says robots.txt is "checked and enforced in code (`assert_allowed`)" — both
true for Divar only. Measured afterwards, not predicted, and the reason for
what follows: Python's `urllib.robotparser`, on 3.11, given Divar's rules as
transcribed, allows three of the four urls they disallow —
`/s/tehran/light?q=206`, `?page=2&q=pride` and `/my-divar/bookmarks` —
because it reads `*` in a path as a character.

**The decision.** The owner's: a matcher of our own, not the standard
library's, reading RFC 9309 §2.2 and nothing more. Groups are found by
product token — `CARO-research`, which the User-Agent we send begins with —
groups naming it are combined, and `*` applies only when none does. The
longest pattern decides and an allow wins a tie; `*` and a final `$` are the
special characters; percent-encoding is compared in one spelling on both
sides. One gate per adapter (`RobotsGate`, in `caro/ingest/robots.py`) is
asked before every request. An execution is a process and a process builds
one adapter, so robots.txt is read at most once per execution, and kept in
memory only. A 2xx states rules; a 4xx other than 429 means the file is
unavailable, so no rule applies; a 5xx, no response, a fetcher that raises,
no fetcher at all and any other status mean nothing is requested. Five more
were decided before the first line was written: 429 is read as unreachable;
Divar keeps its 2026-09-07 transcription beside the gate, and a url either
refuses is refused; a refused url is neither requested nor given an outcome,
only counted in DISCOVERY; date_watch puts the record of what was read on
every row of a round; the probes print it, with nothing stored and nothing
tested. One change to what was approved is mine, and was said when the round
was delivered: a 2xx is a page, not a policy, when its body begins with «<»,
and not only when it carries `<html` or `<!doctype` — an XML document served
with 200 would otherwise be read as an empty policy, which allows
everything. Twice this is stricter than the RFC, on purpose: a 2xx that is a
page or is not UTF-8, and 429.

What was read is recorded — the url, when in UTC, the status, the bytes, the
sha256 of a 2xx body, the verdict, the group, the rule count and why —
printed in DISCOVERY, kept in a snapshot's notes, and carried on every row
date_watch writes. A robots.txt that gives no policy, or that disallows the
sitemap, stops a run before its first page, with nothing written.
`slice_probe2` no longer asks for robots.txt itself: it prints the gate's
copy, and the gate's answer for each path it finds.

Eight commits: `8aadb31`, `523db6c`, `03d3081`, `3cdcc85`, `be4f3c3`,
`55d5838`, `9e4df00` and `1199e7d`.

**Measured.** No request went to any source at any stage. Every suite, every
mutation and the web build ran in a network namespace with no interface up,
and a hook logging every connection a Python process attempted logged none;
neither the collector nor any probe was run. Two things were measured on the
way: the Bama commit's code without its fixture edits stops test_ingest at
the first test that reads a sitemap, whose fixture answered robots.txt with
the sitemap's XML — a page, so nothing was allowed — and the Divar commit's
code without its edits stops at the first Divar adapter, which had no robots
fetcher. Fourteen mutations were predicted with the exact number of checks
each would turn red, after the tests existed and before any mutation ran,
and all fourteen held:

                                                        red   green of 2037
    Bama's _get no longer asks the gate                  16       2021
    Divar's search_url no longer asks it                  3       2034
    the gate stops keeping what it read                   6       2031
    a 5xx read as allowing everything                     7       2030
    no response read as allowing everything               2       2035
    the record loses its time and its hash                8       2029
    the first matching rule decides, not the longest      6       2031
    `*` read as a character                               5       2032
    429 read as allowing everything                       1       2036
    a page served with 200 read as a policy               2       2035
    search_url no longer calls assert_allowed             2       2035
    our product token ignored                            11       2026
    a tie goes to the disallow                            2       2035
    date_watch builds an adapter for every row            2       2035

Every red check is in test_ingest; no other suite moved. With the gate gone
from Bama's `_get`, the disallowed listing and the disallowed category were
requested, the listing got an outcome, nothing was counted, and neither a
503 on robots.txt nor a disallowed sitemap stopped the run. robots.txt was
then fetched zero times in the adapter's own run and in first_run's, and
once in a round of date_watch, which asks the gate itself: the check that a
round reads it once stayed green, while the disallowed url was requested in
all three. With `assert_allowed` gone from `search_url`, a `q=` url was
allowed whenever the live file allows everything — the same removal that on
`cafb893` turned nothing red. `*` read as a character turned red, among
others, the three urls the standard library allowed. Not predicted: five of
the new checks raised, instead of failing, when a value was wrong — `None`
where a string was expected — found while the predictions were written,
before any mutation ran, and fixed in the commits that added them. Each
commit is green on its own — 1983, 2010, 2021, 2027, 2031, 2035, 2037 and
2037 assertions across 15 suites, 1549 to 1603 across 12 without the extras
— and the web build is green with its nine routes, built inside the same
namespace. The round was applied to fresh clones before it was sent, and on
the owner's machine on 2026-10-07 as `8aadb31` to `1199e7d`: the same eight
trees.

**Not measured.** The gate has judged no real robots.txt — every file it has
read was a fixture. The examples from RFC 9309 §5, and the cases of §2.2.2
and §2.2.3, were transcribed into the tests by hand, not fetched; they
should be compared with the RFC before they are quoted as its text.

**What this does not settle.** That robots.txt allows a request is not
permission to make it: the terms of use are a separate question, and Divar's
are still to be read. Two parts of RFC 9309 are left undone: redirects are
followed by the HTTP client and not counted to five (§2.3.1.2), and no
parsing limit is set (§2.5). The scan that finds no adapter built inside a
loop in `scripts/` is a heuristic: a construction in a function that a loop
calls is not seen. RUN5_SPEC §9 stays as it was frozen; until this entry it
was true for Divar only.

## D74 — The province is read where the market is

The roadmap's next item was `province` where the market is. run13 carries it
on 34 of 74 rows, and the ten run13 pages read by hand on 2026-10-06
(FIELD_PROVENANCE.md) put every miss in a shape the rule could not read: a
city and a district (5 of 8), a city, its province and a district (2 of 8),
and a page with no «کارکرد … کیلومتر» line at all (1 of 8, a 1405 Quik). So
what it read leaned to small towns.

**Measured first, and D73's gates read for real.** On 2026-10-10, on the
owner's machine, one read-only script did two things. It sorted the lines
date_watch had stored — for each of the 19 listings with an odometer line,
the two lines after that line in its latest observation — by what the
shipped `province_of` made of them: 8 read; 2 stating their province but not
last («شیراز، فارس، فرهنگیان», «کرج، البرز، گوهردشت»); 9 two-part lines
whose first part names a province, 7 «تهران، …» and 2 «اصفهان، …»; no comma
line without a province, and none without a comma line. The counts predicted
before it ran held. And, with the owner's leave for two requests, it read
robots.txt through the gates D73 built. bama.ir at 2026-10-10T10:46:38Z:
http 200, 592 bytes, sha256
`ec67e8a840ad9e5273a419bd66674c3b9886049bb9609ea6f5abb7b2227f1597`, two
rules from group `*` — the directives of 2026-09-11 — and the sitemap, a
category, a filtered category and a listing allowed. divar.ir at 10:46:44Z:
http 200, 92 bytes, sha256
`cf0415ac314ee550222c5b2d07323f51dec373e2c1bff364a3fd4eeeb9cf0849`, four
rules from `*` — the directives transcribed on 2026-09-07 — its three search
pages allowed, and the gate and `assert_allowed` agreeing on 8 of 8 sample
urls. D73 said the gate had judged no real robots.txt; it has judged two,
and neither transcription had to change.

**The decision.** The owner's, of three put to him: a province the line
states is read wherever it stands after the city, and a two-part line whose
city is one of the thirteen capitals that carry their province's name —
Ardabil, Bushehr, Hamadan, Ilam, Isfahan, Kerman, Kermanshah, Qazvin, Qom,
Semnan, Tehran, Yazd and Zanjan, from Wikipedia's table of the thirty-one,
read 2026-10-10 — gives that province. Not taken: the stated province alone,
which on these lines reads 10 of 19 and no Tehran; and neither, leaving this
entry to record the measurement. A province found by the city says so:
`province_source` — `stated`, `city` or `none` — crosses from the parse to
the snapshot, the promoted row and the reader, and a province with no
recorded source is published as `stated`, since before this every province
was. A stated province wins wherever it stands in the window. «کرج» stays
refused, Karaj being in Alborz by a geography the code does not hold, and so
does a first part that names a province whose capital has another name,
«گلستان، …» or «البرز، …»: the first part is a city. Four commits:
`8f3b913`, `df0d722`, `cff7505` and `dbe7829`.

**The prediction that failed.** The choice was put as 19 of 19 on this
sample, and the check written to confirm it — the shipped `extract_location`
over the same stored lines, run on the owner's machine after the four
commits — was predicted to give 10 stated, 9 by the city and none
unanchored. It gave 9, 8 and 2. The seventeen with an anchor came out one
for one; the two without, `bama:l39y2bdi` and `bama:wmxsljsn`, have a
location line the rule reads (فارس, stated; تهران, by the city), but the
parser never reached it: it anchored only on «کارکرد … کیلومتر», and their
odometer line was something else. The push was held. The miss had been named
before the round began — the last row of FIELD_PROVENANCE's table of
2026-10-06 — and the round went past it: the measurement sorted the two
lines after the odometer line and never asked whether the parser anchors on
that line, and the prediction carried it only as its uncertain case. The
roadmap, after the four commits, said the nineteen lines were all of shapes
the rule reads, and FIELD_PROVENANCE counted them the same way: true of the
lines, not of the parser.

**Measured again.** A second read-only script, on the owner's machine: of
150 stored observations with an odometer line, 132 were «کارکرد … کیلومتر»
and 18 «صفر کیلومتر» — the two, nine rounds each, followed every time by the
age slot (a relative phrase, then an absolute date) and the same location —
no other kind, and no listing changing kind between rounds. Anchored on
«صفر کیلومتر» too, the nineteen gave 10 and 9, and a copy of the rule agreed
with the shipped one on the seventeen it anchors. date_watch stores the
first line of the whole page that begins «کارکرد » or «صفر کیلومتر», split
into lines by the parser's own `_text`, and on all 150 pages that first line
was the car's own odometer line. Every line of that prediction held. It is
the layout docs/WATCH_ROUND1_2026-09-12.md recorded, whose anchor is
«کارکرد N کیلومتر / صفر کیلومتر»; the parser's anchor, written four days
later, took only the first.

**The second decision.** The owner's, of two: a new car's «صفر کیلومتر»
anchors the window as «کارکرد … کیلومتر» does, at the start of a line only,
with the same window, the same two passes and the same labels in the trace.
Not taken: leaving the anchor and correcting the documents to 17 of 19. A
new car's mileage is not read from the line. Two commits: `ea7038b`, and
`ccd2fa6`, which corrects what the four had written.

**Measured.** Two requests went to a source, the robots.txt reads above,
sent by the owner with his leave; nothing else at any stage. Every suite,
every mutation and the web build ran in a network namespace with no
interface. Twelve mutations were predicted with the exact number of checks
each would turn red, after the tests existed and before any mutation ran,
and all twelve held — the first nine against 2077, the last three against
2083:

                                                    red   green
    province_of back to the last part only            6    2071
    province_of reads the first part too              5    2072
    the city rule takes any province's name           2    2075
    the city rule takes a line of any length          2    2075
    the city pass before the stated pass              1    2076
    parse_detail_page calls everything stated         1    2076
    promote_record ignores a recorded `city`          1    2076   survival
    the reader ignores province_source                1    2076   survival
    to_fetch_outcome passes the source underived      2    2075   survival
    the anchor back to «کارکرد … کیلومتر» only        4    2079
    «صفر کیلومتر» anywhere in a line                  1    2082
    the next anchor tried when a window holds none    4    2079

The red checks are in test_ingest but for the three marked; no other suite
moved. Two things not predicted, both about the runs and not the code. The
owner stopped the first nine while the eighth was running, which left its
edit in the scratch clone; it was restored and the eighth and ninth run
alone — and the owner was first told the run had not happened at all, which
was wrong and was corrected in the next report. The last three first ran in
a clone without the web app's node_modules, where the baseline is 1947
rather than 2083: the same four, one and four red; they were run again with
it. Each commit is green on its own — 2045, 2055, 2077, 2077, 2083 and 2083
assertions across 15 suites, 1611, 1621, 1643, 1643, 1649 and 1649 across 12
without the extras — and the web build is green with its nine routes. Both
rounds were applied to fresh clones before they were sent, and on the
owner's machine as `8f3b913` to `ccd2fa6`: the same six trees. After the
last two, the check gave 10 stated, 9 by the city and none unanchored, every
listing as predicted. Between D73 and this entry one commit more, `63868cb`:
README's layout names the decisions' range, and test_claims holds it to the
last one, as it already held /about's count.

**Not measured.** No collection has run on the new rule: the nineteen are
three stored lines a page, put through `extract_location`, not pages through
`parse_detail_page` and a promotion. run13's numbers stay run13's, because
its pages were not kept; three of its rows carry neither mileage nor
province, all three Quiks, which is what a new car's page would have left,
though without the pages that cannot be shown. The thirteen capitals were
transcribed from one table, read once. A line that begins or ends with a
comma («، تهران», «تهران،») was read by the old rule, as its last part, and
is not read by the new one; no stored line has that shape — the eight the
old rule read are all «شهر، استان» — and none was looked for elsewhere.

**What this does not settle.** A district named like a province is read as
that province, stated: «تهران، گلستان» would give گلستان, because a stated
province wins. A new car's mileage stays unread, and whether «صفر کیلومتر»
reads as zero is the ground of D21 and D67, not of this entry. Nothing draws
`province` or `province_source` until a collection shows the coverage, and
`province_source` stays PENDING_LIVE_VALIDATION.

## D75 — run14 reads the province on a collection, and what it turned up

The stored lines had nothing more to give. After D74 the rule was run on
every observation date_watch kept, not only the latest of each listing —
150, over eight rounds: each listing gave one province and one source in
every round, 89 rows stated and 61 by the city, and the location stood
second after the odometer line on all 150; the 30 rows with no odometer line
were 29 pages gone (410) and one 502. The snapshots on the owner's machine
hold provinces already parsed, not lines, so nothing else could be read
again. How much of a collection gets a province is a question only requests
answer, and the owner decided it, of three — run13's pin, a smaller run, not
now: run14 on run13's pin, on his machine, a snapshot and nothing promoted
or published, the predictions first.

**The run,** 2026-10-11. The first attempt stopped at first_run's salt
guard, before any request. A Bama run uses the salt for nothing —
parse_detail_page sets `seller_raw` to None, and no row of run13 carries a
fingerprint — so it was set from a file outside the repository, kept for the
runs to come. The gate read robots.txt at 00:05:28Z: http 200, 592 bytes,
the sha256 of 2026-10-10, no url refused. Twelve category pages, 93 links,
78 unique listings, 77 answered and one not at all.

**What it measured.** A province on 76 of the 77 rows: 44 stated (57.1%), 32
by the city (41.6%) and one with none — where run13, on the same pin, has 34
of 74 (45.9%). تهران on 25, 21 of them by the city, and اصفهان on 14, 8 by
the city, where run13 has 5 and 5; البرز on 6 and خراسان رضوی on 4, all
stated — Karaj's and Mashhad's three-part lines. The five rows with no
mileage — four Quiks and a Pride, all of 1405 — each have a province, which
on their pages takes the «صفر کیلومتر» anchor: inferred, the trace not being
kept. 37 listings are in both runs: the 13 run13 read give the same
province, stated, and of the 24 it did not, all but one are read now.
Predicted before the run, and held: the robots file; 78 unique listings,
within 65 to 85; one fetch unanswered, within three; all three shares within
their ranges; Tehran and Isfahan rising most; a province on every new car;
no disagreement with run13, and at most one listing unread. Not held: 90
links — the target is checked after each category page, and the last carried
the count to 93 — and the new cars all Quiks, when one was a Pride. One
could not be checked: that `province` crosses parse, snapshot and corpus at
one rate, because the report has no province row.

**Four things it turned up, and what the owner decided on each.** The
survival report never audited `province`: its guard asks for the fields
CarListing and FetchOutcome share by name, and `city` lands as `province`,
`seller_raw` as `seller_fingerprint` — renames the CROSSES map in the same
test file records and the guard did not read. Both rows were added, and the
guard is held to CROSSES by where each value lands; added alone, it named
exactly those two: `53bf72c`. Promotion would have published a fetch that
returned nothing: promote_record made a row of the unanswered fetch — an id,
condition unknown — and both guards passed it, where run11's and run13's
snapshots had held only answered fetches. Of three ways — fix it first,
promote as it was, promote later — the owner chose the first: a record whose
status says its fetch returned no listing is refused, by name, and one with
no status is believed as before: `3dadc08`. run14 was then promoted — 78
records in, 77 published, 1 refused; 63,952 bytes, sha256
`00ad4e061b7b058e110300bd8abf87f9b56125055c4ec420a8ce66da662d402c` — and
committed byte for byte as the owner promoted it: `c57dae9`. Nothing reads
it: the default stays run13. The one row with no province was probed, the
owner allowing one listing: robots.txt and the page, two requests, which
went twice, ten seconds apart, because the command was left in a block of
commands meant to be run whole — four requests where two were meant.
bama:4flyapjw's window holds «یاسوج، کهکیلویه و بویراحمد» two lines after
the odometer: its province stated, and spelled with ک where the province's
name has گ. Predicted and held: http 200, the anchor, nothing read. Not
held: why — it was none of the three causes written down, a city no rule
names, a location past the window, or no location at all. A closed table of
spellings seen on a source page, each with where it was seen, now gives the
province it names, and ک and گ are not folded: `d12c592`. run14 stays as it
was collected; the next collection reads it. And promotion had printed
62,207 "bytes" for 63,952 — len() of the text — where run13's commit carried
the file's size; it now counts what it writes: `9e4df12`.

**Measured.** Requests went to Bama only from the owner's machine, with his
leave: the run's — robots.txt, the sitemap, twelve category pages, 78
listings — and the probe's four. Every suite, mutation and build here ran in
a network namespace with no interface. Each change was measured before it
was made, its checks added alone turning red exactly as predicted — the
survival guard one, the promotion checks four, the spelling checks three,
the byte checks one — and each mutation was predicted with the exact number
of checks it would turn red, against the count of the tree it ran on — 2086,
2093 or 2099, and 2083 for the one run on the tree before. All held:

                                                      red   green
    the survival table without the province row         2    2084
    the survival table without the seller_fp row        2    2084
    the province row keyed `city` in the snapshot       2    2084
    promotion publishes no province                     3    2083
      the same, on the tree before the change           1    2082
    survival() reads the snapshot by the parsed name    2    2084
    the status check removed                            4    2089
    only `unknown` refused                              1    2092
    the refusal names no status                         2    2091
    the spellings table empty                           3    2096
    a spelling read as itself                           2    2097
    promotion counts characters again                   1    2098

The red checks are in the suite of the change — survival, corpus or ingest —
and no other suite moved. Not predicted, and about the runs only: the first
launch of the survival mutations died on a NameError in the harness, before
any edit, and was relaunched. Each commit is green on its own — 2086, 2093,
2093, 2097, 2099 and 2099 assertions across 15 suites, 1652, 1659, 1659,
1663, 1665 and 1665 across 12 without the extras — and the web build is
green with its nine routes. Every round was applied to fresh clones before
it was sent, and on the owner's machine as `53bf72c`, `3dadc08`, `c57dae9`,
`d12c592` and `9e4df12`, each script checking that the tree it left is the
one rehearsed.

**Not measured.** Coverage beyond run13's pin: three models of one maker, 78
listings, one day. The spellings table holds one entry, and nothing has
looked for others. The «صفر کیلومتر» anchor on a live page is inferred from
five rows, not traced.

**What this does not settle.** run14 is published and not served: the
default stays run13 and the site still serves `a636ea6`; serving it is the
owner's to decide. A district named like a province is still read as that
province, stated. A new car's mileage stays unread. Nothing draws `province`
or `province_source`.

## D76 — The site serves run14, and the Quik chip names no gearbox

D75 published run14 and left it unserved: the default stayed run13, and
which corpus the site serves was the owner's to decide. On 2026-10-11 he
chose to serve it, measured first, and to take up the province's place on
the site after it, in a round of its own that he approves separately.

**Measured before the change,** on `28f268e`, with the predictions written
first. With `DEFAULT_RUN = "run14"` and nothing else changed, 27 checks went
red in two suites, where 25 were predicted in a range of 25 to 28. 24 were
the provenance chain's measured rows, whose denominators said 74 against
run14's 77. Two were rows the document dashed and run14 carries as keys:
`province_source`, and `document_issue`, which one row's text gives as a
clean title — the second put at 40%. The 27th was the Quik chip, predicted
at 75% to find something, which found nothing. run14 has no automatic car:
every one of its 77 rows says `manual`, no trim of its ten Quiks names an
automatic, and run13's three automatic Quiks — trims `atfullplus`, twice,
and `manualrplus at` — were not drawn again. Nothing in the red line is at
fault; the sample has no such car. Three predictions about the fields failed
as well: `gearbox` has one value, not two; `product_class` has two, not one,
because run14 holds an assignment, `bama:ktawd8le` — the 1405 «Pride» D75
counted among the five rows with no mileage; and the prices have 54 distinct
values, under the range given. Run on run13 as a control, the same procedure
gave back the document's table row for row. The chips moved within every
range predicted, matched and held apart:

                                         run13      run14
    «پراید»                              54, 0      56, 0
    «پراید زیر ۳۰۰ میلیون»                2, 2       1, 3
    the Snapp example                    47, 4      46, 3
    the family example                   53, 11     56, 10
    the Quik example, with «اتومات»       1, 2       0, 0

**The decision.** The owner's, of four: serve run14 and take «اتومات» out of
the Quik chip; serve it and give the chip's place to «پراید سند آزاد»; keep
run13 until a collection carries an automatic car; or keep the chip and let
section 8 of the contract suite pass an example that finds nothing. He chose
the first. The chip reads «یه کوییک کم‌کارکرد تا ۱.۸ میلیارد میخوام». The
guess I gave him when he chose, two or three matches, was made before I had
looked at the rows; the prediction written after, by hand from the rows and
the parser's rules — at most 120,000 km, a budget of 1.8 billion — held
listing for listing: 5 matched and 5 apart on run13, 5 and 4 on run14, the
four apart being the 1405s with no reading. The red line stays where it is
checked, in `webapp/api/constraints.py` and the fixture of the contract
suite's section 13, and on run14 a buyer who asks for «اتومات» is told that
nothing meets it.

FIELD_PROVENANCE.md is measured on run14 by its own procedure. `province` is
on 76 of 77, and `province_source` leaves PENDING_LIVE_VALIDATION, a real
run having produced both its values; every flag of both stays `no`, because
no screen has been designed to draw them, and which one does is the next
round. `gearbox` keeps its facet with one value. The variety condition would
not admit it; it stays for the reason its row gives — «اتومات» is a red line
checked against every row, not a choice a filter offers — and the file says
so where the condition is stated. The deploy checklist looked at
`bama:zeotfdvq`, which is not in run14, and now looks at `bama:czg8hq9p`, in
both runs and unchanged but for the province run14 reads.

**What the round turned up.** The document said a `false` in
`document_issue` meant the parser had read the prose and found no phrase.
`has_document_issue` has never answered `false` for that: it answers `false`
where the text holds «سند آزاد», «سند تک برگ» or «سند دست اول», and null
where it holds no phrase it knows. The paragraph was written so on
2026-09-18, the function is unchanged since `4a16962`, and the bullet above
the table already had it right. The one row of run14 that carries the key,
`bama:bwfgrup6`, is such a `false`, and «پراید سند آزاد» matches it — the
only one of the 56 Prides not held apart. And of the 37 listings run14
shares with run13, two changed in five days: `bama:zvdmu5cv` from 1.02 to
1.2 billion, its odometer from 66,000 to 46,000 km, and `bama:yovfwzpv` from
575 to 560 million. On run11's pin 26 days apart, 3 listings were drawn
again and none had changed (D72).

Four commits, on the owner's machine: `7fe4e72`, `f145bc3`, `a08e6c2` and
`3a03f2f`.

**Measured.** Every suite, mutation and build ran in a network namespace
with no interface, and no request went to any source. Each commit is green
on its own — 2099 assertions across 15 suites at every step, 1665 across 12
without the extras — and the web build is green with its nine routes. Three
mutations on the round's last commit, each predicted to turn exactly one
check red in one suite, all held:

    the Quik chip given «اتومات» back                 contract   1
    the province row back to run13's 34/74            corpus     1
    province_source back to PENDING_LIVE_VALIDATION   corpus     1

The round was applied to fresh clones before it was sent, and on the owner's
machine as `7fe4e72` to `3a03f2f`: 2099 across 15 suites, the web build
green with its nine routes.

**Not measured.** The deployed site, which serves `a636ea6`; run14 reaches
it with the next deployment. Whether any of run14's stated provinces is a
district named like one: nothing on run14 was read by hand to look.

**What this does not settle.** Which surface draws the province is the next
round. run14 is one snapshot, as unjudgeable for an estimator as the two
before it (D55). And the corpus served has no automatic car, so the chip
that showed «اتومات» checked against a field is gone until a corpus carries
one.

## D77 — The car page draws the province, with how it was read

D76 left which surface draws the province to a round of its own, measured
first. The owner said to go on 2026-10-13.

**Measured before the choice,** with the predictions written first; every
count held. The payload already carried `province`, filled from the
listing's `city`, and nothing said how it was known; the car page drew
neither. On run14 the province is on 76 of 77 rows, 44 stated and 32 read
from a city that shares its province's name — Tehran 21, Isfahan 8, Qom 3.
Of its 56 Prides, 14 are in Tehran, 12 in Isfahan, 29 elsewhere and 1 has
none. The snapshot keeps the province and its source and not the line, so
whether a district named like a province stands behind any stated row could
not be measured from anything stored.

I told the owner that misread was possible only behind the 27 stated rows
whose province's capital does not share its name, and the predictions called
those 27 the reads such a district could have produced. That was wrong. A
district named like any province, after any city, is read as that province,
stated, so it can stand behind any of the 44. He had not chosen the probe
built on the 27, and the document and the commits say 44.

**The decision.** The owner's, on two questions. Where the province is
drawn, of four: the car page with its source; the car page and the lists; a
search that reads «در تهران»; nowhere yet. He chose the first. How the
district hazard is measured, of four: keep the line in the snapshot; a live
probe of the 27 pages; both; not now. He chose the first.

**What was built.** The payload carries `province_source`, a closed set —
stated, city, none — on both sides of the wire; nothing upstream of the
reader closes it, so the contract suite reads every published corpus as the
site would and holds what it yields to the set, and follows the served
corpus through the detail path, all 77 listings. The car page has a ninth
cell: «تهران» where the listing names its province, «تهران — از روی نام شهر»
where the city gave it, «ثبت‌نشده» where there is none, and a province with
no recorded source would say «منبعش ثبت‌نشده», a pairing promotion never
writes. The province and its source are `detail` and nothing more. On the
car page a misread is one listing, labelled with how it was read and a click
from its source; in a list it would sit beside others, and a search reading
«در تهران» would drop a misread car from its answer without a word. The
screens suite reads the cell out of all 76 car files and holds it to the
payload. The line a province is read from, `location_raw`, crosses from the
parse to the snapshot and stops there: it is a forbidden key in a published
corpus, promotion does not copy it, and the survival report audits it to the
snapshot and prints a dash for the corpus, where its absence is the decision
rather than a loss.

Five commits, on the owner's machine: `b723b1c`, `1235d45`, `81daa09`,
`5c17caf` and `17982c2`.

**Measured.** Every suite, mutation and build ran in a network namespace
with no interface, and the browser in one with loopback alone; no request
went to any source. Each commit is green on its own — 2103, 2110, 2111, 2118
and 2118 assertions across 15 suites, 1665, 1667, 1668, 1675 and 1675 across
12 without the extras — every count as predicted, suite by suite, with
README and /about carrying each commit's own. The web build is green with
its nine routes after the car page changed and at the end. Built and served
against the real API, three car pages were looked at in a browser, 1280 and
390 wide: `bama:h5vqo2ug` reads «تهران», `bama:czg8hq9p`
«تهران — از روی نام شهر», `bama:4flyapjw` «ثبت‌نشده»; nine cells, three to a
row on the wide screen and one on the narrow, and no horizontal scroll.
Seven mutations on the round's last commit, each predicted to turn checks
red in one suite:

    province_source left unfilled in the payload        contract 1 *
    a city-read province drawn alone                    screens  1
    the document's province_source detail=no            corpus   2
    FORBIDDEN_KEYS without location_raw                 corpus   1
    to_fetch_outcome drops location_raw                 survival 4
    promotion copies location_raw into the row          survival 1
    the parse keeps no line                             ingest   2

Six held. The first, marked, did not: it turned three checks red in two
suites, where one in one was predicted — the screens section's reach checks
read the source from the payload too, and caught its absence as well. The
round was applied to fresh clones before it was sent, and on the owner's
machine as `b723b1c` to `17982c2`: 2118 across 15 suites, the web build
green with its nine routes.

**Not measured.** The deployed site, which serves `a636ea6`. Whether a
district named like a province stands behind any of run14's 44 stated rows:
run14's lines were not kept, and the next collection's will be. Whether the
line survives a real run to the snapshot: the survival report will say, on
that collection.

**What this does not settle.** The lists and the search still do not show or
read the province, until the district hazard is measured on the lines. A new
car's mileage stays unread. And a buyer still cannot ask for cars near him:
the evidence for it is on the car page, and the question is not yet in the
search.

## D78 — The site serves main again, seen from the outside

The site had served `a636ea6` since 2026-09-27. The deployment of 2026-10-05
was refused (D65), and nothing decided after D64 had reached it. On
2026-10-14 `main` was deployed from `Tecso-Dev/caro` by the person whose
Vercel account holds the project, a friend of the owner. The steps written
for him were these: the Vercel GitHub App on `Tecso-Dev` with access to
`caro`; the project connected to `Tecso-Dev/caro`, with `main` its
production branch; `CARO_INBOX=off` for production and previews, with
`CARO_RUN` and `CARO_ADMIN_TOKEN` unset; a deployment of `main`; and the
pages to look at after it. Which of them he took is not recorded. I first
wrote the steps for the owner's own account, reading D64's
«the one the author already deploys to» as saying the project was his. It is
not, and they were rewritten before anything was done.

**Measured,** from the outside on 2026-10-14, in the owner's browser and by
fetching two pages:

    /                        the five chips under the search box, the
                             Quik one without «اتومات»
    /about                   77 decisions, 2118 assertions, 15 suites
    the corpus badge         REAL DATA · ۷۷: data/corpora/run14.json,
                             77 rows, the gate not passed, the evidence
                             identity «run14 · SHA-256 00ad…402c»
    /search, the Quik chip   77 considered, 64 appraisable, 5 matched,
                             4 held apart for an unrecorded odometer,
                             NOT SERVED

`/about`'s three numbers stand together on `bd8d56d` and on no earlier
commit, so the site serves the last commit pushed. The badge's digest is the
published file's own (D75). The five matched and the four held apart are the
ones the round measured on run14 here (D76), as far as the rows show them —
year, odometer and price.

**Not measured.** The contact page's inbox. The page draws its form until
`/api/contact/status` answers, so a fetch of the page shows the form
whatever the setting, and the status was not read: whether `CARO_INBOX=off`
is set on this deployment is not known. The car page's province cell on the
live site: the tree deployed is the one whose screens suite reads the cell
out of every car file (D77), and no live car page was looked at. How the
next deployment is made, by a push or by hand. The cause of the
«Not authorized» of 2026-10-05. And whether the site can be reached from
Iran, set aside in D64.

**What this does not settle.** Until it is known how deployments are made, a
commit is on the site only once the site has been checked for it. And if the
inbox is not off, the contact form is drawn and every message is refused
with a 503 — the state D64 switched off.

## D79 — No district behind a stated province on run15, and a capital alone is the city

D77 left the district hazard to be read on the lines of the next collection.
The owner chose it on 2026-10-14, of the ways offered: run15 on the pin of
run11, run13 and run14, on his machine, a snapshot and nothing promoted or
published, the predictions written first and a script that only reads the
snapshot to read the lines.

**The run,** 2026-10-14 at 00:31Z, on `08688d9`. The gate read robots.txt:
http 200, 592 bytes, the sha256 of 2026-10-10, no url refused. Ten category
pages, 90 links, 75 unique listings: 74 answered with a listing, and one
answered 200 and parsed to nothing. 54 Prides, 10 Tibas and 10 Quiks, all
manual; the five with no mileage are of 1405, and each has a province. The
province is on all 74, 48 stated and 26 by the city — تهران on 26, 20 of
them by the city, اصفهان on 10, eighteen provinces in all. The line it was
read from is on all 74; the reader, run again on every line, gives back the
province and its source; and the survival report carries `location_raw` to
the snapshot on all 74 and prints a dash for the corpus.

**The hazard, measured.** None of the 48 stated rows stands on a district
named like a province. On 24 the line's first part is the capital of the
province read, by a table of the thirty-one capitals that the script holds
and the repository does not. The other 24 were read by hand here, not
against a source: each first part is a city or county of the province its
line names — رباط کریم and ورامین in تهران, کاشان and نایین in اصفهان, آمل
and نوشهر in مازندران, and so on. Every one of the 74 lines is
«city، province، district», the province left out where it is named as the
city and the district where there is none:

                                                        lines   read as
    a capital named as its province, and a district        26   city
    a capital named as its province, alone                  5   stated
    another capital, its province and a district           12   stated
    another capital and its province                        7   stated
    any other city and its province                        24   stated

A district stands on 38 lines, and none is named as a province is; had one
been, the line would have been read as that province, stated, and the script
would have flagged it — «تهران، …» by its first part, «شیراز، فارس، …» by a
second province's name. One district holds a province's name among other
words, «شیراز، فارس، شهرک گلستان», and is read as فارس, rightly, because
parts are matched whole. Of run14's 44 stated rows, 14 were drawn again,
none on such a district; the other 30 were not drawn, and cannot be read.

**What it turned up.** The five lone names — «کرمان» three times, «زنجان»
and «یزد» — were read as stated. By the shape every other line keeps, each
is the city with its province left out, and none of the other 43 stated
lines is a province alone; the province was known from the city, which is
what `city` means. The province was right and the label said more than the
line, where D77 made the label so that a province known from a city's name
is never shown as stated. The tests held the old reading on purpose, a lone
«تهران» marked as a line that states its province. The owner decided on two
questions. Of fixing the reader, documenting the label, or neither yet, he
chose the first. And of keeping run15 a snapshot until run16 is collected on
the fixed reader, publishing and serving run15 as collected, or publishing
it alone, he chose the first.

**Predictions.** Written before the run: the robots file; the pages, links,
unique listings and the one unanswered, each within its range; the models;
no automatic car; five new cars, each with a province; the survival row; the
province on all 74, stated at 64.9% within 48 to 65 and by the city at 35.1%
within 33 to 50; the line on every row with a province; the reader again,
giving back every row; three-part lines, 12 within 5 to 15; and no row
flagged, the outcome put at 65%. Four did not hold. The listings run15
shares with run14 were 28, where 38 to 56 came from a decay fitted to three
earlier pairs — fewer than the 37 run13 and run14 shared at five days, so
the overlap is not a function of the gap alone. run14's stated rows drawn
again were 14 for 20 to 34, from the same miss. The lone names were 5 for 0
to 2. And the rows the capitals confirm were 24 for 8 to 22, the five lone
names among them.

**What was built.** Two commits, on the owner's machine: `f82efec` and
`bf8746c`. `province_of` no longer reads one of the thirteen capitals named
as their province as a whole line, and `province_from_city` reads the city
alone as well as the city and its district. A province alone whose capital
is named otherwise is still stated, and the labelled path, never seen live,
reads its line as the window does. FIELD_PROVENANCE says so. Snapshots and
published corpora stay as they were collected, as run14 did after `d12c592`
(D75).

**Measured.** Every suite, mutation and build here ran in a network
namespace with no interface. Predicted before the change and held: the code
alone turned 4 checks red, all in ingest, and the new and changed checks
alone turned 8 of 2128 red on the old code, the eight named. Each commit is
green on its own, 2128 assertions across 15 suites and 1685 across 12
without the extras, and the web build is green with its nine routes. Five
mutations, each predicted with the checks it would turn red, all held, every
red check in ingest:

                                                        red   green
    province_of reads the thirteen whole again            7    2121
    province_from_city reads two parts only again        10    2118
    province_of reads no line whole                       2    2126
    province_from_city takes any province alone           1    2127
    the labelled path asks province_of only again         2    2126

The repository's own `extract_location`, at `08688d9` and at the round's
tip, on run15's 48 stated lines as the script printed them: stated on all 48
at the first; at the second, the same on 43 and the five lone names by the
city. The round was applied to fresh clones before it was sent, and on the
owner's machine as `f82efec` and `bf8746c`, pushed to both repositories.
There all 2128 assertions passed across 15 suites, and the script, run again
on run15's snapshot, said 69 rows give back the province and its source and
5 do not: the five lone names, recorded stated and read now by the city.

**Not measured.** run14's other 30 stated rows. Why one page answered and
parsed to nothing. A shape beyond the 74 lines — a province alone, or a city
other than a capital with a district — neither seen. And how many of run14's
44 stated rows are a capital alone: its lines were not kept.

**What this does not settle.** run15 is a snapshot, read by the rule before
`f82efec`, and is not published. run16 waits for the owner's leave. The
lists and the search still do not show or read the province; that is decided
on run16. A new car's mileage stays unread.

## D80 — run16 is served, every line read before it was published

D79 left publishing and serving to run16, collected on the fixed reader with
the owner's leave. He gave it on 2026-10-15, and decided, of three — publish
and serve it, publish it alone, keep it a snapshot — the first.

**The run,** 2026-10-15 at 10:38Z, on `1ebbf4a`, the predictions written
first; all eleven held. The gate read robots.txt as on 2026-10-10: http 200,
592 bytes, the same sha256, no url refused. Thirteen category pages, 98
links, 74 unique listings: 73 answered with a listing, and one answered and
parsed to nothing. 53 Prides, 10 Tibas and 10 Quiks; one automatic, a 1401
Quik; three with no mileage, all of 1405. A province on all 73, 42 stated
and 31 by the city, three of those a capital alone, read so from the first
by `f82efec`. The line is on every row, and the reader, run again on every
line, gives back the province and its source on all 73. None of the 42
stated rows stands on a district named like a province: on 22 the line's
first part is the capital of the province read, and the other 20 were read
by hand here, not against a source — each a city or county of the province
its line names. Beside run15, a day earlier, 34 listings are in both, every
one with the same line, and one changed source: `bama:hvrfjqui`, «زنجان»,
stated then and by the city now. Beside run14, 32 are in both, and two of
them are lone capitals run14 served as stated: `bama:hvrfjqui`, and
`bama:x5vie8zr`, «کرمان».

**Published.** Promoted on the owner's machine: 74 records in, 73 published,
the one fetch that returned no listing refused by its status, both guards
clean; 60,788 bytes, sha256
`71f196566d09a713886e476f18b4af5ad03e708bd292d74d0ee9bbcb13f7acc1`; no row
carries `location_raw`. Two rows carry a business badge, the first a
published corpus holds, and `seller_type` says `dealer` on both.

**Measured before serving it.** Added alone, run16 changed nothing: 2128
assertions across 15 suites. With `DEFAULT_RUN = "run16"` besides, 30 checks
went red in two suites, where 27 were predicted: the provenance chain's 26
measured rows, their denominators 77 against 73; section 9's reach for a
listing with no province, which run16 does not hold; and three not
predicted. Section 5's control forbade every unchecked phrase in every
match, and went red on `bama:0o9rpjba`, a 1405 Pride with no reading,
matched by «پراید», the Snapp example and the family one — none of which
asks anything of the odometer — and drawn with «کارکرد ثبت‌نشده», as every
surface draws a car with no reading (D67): the phrase UNCHECKED_FA also
gives the mileage. run14's cars with no reading were four Quiks of 1405,
priced past the other examples' budgets and held apart where the mileage was
asked, and an assignment, so no served corpus had put one among the matches
before.

**The decisions.** The owner's, on two questions. Of holding the control to
the constraints a query stated, giving a match with no reading a phrase of
its own, or keeping such a car out of the matches, he chose the first: a
match is checked against the constraints stated and no others (D65), and
what it may never say is that one of those went unchecked. And of
`seller_type` leaving PENDING_LIVE_VALIDATION for SOURCE_BACKED with every
flag `no`, or staying, the first: a real run has produced the only value a
badge can give.

**What was built.** Five commits, on the owner's machine. `abe5809`
publishes run16 byte for byte. `b8bf604` draws section 9's listing with no
province from a temporary artifact, as section 7 draws the odometer grades
no real corpus holds. `4928ef6` holds section 5's control to the constraints
stated, read from the intent as `constraints.judge` reads it and written
again in the suite, so that the two are compared. `948bff7` serves run16:
FIELD_PROVENANCE measured on it by its own procedure, `seller_type` out of
pending in the document and in `eligibility.py`, `document_issue` a dash
again, `gearbox` with two values, and the deploy checklist on
`bama:q571duyy`, a listing in run14 and run16 and unchanged between them.
`80ccb6b` brings the roadmap to run16.

**Measured.** Every suite, mutation and build here ran in a network
namespace with no interface. Each commit is green on its own — 2128, 2128,
2128, 2129 and 2129 assertions across 15 suites, the one more being section
5 checking an answer past k, and 1685 across 12 without the extras at every
step — and the web build is green with its nine routes, the type check clean
and lint with no error and its one warning. Five mutations on the round's
tip, each predicted with the checks it would turn red; the last is counted
out of 2128, run14 giving section 5 one answer fewer past k:

                                                        red   green
    section 5's control back to every phrase              3    2126
    the budget's phrase drawn in every match              5 *  2124
    a listing with no province said as «—»                1    2128
    seller_type pending again                             1    2128
    DEFAULT_RUN back to run14                            26    2102

Four held. The second, marked, turned five checks red where four were
predicted: the cell it added also changed the row section 7 reads. The round
was applied to fresh clones before it was sent, and on the owner's machine
as `abe5809` to `80ccb6b`: all 2129 assertions, and the corpus in the
repository byte for byte the file he promoted. He pushed it to both
repositories.

**The site.** The owner's screenshots of /about at 10:29Z on 2026-10-15
showed 79 decisions, 2128 assertions and 15 suites, which stand together on
`1ebbf4a` alone, committed at 10:26Z and pushed after it. And about five
minutes after `80ccb6b` was committed and pushed, /about, fetched from here,
said 2129 assertions and 79 decisions: a tree that serves run16. Twice,
then, the site was built from a push to `main` within minutes, as
`.github/workflows/ci.yml`, merged from the project holder's pull request on
2026-10-14, says the hosts do. Whether he deployed either by hand in those
minutes was not asked.

**Not measured.** The header's chip and the car page's province cell on the
live site: the page fetched here draws neither until its script runs, and no
screenshot of them was taken. The CI workflow's runs on GitHub, which cannot
be read from here. The Railway that `ci.yml` names as building the API,
where D64 recorded one Vercel project of two services. Why one page answered
and parsed to nothing, in run15 and in run16 alike.

**What this does not settle.** Whether lists and search draw the province is
the owner's to decide, now on a corpus whose every line was read. A new
car's mileage stays unread, so a 1405 with none is a match wherever the
odometer was not asked about. And run16 is one snapshot, as unjudgeable for
an estimator as those before it (D55).

## D81 — The lists draw the province, with how it was read

D80 left to the owner whether the lists and the search draw the province, on
run16, whose every line was read before it was published. He decided on
2026-10-15, of four ways offered: the lists first, in a round of their own,
and the search after, in the next.

**What was built.** Four commits, on the owner's machine. `3c595c2` has
section 7 of the screens suite tell a row held apart from a match by the
payload's `evidence_unchecked`, no longer by how many cells it has: with a
cell added after the price, it would take every match for a row held apart
and every row apart for a match, as an added cell misled it in D80.
`d6ef331` draws the province in a cell of its own in the lists an ungated
corpus serves — search's matched and held-apart tables, and compare's
evidence rows — in the car page's words: «تهران» where the listing names it,
«تهران — از روی نام شهر» where a city's name gave it, «ثبت‌نشده» where there
is none (D77). Drawn so, the card guard turned four checks red, as
predicted, and `province` and `province_source` may now be drawn on a card,
in `eligibility.py` and in FIELD_PROVENANCE; `gate` and `facet` stay `no`.
`ListingCard` and compare's ranked view draw rows that carry no province,
and only a gated corpus serves them; they are as they were. `46490a8` reads
the cell out of search's tables for section 5's queries on the served
corpus, 63 rows, 34 stated and 29 by the city, and out of compare's evidence
rows for one listing of each kind, the one with no province from a temporary
artifact, as section 9 draws it; and the corpus suite holds that every
surface that reads the province reads how it was known — the car page,
search's tables and compare. `f080aab` brings the roadmap to the lists.

**Measured.** Every suite, mutation and build here ran in a network
namespace with no interface. Each commit is green on its own — 2129, 2133,
2140 and 2140 assertions across 15 suites, and 1685, 1689, 1692 and 1692
across 12 without the extras — and the web build is green with its nine
routes, the type check clean and lint with no error and its one warning.
Five mutations on the round's tip, each predicted with the checks it would
turn red, all held; the first two are counted out of 2139, because a list
that no longer reads the source has one check fewer in the card guard:

                                                        red   green
    search's tables pass no source to the label           2    2137
    compare's rows draw the province bare                 2    2137
    eligibility.py: the province off the card again       1    2139
    FIELD_PROVENANCE: the province off the card again     3    2137
    section 7 tells a row's kind by its cells again       7    2133

**In a browser.** The tip, built and served here with loopback alone, drawn
1280 and 390 pixels wide. Search for «پراید» draws 8 of its 53 matches and
holds none apart, and each row's province cell says what the API's row and
the corpus say, 8 of 8 at both widths. Compare of `bama:d1hd97vo`,
`bama:qbgkl0kr` and `bama:q571duyy`, not served, draws three evidence rows:
«تهران», «هرمزگان» and «تهران — از روی نام شهر». Neither page scrolls
sideways at either width; at 390 the table scrolls in its own box, so a
phone shows the province after a swipe, and a label read by the city wraps
to three lines. Of seven predictions six held. The seventh said no page
would log an error, and each logged one: the site's stylesheet from Google
Fonts, which a namespace with no network cannot reach; /about, which the
round did not touch, logs the same.

**The site.** The round was applied to fresh clones before it was sent, and
on the owner's machine as `3c595c2` to `f080aab`, at 23:31Z on 2026-10-15:
all 2140 assertions. He pushed it to both repositories, and both `main`s
were `f080aab` when read here, each commit's tree the one verified. His
screenshot of search at 23:32Z showed the table without the province, from
before the site was built. At 23:36Z a browser on his machine read /about —
80 decisions, 2140 assertions, 15 suites — and in the next minute search for
«پراید», its 8 rows and their labels those drawn here; compare's three; the
car page of `bama:q571duyy`, «تهران — از روی نام شهر»; and the header's
chip, «REAL DATA · ۷۳». The chip and the car page's cell are the two D80
left unmeasured on the live site. A third time, the site was built from a
push to `main` within minutes. And a fetch from here, at about 23:34Z and
again at about 23:42Z, said 79 decisions and 2129 assertions, /about as it
stood on `80ccb6b`: a copy kept somewhere between, not what the site served,
since the browser read 80 and 2140 between the two. A page fetched from here
is not, alone, what the site serves.

**Not measured.** The layout on the live site: the browser that read it
there was not showing the page, and laid it out at no width. The CI
workflow's runs on GitHub, which cannot be read from here. The Railway that
`ci.yml` names as building the API, where D64 recorded one Vercel project of
two services. Why one page answered and parsed to nothing, in run15 and in
run16 alike.

**What this does not settle.** The search does not read the province: a
query that says «در تهران» is the next round, as the owner decided. When it
does, a listing with no province must be held apart, not dropped from the
answer without a word (D65), and run16 holds a province on every row, so
that case stands on a temporary artifact until a corpus brings one. A new
car's mileage stays unread.

## D82 — The search reads the province a buyer names

D81 left the search not reading the province, as the owner had chosen: the
lists first, the search after. Before any change, on `ef0c3d5` with run16
served, thirty-one phrasings of a place after «پراید» — «در تهران»,
«توی اصفهان», «غیر از تهران», «قفل مرکزی» among them, all made here, since
no log of what buyers write exists — each returned the same 53 matches: a
place narrowed nothing. Twenty-seven left nothing under «نفهمیدیم», so the
page read as understood whole, «خودرو: پراید» and the risk profile and not a
word about the place; the four that name a province with « و » in it left a
fragment of the name there, «بلوچستان», «بختیاری» or «بویراحمد». The owner
decided on 2026-10-17, of the ways offered for each of four questions: the
reader takes a province by its full name, with a rule for negation and
nearness; several named are any-of; a province known from the city's name
counts as met, and the table says which (D81) — on run16, of the 18 Prides
in Tehran 15 are known from the city's name and 3 are stated, so counting
the stated alone «پراید در تهران» would have matched 3, held 25 apart and
left out 25, where counting both it matches 18 and leaves out 35; and the
ranked path is left as it is, with a pinned test and the documentation, as
its red lines are (D66).

**What was built.** Four commits, on the owner's machine. `2857ad7` gives
the intent a `provinces`, any one of which meets it, empty unless stated.
`judge` reads it from the listing's own province — `city` on the object the
reader returns — after the odometer and before the red lines: a listing in
one of them meets it, in another breaks it, and with none is held apart,
naming «province», in the words «استان ثبت‌نشده». A province known from the
city's name meets it as a stated one does. The payload, the client's types
and the intent panel carry it, and nothing set it yet. `2f7ff98` is the
reader, and it makes `province` a facet in `eligibility.py` and in
FIELD_PROVENANCE, whose paragraph that held it back until this search
existed now says so. `973a51b` runs the reader on whole corpora and draws
what it gives. `914aea6` pins that the ranked path reads no province, and
brings the roadmap to it.

**The reader.** `read_provinces` takes a province by its full name, as
`PROVINCES` and its one spelling hold it, folded as the parser folds a
query, and as a whole word only. It reads it where it is a place the buyer
wants the car to be in. After a locative — «در», «توی», «تو», «ساکن» or
«استان», with «شهر» or «استان» between — it is read. With nothing before it,
«پراید تهران», it is read too, and the panel says «تهران» را استان تهران
گرفتیم, to be corrected. Several joined by « و », « یا » or «،» are one
group and any-of: «در تهران یا اصفهان». Not read, and listed under
«نفهمیدیم» by hand, since a clause that names a model is otherwise taken as
understood whole: a negation before the name («غیر از», «به جز», «نه»,
«خارج از», «بدون») or after it («نباشه», «نیست», «نمی‌خوام»); a nearness
(«نزدیک», «اطراف», «حوالی», «حومه»); a plate, «پلاک تهران», which says where
a car was registered, not where it is, and no corpus field holds a plate;
«مرکزی» and «گلستان» with no locative, which are ordinary words
(«قفل مرکزی»); and «خراسان» and «آذربایجان» alone, each of which begins the
names of several provinces. No city is read (D74). Five of these rules are
the reader's own, beyond the owner's four decisions, and each only declines,
says that it declined, or inherits: the plate; the negation after the name;
the group, which takes its first name's reading, so that «سیستان و بلوچستان»
is no longer cut at its « و » and «غیر از تهران و اصفهان» declines both; the
two names that begin several; and the locatives «توی», «تو» and «ساکن»,
which change only whether the assumption is drawn.

**Measured.** Every suite, mutation and build here ran in a network
namespace with no interface. Each commit is green on its own, and the web
build is green with its nine routes, the type check clean and lint with no
error and its one warning. Counted for this entry on the base and on each
pushed commit, the totals and the three suites that moved:

                                 base  2857ad7  2f7ff98  973a51b  914aea6
    15 suites                    2140     2153     2224     2305     2311
    12 without the extras        1692     1692     1763     1763     1767
    test_api_contract             251      260      260      316      318
    test_screens                  146      150      150      175      175
    test_ranking                  125      125      196      196      200

The reader was tried first on phrasings made for it: seventeen that name a
province, seven that do not, five negated or near, two ordinary words, then
the plate, the negation after the name and the group. It read 17 of 17, none
of 7, none of 5 and none of 2, and read «پراید در مرکزی», «پراید در گلستان»
and «پراید استان مرکزی»; it declined 5 of 5 negations after the name and 3
of 3 plates, listing each, and listed the two names that begin several. The
51 distinct queries the suites hand the parser parse as before, 51 of 51,
and their 204 answers on the four published runs differ from the answers
before the first commit in one key only, `intent.provinces`, empty: 204 of
204, searched for this entry on `ef0c3d5` and `2857ad7`, and on `ef0c3d5`
twice, to see that an answer is the same twice.

**On whole corpora.** `test_api_contract` asks every published run «در X»
for each of the 31 names and the one spelling, with no model and with each
of پراید, تیبا and کوییک — 512 answers — and counts what each should hold by
plain Python over the artifact, the province present and equal, or absent:
512 of 512 agree. The runs hold the province none, some and all of the way,
and the rule's three answers all occur. D81 left the case of a listing with
no province standing on a temporary artifact, run16 holding a province on
every row; the other published runs bring it, and the tests now run on them.
«پراید در تهران» comes out:

            Prides  matched  apart  left out  province held
    run16       53       18      0        35       73 of 73
    run14       56       14      1        41       75 of 76
    run13       54        3     31        20       34 of 74
    run11       56        0     56         0        0 of 75

Three province queries on each run go through the checks the search box's
examples get: no car shown breaks a constraint stated, each car held apart
names what it lacks, and a car with neither a price nor a province is held
apart naming both, the price first, on run13 and run14. On run11 nothing
matches and every Pride is apart; on run16 nothing is.

**Mutations.** Forty-nine, one change to the code each, run on the tip of
its commit. The predictions file named the kinds for the first two commits,
and each of the last twenty with the checks it should turn red, before it
ran. All but one turned something red. The first twenty-nine are eleven
against the judge, the payload and the types — among them a missing province
counted as met, the field read under a name the reader does not use, and the
key missing from the Python literal or from the TypeScript union — and
eighteen against the reader, one rule or one input taken out at a time, with
the facet flag moved in the code and not in the document, and the reverse.
Each was red in the suite that guards it, and three in `tsc` as well. The
last twenty were run on the tree before their commit too, to see what the
new tests add:

    commit 3, against the tree before it                  red   before
    the answer ignores the province named                  39        0
    the reader gives no province known from a city         21        2
    the parser's spelling table goes unused                 4        0
    the panel hides what was not understood                 2        0
    the panel hides the assumptions                         1        0
    a held-apart row omits the province it lacks            2        0
    a missing province counts as met                       28        4
    another province counts as unknown                     34        4
    only the first of several provinces counts              4        1
    the province is judged before the price                 4        1
    a plate is read as a place                              1        0
    a bare name leaves no assumption                        1        0
    a negation cue is no cue                                1        0
    the intent drops its provinces                          2        0
    commit 4, against the tree before it
    a Row gains a province field                            1        0
    `_passes` drops a row that has none                     4        0
    `_passes` drops a row that has another                  0        0
    the relaxation ladder drops the provinces               1        0
    a published corpus is built gated                       6        6
    the ranked path empties its list on a province          1        0

Nine of the fourteen on the third commit are green before it, two of them a
gap older than this round, closed by the way: no test drew the panel's
assumptions or its «نفهمیدیم» from a real answer. The reader giving no
province known from a city's name was red before as well, in two of D81's
checks that say none was drawn; the oracle now names the cars that differ.
The one that stays green, `_passes` dropping only a row that has a province
not among those named, is an equivalent mutant today: no Row has one, so
nothing can see it, and the pin turns red the day a Row gains the field,
which is when it would begin to matter.

**In a browser.** The tip, built and served here with loopback alone, drawn
1280 and 390 pixels wide, on run16 and on run13. On run16 «پراید در تهران»
draws «استان: تهران» in the panel and 8 of its 18 matches, none held apart,
each row's province cell what the API's row says, 8 of 8 at both widths;
«پراید تهران» adds the assumption; «پراید غیر از تهران» and
«پراید پلاک تهران» draw their phrase under «نفهمیدیم», with no «استان» line
and the 53 matches of «پراید» alone. On run13 «پراید در تهران» draws its 3
matches and 8 of the 31 held apart, each saying «استان ثبت‌نشده» inside its
table's own box, 8 of 8; «در تهران» draws 5 and 8 of 40. No page scrolls
sideways at either width, and at 390 each table scrolls in its own box. Each
page logged one error, the stylesheet from Google Fonts, which a namespace
with no network cannot reach.

**Predictions.** The file written before the first change made 24: the first
commit's four, the reader's ten, the corpora's four and their mutations, the
pin's one and its mutations, and the three of the whole round. Twenty held.
Four held in part. A TypeScript `Intent` without the field was to turn red
in the contract suite alone, and turned `tsc` red too, since the panel reads
the field. The reader giving no province known from a city's name was to be
green on the tests before the third commit, and two of D81's checks were red
on it. A strict `_passes` was to turn two checks red and turned three, since
with no row left at any step the ladder walks to its end and the spec that
comes back differs; and the check that no published corpus is ranked was to
be among the six that a gated one turns red, and is not, since an older
check in section 6 stops the suite first. The reduced count at the end,
1767, was one under the 1768 to 1842 stated. The point values missed, in
both directions: +27 expected of the first commit and +13 measured, +104
expected of `test_ranking` in the second and +71 measured, +68 expected of
the third and +81 measured, and 2167, 2271, 2339 and 2345 expected at the
four commits against 2153, 2224, 2305 and 2311, every total inside its
stated range but for that one.

**Found, and not fixed.** Section 6 of the contract suite reads
`r.fault.code` for the detail of a check, and a published corpus that is
gated has no fault, so the suite stops there with an `AttributeError`: under
that one mutation section 18 never runs in the full suite. Alone it is green
on the clean tree and red under the mutation, with the message that says
what to decide first. It is an older suite's fault, and whether it gets a
commit of its own is the owner's to say. The reader's own limits are in the
roadmap, and were tried on the tip: «پراید خلیج فارس» reads «فارس» as the
province, since the name is read wherever it stands; «پراید در مشهد» reads
no province and says nothing, a city in a clause that names a model being
dropped without a word, which is the clause rule's fault and not this
reader's; and «پراید در تهرانپارس» reads no province and adds the model
`pars`, the alias being a substring.

**The site.** The round was applied to fresh clones before it was sent, at
11:16Z on 2026-10-17: each commit's tree the verified one, each commit green
on its own, the script refusing on a modified tree, on a `git am` in
progress and on a tree outside the chain, and resuming after each of the
first three commits. On the owner's machine it ran as `2857ad7` to `914aea6`
at 11:20Z, all 2311 assertions, the build's nine routes with no error, four
commits ahead of `origin/main`. He pushed it to both repositories, and both
`main`s were `914aea6` when read here between 11:22Z and 11:28Z, tree
`d53b4f1`, four commits ahead of `ef0c3d5`, each authored and committed by
him alone. The `ci` workflow's run on `914aea6`, number 8, was created at
11:21:56Z and finished green in 1 m 13 s; the push of four commits made one
run, on the last, and all eight runs the workflow has had are green. The
site was built from the push within six minutes, a fourth time: a browser on
the owner's machine read /about at no later than 11:28Z — 81 decisions, 2311
assertions, 15 suites — and then search. «پراید در تهران» read 73 checked,
63 appraisable and 18 matching, «استان: تهران» in the panel, and in the
first eight rows «تهران» on two and «تهران — از روی نام شهر» on six, label
for label and in order as drawn here. «پراید تهران» read the same 18 with
«تهران» را استان تهران گرفتیم. «پراید غیر از تهران» read 53 matches, no
«استان» line, and «غیر از تهران» under
«بخش‌هایی که نفهمیدیم — نادیده گرفته شدند، حذف نشدند», the table holding
Tehran and also Isfahan, Hormozgan and Alborz.

**Not measured.** How buyers write a place: the phrasings are made here, and
what they show is that the rules do what they say, not that they meet what
buyers write. The layout on the live site at 390 pixels: the browser that
read it there reported a viewport of no width, as in D81, and one screenshot
of its table at about 800 pixels shows the province column whole,
«اصفهان — از روی نام شهر» on one line. The CI run's log, whose assertion
count was not read, only its status. And, from D81, the Railway that
`ci.yml` names as building the API, where D64 recorded one Vercel project of
two services, and why one page answered and parsed to nothing, in run15 and
in run16 alike.

**What this does not settle.** The ranked path reads no province, and only
the synthetic corpus is ranked today. There «۲۰۶ زیر ۸۰۰ میلیون در تهران»
lists «استان: تهران» in the panel and returns the same six cars as without
it, which is pinned; the pin turns red the day a `Row` carries a province,
`_passes` reads one, or a published corpus is gated, and its message says to
decide first (the roadmap, item 2). A city is not read: «پراید در مشهد»
narrows nothing, and the roadmap's third item says what else the reader
leaves.

## D83 — The Gulf is not a province, and the cities are measured

D82 closed with three things found and not fixed. Section 6 of the contract
suite stops with an `AttributeError` when a published corpus is ranked, so
that section 18 never runs in the full suite. «پراید خلیج فارس» reads «فارس»
as the province, since the name is read wherever it stands. And a city, in a
clause that names a model, is dropped without a word. The owner decided on
2026-10-17, of the ways offered for each: the crash gets a commit of its
own, in the test only; the Gulf becomes a name the reader knows holds a
province's and is not one; and the cities are measured first, with nothing
in the tree changed. After the measurement he chose, of the two rules tried
on them, the cue rule — a cue the reader already knows is listed with the
word after it — to be built in the next round, after its predictions are
written, and asked for three things the measurement turned up to be measured
next, before anything is built for them. None of the four is in this entry's
commits.

**What was built.** Two commits, on the owner's machine. `3695f0c` guards
the two expressions in section 6 that read the fault of a refusal:
`r.fault.code`, which is also the detail of its check and so is evaluated
whether the check passes or not, and `r.fault.still_available`. They are
guarded the way the file's other uses of `.fault` already were, and no check
is added or removed. `6300b82` makes «خلیج فارس» a name the reader knows
holds a province's and is not one. It stands in the alternation of names,
longest first, so the «فارس» inside it is never matched alone, and it is
declined where the families «خراسان» and «آذربایجان» are, whatever stands
before it, and listed under «نفهمیدیم» with what stands before it:
«خلیج فارس», «در خلیج فارس», «غیر از خلیج فارس». «فارس», «در فارس» and
«استان فارس» are read as before. Its tests are, in `test_ranking`, four rows
of «named, and not read», three of «read» that must stay and one group
beside a name that is read, and in the contract suite two checks over the
four published runs. The roadmap drops its bullet that the Gulf is read, and
says what still is.

**Measured.** Every suite, mutation and build here ran in a network
namespace with no interface. Each commit is green on its own, the suites and
the web build with its nine routes, and so is the Gulf commit applied alone
on the base, without the first. Counted for this entry on the base and on
each pushed commit, the totals and the two suites that moved:

                                 base   3695f0c   6300b82
    15 suites                    2311      2311      2321
    12 without the extras        1767      1767      1775
    test_api_contract             318       318       320
    test_ranking                  200       200       208

**The crash.** Reproduced first, on `88beef9`, with the one mutation that
builds a published corpus gated: 6 checks red and 93 green, and then
`AttributeError: 'NoneType' object has no attribute 'code'` at line 453,
with section 18 never reached. With both expressions guarded the suite runs
to its last line: 254 green and 58 red, in sections 2, 3, 5, 6, 11, 13, 15
and 18, the last of them section 18's «no published corpus is ranked», with
the message that says to decide first. Each guard is needed: with the old
expression of 453 put back the suite stops at 453, and with the old
expression of 456 put back it stops there, one more check red before it. The
check still bites: with the API's gate code renamed, the two checks of the
gate are red, before the fix and after it, and nothing crashes. Without the
mutation the count is unchanged, 2311.

**The Gulf.** Fifteen phrasings of the Gulf and what stands near it, made
here, were run on the base and on `6300b82`. The nine that hold «خلیج فارس»
changed. Eight of them were read as the province فارس, with «فارس» را استان
فارس گرفتیم in the panel — «غیر از خلیج فارس» and «ساحل خلیج فارس» among
them, and the two with a second name, «در تهران و خلیج فارس» and
«خلیج فارس و تهران» — and none is. The ninth, «خلیج فارس نباشه», was never
read, and is now listed whole where it listed «فارس نباشه»; the commit
message counts the nine together. The six that do not hold it did not
change: «فارس», «در فارس», «استان فارس», «فارسی», and the two spellings
left, «خلیجفارس» with no space, which matches nothing, and «خلیجِ فارس» with
a kasra, which is read as the province, since a diacritic is not stripped.
The five manufacturers' names that hold a province's, «کرمان موتور»,
«یزد خودرو», «گیلان خودرو», «مازندران خودرو» and «کرمان خودرو», are read as
the province, bare, with the assumption shown, before and after: the same
kind as the Gulf, not asked for, and left. The 51 distinct queries the
suites hand the parser parse to the same intent in every field, 51 of 51,
the rows of D82's battery are the same, and «پراید در X» for the 31
provinces reads 31 of 31. On the four published runs «پراید خلیج فارس» gives
the answer «پراید» gives, states no province, and leaves the phrase under
«نفهمیدیم». Applied alone on the base the commit gives 2321 across 15 suites
and 1775 across 12.

**Mutations.** Five, one change to the code each, run on the tip of the Gulf
commit. The predictions file named each, and the suite that should turn red,
before it ran. All five turned something red, and the table says where:

    on the tip of 6300b82                         ranking  contract
    the Gulf is not among the names                     5         2
    the Gulf is found and read as the province          4         2
    the Gulf is read after a locative                   2         0
    the Gulf is declined and not listed                 3         1
    Fars alone is declined too                          5         4

The third is red in `test_ranking` alone: the contract suite's one check has
no locative in it, so a Gulf read after «در» is seen there only by the unit
tests.

**The cities.** Measured with nothing in the tree changed. A copy of
`ranking.py`, with one line added in memory to keep what the parser computes
on the way and throws away, returned the parser's own intent on 531 inputs
of 531. Two rules were tried over what the parser leaves, both written down
before either ran. The residue rule lists every run of adjacent words left
in a clause once the model names, the spans the parser acted on, the
province names and the digits are blanked, less a stoplist built from the 51
queries alone: six words that are no request, «ماشین», «برای», «یه», «با»,
«دارد» and «میخوام». The cue rule lists a cue the province reader already
knows — «در», «توی», «تو», «ساکن», «اطراف», «حوالی», «حومه», «بجز», «پلاک»,
«نزدیک», «نزدیکی», «غیر», «به جز», «خارج از» — with the one or two words
after it, past «استان» or «شهر», that are not digits, model names, acted
spans or provinces. Thirty-five cities, none a province's name, in ten
placements beside «پراید» made 350 phrasings: «در X», bare, «ساکن X», after
a comma, «توی X», «نزدیک X», «غیر از X», after a budget as in
«تا ۳۰۰ میلیون در X», first before «پراید», and alone before a comma. The
list first held 36. «همدان» is a province's name, which the reader reads,
and the first run, of 360, counted 12 under «نفهمیدیم», two of them
«نزدیک همدان» and «غیر از همدان», which the reader declines. It was found
after that run and before any prediction was scored; the run was repeated on
the 35, which are the numbers here, and the first output is kept.

Today the city is under «نفهمیدیم» in 10 of the 350: five names of more than
six characters, in the two placements where the city is a clause of its own.
The other 340 are dropped without a word: 245 because the clause names a
model and is taken as understood whole, 60 because the clause is six
characters or fewer, and 35 because the budget clause takes everything after
its amount, the city with it. The residue rule shows the city in 315 of the
350 (90%): the 10 seen today and 305 more, in every placement but the
budget's. The cue rule shows it in 220 (62.9%): the 10 seen today and the
210 of the six placements that hold a cue, where the three that leave the
city bare and the one after a budget add nothing. Four names that hold
something the parser acts on as a substring — «شاهین‌شهر», which adds the
model `shahin`, «پارس‌آباد» and «تهرانپارس», which add `pars`, and «شهریار»,
which sets a commute use — made 40 phrasings in which neither rule shows the
city, 0 of 40; the residue rule lists a fragment, «شهر», «آباد» or «ار», and
every one of the 40 changes the intent in a field the buyer did not write.

    the city is listed as not understood       n  as is  residue   cue
    35 cities in 10 placements               350     10      315   220
    4 names that hold an alias or a cue       40      0        0     0

What each rule adds elsewhere is counted on the 51 queries the suites hand
the parser, and on 60 ordinary sentences made here, with no city in them and
none used to build the stoplist:

    queries that gain an item               n  residue   cue
    the 51 the suites hand the parser      51        6     0
    60 ordinary sentences, no city         60       44     3

With an empty stoplist the residue rule adds an item to 16 of the 51. With
the six words it adds one to 6: «خوب» twice, «قطعات ارزون», «کم کارکرد»,
«مشکی», and «زیر» with «هزار کیلومتر» from
«۲۰۶ زیر ۱۰۰ هزار کیلومتر، بودجه ۹۰۰ میلیون», which is a request the parser
dropped (under «Found, and not fixed»). The cue rule adds nothing to the 51.
On the 60 sentences the residue rule lists something on 44 (73%), 48 items,
0.8 a sentence. By hand, 11 of the 48 are function words, politeness or the
rest of a request the parser did read — «سلام» twice, «توی», «در», «یا»,
«اگه امکانش هست», «قیمت», «در شهر», «نفره», «مناسب» and «توی بودجه ام باشه»
— and the others are requests the parser ignores: a colour, a trim, a body
type, a condition. The cue rule lists something on 3 (5%), «در حد نو»,
«در حال حاضر» and «توی بودجه ام», and a stoplist of three words, «حد», «حال»
and «بودجه», would silence them. None of what either rule adds names a
place, since the 111 queries hold no city. What the numbers inform is
therefore less the cities than what the page says of the rest of a sentence:
the residue rule gives up the contract that a clause which names a model is
understood whole, and the cue rule keeps it and adds a cue. Against the
assertions that stand, the residue rule turns 6 red, all in `test_ranking` —
it lists «خوب», «قطعات ارزون», «باشه» and «پلاک ملی» where the tests say
nothing is left, and a second word beside «مرکزی» and «گلستان» — and the cue
rule turns 1, «پراید پلاک ملی در تهران», whose «پلاک ملی» it lists. The
other 14 suites are green under both.

**Found, and not fixed.** Three more ways the parser drops words without a
word, each tried on the real parser and measured no further. A distance with
no «کارکرد» before it is not read and not listed:
«۲۰۶ زیر ۱۰۰ هزار کیلومتر», «پراید کمتر از ۵۰ هزار کیلومتر» and
«پراید ۵۰ هزار کیلومتر» all give no `max_mileage_km` and nothing under
«نفهمیدیم», where «۲۰۶ کارکرد زیر ۱۰۰ هزار کیلومتر» gives 100000, because
the regex wants the word before «زیر», «تا» or «کمتر از»; `test_ranking`
calls the first of the four, with its budget, an explicit km cap, and pins
the budget alone. The budget clause takes everything after its cue up to the
next «،» once it holds an amount, so a word after the amount goes with it:
«تیبا تا ۲۰۰ میلیون سفید» gives the budget and nothing under «نفهمیدیم», and
«پراید تا ۳۰۰ میلیون در مشهد» gives 2 matches and 3 apart on run16 with the
city nowhere on the page. And a cue or an alias is matched inside a longer
word: «محدوده» holds «حدود» and makes the budget flexible, «شهریار» makes a
commute, «بارفروش» a cargo use, «سودان» a resale and «بچه‌دار» a first
family car, each with its assumption on the page, and the aliases do the
same in «شاهین‌شهر», «پارس‌آباد» and «تهرانپارس». On run16 a city the parser
drops changes nothing: «پراید در مشهد», «پراید در شیراز» and «پراید کرج»
each answer with the 53 matches of «پراید» alone, no province, nothing under
«نفهمیدیم». From CI, not read for more than the notices: run 10's
annotations announce that the `ubuntu-latest` label moves to Ubuntu 26 from
2026-10-19, and warn that actions on Node 20 are forced to Node 24.

**Predictions.** The file written before anything was run or changed made
21: the crash's six, the Gulf's seven and the cities' eight. Eighteen held.
Three held in part. The five Gulf mutations were each to turn red in both
suites; four did, and the Gulf read after a locative turned red in
`test_ranking` alone, for the reason above. The stoplist built from the 51
was to hold about 13 words (8 to 22) and holds 6. On the 60 held-out
sentences the residue rule was to list something on 52 (87%; 75 to 95%), 1.7
items a sentence (1.2 to 2.6), and listed on 44 (73%), 0.8 a sentence: fewer
than stated, with a shorter stoplist. The point values missed, inside their
ranges: 58 checks red under the gated mutation where 35 (12 to 90) were
stated; the residue rule with no stoplist on 16 of the 51 where 19 (14 to
26), and with the six words on 6 where 9 (5 to 14); the cue rule on 3 of the
60 (5%) where 5 (8%; 3 to 15%). Two predictions were amended before anything
ran: the count under the gated mutation, written before section 13's loops
had been listed, and the count on the 51, from a loose reading. And one
input was wrong: the file said no city on the list is a province's name, and
«همدان» is.

**The site.** The entry before this one, D82's own commit `88beef9`, was
pushed at 21:42Z on 2026-10-17: its run, number 9, was created at 21:42:58Z
and finished green in 1 m 21 s, and a browser on the owner's machine read
/about between 21:43:50Z and 21:44:11Z — 82 decisions, 2311 assertions, 15
suites — at most 1 m 13 s after the push. The two commits here were applied
to fresh clones before they were sent, at 22:17Z: each commit's tree the
verified one, each green on its own, the script refusing on a modified tree,
on a `git am` in progress and on a tree outside the chain, and resuming
after the first commit. On the owner's machine they ran as `3695f0c` and
`6300b82` at 22:24Z, all 2321 assertions, the build's nine routes with no
error, two commits ahead of `origin/main`. He pushed them to both
repositories, and both `main`s were `6300b82` when read here at 22:29Z, tree
`fd6adac`, two commits ahead of `88beef9`, each authored and committed by
him alone, six files with 69 lines added and 16 removed and no change of
mode. The `ci` workflow's run on `6300b82`, number 10, was created at
22:26:46Z and finished green in 1 m 12 s; the push of two commits made one
run, on the last, and all ten runs the workflow has had are green. The site
had it at the first read, 3 m 23 s after the run was created: the same
browser read /about at 22:30Z, 82 decisions, 2321 assertions and 15 suites.
«پراید خلیج فارس» read 73 checked, 63 appraisable and 53 matching, as
«پراید» alone does, with no «استان» in the panel and «خلیج فارس» under
«بخش‌هایی که نفهمیدیم»; «پراید در فارس» read 2 matching and «استان: فارس».

**Not measured.** How buyers write a place: the cities, the placements and
the 60 sentences are made here, and what they show is what a rule does, not
what a buyer writes. Whether a person is helped or put off by the extra
lines of the residue rule: no one has read a page with them. How often a cue
is followed by a word that is no place, beyond the 3 of 60 found: the 60 are
few. The live site beyond /about and the three searches read. The CI run's
log, whose count was not read, only its status, and what the move of
`ubuntu-latest` to Ubuntu 26 does to it. And, from D81, the Railway that
`ci.yml` names as building the API, where D64 recorded one Vercel project of
two services.

**What this does not settle.** A city is still dropped without a word:
«پراید در مشهد» narrows nothing and the page says nothing of it. The cue
rule, when it is built, will add the city in the six placements that hold a
cue and in none of the others: not the bare ones, and not the one after a
budget, where the budget clause takes the city first, the second of the
three findings above. It adds none of the four names that hold an alias or a
cue. It does not change the ranked path, which reads no province and is
pinned (D82). The Gulf is declined; its spelling with no space and with a
kasra is not, and a province's name inside a manufacturer's is still read as
the province.

## D84 — What the parser dropped is seen, and a floor is only a floor

D83 closed with the owner's choices of 2026-10-17: the cue rule for the
cities, to be built in a round of its own with its predictions written
first, and three things the parser drops without a word — a distance with no
«کارکرد» before it, whatever follows a budget's amount, and a cue or a
model's name matched inside a longer word — to be measured before anything
was built for them. Building the third turned up a fourth, older than all of
them: the budget floor. This entry records the nine commits that came of
them, pushed by the owner in four pushes on 2026-10-17 and 2026-10-18, and
what each push did on CI and on the site. Each commit was prepared away from
his machine, applied there with `git am` from a script that checks the state
it starts from, and rehearsed first on fresh clones of the repository; each
is authored and committed under his name and no other.

    commit    what it does                                    15 suites  12
    105bad4   a cue the reader knows is listed, with its words     2377  1831
    9bda56d   a distance cap is read without «کارکرد»               2448  1902
    9623ec3   a place after a budget's amount is listed             2475  1929
    e1eff8c   a model's number is one only where it stands alone    2520  1974
    d053acb   the roadmap names the budget floor's faults           2520  1974
    4826748   both CI jobs pinned to ubuntu-24.04                   2520  1974
    cddefb7   a floor is an amount of money right before «به بالا»  2577  2031
    d34ce32   a floor is not also the ceiling                       2608  2062
    831b28e   the roadmap names what the floor reads and leaves     2608  2062

Counted again for this entry on a fresh clone of `Tecso-Dev/caro`, each
commit in a worktree of its own, under `unshare -n`: every one is green on
its own, at the counts in the table, the ones each code commit's message
states.

**The cities** (`105bad4`). A clause that names a model is taken as
understood whole, so «پراید در مشهد» dropped the city: of D83's 350
phrasings of 35 cities, 10 were listed under «نفهمیدیم» and 340 were not. A
cue the province reader already knows — «در», «توی», «تو», «ساکن», «اطراف»,
«حوالی», «حومه», «بجز», «پلاک», «نزدیک», «نزدیکی», «غیر», and the pairs
«نزدیک به», «نزدیکی به», «غیر از», «به جز», «خارج از» — is now listed with
the one or two words after it, past «شهر» and «استان», after everything else
in `unparsed`. Model names, the spans the parser acted on, province names
and digits are blanked first, so «غیر از تیبا» and «در تهران» list nothing,
and «حد», «حال» and «بودجه» are never the word, so «در حد نو» and
«در حال حاضر» list nothing either. Nothing is read from what is listed: the
spec is the same in every field but `unparsed`, and the old list is a prefix
of the new one. Of D83's 350 the city is shown in 220, as D83 measured for
the rule, and in none of the 40 phrasings whose names hold an alias or a
cue; of 300 more, twenty cities in fifteen placements with «شهر», «استان»,
the pairs and «پلاک ملی در», in 300. None of the 51 queries the suites hand
the parser gains an item, nor any of 60 ordinary sentences. On the 906
inputs of the measurement and 40000 generated ones, the lists are those of a
separate copy of the rule kept outside the repository. What stays dropped is
pinned by tests: a city no cue stands before, a city after a budget (the
next paragraph but one), a second city after « و » or «یا», and «نه» and
«بدون».

**A distance cap** (`9bda56d`). «۲۰۶ زیر ۱۰۰ هزار کیلومتر» was neither read
nor listed: the odometer wanted «کارکرد» before the cap. Of 20 caps written
for the measurement none was read. Four more shapes are read now when the
«کارکرد» form finds nothing: a cap word, a figure and a distance word; the
figure first, with «یا کمتر», «و کمتر» or «به پایین»; the distance word
first; and «زیر ۱۰۰k». «حداکثر» joins the «کارکرد» form. With neither «هزار»
nor «کارکرد» before it, a figure is a cap only from 10000 on, because
nothing else says it is an odometer: «تا ۱۰۰۰ کیلومتر دورتر از تهران» is a
distance to travel and «وانت تا ۱۵۰۰ کیلو بار» a weight, and of 8 such
phrases a floor of 1000, the one the «کارکرد» form uses, would have read 7.
Of the 20 caps 19 are read and none wrong, and none of 12 phrases that hold
a distance and are no odometer, 8 that give a figure and no cap, or 3 that
are vague. One of the suites' 51 queries changes:
«۲۰۶ زیر ۱۰۰ هزار کیلومتر، بودجه ۹۰۰ میلیون» gets its cap. A stated cap is
read before the vague «کم‌کارکرد», as the «کارکرد» form always was, so the
default is not adopted and its note is not shown: on 430 of 29855 generated
inputs that is the only change, in `assumptions`.

**A place after a budget** (`9623ec3`). The budget clause runs to the next
«،», so «پراید تا ۳۰۰ میلیون در مشهد» lost the city: of 35 cities written
after a budget none was listed. What follows the amount is now handed to the
cue rule as one more clause, for a cue and no more, and cut the way the rest
of the query is; the budget and every other field are as they were. All 35
are listed, under each of «تا», «زیر», «حداکثر», «بودجه», «قیمت» and
«کمتر از», and none of the 51 queries nor of 120 ordinary sentences changes.
The first version listed «در مشهد مدل» where a year clause followed; the cut
came from writing the tests, before anything was committed. Of 9072 inputs
written for the year clause, 1134 differ from the version without the cut,
and in 108 of them the old floor rule had read «از ... به بالا» in
«شیراز مدل ۱۴۰۱ به بالا» as a budget floor: the fourth thing, below.

**A model's number** (`e1eff8c`). The parser looked for each model's number
as a substring of the query, so «دنا تا ۱۳۱۰ میلیون» added `pride` (131 is
Pride's) and «تیبا مدل ۱۴۰۵» added `405`: of 2901 budgets «تیبا تا N میلیون»
54 added a model nobody wrote, and of 26 years «تیبا مدل Y» one did. A
number is now looked for in the query less its amounts of money, and not
beside another digit; a name is matched as ever. None of the 2901 and 26
adds a model now, the 45 uses of a number as a model written for the
measurement are all read, and the 18 amounts and years that hold a model's
number give the models written. The rule as first written also took out the
clause the budget cue had consumed, and lost «تا ۳۰۰ میلیون ۲۰۶»: of 2160
inputs with a number after the budget, that rule read the models on 432 and
this one on all 2160. No input of the measurement put a number after the
budget; it was found while the tests were written.

**Letters beside a word — measured, and left.** A cue or an alias is still
matched inside a longer word: «محدوده» sets a flexible budget, «بارفروش» a
cargo use, «پارس‌آباد» the model `pars`. Which letters may stand beside a
word is a choice about Persian, not a measurement, and the three ways
measured are in the roadmap's item 4 with their numbers; on 2026-10-18 the
owner chose to leave all three unbuilt.

**The budget floor** (`d053acb`, then `cddefb7`, `d34ce32`, `831b28e`). The
text between «از» or «بالای» and the first «به بالا» went to `parse_amount`,
which takes a bare number for millions. «از» also ends many words and is the
word of «غیر از», and «به بالا» also ends a year clause, so
«پراید از مدل ۹۸ به بالا» set a floor of 98,000,000: of 35 such phrases,
five years after seven lead-ins, 35 set a floor, at the tip and at `cac054b`
alike, so the fault is older than this work. With words between a «از» and
an amount, the amount that was the budget became the floor: of 128 phrases
written to show it, 128 set one. And a floor's amount was taken for the
ceiling too whenever no clause named one, so «پراید از ۴۰۰ میلیون به بالا»
had 400,000,000 for both and matched none of run16's 53 Pride listings.
`d053acb` recorded the faults in the roadmap and changed nothing. Three
measurements followed, each in memory on the tip and with its predictions
first: the faults themselves; three changes of the old expression; and seven
expressions tied to the words around them. The owner chose on 2026-10-18, of
the ways offered: a floor tied to its words, in two commits, one for the
floor and one so that it is not also the ceiling; «بالای X» without
«به بالا» left a ceiling, as it is, and recorded with its numbers; and four
more topics, each a round of its own.

`cddefb7` reads a floor only as a cue («از» or «بالای», and not the end of a
word), an amount of money and «به بالا», with nothing between them, or the
same before a year clause with its own «به بالا». None of the 35 and none of
the 128 sets a floor now, and «پراید از مدل ۱۴۰۱ به بالا» matches 1 of
run16's 53 Pride listings, as «پراید مدل ۱۴۰۱ به بالا» does. `d34ce32` reads
the floor first and lets the budget cues and the lone amount read the query
with the floor's phrase blanked out: of 144 phrasings of a floor, all 144
had its amount for the ceiling and 96 printed
«عدد قیمت را سقف بودجه فرض کردیم»; none does now, and floor and ceiling are
both as meant on all 144, where they were on none. On run16
«پراید از ۴۰۰ میلیون به بالا» matches 47 of the 53 (3 have no price, 3 are
below it) and «پراید از ۲۰۰ میلیون به بالا» 50. Of the 16378 queries written
for the checks of the last three changes, 162 differ from before, each in
the floor alone, and none of the 171 the suites and the measurements hold.
`831b28e` records in the roadmap what is read and what is left.

What the tie costs is a choice, and it is recorded with its numbers. Of 572
phrases written for the last measurement the floor changes on 272: on 128 it
was the budget or an odometer's figure and is none now, and on 144 it was
right by accident and is no longer read — a word between the cue and the
amount (96), the «از» that ends a word (24), and the lower end of a range
with a year clause (24). In the first two the amount that was the floor is
the ceiling now: the meaning reversed. A negated floor,
«پراید از ۴۰۰ میلیون به بالا نباشه», had a floor and a ceiling of 400
million and has the floor alone: wrong before and after, and the ceiling it
had right by accident is gone. Each is pinned by a test, and the four topics
the owner queued — other words for a floor, the bare «X به بالا», ranges,
and the negated floor — are in the roadmap with what was measured for each.

**The CI pin** (`4826748`). GitHub moves the `ubuntu-latest` label to Ubuntu
26.04 from 2026-10-19, and the runs' annotations said so twice on each run.
Both jobs name ubuntu-24.04 now, so that a move to the new image is a change
made on purpose, in a commit and a run of its own; nothing else in the
workflow changed. The two notices are gone from the runs after it; the three
warnings that remain — Node 20 deprecated for the checkout, setup-node and
setup-python actions, and a custom font at `webapp/web/app/layout.tsx` line
29 — are older and not acted on.

**Mutations.** Each change to the parser was mutated before it was
committed, one change to the code at a time, with the tests run against each
mutant. The cities: of 38 mutants 35 turned something red, and the three
that survived — province names left unblanked, a one-letter word taken, and
a mark inside a pair ignored — were caught once a row was added for each.
The distance cap: 25 of 25. The place after a budget: 10 of 14; of the four
that survived, three differ from the commit on none of the 47630 inputs
measured, and the fourth, a cut joined with nothing instead of a space,
differs on 432, all with a year clause flush against text on both sides, and
no row pins it. The model's number: 7 of 7, after two rows were added for
two that survived the first run. The floor: of 28 distinct mutants of its
two commits 23 turned something red; the 5 that survive, each green under
all 15 suites, are named with the reason in the round's measurement, and no
row was added after the run to catch them. The first four were run against
all fifteen suites, and none of their mutants turned anything red outside
`test_ranking`; the floor's were run against `test_ranking`, and its
survivors against all fifteen.

    on the site, 2026-10-25, run16       read as                     matched apart
    «پراید از ۴۰۰ میلیون به بالا»        floor 400 M, no ceiling          47     3
    «پراید از ۲۰۰ میلیون به بالا»        floor 200 M, no ceiling          50     3
    «پراید از مدل ۱۴۰۱ به بالا»          year 1401, no floor               1     0
    «پراید در مشهد»                      «در مشهد» listed                 53     0
    «پراید تا ۳۰۰ میلیون در مشهد»        ceiling 300 M, «در مشهد» listed   2     3
    «۲۰۶ زیر ۱۰۰ هزار کیلومتر»           cap 100,000 km, model 206         0     0
    «دنا تا ۱۳۱۰ میلیون»                 ceiling 1,310 M, Dena alone       0     0

**As pushed.** D83 itself, `cac054b`, was green on CI in 1 m 15 s, and its
`/about` read 83 decisions two minutes after the run began. The four pushes
since ran CI once each, on the tip of the push, on both repositories, and
every run succeeded; no commit inside a push has a run of its own, so the
counts of those five are the ones measured here. The site was not read after
the first two pushes, and after the pin's only for two of the floor's
queries. After the last it was read on 2026-10-25: `/about` says 83
decisions, 2608 assertions and 15 suites, and the search reads the queries
of the table as the commits say, on run16, the corpus it serves, which no
estimator has cleared, so it shows evidence and no ranking. Before the
floor's push the same site had read the first query of the table with a
floor and a ceiling of 400 million, the note printed and none of the 53
matched, and the third with a floor of 1,401,000,000. Two things the roadmap
listed as not checked on the live site were read on the same day: the
contact page says its inbox is off and links to the repository's Issues, and
`/api/contact/status` answers that it is closed; and the car page draws the
province with how it was read, «تهران — از روی نام شهر» on `bama:6gxzhlq8`.

**What the predictions got wrong.** Every round wrote its predictions down
before it ran; these are the ones that missed. Of the cities', the mutants
were predicted all red, and three survived until a row was added for each.
Of the second package's, a count was off by one; the first build changed
`assumptions`, which the prediction had left out (the 430 above); two builds
together changed `unparsed` on 535 of 62392 inputs where the prediction said
no build alters what another does — the cap the first reads is blanked out
of the second's tail; the new rows numbered 143 where 99 were predicted; the
mutants of the place were predicted all red and four survived, and two of
the number's survived until rows were added; and twice the inputs written
for a rule were blind to a shape the build mishandled (the cut and the
number after a budget), found both times while the tests were written. Of
the floor's: a denominator taken without counting the priced listings, and a
bound that was a guess; a flaw in one candidate's leftover unit that moved
figures in four predictions, a clause cut at « و » that moved a fifth, a
sentence about two candidates that was wrong, and inputs missing for the
wide expression; one sentence that lacked "except at the tip"; and in the
build, a mutant predicted to be caught by one row was caught by four. The
base of the floor's rehearsal was also wrong at first: it assumed the pin
was not yet pushed, and the cases that depend on it were run again from the
commit before it. And one progress message to the owner gave 21 of 23
mutants caught where it was 20; the next message corrected it.

**The rule this adds.** Every phrasing measured here was written for the
measurement; no log of what buyers type exists. So a rule is checked only on
the shapes its author thought of, and twice in this entry a fault was found
by trying a build on a phrasing no set held. That is not a reason to stop
measuring on made phrasings. So from here each build is also tried on
phrasings outside its sets before its tests are written, and what a rule
does not read is listed rather than dropped: what is listed can be seen.
