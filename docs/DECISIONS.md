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

Bama `primary_offers`, Divar `breadth`, Sheypoor `corroboration`. Specs and
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
which they usually do, the finding is the opposite of confirmation: it is
inconsistency. Three things follow, all more useful than agreement would be:

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
