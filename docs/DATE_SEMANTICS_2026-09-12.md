# What bama's dates mean, measured

`scripts/date_probe.py --from-corpus run11 --sample 20`, run 2026-09-12
against a corpus collected 2026-09-10. Every sampled listing was provably
live two days before the run; that is the whole leverage.

19 fetched, 1 gone (404 — **the first absence this project has ever
observed**), 0 unreadable.

---

## 1. Where the date lives

**The `<title>`, on 19 of 19. Not in the JSON-LD.**

The 37 distinct JSON-LD key names were enumerated rather than pattern-matched,
and not one denotes a listing date. `productionDate` and `vehicleModelDate`
are the car's model year.

    پراید 131 LE فروشی - 1405/5/24 | باما

So this is not a matter of extending the `ld.get(...)` reads. The parser does
not read the title tag at all, and would need a new extraction path.

## 2. What it means — and the prediction that was wrong

Before the run I predicted **title moved 0, stable 19**, on the reasoning
that the six titles visible in the previous run were all ≥ 2 days old.

Measured:

```
    TITLE DATE   moved  1 · stable 18 · unreadable 0
    PHRASE       moved  7 · stable  7 · absent     5
```

One counterexample, `l39y2bdi`: its title states `1405/6/20` = **2026-09-11**,
a day AFTER the corpus proved it was already live. A publication date cannot
do that.

**So the title date is not a publication date either.** The prediction was
wrong, and it was wrong in the direction that mattered — it would have
licensed reading `first_seen_on` straight off the title.

### The two fields are not the same quantity

Six listings carry title `1405/6/19` (= 2026-09-10) while their phrase says
«دیروز» (= 2026-09-11). If both tracked one event they would agree. They
disagree by exactly one day, on six of nineteen.

What is established:

- both can move forward while a listing stays live;
- the title date is far stickier — 1 of 19 against 7 of 19;
- neither is first publication.

What is **not** established, and should not be guessed: which event each one
tracks. "Title updates on a full edit, phrase on any bump" fits the data and
so do other stories. Distinguishing them needs the same listings observed
again, which is a second run of this script and not an argument.

## 3. Granularity

    title date   day-granular, present on every page, at every age
    phrase       finer when present — hours on the freshest listing — and
                 ABSENT entirely on 5 of 19

All five phrase-less pages are full pages, ~87–101 KB, with spec rows. Their
title dates are the five oldest in the sample: 2026-08-15, 08-23, 08-24,
08-26, 09-04. **The phrase is rendered only for recent listings and stops
being rendered as a listing ages.** The title date does not.

---

## 4. What this does to the temporal contract

### The optimism in NETWORK_OBSERVATION §5 was too strong

That section said "the source states the date, so the axis does not depend on
observing appearance at all". Measured, the stated date **moves**. Third
correction to this line of reasoning, and the pattern is worth naming: each
correction has come from measuring the thing rather than from thinking harder
about it.

### But the contract's machinery survives, because the shape is the same

A date that can only move FORWARD is an **upper bound** on when the listing's
current spell began. That is exactly the shape of
`observed_appearance=False` — a recorded date that the truth sits at or
before — and §3 of `TEMPORAL_CONTRACT.md` already proves what to do with an
upper bound:

> train placement is always sound; test placement never is.

So nothing in §3 is discarded. What changes is the *source* of the bound and
its tightness: instead of "sometime before we started watching", it is a
specific day, available on the first collection, wrong for roughly 1 listing
in 19 over a two-day window.

### And an axis exists today that nobody knew was there

The nineteen title dates span **2026-08-15 to 2026-09-11** — about four
weeks. Run 11's corpus is not a flat instant; it has a temporal spread, and
it always did. `rows_from_corpus` sets `first_seen_ordinal=0` on every row
because nothing ever read the title, not because the listings are
contemporaneous.

This does not rescue Run 11. That artifact carries no such field, its
verdict is frozen at `UNJUDGEABLE — missing_temporal_axis`, and a corpus
built with a posting date is a new corpus with a new id and a new sha256.

### What is still missing, and is not obtainable this way

Time-on-market. A spell start is not a disappearance, and the one 404 in
this sample is one observation, not a series.

---

## 5. Province: the rule is confirmed and the anchor is not usable

On 14 of 14 pages where the phrase appears, the layout held exactly:

```
    کارکرد N کیلومتر   (or صفر کیلومتر)
    [relative phrase]
    <location>
```

Not a coincidence at that count. But the anchor is the phrase, and §3 above
shows the phrase is **absent on 5 of 19 pages — 26%** — precisely the older
listings.

So the positional rule is correct and the anchor is wrong. A province fix
built on it would silently drop a quarter of listings, skewed toward the
long-lived ones. The mileage line is present on all of them and is the
candidate to anchor on instead; that needs its own check before anything is
written.

---

## The three questions, answered

| | |
|---|---|
| **Where?** | `<title>`, every page. Never JSON-LD. |
| **What does it mean?** | Not publication. It moves — rarely for the title, often for the phrase — and which event each tracks is not yet established. |
| **How precise?** | Title: day, always. Phrase: finer, but gone on older listings. |
