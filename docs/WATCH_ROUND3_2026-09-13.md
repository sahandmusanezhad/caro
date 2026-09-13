# Round 3 — the interval that was not reached, and the listing nobody could read

`data/observations/date_watch.jsonl`, 60 observations, three passes.
Everything below comes from that file. Nothing was fetched to write it.

```
    pass 1   2026-09-12 09:57 UTC   v1
    pass 2   2026-09-12 15:44 UTC   v1      5.78 h after pass 1
    pass 3   2026-09-13 11:45 UTC   v3     20.03 h after pass 2
```

---

## 1. There is still no transition over 24 hours

The report's header says `span 25.9 hours (1.08 days)`, and that is the
distance from the FIRST observation to the LAST. It is not an interval any
transition was measured across. The transitions are consecutive pairs — which
is the correct pairing, and the reason the correct pairing matters is visible
right here:

```
    first → last span              25.81 h     crosses a day
    largest consecutive interval   20.03 h     does not
```

So round 3 did not answer the question it was run for. The report says so
itself, in the one line that counts:

```
    No backward transition across 36 comparable
    transition(s), of which 0 span 24h or more.
```

Zero. The threshold was 2026-09-13 15:44 UTC — twenty-four hours after pass
2 — and pass 3 ran at 11:45, three hours and fifty-nine minutes early. A
calendar day had passed; a day had not.

That distinction is the same one the report was fixed to make, arriving from
the other side: it was counting calendar days instead of rounds, and now the
operator counted a calendar day instead of an interval. The fix moved the
error from the code into the schedule, which is progress only if the schedule
is stated. **Round 4 must run at least 24 h after 2026-09-13 11:45 UTC — so
2026-09-14 11:45 UTC or later.**

## 2. The statistic that looks like an answer is computed on the frozen set

`36 comparable transition(s) — forward 0, unchanged 36, BACKWARD 0` reads like
evidence about a mutable field. It is not. Eighteen listings × two consecutive
pairs = thirty-six, and those eighteen are exactly the listings whose date has
not moved since the watch began:

```
    2026-08-15   08-23   08-24   08-26   09-04   09-06   09-07   09-07
    09-09        09-09   09-09   09-10   09-10   09-10   09-10   09-10
    09-10        09-10
```

Every one identical in all three passes. Meanwhile the two listings that are
NOT in that set are the only two with anything to say, and both are excluded:

```
    bama:msy1ffh6   HTTP 410 in all three passes   → UNREADABLE
    bama:l39y2bdi   title in a form the parser cannot read → not comparable
```

So the monotonicity line measures the eighteen listings that never move, and
reports that they did not move. **A statistic computed over the static subset
is not evidence about the dynamic one**, and more rounds of the same will add
more of it. This is the finding of round 3.

## 3. `l39y2bdi` moved again — twice — and the parser cannot see it

The one listing `DATE_SEMANTICS` flagged as having moved once now has three
readings. The Jalali conversions are the script's own `jalali_to_iso`:

| pass | observed (UTC) | title says | = ISO | observation day |
|---|---|---|---|---|
| 1 | 09-12 09:57 | `1405/6/20` | 2026-09-11 | 2026-09-12 |
| 2 | 09-12 15:46 | «امروز شنبه ۲۱ شهریور» | 2026-09-12 | 2026-09-12 |
| 3 | 09-13 11:48 | «امروز یکشنبه ۲۲ شهریور» | 2026-09-13 | 2026-09-13 |

Forward, one day at a time, on a listing that stayed live throughout.

### What this refutes

The cheapest explanation for a date that equals today is that it IS today —
that the field renders the request date and says nothing about the listing.
Passes 2 and 3 are both consistent with that. **Pass 1 is not.** At 09:57 on
2026-09-12 the page declared `1405/6/20`, which is the day BEFORE the fetch.
A render-date field cannot produce yesterday.

The eighteen frozen listings say the same thing at scale: if the title carried
the render date, all of them would read 09-12 and 09-13. They read 08-15
through 09-10 and never moved.

    the title date is NOT the render date.

That is one rival closed by measurement rather than by argument, and it is the
first thing about this field that has been closed at all.

### What this does NOT establish

- **Which event moves it.** A renewal, a bump, an edit, a re-post — the data
  distinguishes none of them. One listing moving while eighteen do not says
  the cause is specific to that listing, not that it is any particular cause.
- **That a cache is not involved in pass 1.** A stale response at 09:57
  would produce the same reading. Two fetches minutes apart would test it;
  none were taken.
- **Anything about monotonicity.** Two forward steps on one listing is two
  observations of one listing. The field has now been seen to move four times
  in this project's history and never seen to move backwards, which is
  consistent with monotonicity and is not close to establishing it.

### And the parser is blind to exactly this listing

`_JDATE` reads `۱۴۰۵/۶/۲۲` and nothing else. `_DATEISH` knows the Persian
month names — which is why pass 3 says `PRESENT_BUT_UNPARSED` and not
`ABSENT_IN_SOURCE`, and that is the vocabulary working as designed. But
"date-shaped and unreadable" keeps the listing out of every comparison, so:

    the only listing in the sample that moves
    is the only listing whose date cannot be parsed.

Round 4 against the current parser will produce a third pair for the eighteen
and nothing for this one. The question stays open by construction.

The raw title is recorded verbatim in every observation, so this is fixable
without re-observing anything: the stored strings can be re-read. That is a
change to the instrument and it is not made in this document.

## 4. A correction: the absence was a 410, not a 404

`DATE_SEMANTICS_2026-09-12.md` records «1 gone (404 — the first absence this
project has ever observed)». The file says otherwise, in all three passes:

```
    bama:msy1ffh6   http_status 410   410   410
```

410 is Gone, not Not Found — the source stating the resource is deliberately
and permanently removed rather than merely missing. That is a stronger claim
by the source, and it is still one endpoint's claim about one URL: not a sale,
not a deletion date, not time-on-market. `duration_stats` still needs ≥30
observed disappearances and a present/absent series per listing; this is one
URL, unreachable three times.

The correction matters less for what 410 means than for how it got recorded
wrong: the status was in the data from the first round and the prose said
something else.

## 5. What round 4 must be

1. **After 2026-09-14 11:45 UTC.** Not "tomorrow" — an interval.
2. Against a parser that can read «۲۲ شهریور», or it will add thirty-six more
   unchanged pairs from the frozen set and nothing else.
3. And with the version consequence stated: every pair spanning an extractor
   change is tagged `legacy`, correctly. The stored raw titles mean a rule
   change can be applied backwards to what is already recorded, so the series
   can be re-read rather than restarted — but that is a decision about the
   instrument, and it belongs in its own change.
