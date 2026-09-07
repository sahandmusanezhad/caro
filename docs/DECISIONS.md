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

## D31 (result) — the ceiling is the market's shape, not our route

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
shortfall is not our sampling and not the route — it is the shape of the
market. Pride's inventory is long-tailed across trims, and no acquisition
strategy makes `pride-151-sl` have more than the two cars that are listed.

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

D31 closed acquisition: the trim tail is the market's shape, and no crawling
fixes it. The remaining honest option is to keep trim-level conditioning and
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
requires. Their coverage figures are not evidence; they are noise that
happens to look reassuring.

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
what the glob actually produced, so the scope in the docstring and the
scope in the code cannot drift apart. Two ways of listing the same files,
compared — the same move as reading the instance numbers out of this file
rather than copying them.

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
