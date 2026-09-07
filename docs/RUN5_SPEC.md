# Run 5 — pre-registration

**Status: FROZEN, NOT STARTED.** Written before any request was sent. Every
number below comes from `scripts/run5_target.py`, which derives it from the
Run 3 snapshot; re-run it to check this document rather than trusting it.

The point of registering this in advance is narrow and specific. D34 returned
`UNJUDGEABLE_SLICE`, and the single most likely way to waste that result is to
collect data, find the slices still short, and relax a threshold — 5, or 70%,
or 58 — because at that moment it will look like a technicality. Each of those
numbers was set for a reason that does not change when collection is
inconvenient. Fixing them here, before anyone is invested, is the only time
the decision is cheap.

---

## 0. The finding that changed the plan

The obvious plan was "collect roughly twice Run 3". It cannot work, and the
reason is structural rather than a matter of degree:

    thin slice   rows in trims with FEWER than 5 listings   (needs n ≥ 58)
    coverage     share of rows in trims with 5 OR MORE      (D30 wants ≥ 70%)

They are complements of each other. So:

| strategy | eligible | trims | thin | held-out | coverage | verdict |
|---|---|---|---|---|---|---|
| deepen — more listings in the trims we have (D31) | — | — | — | — | — | **unreachable** |
| broaden — new trims, same size mix as now | 229 | 74 | 107 | 62 | 40% | fails D30 |
| **mixed** — every trim over the floor, plus enough thin ones | **312** | **62** | **60** | **76** | **76%** | **ok** |

**Deepening is unreachable, and that is a finding rather than a bug.**
D31 chose to deepen existing trims precisely because it raises conditional
coverage. It does — and it empties the thin slice while doing it, because a
trim that gains a fifth listing stops being thin. Pushed far enough, the thin
slice has nothing in it and can never reach 58. The two frozen gates pull in
opposite directions on acquisition strategy, and neither pure strategy
satisfies both.

This is exactly the thing that had to be discovered on paper. Found in week
two of collecting, it arrives as pressure to move a threshold.

## 1. Budget

**576 requests, hard cap.** Detail pages, trim pages, `robots.txt`, redirects
and errors all count. Run 3 spent ~314.

Derivation: 312 eligible ÷ 0.701 eligible-per-fetch (measured in Run 3, not
assumed) = 445 detail pages; ~56 trim pages to enumerate them; ×1.15 for
duplicates and dead slugs.

The cap bounds what a bug can cost. It is not a plan to spend it, and hitting
it is a stop, not a budget increase.

## 2. Target

**312 appraisal-eligible listings, in a specific shape:**

- ~62 distinct trims
- every well-observed trim at **5 or more** listings
- enough trims left below the floor to hold **≥58** listings in the thin slice
- conditional coverage **≥70%**

The shape is the requirement, not the count. 312 listings collected the
obvious way — deepest models first — satisfies neither gate, and the count
alone would read as success. A run that reports "312 eligible ✓" without the
shape has not done the experiment.

## 3. Stopping rule

Stop at whichever comes first:

1. the target shape in §2 is met — **success**;
2. the 576-request cap is reached — **stop and report what the corpus is**;
3. the route is measured to be unable to supply the shape — **stop and report
   the ceiling** (D28's standing rule: measure the route's own ceiling before
   concluding anything about the market; D31 found a 63% ceiling this way);
4. anything in §4 would have to change to continue — **stop**.

Not a stopping rule: "the numbers look good enough". Not a stopping rule:
"one more model would probably do it".

## 4. No-tuning rule

Frozen for the duration. Changing any of these ends Run 5; it does not amend
it, and the result is reported under the changed conditions as a different
experiment.

| frozen | value | set by |
|---|---|---|
| estimator | `PartialPoolingQuantiles`, all hyperparameters | D32 |
| shrinkage | empirical-Bayes λ = τ²/(τ² + σ²/n) | D32 |
| gate | `HierarchicalGate`, conjunctive | D33 |
| `MIN_SLICE_N` | 58 | 2.5 SE on a 15-point deviation |
| `MIN_PER_TRIM_FLOOR` | 5 | D30 / data contract |
| `THIN_TRIM_MAX` | 4 | D32 |
| hold-out fraction | 0.25 | D34 |
| split seed | 0 | D34 |
| coverage requirement | 70% | D30 |
| eligibility | `caro.ingest.quality.eligibility` | D22 |
| price/mileage validity | unchanged | D20, D22 |
| `seller_type` | diagnostic, never a feature | D26 |

The estimator is not refitted, retuned, or re-specified after seeing the new
corpus. That is the whole content of D35: *acquisition and estimator do not
change in the same run*, because after they both move, no result can be
attributed to either.

## 5. Split rule

Unchanged from D34: `held_out_trim_split(fraction=0.25, seed=0)`, holding out
entire **trims**, not rows. Thin slice is `THIN_TRIM_MAX`-or-fewer within the
training set.

Lowering the fraction would grow the held-out slice without collecting
anything. That is the specific move this section exists to forbid.

Single-snapshot limitation, carried forward: there is no time dimension, so
`cluster_temporal_split` cannot run and Run 5 says nothing about temporal
generalisation. A second snapshot is the separate experiment that would.

## 6. PASS

`HierarchicalGate` returns `ACCEPTED` — all of:

- both judgeable slices at n ≥ 58;
- calibration deviation within 2.5 binomial SE on every judged slice;
- model MAE beats the parent-median baseline;
- extrapolation flagged wherever λ or n says it happened.

What PASS licenses: **the estimator has earned a benchmark it can be judged
on, and passed it.** Not "CARO knows what cars are worth". Serving is a
further decision with D30's preconditions above it (D36 tier: mechanism, not
market fact).

## 7. REJECT

The gate returns `REJECTED`: the slices were judgeable and the model failed
one.

**This is a valid result and the run succeeded.** It says partial pooling does
not support trim-level conditional appraisal on Bama data — a real finding,
worth more than the question staying open. It is not a reason to retune and
re-run; that would be a second experiment, and it would have to say so.

## 8. UNJUDGEABLE

The corpus still cannot judge a slice. Report **which** slice, **how short**,
and **whether the route can supply the difference** — the last is what
separates "collect more" from "this route cannot answer this question", and
D31 has already shown the second is possible.

Do not re-run with adjusted thresholds. `UNJUDGEABLE` twice is a statement
about the source, and a much more useful one than a passing number obtained by
moving 58.

## 9. Acquisition rules (frozen, inherited)

- `robots.txt` checked and enforced in code (`assert_allowed`); a disallowed
  URL raises rather than warning.
- No anti-bot evasion, no rotation, no session or OTP handling. If the source
  blocks us, that is `UNKNOWN` and gets recorded (D1) — never treated as
  absence.
- Deduplication by listing id across all arms, before any count is reported;
  Run 3's 15% cross-arm overlap is why counts and unique counts are separate
  columns.
- No phone numbers, no personal identifiers, ever. `seller_fingerprint` is a
  salted hash used only for dedup, and refuses to run without
  `CARO_SELLER_SALT`.
- Politeness: unchanged rate limiting, one worker.

## 10. Request envelope

| | |
|---|---|
| eligible per detail fetch | 0.701 *(Run 3, measured)* |
| detail fetches for 312 eligible | 445 |
| trim pages to enumerate them | ~56 |
| duplicates and dead slugs | +15% |
| **hard cap** | **576** |

The conversion rate is Run 3's own, not an optimistic one. If the real rate
comes in lower, the cap binds before the target — which is §3 case 2, a
reportable outcome, not a reason to raise the cap.

## 11. What gets recorded

Run 5 must be replayable from the repository with no network:

- `data/snapshots/run5/listings.json` — raw pages, positionally encoded, as
  Run 3 did, so parsing can be re-run against changed code;
- `data/snapshots/run5/arms.txt` — per-record acquisition arm;
- request log: URL, status, timestamp, bytes — including redirects and
  errors, because Run 3's `?page=N` redirect was only visible in the log;
- `docs/RUN5_<date>.txt` — the funnel (fetched / parsed / usable / eligible),
  per-model ladder, stratification, and the gate verdict;
- `docs/BENCHMARK_RUN5_<date>.txt` — the three slices and the verdict, in the
  same format as D34's, so the two are directly comparable;
- this file, unmodified, with the commit it was frozen at.

If the run produces a number that is not reproducible from those files, the
number does not count.

---

**Not started.** Nothing here executes until there is an explicit decision to
run it.
