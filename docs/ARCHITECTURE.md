# Architecture

## Three layers, one boundary

```
SourceAdapter → W0 tracking → W1 appraisal → W2 decision → Verdict
```

Each layer is frozen before the next is built on it. W0 does not know W1 exists;
W1 does not import W2. The dependency arrow only ever points one way.

## Deliberately NOT agents

This is the section worth reading. Anyone can add agents; knowing where they
must not go is the actual skill.

| Component | Why it is deterministic code |
|---|---|
| Price / mileage / date parsing | Regex is faster, cheaper, exact and testable. An LLM here is strictly worse. |
| Repost identity | Hashing and similarity scoring. An LLM would be slower, costlier and less precise — and a false link fabricates vehicle history. |
| Snapshot integrity | A rate-limit block must be caught by a rule, not a judgement call. |
| Market estimate | Must be reproducible, backtestable and decomposable. An LLM cannot be backtested. |
| Risk scoring | A fixed rubric over extracted flags. Consistency beats nuance. |
| **Adversarial review** | **A reviewer that can be argued with is not a reviewer.** |
| Evidence ledger | A validator must be incorruptible, so it cannot itself be a model. |
| Confidence policy | A published rulebook the reader can audit line by line. |
| Source adapters | Fetching and parsing are engineering, not reasoning. |

**The line:** LLMs handle *language* — reading messy prose, phrasing an
explanation. Deterministic code handles *numbers, ranking, and truth-checking*.
A system that asks an LLM to subtract two prices is not an AI product; it is a
demonstration that the builder does not know where the boundary is.

## The single LLM entry point

`ExplanationAgent` receives a **frozen** `Verdict` plus the evidence ledger and
renders Persian prose. It runs after every decision is made. It has no path to
alter a number, a confidence level or an outcome — `Verdict` is
`@dataclass(frozen=True)` and a test asserts that mutation raises
`FrozenInstanceError`.

The shipped implementation is template-based, which is why the demo needs no
API key. Swapping in a model changes the phrasing and nothing else.

## Judge priority

Resolved by **priority, never by vote**:

```
1. data integrity          a suspect snapshot beats everything
2. hard contradictions     a veto is a veto
3. benchmark acceptance    an unbenchmarked estimator cannot serve
4. statistical estimate
5. comparable evidence
6. language interpretation ← can never overturn 1–5
```

A hard finding — out-of-distribution price, never-confirmed-present — returns
`reject` regardless of how good every other signal looks.

## Runtime pipeline

```
EvidenceAgent      observation history, gaps, reposts, price changes
ComparableAgent    which rung of the relaxation ladder, and how many
EstimationAgent    quantiles, if and only if the gate passed
RiskAgent          deterministic flags over the evidence packet
AdversarialAgent   five checks that try to invalidate the conclusion
Judge              priority resolution, confidence downgrade
ExplanationAgent   renders the frozen verdict
```

`AgentTrace` records all seven. `EvidenceLedger` records every claim and the
observations behind it. Both are surfaced in the demo page, from real output.
