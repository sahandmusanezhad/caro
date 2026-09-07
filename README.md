# CARO

**An evidence-grounded, uncertainty-aware decision engine for used-car listings.**

CARO estimates a market range for a listing, then tries to prove itself wrong.

```
python3 -m pip install -e .
make test        # 241 assertions, no API key, no network
make winrate     # the number that decides whether this product should exist
make demo        # regenerate demo/index.html from live pipeline output
make policy      # print the confidence rulebook
```

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
      SourceAdapter(s)              ← caro/ingest — deterministic, not agents
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
| **Live crawler against a marketplace** | ❌ not in this repo |
| **Real corpus** | ❌ every number here comes from a synthetic corpus |

**Synthetic validation proves the implementation is correct. It does not prove the product is right about the market.** Those are different claims and this repo only makes the first one.

## Repository layout

```
caro/            ingest · tracking (W0) · appraisal (W1) · ranking (W3) · agents (W2)
tests/           241 assertions across the four layers
demo/            export_demo.py regenerates index.html from real output
docs/            architecture, decisions, evaluation, roadmap
```

## Documentation

- [ARCHITECTURE](docs/ARCHITECTURE.md) — the layers, and which components are deliberately *not* agents
- [DECISIONS](docs/DECISIONS.md) — the design record, including bugs found and what they cost
- [EVAL](docs/EVAL.md) — how the benchmark harness was itself validated
- [ROADMAP](docs/ROADMAP.md) — the honest gap list

## License

MIT.
