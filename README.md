# CARO

**An evidence-grounded, uncertainty-aware decision engine for used-car listings.**

CARO estimates a market range for a listing, then tries to prove itself wrong.

**It is live at https://caro-rho.vercel.app.** The site serves 73 real Bama
listings collected on 2026-10-15 (`data/corpora/run16.json`). Ask it in
Persian for a car, and it shows the listings that meet the request, what it
read from the request and what it did not. It does not rank them: no
estimator has cleared the acceptance gate on a real corpus (D43), and a
ranking that has not cleared it is not served. Every screen says which
corpus it is reading.

---

## Where it stands

The brief asks for **crawl offers → normalize messy data → rank by user
intent → explain the best choice**.

| Requirement | State, 2026-10-25 |
|---|---|
| crawl offers | ⚠️ **one source.** Four runs of `BamaAdapter` are published — run11 (2026-09-10), run13 (2026-10-06), run14 (2026-10-11) and run16 (2026-10-15): 76, 74, 77 and 73 listings, of which 71, 64, 64 and 63 can be appraised. The site serves run16. `DivarCarAdapter` has its robots gate, its pause and its stop on a block, and since 2026-10-26 the extraction of a category page (`caro/ingest/divar_page.py`), written offline against the shape the owner's probe found; it has read the owner's saved copy of one real page once (2026-10-26: 24 of 24 listings, 22 prices confirmed by the card, the page's own body-condition field), and its live path has never run. Sheypoor and Khodro45 have no adapter. |
| normalize messy data | ✅ **built.** Persian numerals and amount words, toman and rial, mileage, Jalali and Gregorian years, make and model aliases, trim, gearbox, fuel, colour, body condition from free text, and the province, with how each was read. |
| rank by user intent | ⚠️ **built, not served on real data.** `caro/ranking.py` reads a Persian request, filters, relaxes and scores. No estimator has cleared the gate on a real corpus, so the site shows evidence, not a ranking. On the synthetic corpus, where the gate passes, the ranking is served and measured. |
| explain the best choice | ✅ **built.** A frozen verdict, an evidence ledger, and an adversarial review that is code, not a prompt. |
| deployed | ✅ **from each push to `main`** — one Vercel project of two services (D64, D80). |

Everything that is left until the end of the project — in order, with what
closes each item and who does it — is in [ROADMAP](docs/ROADMAP.md). How the
work is done, and the rules every session keeps, are in
[WORKING_AGREEMENT](docs/WORKING_AGREEMENT.md).

## Try it

Four requests on the site, as it answered them on 2026-10-25:

```
پراید از ۴۰۰ میلیون به بالا      a budget floor of 400 million and no ceiling:
                                  47 of run16's 53 Pride listings meet it, and
                                  3 are held apart because they carry no price

پراید در مشهد                     a city is not read, so it is not used; the
                                  page lists «در مشهد» under «نفهمیدیم» and
                                  shows the 53 Pride listings

۲۰۶ زیر ۱۰۰ هزار کیلومتر          the model 206 and an odometer cap of
                                  100,000 km

پراید در تهران                    the province is a constraint like the
                                  budget: 18 of the 53 are in Tehran
```

The search page's panel is «آنچه از جمله‌ی تو فهمیدیم»: the model, the
ceiling and the floor of the budget, the minimum year, the odometer cap, the
province, the use, the risk profile and the red lines. Whatever the parser
assumed is printed with it — «عدد قیمت را سقف بودجه فرض کردیم» when a lone
amount is taken for the ceiling — and what it leaves unread is listed under
«نفهمیدیم» wherever a rule finds it. A listing is a match only where every constraint
stated was checked against it; one that carries no value for a constraint is
held apart and says which (D65).

## The appraiser: two benchmarks, and why it does not serve

**Two benchmarks. They disagree. The estimator is not serving, and the
baseline is what ships.**

```
                     corpus                        model MAE   baseline    verdict
Run 3   155 eligible, 43 trims, 4 Saipa models      63.9M      133.4M    -52.1%
        single snapshot, collected 2026-09-07                            UNJUDGEABLE_SLICE

Run 5   228 eligible, 100 trims, 44 makes          607.0M      526.3M    +15.3%
        pre-registered before any request                                REJECTED
```

**Neither figure can be re-derived from this repository.** Both runs happened
and the verbatim output of each is committed under `docs/`; their input
corpora were never committed and are not recoverable. D46 records the search
and what follows from it. The status has five rows rather than one, because
"not reproducible" collapses distinctions this project needs:

    execution evidence          ✓   the run happened, on a dated corpus
    result transcript           ✓   committed, verbatim, in docs/
    repository replay           ✗   the input is not in the repository
    independent reproduction    ✗   no third party can re-derive the numbers
    full provenance             ✗   code + input + configuration → output
                                    cannot be closed from what is committed

Same estimator. Same gate. Same frozen constants — `MIN_SLICE_N=58`,
`MIN_PER_TRIM_FLOOR=5`, hold-out 0.25, seed 0. The only thing that changed
is the corpus, and the second one is larger, was collected against a
specification written before the first request, and **rejected the model**.

**And then the rejection failed its own significance test.** A paired
bootstrap over trims puts the 95% interval on that +15.3% at **[−324M,
+436M]** — straddling zero. The probability the model is worse by more than
the 10% the gate rejects on is **58%**, barely a coin flip. So:

> The frozen gate returned REJECTED under its registered criterion. That
> criterion has no uncertainty control, and the difference it rejected on
> cannot be distinguished from sampling noise on this corpus. The estimator
> is not shown to be better than its baseline; it is also not shown to be
> worse.

Both halves are load-bearing. The verdict is not edited after the fact —
that would be D35's tuning loop run backwards — but D39 records that
`mae_tolerance` is a bare `>` on a point estimate, sitting one field away
from a calibration criterion that D33 hardened to 2.5 SE.

So the decision is D12's, written long before the number that triggered it:
*if the baseline wins, ship the baseline and say so.* On this corpus nothing
beat the baseline, and that is the shipping rule's answer even when the
margin is unmeasurable.

**Why they disagree.** Run 3 was four Saipa models. Run 5 spans 44 makes and
a **143× price range** (350M to 50B toman). Partial pooling shrinks a thin
trim toward its parent, and where the parent is thin too, toward the global
level — across 143× that is not a mild correction, it is a large error,
while a baseline that never pools past `make|model` stays well behaved.
Run 5's pre-registration constrained the trim-size distribution in detail and
said **nothing** about price heterogeneity: the registration was blind, in
advance, to the variable that decided the outcome. That is the most useful
finding either run produced. It does **not** establish that partial pooling
is wrong for Iranian used cars, and D35 forbids testing that as a
continuation of this run — *estimator loses → change the corpus → estimator
wins* is the exact loop this project is built to refuse.

> **The fix is a corpus that can judge, not a tuning pass that makes the
> question go away.**

Three independent, *measured* reasons the appraiser stays locked:

| | finding | how it was established |
|---|---|---|
| **D30** | conditional coverage 55% against a 70% requirement | measured on the corpus |
| **D31** | the acquisition ceiling is 63% | proved from the source's own trim census — 135 listings across 34 Pride trim pages, 22 holding fewer than five |
| **D34** | the corpus cannot calibrate the estimator | n=54 and n=26 against a derived floor of 58 |

The runs published since, run11 to run16, hold 73 to 77 listings each, and
no estimator has cleared the gate on any of them. Clearing it on real data is
step 7 of the roadmap's order of work.

## What the live runs found

The first collection runs against bama.ir, in September, broke things that
looked like they worked:

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

The runs that are published came later. Every line of run16, the one the
site serves, was read before it was published, and no district named like a
province stands behind any of its 42 stated provinces (D80). Every finding is
recorded in
[`docs/DECISIONS.md`](docs/DECISIONS.md) with what it replaced and what being
wrong would have cost.

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

## Run it

```
git clone https://github.com/Tecso-Dev/caro && cd caro
./scripts/setup.sh                  # finds or installs numpy; tells you what to run
#                                   add --extras, and npm install in
#                                   webapp/web, for all fifteen suites

python3 tests/run_all.py            # 2925 assertions, no API key, no network
python3 tests/run_all.py ranking    # one suite by name: here the ranking benchmark
python3 demo/export_demo.py         # regenerate demo/demo_data.json from live output
```

Those three run on a clean clone with no network. The run scripts do not:
`scripts/benchmark_run3.py`, `benchmark_run5.py`, `run5_significance.py`,
`rank_run3.py`, `rank_run5.py` and `demo/export_ranking.py` all raise
`FileNotFoundError` — three of them as `CorpusUnavailable`, which names D46 —
because the corpora they read were never committed. Read their committed
output in `docs/` instead: `RUN3_2026-09-07.txt`, `RUN5_2026-09-07.txt`,
`BENCHMARK_RUN5_2026-09-07.txt`, `RUN5_SIGNIFICANCE_2026-09-07.txt`,
`RANK_RUN5_2026-09-08.txt`, `GATE_DIAGNOSIS_2026-09-08.txt`.

**numpy is the only hard dependency of `caro/`.** Three of the fifteen test
suites need more, and the runner says so rather than failing:

```
python3 tests/run_all.py            # 2379 assertions across 12 of 15 suites
./scripts/setup.sh --extras         # scipy + the API packages
(cd webapp/web && npm install)      # node packages: the screens suite draws with them
python3 tests/run_all.py            # 2925 across all fifteen
```

A suite whose extra module or program is absent is skipped by name with the
command that enables it — skipped is never printed as passed, and the count
reads "12 of 15". None of the extras is needed by the package: scipy builds
an oracle inside `tests/test_appraisal.py`, fastapi is only reachable from
`webapp/`, and node only draws the site's own components in
`tests/test_screens.py`.

Use `setup.sh --extras` rather than a bare `pip install`. On Debian-family
systems the system Python is externally managed (PEP 668), so `pip install
scipy` fails with `externally-managed-environment`, and the venv that the
error recommends may itself be unavailable, because `python3-venv` is a
separate package. The script walks four routes in order of how little they
disturb the machine — numpy already present, a venv, a `--user` install, and
only then a mention of `sudo` — and needs root for none of them. **Nobody
should need root to run a test suite.**

Ridge regression is written out in four lines of linear algebra rather than
imported, because depending on scikit-learn for it costs a heavyweight
install that lags new Python releases by months. The closed-form solution is
asserted, in `tests/test_hierarchical.py`, to match a solution found another
way — least squares on the augmented system, solved by SVD — to 1e-9, on the
design matrices both models build and on 200 seeded problems shaped like
them. No build tool either: the suites are plain scripts, and the `Makefile`
is a convenience nothing depends on (`make winrate`, `make policy`).

### The site, locally

Two processes, from the repository root; [webapp/README](webapp/README.md)
has the rest — the environment variables, which corpus is served, and how
the Vercel project is set up.

```
pip install -r webapp/requirements.txt          # or ./scripts/setup.sh --extras
uvicorn webapp.api.main:app --reload            # the API, 127.0.0.1:8000
(cd webapp/web && npm install && npm run dev)   # the site, 127.0.0.1:3000
```

The API is FastAPI and imports `caro` directly: `/api/search`,
`/api/search/reweight`, `/api/listing/{id}`, `/api/compare`, `/api/corpus`,
`/api/health`, and the contact and admin endpoints. The deployed site keeps
its inbox off and points to GitHub Issues instead (`CARO_INBOX=off`, D68), and
`/admin` opens only where `CARO_ADMIN_TOKEN` is set. The site
is Next.js, TypeScript and Tailwind, in right-to-left Persian: `/`, `/search`,
`/car/[id]`, `/compare`, `/how-it-works`, `/about`, `/contact` and `/admin`.
`.github/workflows/ci.yml` runs every suite and the site's type check, lint and
build on each push to `main` and each pull request, and fails when a suite is
skipped.

### A live collection

Only the owner starts one, on his own machine. No script here runs on its
own, and every suite passes with the network switched off.

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

For a source whose pages nothing here holds yet (Divar's listing page,
Sheypoor, Khodro45), the first step is a probe, not a collection:

```
python3 scripts/page_probe.py --source divar --origin https://divar.ir \
    --url https://divar.ir/s/tehran/car
python3 scripts/page_probe.py --survey   ~/caro-probes/<run>/01-….html   # the one to send
python3 scripts/page_probe.py --around /v/ ~/caro-probes/<run>/01-….html   # cards that differ in shape
python3 scripts/page_probe.py --rows     ~/caro-probes/<run>/01-….html --no-text
python3 scripts/page_probe.py --scripts  ~/caro-probes/<run>/01-….html
python3 scripts/page_probe.py --skeleton ~/caro-probes/<run>/01-….html --no-text
python3 scripts/first_run.py --page      ~/caro-probes/<run>/01-….html   # Divar: what the parser reads
```

It reads robots.txt through the same gate, asks for at most five urls under
the same pause and User-Agent, keeps the pages outside the repository, and
stops at the first one that does not return. No login, no click, no contact.
`--rows` finds the cards of a list and prints one in full; `--scripts` prints
the shape of the JSON a page carries in a script (the keys and the kind of each
value, never a value); `--skeleton` is the whole page. Every digit taken from a
page is `#` in all three; they are what can be sent to have a parser written.
`--survey` is all of them in one answer and prints, besides, the smallest, the
middle and the largest of the numbers under a name like price, mileage or year
(that is how a price's unit is read), and never a number under a person's name.
`--around /v/` is `--rows` for a list whose cards differ in shape.

Structured snapshot records land in `data/snapshots/` — one `FetchOutcome`
per listing, not the raw HTTP response. That directory is **operational and
never published**; a run whose numbers are published needs a publishable
artifact under `data/corpora/`, written by `scripts/promote_corpus.py`, which
redacts seller-authored text and validates against
[DATA_CONTRACT](docs/DATA_CONTRACT.md).

`--replay FILE` reads a snapshot this script wrote (the records of status ok
are the listings) or the older file with a top-level `listings`, and prints the
inventory again with no network, no salt and nothing written. Until 2026-10-29
it read only the second, and replaying a snapshot yielded zero listings, quietly.
`--page FILE` does the same for one saved Divar category page.

---

## The problem

Torob works because one product has many sellers: one SKU, twelve prices, pick the cheapest trustworthy one. Matching is trivial; the value is the comparison.

**In used cars that premise collapses.** No two cars are the same object — mileage, paint history, documents, region, and seller honesty all differ. So a naive "Torob for cars" is a marketplace with a sort button, and sorting by price can harm the buyer, because the cheapest listing can systematically favour damaged cars.

CARO's answer is not a cheaper number. It is a **defensible** one — an estimate that carries its own evidence, its own uncertainty, and a record of the checks that tried to invalidate it.

## The one design decision that matters

> **The adversarial reviewer is deterministic.**

A reviewer written as a language-model prompt can be talked out of a finding, can invent one that is not there, and answers differently on a rerun. A reviewer written as checks over an evidence packet can do none of those. For a system whose entire pitch is *we do not overclaim*, the component that polices overclaiming is the last place to put a language model.

Two consequences:

- **The whole system runs offline.** No API key. A language model is optional and enters at exactly one point — rendering a finished verdict as prose.
- **`Verdict` is a frozen dataclass.** The language layer receives it after the decision is made and *structurally cannot* alter a number, a confidence level, or an outcome. There is a test that asserts the mutation raises.

**A language model may explain a decision. It may not make or overturn one.**

## Architecture

```
  BamaAdapter · DivarCarAdapter · CsvAdapter    ← caro/ingest — deterministic, not agents
             │
        FetchOutcome  →  scripts/promote_corpus.py  →  data/corpora/<run>.json
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
   Shortlist + Verdict + Evidence Ledger   →   webapp/api (FastAPI)  →  webapp/web (Next.js)
```

| Layer | Module | What it guarantees |
|---|---|---|
| **Ingest** | `caro/ingest/` | A blocked source halts collection — no rotation, no retry-harder. A failed page is ignorance about that page, not absence of its listings. A raw seller identifier never reaches disk. robots.txt is read before the first request and asked before every one after. |
| **W0** | `caro/tracking.py` | A failed fetch is never an absence. A disappearance is never a sale. A blocked crawl cannot corrupt the history. Reposts link on precision, never on a guess. |
| **W1** | `caro/appraisal.py` | No physical car appears on both sides of a split. Quantiles cannot cross. An unbenchmarked estimator cannot serve a number. |
| **W3** | `caro/ranking.py` | Assumptions are surfaced, never silent. What the parser leaves is listed under «نفهمیدیم» where a rule finds it. A deal-breaker is never relaxed away. Every scoring term is inspectable. Risk is priced in tomans, not normalised. |
| **W2** | `caro/agents.py` | Every user-facing claim resolves to an observation. Hard contradictions veto. Confidence is a published policy, not a fitted score. |
| **Site** | `webapp/` | The API may not be more informative than the evidence behind it (D50). A REAL failure never becomes a SYNTHETIC success (D49). The corpus label is on every screen. |

[ARCHITECTURE](docs/ARCHITECTURE.md) says which components are deliberately *not* agents, and why.

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
- A retired overclaim does not come back: `tests/test_claims.py` holds every one D36 catalogues, and says plainly that it cannot catch a new one.

## The number

The thesis is that sorting by price can harm the buyer, because the cheapest
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

`make policy` prints it: three dimensions — evidence, temporal and comparable
strength — each from a named band with a stated rationale, and an overall
status from fixed thresholds. So "why 0.65?" has the answer *"that is the
published band for 3–4 days of confirmed observation, and here is the
table"*, not *"the scorer said so"*.

The tier of a comparable set sets a **ceiling**; the count decides how much of it is earned. No quantity of loosely matched listings can outrank a tightly matched set.

These bands are calibrated by judgement, not fitted to data. That is stated in the code, in the policy printout, and here — see [ROADMAP](docs/ROADMAP.md).

## What the parser reads

`caro/ranking.py` reads a Persian request with rules, not a model; each rule
added or changed since D82 was measured on phrasings written for it before it
was built. It reads
the model (by name, or by its number where the number stands alone), the
ceiling of a budget (after «زیر», «تا», «حداکثر», «کمتر از», «بودجه»,
«قیمت», or a lone amount, with the assumption printed), its floor (a cue, an
amount of money and «به بالا», with nothing between them; or «حداقل», with
«قیمت» if it is written, and an amount; or an amount and «و بالاتر», «و بیشتر»
or «یا بیشتر»), the minimum year,
an odometer cap in five shapes, the province where the car should be, the
use, the risk profile and the red lines. It lists under «نفهمیدیم» what it
does not read: a city after a cue it knows («در مشهد»), a figure with no
scale word, a phrase it cannot place.

What it does not read yet, each pinned by a test so that it changes on
purpose, is in the roadmap's items 3 to 5 with the numbers measured for it:
a city, «بیشتر از», «بیش از», «بالاتر از» and «حداقل بودجه» as a floor, a bare
«X به بالا», ranges, a negated floor, and «بالای X» without «به بالا», which
is read as a ceiling by the owner's choice. No log of what buyers type
exists, so what the parser does is measured on made phrasings, and what
buyers write is not.

## What is real, and what is not

Every claim below carries the *kind* of evidence behind it, because "built"
and "validated on real data" are not the same sentence and this project has
blurred them before (D41). Five levels, weakest last:

| | | Claim |
|---|---|---|
| **VALIDATED** | evidence on real data | ingestion and retrieval reach real Bama listings; parsing and normalisation to the level the 515 ingest assertions reach; the relaxation ladder; the refusal and uncertainty policy; four published corpora |
| **EVALUATED** | measured on real data, and it did not pass | conditional appraisal — Run 3 `UNJUDGEABLE_SLICE`, Run 5 `REJECTED` with D39's interval attached; the baseline class, which fails the gate on Run 5's corpus at 0.206 coverage error |
| **AUDITABLE** | traceable on real data, no ground truth required | the decision ledger — which inputs each ranking decision actually had. On Run 5 it reports 38% mean completeness with a reason for every absence (`scripts/rank_run5.py`) |
| **NOT VALIDATED** | correct within a contract this project wrote | ranking correctness — the win-rate beats price-sort on a synthetic corpus whose generating process this repository defines. It says the ranker responds correctly in a world built to have that property; it is not evidence about Iran |
| **NO GROUND TRUTH** | not measurable here, and no substitute is honest | whether CARO's ordering is *better for a buyer* than the baseline on real listings. Disappearance is not a sale (D2); a rubric written here is the same self-written utility; a language model asked to judge the ordering has only moved that utility into a prompt |

And the specific gaps behind those rows:

| | Status |
|---|---|
| Tracking, appraisal, decision layer | ✅ built, tested |
| Adversarial review, evidence ledger | ✅ built, tested |
| The site and its API, deployed from `main` | ✅ built, tested by two suites of their own |
| Demo page, fed from pipeline output | ✅ built |
| Source adapter contract + CSV adapter | ✅ built |
| Divar + Bama adapters; robots.txt read in code (RFC 9309, D73) | ✅ built, tested offline |
| Cross-source identity and supply correction | ✅ built, tested |
| **Real Bama corpora** | ✅ the September runs (Run 5: 403 parsed, 228 appraisal-eligible; never committed, D46) and four published since — the site serves run16 |
| **The fields the ranking reads, on real data** | ✅ recorded — run16 carries the body condition, gearbox, fuel and province on all 73 listings and the colour on 70 — though no ranking runs on them yet (the next row) |
| **A shortlist over real listings** | ❌ does not exist — no estimator clears the gate on any real corpus, so `Ranker.score` raises and every shortlist refuses |
| **Live collection run against Divar** | ❌ the network path is unexercised |

Two kinds of validation, and they support different claims.

**Synthetic validation proves the implementation and the ranking behaviour.**
The win-rate benchmark, the leakage-free split, the quantile machinery — all
of it runs against a world whose true prices are known, which is the only way
to check that the code does what it says.

**The real Bama corpora test the pipeline against market-shaped data**, and
are where every finding above came from — the currency label, the
placeholder odometers, the silent redirects. They do **not** yet establish
conditional serving: D34 finds the thin and held-out slices too small to
judge calibration. The honest result there is `UNJUDGEABLE_SLICE`, which is
not a positive claim about the market.

What this repo does *not* claim: that CARO prices Iranian used cars
correctly. Nothing here has been checked against a transaction, only against
asking prices — and the appraiser is not serving.

## Sources, and what each is for

Each source has a role — not ten sites for volume.

| Source | Role | State |
|---|---|---|
| **Bama** | `primary_offers` — richest structured fields, sets the canonical schema | Built and run. Publishes a car sitemap; nothing relevant disallowed (verified 2026-09-07, and read again by the adapter before every run). Discovery is sitemap-first, so coverage is knowable rather than estimated. |
| **Divar** | `breadth` — largest volume, private sellers the specialist sites never see | The robots gate, the pause, the stop and the extraction of a category page are built and tested offline; the extraction reads a JSON-LD list of vehicles and the cards beside it, and has read one saved real page (24 of 24 listings); the make and model table is domestic only, so 10 of the 24 have no model; nothing has run live. Category browsing and listing pages allowed; **search urls (`?q=`) disallowed**, and a url robots.txt refuses is not requested. |
| **Sheypoor** | `corroboration` — its value is the cross-source clusters it creates, not the listings it adds | No adapter. |
| **Khodro45** | not yet given one | No adapter. |

Both adapters read robots.txt before their first request and ask it before
every request after (`caro/ingest/robots.py`, RFC 9309, a matcher of our
own): a url it disallows is not requested, and a robots.txt that gives no
policy stops the run. Divar keeps its 2026-09-07 transcription beside the
live file, and a url either one refuses is refused.

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

The lowest public ask is a price the seller has publicly quoted for this
car. It is actionable price evidence, not transaction evidence — the number
may be stale, specific to one channel, or since raised, and none of that is
visible from here. An earlier version of this copy said more than that, and
D36 records it as instance #7.

## Collection, and what was deliberately not built

`caro/ingest/divar_car.py` collects public Divar car listings. Its Persian
normalisation and browser-fetch approach are adapted from
[SorinFlow](https://github.com/Tecso-Dev/SorinFlow-DaTA-mAmager) (MIT) — a
property scraper — with attribution in [NOTICE](NOTICE).

Three of its components were **not** ported, and the omissions are the point:

| Left behind | Why |
|---|---|
| Contact reveal (phone numbers) | The ingest contract forbids emitting a personal identifier. `seller_fingerprint` is a salted hash for deduplication and nothing else. A corpus of phone numbers is a liability in a public repo whatever the licence permits. |
| Multi-account rotation | That is evasion. CARO stops when a source stops answering and records the gap. A test asserts it stops after three blocked requests rather than continuing. |
| Session / OTP handling | Follows from the above — nothing here authenticates. |

Nor does anything here solve a CAPTCHA or work around a block. A seller is a
dealer only where the source shows a business badge, never by a guess about
the person (D26). The cost is real: no contact details, a lower volume
ceiling, and collection halts when a source says halt. That is the correct
trade for a system whose pitch is that it does not overclaim.

## Repository layout

```
caro/            ingest · tracking (W0) · appraisal (W1) · hierarchical (D32)
                 ranking (W3) · agents (W2) · corpus_reader · synthetic
tests/           2925 assertions across fifteen suites
webapp/          api (FastAPI, imports caro) · web (Next.js 15, TypeScript, Tailwind)
scripts/         setup, live runs, promotion, replays, the benchmark, the probes
data/corpora/    the published runs — run11, run13, run14, run16; snapshots are never committed
data/derived/    the date-watch rounds' summaries
demo/            index.html is hand-maintained; export_demo.py writes demo_data.json
docs/            architecture · DATA_CONTRACT (frozen) · DECISIONS (D1-D84) · eval · roadmap
```

## Documentation

- [ROADMAP](docs/ROADMAP.md) — everything left until the end of the project, in order, with what closes each item
- [WORKING_AGREEMENT](docs/WORKING_AGREEMENT.md) — how the work is done: measured rounds, separate commits, and the rules no session breaks
- [DECISIONS](docs/DECISIONS.md) — the design record, including bugs found and what they cost
- [ARCHITECTURE](docs/ARCHITECTURE.md) — the layers, and which components are deliberately *not* agents
- [DATA_CONTRACT](docs/DATA_CONTRACT.md) — what a published corpus holds, and what it may never hold
- [EVAL](docs/EVAL.md) — how the benchmark harness was itself validated
- [webapp/README](webapp/README.md) — running, configuring and deploying the site

## License

MIT, in [LICENSE](LICENSE); what is adapted from elsewhere is credited in [NOTICE](NOTICE).
