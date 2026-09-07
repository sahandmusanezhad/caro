# CARO

**An evidence-grounded, uncertainty-aware decision engine for used-car listings.**

CARO estimates a market range for a listing, then tries to prove itself wrong.

---

## The result, up front

CARO's estimator beats its baseline by **52%** on aggregate error. **It is
not serving.** Those two facts are the project.

```
BENCHMARK — partial pooling on the Run 3 corpus (155 eligible listings)

  slice                   n          MAE     cover   err  shrink  extrap
  well-observed trim     75   64,072,026      69%    1%    0.93      0%
  thin trim              54   63,738,855      70%    0%    0.84    100%
  held-out trim          26  115,525,217      77%    7%    0.00    100%

  MAE 63,932,559  vs  parent-median baseline 133,372,093   (-52.1%)

  VERDICT: UNJUDGEABLE_SLICE

  estimator quality                  promising
  evidence for conditional serving   INSUFFICIENT
  decision                           DO NOT SERVE
```

The two slices the claim depends on carry n=54 and n=26 against the 58 a
calibration verdict needs — 2.5 binomial standard errors on a 15-point
coverage deviation. Their coverage numbers look excellent. They are noise
that happens to look reassuring, and a demo would quote them.

> **The fix is a corpus that can judge, not a tuning pass that makes the
> question go away.**

Three independent, *measured* reasons the appraiser stays locked — none of
them a judgement call:

| | finding | how it was established |
|---|---|---|
| **D30** | conditional coverage 55% against a 70% requirement | measured on the corpus |
| **D31** | the acquisition ceiling is 63% | proved from the source's own trim census — 135 listings across 34 Pride trim pages, 22 holding fewer than five |
| **D34** | the corpus cannot calibrate the estimator | n=54 and n=26 against a derived floor of 58 |

## What the live runs actually found

Four collection runs against bama.ir. Each one broke something that looked
like it worked:

- **The sitemap does not list listings.** It lists brand pages. Run 1
  collected zero cars and reported success.
- **`/car/saipa` silently returns the generic feed.** It is not a brand slug.
  A guessed URL that answers `200` is the most expensive kind of bug here,
  and this pattern recurred **three times** across the runs.
- **The site declares `priceCurrency: "IRR"` and publishes toman.** Reading
  the label literally divides every price by ten, and the currency whitelist
  cannot catch it because `IRR` is a code we recognise. Caught by
  cross-checking the structured price against the one rendered to buyers.
- **`999,990 km` on a 1384 Pride; `1 km` on a 1385 Pride.** In range, present,
  and false. Semantic validation is not a bounds check.
- **`?page=N` answers 200 and redirects to page 1.** Four "pages" dedupe to
  ten listings. Reporting that as a homogeneous market would have blamed
  Iran's used-car trade for a bug in the crawler.

Every one is recorded in [`docs/DECISIONS.md`](docs/DECISIONS.md) with what
it replaced and what being wrong would have cost.

## Why this shape

The brief was *crawl → normalise → rank by intent → explain*. The part that
turned out to be hard is none of those: it is knowing when the evidence is
good enough to speak. So the architecture is a chain of gates, each of which
can only make a narrower claim than the one before it:

```
acquisition validity  →  sample sufficiency  →  estimand validity
                      →  estimator acceptance  →  serving
```

Run 3 clears the first two. D30 stops it at the third. D34 stops it at the
fourth. A number that reaches the end has passed all of them, and a number
that does not is *absent* rather than caveated —
`MarketEstimator.predict()` raises rather than returning, and
`aggregate()` refuses a model-level figure that arrives without its sampling
sensitivity.

CARO reports uncertainty about prices. It also reports **uncertainty about
its own ability to assess uncertainty**, and refuses on it.

```
git clone https://github.com/sahandmusanezhad/caro && cd caro
./scripts/setup.sh                  # finds or installs numpy; tells you what to run

python3 tests/run_all.py            # 556 assertions, no API key, no network
python3 scripts/benchmark_run3.py   # the benchmark above, from the stored corpus
python3 tests/run_all.py ranking    # just the win-rate benchmark
python3 demo/export_demo.py         # regenerate demo/index.html from live output
```

**numpy is the only hard dependency.** Ridge regression is written out in
four lines of linear algebra rather than imported, because depending on
scikit-learn for it costs a heavyweight install that lags new Python
releases by months — the kind of friction that stops a reviewer before they
see a test pass. The closed-form solution is asserted to match `sklearn.Ridge`
to 1e-9 where sklearn happens to be available.

No build tool either — the suites are plain scripts. A `Makefile` exists as a
convenience but nothing depends on it.

`setup.sh` tries four routes in order of how little they disturb the machine:
numpy already present (common — distributions ship `python3-numpy`), then a
venv, then a `--user` install into `~/.local`, and only then does it mention
`sudo`. Debian-family systems make this necessary rather than fussy: the
system Python is externally managed (PEP 668) *and* `python3-venv` is a
separate package, so the obvious command fails and the obvious fix also
fails. **Nobody should need root to run a test suite.**

### First live collection

```
pip install playwright && playwright install chromium
export CARO_SELLER_SALT="$(head -c 24 /dev/urandom | base64)"
python3 scripts/first_run.py --source bama --limit 50
```

Deliberately small. The point of a first run is not volume — it is the
inventory it prints: fill and garbage rate per field, model coverage, and the
condition distribution. Those numbers decide whether the corpus can support
an estimate at all, and the script says so outright:

```
VERDICT
  NOT READY — under 80% usable prices. Fix extraction before fitting anything.
```

Raw responses land in `data/snapshots/`, so `--replay` re-parses offline and
asks the site for nothing.

---

## The problem

Torob works because one product has many sellers: one SKU, twelve prices, pick the cheapest trustworthy one. Matching is trivial; the value is the comparison.

**In used cars that premise collapses.** No two cars are the same object — mileage, paint history, documents, region, and seller honesty all differ. So a naive "Torob for cars" is a marketplace with a sort button, and sorting by price actively harms the buyer, because the cheapest listing can systematically favour damaged cars.

CARO's answer is not a cheaper number. It is a **defensible** one — an estimate that carries its own evidence, its own uncertainty, and a record of the checks that tried to invalidate it.

## The one design decision that matters

> **The adversarial reviewer is deterministic.**

A reviewer written as an LLM prompt can be talked out of a finding, can invent one that is not there, and answers differently on a rerun. A reviewer written as checks over an evidence packet can do none of those. For a system whose entire pitch is *we do not overclaim*, the component that polices overclaiming is the last place to put a language model.

Two consequences:

- **The whole system runs offline.** No API key. An LLM is optional and enters at exactly one point — rendering a finished verdict as prose.
- **`Verdict` is a frozen dataclass.** The language layer receives it after the decision is made and *structurally cannot* alter a number, a confidence level, or an outcome. There is a test that asserts the mutation raises.

**LLMs may explain a decision. They may not make or overturn one.**

## Architecture

```
  DivarCarAdapter · CsvAdapter    ← caro/ingest — deterministic, not agents
             │
        FetchOutcome
             │
    ┌────────▼─────────┐
    │  W0  tracking    │  snapshot integrity · repost identity · censoring
    └────────┬─────────┘
    ┌────────▼─────────┐
    │  W1  appraisal   │  leak-free split · baselines · AcceptanceGate
    └────────┬─────────┘
    ┌────────▼─────────┐
    │  W3  ranking     │  Persian intent · relaxation ladder · scoring
    └────────┬─────────┘
    ┌────────▼─────────┐
    │  W2  agents      │  evidence → comparables → estimate → risk
    │                  │  → adversarial → judge → explanation
    └────────┬─────────┘
             ▼
   Shortlist + Verdict + Evidence Ledger
```

| Layer | Module | What it guarantees |
|---|---|---|
| **Ingest** | `caro/ingest/` | A blocked source halts collection — no rotation, no retry-harder. A failed page is ignorance about that page, not absence of its listings. A raw seller identifier never reaches disk. |
| **W0** | `caro/tracking.py` | A failed fetch is never an absence. A disappearance is never a sale. A blocked crawl cannot corrupt the history. Reposts link on precision, never on a guess. |
| **W1** | `caro/appraisal.py` | No physical car appears on both sides of a split. Quantiles cannot cross. An unbenchmarked estimator cannot serve a number. |
| **W3** | `caro/ranking.py` | Assumptions are surfaced, never silent. A deal-breaker is never relaxed away. Every scoring term is inspectable. Risk is priced in tomans, not normalised. |
| **W2** | `caro/agents.py` | Every user-facing claim resolves to an observation. Hard contradictions veto. Confidence is a published policy, not a fitted score. |

## Invariants, enforced in code

These are tested, not documented-and-hoped:

- `UNKNOWN ≠ ABSENT` — 403/429/5xx/timeout classify as unknown; only a definitive 404 is absence.
- **No `sold` field exists.** We never observed a transaction, so we never name one.
- A snapshot with an implausible disappearance rate is `SUSPECT` and excluded from every longitudinal statistic — because a rate-limit block looks exactly like a mass disappearance.
- Days we did not check are counted as **unknown**, never as active. `span + 1 == present + absent + unknown`.
- `MarketEstimator.predict()` raises `NotBenchmarked` until `AcceptanceGate` passes.
- A model that loses to the comparable baseline is **rejected, and the failure message says to ship the baseline**.
- Every `Claim` cites `EvidenceItem` ids; `EvidenceLedger.unsupported_claims()` must be empty on every path.
- Target is an **asking price**. The vocabulary never says "fair price", "true value", or "transaction price".

## The number

The thesis is that sorting by price harms the buyer, because the cheapest
listing can systematically favour damaged cars. That is a claim, so it gets
an experiment — `make winrate`:

```
queries=11  win-rate=100%  CARO=-46,928,024  price-sort=-60,165,712  random=-105,918,867
uplift over price-sort: +22.0%
```

What this tests, precisely: in a world where the cheapest listings *are*
disproportionately damaged, does CARO's ranking respond to that correctly
while price-sorting does not. It does not test whether Iranian used-car
prices have that property — the generating process was built with it. The
market question is open and belongs to a blind human panel.

Utility is ground truth from the generating process, which the ranker never
sees — it works from a fitted estimator, so the comparison is not circular.
On real data there is no such function and the honest substitute is a blind
human panel; that result belongs in EVAL.md whatever it says.

**This benchmark caught a real bug.** The first ranker normalised risk to
[0,1] across the candidate set — scale-free, so a 20% defect probability cost
the same on an 800M car as on a 2B one. It kept choosing expensive damaged
cars and *lost* to price-sorting. The fix restored the formula from the
original thesis — `value = estimate − asking − risk_discount`, every term in
tomans, subtracted before normalisation. Risk is priced, not scored.

## Confidence is a rulebook, not a number

`make policy` prints it. Six dimensions, each from a named band with a stated rationale — so "why 0.65?" has the answer *"that is the published band for 3–4 days of confirmed observation, and here is the table"*, not *"the scorer said so"*.

The tier of a comparable set sets a **ceiling**; the count decides how much of it is earned. No quantity of loosely matched listings can outrank a tightly matched set.

These bands are calibrated by judgement, not fitted to data. That is stated in the code, in the policy printout, and here — see [ROADMAP](docs/ROADMAP.md).

## What is real, and what is not

| | Status |
|---|---|
| Tracking, appraisal, decision layer | ✅ built, tested |
| Adversarial review, evidence ledger | ✅ built, tested |
| Demo page, fed from pipeline output | ✅ built |
| Source adapter contract + CSV adapter | ✅ built |
| Intent parsing + ranking, beating sort-by-price | ✅ built, benchmarked on a synthetic task |
| Divar + Bama adapters, robots-verified | ✅ built, tested offline |
| Cross-source identity and supply correction | ✅ built, tested |
| **Real Bama corpus** | ✅ 4 live runs; 221 parsed, 155 appraisal-eligible |
| **Real conditional-appraisal validation** | ❌ `UNJUDGEABLE_SLICE` — W1 locked (D34) |
| **Live collection run against Divar** | ❌ the network path is unexercised here |

Two kinds of validation, and they support different claims.

**Synthetic validation proves the implementation and the ranking behaviour.**
The win-rate benchmark, the leakage-free split, the quantile machinery — all
of it runs against a world whose true prices are known, which is the only way
to check that the code does what it says.

**The real Bama corpus tests the pipeline against market-shaped data**, and
is where every finding in the section above came from — the currency label,
the placeholder odometers, the silent redirects. But it does **not** yet
establish conditional serving: D34 finds the thin and held-out slices too
small to judge calibration. The honest result there is `UNJUDGEABLE_SLICE`,
which is not a positive claim about the market.

What this repo does *not* claim: that CARO prices Iranian used cars
correctly. Nothing here has been checked against a transaction, only against
asking prices — and the appraiser is not serving.

## Repository layout

```
caro/            ingest · tracking (W0) · appraisal (W1) · hierarchical (D32)
                 ranking (W3) · agents (W2) · quality · coverage · stratification
tests/           556 assertions across six suites
scripts/         live runs, replays, the benchmark, the run-3/4 experiment plans
data/snapshots/  the collected corpora, replayable offline
demo/            export_demo.py regenerates index.html from pipeline output
docs/            architecture · DATA_CONTRACT (frozen) · DECISIONS (D1-D35) · eval
```

## Sources, and what each is for

Three offer sources, each with a role — not ten sites for volume.

| Source | Role | Access, verified 2026-09-07 |
|---|---|---|
| **Bama** | `primary_offers` — richest structured fields, sets the canonical schema | Publishes a **car sitemap**; nothing relevant disallowed. So discovery is sitemap-first: coverage is knowable rather than estimated, and it needs far fewer requests than crawling search pages. |
| **Divar** | `breadth` — largest volume, private sellers the specialist sites never see | Category browsing and listing pages allowed; **search urls (`?q=`) disallowed**. `assert_allowed()` raises on a violating url rather than trusting a comment. |
| **Sheypoor** | `corroboration` — its value is the cross-source clusters it creates, not the listings it adds | Not yet verified. |

Specs and price-guide sites are `taxonomy_only`: useful for normalising model
names, never ingested as offers. A price-guide page is not a price anyone is
asking, and letting one into the corpus teaches the appraiser from a number
that does not exist in the market.

### Several sites listing one car is not corroboration

It is tempting to render a cross-source cluster as "confirmed by 3 sources".
A test asserts the UI never says «تأیید», because corroboration needs
independent *observers* of one fact — and here there is one observer, the
seller, publishing in several places. When the prices differ, the finding is
the opposite of confirmation:

```
همین خودرو در ۲ سایت آگهی شده، با ۳۰ میلیون اختلاف قیمت —
کمترین قیمت اعلام‌شده ۱.۴۲ میلیارد است

همین خودرو با قیمت ۱.۴۲ میلیارد نیز منتشر شده؛ اختلاف قیمت
بین کانال‌ها ۳۰ میلیون تومان است. این اختلاف یک نکته‌ی قابل
بررسی برای مذاکره است.
```

An earlier version of this block printed «فروشنده خودش این خودرو را جایی
۱.۴۲ میلیارد گذاشته؛ بالاتر از این عدد جای چانه‌زنی دارد» — the seller has
put it somewhere at that price, so you can bargain above it. That copy was
retired from the code, and survived here for one more revision because it
sits below the paragraph that was being corrected. It is instance #7 in D36.

The lowest public ask is a price the seller has publicly quoted for this
car. It is actionable price evidence, not transaction evidence — the number
may be stale, specific to one channel, or since raised, and none of that is
visible from here.

## Collection, and what was deliberately not built

`caro/ingest/divar_car.py` collects public Divar car listings. Its Persian
normalisation and browser-fetch approach are adapted from
[SorinFlow](https://github.com/Tecso-Dev/SorinFlow-DaTA-mAmager) (MIT) — a
property scraper — with attribution in [NOTICE](NOTICE).

Three of its components were **not** ported, and the omissions are the point:

| Left behind | Why |
|---|---|
| Contact reveal (phone numbers) | The ingest contract forbids emitting a personal identifier. `seller_fingerprint` is a salted hash for deduplication and nothing else. A corpus of phone numbers is a liability in a public repo whatever the licence permits. |
| Multi-account rotation | That is evasion. CARO stops when a source stops answering and records the gap. A test asserts it halts after three consecutive failures rather than continuing. |
| Session / OTP handling | Follows from the above — nothing here authenticates. |

The cost is real: no contact details, a lower volume ceiling, and collection
halts when Divar says halt. That is the correct trade for a system whose
pitch is that it does not overclaim.

## Documentation

- [ARCHITECTURE](docs/ARCHITECTURE.md) — the layers, and which components are deliberately *not* agents
- [DECISIONS](docs/DECISIONS.md) — the design record, including bugs found and what they cost
- [EVAL](docs/EVAL.md) — how the benchmark harness was itself validated
- [ROADMAP](docs/ROADMAP.md) — the honest gap list

## License

MIT.
