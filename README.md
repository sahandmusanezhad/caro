# CARO

**An evidence-grounded, uncertainty-aware decision engine for used-car listings.**

CARO estimates a market range for a listing, then tries to prove itself wrong.

```
python3 -m pip install -e .
make test        # 190 assertions, no API key, no network
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
    │  W2  agents      │  evidence → comparables → estimate → risk
    │                  │  → adversarial → judge → explanation
    └────────┬─────────┘
             ▼
     Verdict + Evidence Ledger
```

| Layer | Module | What it guarantees |
|---|---|---|
| **W0** | `caro/tracking.py` | A failed fetch is never an absence. A disappearance is never a sale. A blocked crawl cannot corrupt the history. Reposts link on precision, never on a guess. |
| **W1** | `caro/appraisal.py` | No physical car appears on both sides of a split. Quantiles cannot cross. An unbenchmarked estimator cannot serve a number. |
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
| **Live crawler against a marketplace** | ❌ not in this repo |
| **Real corpus** | ❌ every number here comes from a synthetic corpus |
| **Ranking a candidate set by user intent** | ❌ not built — see ROADMAP |

**Synthetic validation proves the implementation is correct. It does not prove the product is right about the market.** Those are different claims and this repo only makes the first one.

## Repository layout

```
caro/            tracking (W0) · appraisal (W1) · agents (W2) · ingest
tests/           190 assertions across the three layers
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
