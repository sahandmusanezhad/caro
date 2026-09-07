# CARO

**An evidence-grounded, uncertainty-aware decision engine for used-car listings.**

CARO estimates a market range for a listing, then tries to prove itself wrong.

```
git clone https://github.com/sahandmusanezhad/caro && cd caro
./scripts/setup.sh                  # finds or installs numpy; tells you what to run

python3 tests/run_all.py            # 349 assertions, no API key, no network
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

**In used cars that premise collapses.** No two cars are the same object — mileage, paint history, documents, region, and seller honesty all differ. So a naive "Torob for cars" is a marketplace with a sort button, and sorting by price actively harms the buyer: the cheapest listing is usually the most damaged one.

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
listing is usually the most damaged one. That is a claim, so it gets an
experiment — `make winrate`:

```
queries=11  win-rate=100%  CARO=-46,928,024  price-sort=-60,165,712  random=-105,918,867
uplift over price-sort: +22.0%
```

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
| Demo page, fed from live pipeline output | ✅ built |
| Source adapter contract + CSV adapter | ✅ built |
| Intent parsing + ranking, beating sort-by-price | ✅ built, benchmarked |
| Divar + Bama adapters, robots-verified | ✅ built, tested offline |
| Cross-source identity and supply correction | ✅ built, tested |
| **Live collection run against Divar** | ❌ the network path is unexercised here |
| **Real corpus** | ❌ every number here comes from a synthetic corpus |

**Synthetic validation proves the implementation is correct. It does not prove the product is right about the market.** Those are different claims and this repo only makes the first one.

## Repository layout

```
caro/            ingest · tracking (W0) · appraisal (W1) · ranking (W3) · agents (W2)
tests/           349 assertions across the five layers
demo/            export_demo.py regenerates index.html from real output
docs/            architecture, decisions, evaluation, roadmap
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
seller, publishing in several places. When the prices differ, which they
usually do, the finding is the opposite of confirmation:

```
همین خودرو در ۳ سایت آگهی شده، با ۳۰ میلیون اختلاف قیمت —
کمترین قیمت اعلام‌شده ۱.۴۲ میلیارد است

فروشنده خودش این خودرو را جایی ۱.۴۲ میلیارد گذاشته؛
بالاتر از این عدد جای چانه‌زنی دارد.
```

The lowest public ask is a number the seller has already accepted. That is
worth more than agreement would have been.

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
