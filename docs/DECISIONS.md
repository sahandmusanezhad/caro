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
