# Snapshot-2 — pre-registered, not executed

**Status: FROZEN and NOT STARTED. No request has been made under this
protocol. It is registered so that if it is ever run, it is run against a
document written before the data existed.**

> **This collection is not a repair of Run 5.** It is a separately
> pre-registered observation, intended to test ingestion completeness and to
> measure whether a future evaluation with natural snapshot overlap is
> feasible at all.

D44 decided to stop technical work and record the video. This document exists
because one piece of that work is worth doing *if* the time budget allows, and
because the only safe way to leave it available is to fix its rules now,
before anyone knows what it would return.

## 1. Why this is not the loop D35 forbids

The forbidden chain and this one differ at exactly one link:

    FORBIDDEN                          THIS
    Run 5 fails                        Run 5 frozen
    discover the split problem         D43 diagnostic
    collect overlapping data           pre-register Snapshot-2
    Run 6 passes                       collect independently
    claim the estimator works          measure overlap and support
                                       DO NOT alter Run 5

The difference is not sincerity, it is permission: **this protocol may not
feed a benchmark.** Its outputs are ingestion facts and corpus geometry. If
the results are used to re-run a gate in the same breath, it has become the
forbidden chain regardless of what this section says.

## 2. The registered objective, and what counts as success

    PRIMARY   does the detail extractor record the condition block?
              success = COND: empty → populated

That is an ingestion result and it is independent of every appraisal
question. **If Snapshot-2 establishes only that, it is a complete success**,
even if a future appraisal benchmark fails again or is never run.

    SECONDARY (measurements, not objectives)
              natural trim overlap between snapshot 1 and snapshot 2
              support distribution per trim and per parent
              parent overlap
              train/test price distributions, if a split is ever formed

## 3. Stop conditions — do not benchmark if any holds

    · snapshot-2 has insufficient trim overlap
    · timestamps are insufficient for the intended split
    · source semantics changed
    · the parser introduces unresolved schema ambiguity
    · comparable support remains too sparse

## 4. Positive conditions — a future benchmark may be *designed* only if

    · snapshot overlap is measured
    · support distribution is reported
    · train/test price distributions are reported
    · parent overlap is reported
    · no post-hoc filtering was used to create the overlap

The last is the load-bearing one. Overlap that exists because rows were
dropped until it existed is not overlap.

## 5. The two snapshots are not merged

"Crawl again, merge everything, and the split problem goes away" is the
failure this section prevents. Before any merge is even discussed, report:

    snapshot_1 · snapshot_2 · intersection · new trims · persistent trims

A merge that has not published those five numbers is a corpus of unknown
geometry wearing a larger n.

## 6. Budget and hard stop

Registered like Run 5: a budget in requests, a stopping rule, and a hard stop
that does not depend on the result.

    HARD STOP — if the collection does not fit the available time, or if
    snapshot-2 still lacks support, the benchmark is NOT touched again.
    Record the video.

## 7. The sentence that closes it

> **A favourable overlap or coverage result does not retroactively alter
> Run 5.** Run 5 stands as registered — REJECTED under v1, with D39's interval
> attached. Nothing collected here can change that, and a later document that
> reads Snapshot-2 as revising Run 5's verdict is the thing this protocol
> exists to prevent.
