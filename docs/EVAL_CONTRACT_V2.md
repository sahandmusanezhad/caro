# Evaluation Contract v2 — registered before Run 6

**Status: FROZEN. Run 6 has not been designed against it yet, and no corpus
for Run 6 exists.**

## Why this exists, and why its timing is the problem

D39 established that `HierarchicalGate`'s MAE criterion is a bare `>` on two
point estimates. Run 5's REJECT sat at +15.3% with a 95% interval of
[−324M, +436M]: the verdict it produced cannot be distinguished from noise.
Running Run 6 against that same criterion would produce another result with
the same defect.

**This contract is being written after a loss, which is the single most
suspicious moment to change an evaluation rule.** D35 exists to forbid
exactly that move. So the defence has to be structural rather than a promise:

> **The v2 rule is strictly harder than v1 in both directions.**
>
> v1 accepted whenever model MAE ≤ 1.10 × baseline — a permissive band that
> Run 5's estimator would have passed at, say, +8%. v2 accepts only when the
> confidence interval lies **entirely below zero**, which is a far higher bar
> than v1 ever set. It also rejects only when the interval lies entirely
> above the tolerance, which is higher than v1's bar for rejection.
>
> A rule rewritten to rescue an estimator would loosen acceptance. This one
> tightens it.

Applied to Run 5's own numbers, v2 returns **UNJUDGEABLE**, not ACCEPTED.
That is the check: the new contract does not hand the previous run a win.
Run 5's registered verdict stands as REJECTED under v1 regardless — v2
governs Run 6 onward and is not retroactive.

## 1. One primary criterion

    ΔMAE = MAE(candidate) − MAE(baseline)     on the Q50 prediction

judged by a **paired cluster bootstrap**, 10,000 resamples, 95% interval.

    CI entirely below 0                      → candidate BEATS baseline
    CI entirely above the tolerance band     → candidate LOSES to baseline
    CI spans either                          → UNJUDGEABLE

Three outcomes, and the third is the one v1 could not express. A comparison
that cannot separate the two models is not a win for either.

## 2. Clustering, and why it is at trim level

Resampling is over **trims**, not rows. Rows inside one trim share a price
level, a parent, and the composition bias of the trim page they came from;
treating 228 of them as independent draws would shrink the interval by
claiming more information than the corpus holds.

This is a modelling choice and it must be reported as one. Every run under
this contract also prints the **row-level** interval beside the trim-level
one — not as an alternative verdict, but so a reader can see which direction
the assumption moves the answer and by how much. If the two disagree about
the verdict, that disagreement is reported and the verdict is UNJUDGEABLE.

Where repost clusters exist (a second snapshot would create them), the
cluster unit becomes the physical car and trims nest inside it. Single
snapshots have no reposts, which is why trim is the unit today.

## 3. Two diagnostics, which never gate

    mean pinball loss across the fitted quantiles
    interval coverage AND interval width, together

They are reported every run and they decide nothing. The reason is stated
because it is the tempting mistake:

> With three gates you get a 2-of-3 vote, and a candidate that loses the
> primary criterion can be declared a winner by two diagnostics. That is
> choosing the metric after seeing the result, one step removed.

The registered sentence is:

    Primary objective:      median point prediction.
    Distributional metrics: explain why the result looks the way it does.

Coverage and width are reported **as a pair, always**. Coverage alone is
gameable by widening the interval until it contains everything; a model
quoting 400M–2.5B has excellent coverage and no product value. Neither
number may be quoted without the other.

## 4. What this contract does not touch

`MIN_SLICE_N` (58), `MIN_PER_TRIM_FLOOR` (5), `THIN_TRIM_MAX` (4), the
hold-out fraction (0.25), the seed (0), D30's 70% conditional-coverage
precondition, the estimator, and the eligibility rules are **unchanged**.

Thin and held-out slices continue to yield UNJUDGEABLE rather than FAIL when
they fall below `MIN_SLICE_N` — they already did, and Run 5's held-out
slice at 51 was reported that way.

## 5. Order of operations

1. This contract is frozen (it is, as of this commit).
2. Run 6 is registered against it — corpus definition, budget, stopping rule
   — **before** any collection.
3. Run 6 runs.
4. Whatever comes out is reported.

Registering the contract and the corpus in one document would let the corpus
be shaped to the criterion. They are separate files and separate commits, in
that order, for that reason.

## 6. The standing risk this contract cannot remove

A contract written after a loss can always be a rationalisation, no matter
how it is argued. The structural defence in the header is the strongest
available and it is not a proof. What would falsify the good faith is simple
and worth stating so it can be checked: **if a later version of this contract
loosens acceptance rather than tightening it, it is the thing this document
claims not to be.**
