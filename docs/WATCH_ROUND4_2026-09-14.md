# Round 4 — the daily bucket arrives, a listing disappears, and the answer is quarantined

`data/observations/date_watch.jsonl`, 80 observations, four passes.
Everything below is read out of that file. Nothing was fetched to write it.

```
    pass 1   2026-09-12 09:57 UTC   v1
    pass 2   2026-09-12 15:44 UTC   v1      5.78 h
    pass 3   2026-09-13 11:45 UTC   v3     20.03 h
    pass 4   2026-09-14 15:21 UTC   v4     27.60 h   ← the first ≥24h interval
```

---

## 1. The ≥24h bucket exists now, and it is the frozen set again

```
    24h or more: 17 comparable transition(s) — forward 0, unchanged 17, BACKWARD 0
```

Seventeen. The sample is twenty. The three that are not in it:

```
    bama:xlyildqb    became unreadable            (see §3)
    bama:msy1ffh6    unreachable both times
    bama:l39y2bdi    representation changed       (see §4)
```

So the seventeen are seventeen of the eighteen listings whose title date has
not changed once in four passes over fifty-three hours — checked directly, not
inferred from the class counts: **all eighteen are byte-identical across all
four rounds.**

This is the same shape round 3 had, one bucket up. The number answers "do
these seventeen static listings move over a day", and they do not. It is worth
having and it is not the question. The question is about a field that moves,
and the only listing in the sample that moves is excluded again.

## 2. What DID move, and it is the phrase that makes it legible

`bama:l39y2bdi`, four passes, every field:

| observed (UTC) | title says | = ISO | phrase | v |
|---|---|---|---|---|
| 09-12 09:59 | `1405/6/20` | 2026-09-11 | «۲۲ ساعت پیش» | 1 |
| 09-12 15:46 | «امروز شنبه ۲۱ شهریور» | 2026-09-12 | «امروز» | 1 |
| 09-13 11:48 | «امروز یکشنبه ۲۲ شهریور» | 2026-09-13 | «امروز» | 3 |
| 09-14 15:22 | «امروز دوشنبه ۲۳ شهریور» | 2026-09-14 | «امروز» | 4 |

Three consecutive days on which the declared date equals the day we looked.

The report flagged the phrase for it:

```
    phrase INCONSISTENT bama:l39y2bdi: +0 day(s) over 27.6h
```

That is not noise. A phrase rendering elapsed time cannot stay at «امروز»
across 27.6 hours unless **the event it counts from keeps moving.** The phrase
and the title agree, which is the corroboration rounds 1–3 did not have: two
independently rendered fields both resetting, daily, on one listing.

And the first row is what stops this being the trivial explanation. At 09:59
on 09-12 the page said `1405/6/20` — the day BEFORE — with «۲۲ ساعت پیش»
beside it, an elapsed-time phrase pointing at roughly the same moment. A field
that simply prints today's date cannot produce yesterday, and cannot produce a
phrase that agrees with yesterday. The eighteen frozen listings say the same
at scale: if the title carried the render date they would all read 09-14, and
they read 08-15 through 09-10.

### The leading reading, and what still keeps it from being a finding

The economical account is that **this listing is being re-published daily**,
and the declared date is the date of the most recent re-publication — which is
the "start of the current listing spell" that `DATE_SEMANTICS` had to retract
on 2026-09-12 for want of evidence.

The evidence is better now and it is still one listing:

- it does not establish WHICH event re-stamps it — a bump, a re-post, an
  automated dealer refresh, an edit — only that something does, daily;
- one listing out of twenty behaving this way is consistent with "the other
  nineteen are simply never bumped", and equally consistent with this one
  being a different KIND of listing whose date field works differently;
- and the retracted sentence stays retracted until a second listing does the
  same thing. One case that fits a story is not the story.

## 3. The first disappearance this project has actually watched happen

```
    bama:xlyildqb   09-12 09:57  200 PRESENT
                    09-12 15:44  200 PRESENT
                    09-13 11:45  200 PRESENT
                    09-14 15:21  410 UNREADABLE
```

Present three times, then gone. That is **not** what `msy1ffh6` is —
`msy1ffh6` has returned 410 on every pass since the first, so it was never
observed present and its absence establishes nothing about when it went.

This one is the other kind. `duration_stats` needs observed disappearances:
a listing seen present and later seen absent, with both sides in the series.
This is the first of those, and the count it needs is ≥30.

What it does NOT say, and the temptation is the whole reason to write it down:

- **not a sale.** 410 is the source declining to serve a URL. A listing can be
  withdrawn, edited into a new id, taken down by the marketplace, or removed
  by a seller who changed their mind.
- **not a date.** It went somewhere inside a 27.6-hour window. That is the
  resolution of this series, not a timestamp, and a daily series can never do
  better than a day.
- **not a duration.** Its title date was 2026-08-15, the oldest in the sample,
  which makes "up about thirty days, then gone" a tempting sentence. It is one
  observation of one listing and the thirty days are a lower bound on a spell
  whose start is a field of unknown semantics (§2).

## 4. The answer to the question round 4 was run for is in the file, quarantined

`l39y2bdi`'s pass-3 record was written by v3, which could not read
«۲۲ شهریور». Pass 4 is v4, which can. So the 27.6-hour transition is classed
`representation changed` and kept out of the comparable count — correctly:
one side has no value to compare.

But `--reanalyse` has already read pass 3's stored title with v4 and gets
2026-09-13. Against pass 4's 2026-09-14 that is a **forward** transition over
27.6 hours — the first ≥24h movement in the series, on the only listing that
moves — and it is deliberately not counted, because one side of it is a value
derived today from bytes fetched yesterday.

That is the design working, not a limitation to route around. The fix is a
pass, not a rule:

    round 5, ≥24h after 2026-09-14 15:21 UTC, is v4 against v4,
    and gives this listing its first uncomparable-to-nothing pair.

Nothing needs changing before it. Run it after **2026-09-15 15:21 UTC**.

## 5. Smaller things this round confirmed

- `phrase disappeared 3` in the ≥24h bucket. `DATE_SEMANTICS` §3 recorded that
  the relative phrase stops being rendered as a listing ages; three more
  crossed that threshold in a day. Consistent, and still a rendering rule
  rather than a fact about the market.
- Extraction over eighty observations: `PRESENT 73`, `UNREADABLE 5`,
  `ABSENT_IN_SOURCE 1`, `PRESENT_BUT_UNPARSED 1`. The last two are both
  `l39y2bdi` under v1 and v3, and both are now superseded by re-analysis —
  which is to say the vocabulary's two "I could not read this" verdicts were
  both about the extractor and both were correctly labelled as such at the
  time.
