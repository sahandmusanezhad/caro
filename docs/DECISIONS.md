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
