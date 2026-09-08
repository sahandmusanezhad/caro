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

## 6. What D45 changed about this protocol, before it ran

The protocol was registered with the primary objective *does the detail
extractor record the condition block*. Checking the earlier snapshot first
answered a different and better question, and the objective is narrowed
accordingly — **this amendment is made before the first request, and its
direction is to make the objective harder to satisfy, not easier.**

D45: Run 3 recorded condition on 214/221 listings; Run 5 recorded it on 0/403.
So the extractor *can* record it and once did. `scripts/rank_run3.py` then
showed the downstream effect offline: the risk term goes from absent to a
six-valued column, ledger completeness 38% → 50%, and the accident
deal-breaker excludes 3 cars instead of 0.

That is the offline half of the objective, met at zero request cost. What
remains is the half no existing data can answer:

    PRIMARY   does the COLLECTION PATH record the condition block?
              success = COND non-empty on ≥ 90% of collected detail pages

    "the parser can read it" is now proven and is no longer the claim. The
    claim is about the collection, which is where it was lost.

## 7. Corpus, budget, stopping rule, hard stop

**Selection rule, fixed before the first request.** The 12 trims with the most
appraisal-eligible rows in Run 5, ties broken by ascending `model_key`. It uses
only Run 5's own data, it is deterministic, and it is stated here so the
selection cannot be revised after seeing what came back. Applied, it yields:

    Chery|arrizo5|atexcellent   7    Geely|emgrand7|at 2014      6
    JAC|j5|at                   7    IKCO|Dena|plus basicmanual  6
    MVM|110|3cylinder           7    IKCO|Samand|lx basic        6
    Mazda|323|at                7    Lifan|x50|at                6
    Besturn|b30|at              6    Mg|360|atturbo              6
    Capra|2|4wd                 6    Peugeot|206|type1           6

    76 eligible rows across the 12 in Run 5.

**This is a deliberate re-visit, and calling it "natural overlap" would be a
lie.** Overlap here is engineered by construction: the same trims are
collected again on purpose. So the quantity being measured is **persistence**
— of trims Run 5 found, how many still carry listings, and how many listings
recur — and not the natural overlap a fresh discovery pass would produce.
A future benchmark cannot cite this as evidence that natural overlap exists.

    BUDGET        120 requests, hard cap
                  12 trim pages + up to 8 detail pages per trim (96)
                  24 spare, for retries and for a trim page that paginates

    STOPPING      stop at 120 requests, or when all 12 trims are done,
                  whichever comes first. A trim that returns nothing is
                  recorded as returning nothing and is not replaced —
                  substituting a trim that "works" is selection after the
                  fact.

    HARD STOP     if the collection does not fit the available time, or if
                  the condition block does not record, the benchmark is NOT
                  touched again. Record the video. This does not depend on
                  the result and is not revisable once collection starts.

**What is recorded per listing.** The Run 5 eleven-field record, with COND
filled, plus the three fields the detail page publishes beside it and Run 5
never carried: body colour, interior colour, gearbox. `DESC` stays empty, on
purpose and for the same reason as before — descriptions carry masked phone
numbers and no eligibility or estimator rule reads them.

## 8. The sentence that closes it

> **A favourable overlap or coverage result does not retroactively alter
> Run 5.** Run 5 stands as registered — REJECTED under v1, with D39's interval
> attached. Nothing collected here can change that, and a later document that
> reads Snapshot-2 as revising Run 5's verdict is the thing this protocol
> exists to prevent.
