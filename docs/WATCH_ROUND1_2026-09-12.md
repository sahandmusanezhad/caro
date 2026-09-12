# Round 1 of the watch, analysed — two findings, no new requests

`data/observations/date_watch.jsonl`, 20 observations, 2026-09-12 09:57 UTC.
19 fetched, 1 absent. Everything below comes from that file; nothing was
fetched to write it.

---

## 1. The province anchor: 19 of 19, and there is no second template

Anchored on the mileage line, recorded for every page rather than only the
ones carrying a relative phrase:

```
    کارکرد N کیلومتر  /  صفر کیلومتر      ← the anchor
    <age slot>                            ← phrase (14)  OR  1405/6/13 (5)
    <location>                            ← 19 of 19
```

The five pages with no relative phrase are **not a different template.** They
render the same slot as an absolute Jalali date. One template, one slot, two
renderings of the same thing — relative while recent, absolute once old.

So the earlier reading — "a full page with no phrase is a second template the
positional rule does not cover" — is wrong, and the province conclusion
changes with it:

| | |
|---|---|
| earlier | rule confirmed on 14 of 19; anchor unusable on 26% |
| now | **rule holds on 19 of 19 with the mileage line as the anchor** |

That is a candidate worth writing a parser test against. It is still one
sample of nineteen from one make family on one day, so it is a candidate and
not a decision.

## 2. The age slot and the title may be one field, not two

`DATE_SEMANTICS_2026-09-12.md` says the title date and the relative phrase
"are not the same quantity". Round 1 makes that doubtful.

Comparing, per listing, the title date against the date the phrase implies
(observation day minus the phrase's whole days):

```
    agree                 3
    phrase is +1 day     11
    phrase is earlier     0
    differ by ≥2 days     0
    no phrase             5   (absolute date in the slot instead)
```

**Every single disagreement is exactly one day, in one direction.**

Two independent events — a posting and a later bump — would scatter: some
listings hours apart, some weeks, some in either order. A one-sided,
one-day-maximum offset is instead what you get from ONE timestamp rendered
two ways: a calendar date on one side, and whole elapsed 24-hour blocks on
the other, which disagree exactly when the time of day of the posting is
later than the time of day of the observation.

This is a hypothesis with a regularity behind it, not a result. It is
recorded because it points the other way from what the previous document
concluded, and that document is corrected to match.

### The prediction, written before round 2

If it is one timestamp rendered twice:

- the title date of a listing that is not touched **stays put**;
- its phrase advances by exactly one day per day;
- a listing whose title date moves has its phrase reset at the same time.

If they are two fields, phrases and title dates will move independently, and
a disagreement of more than one day will appear.

Round 2 separates these. Nothing needs to be argued in between.

## 3. What round 1 cannot say

- **Nothing about monotonicity.** One round has no transitions. The report
  says so and declines to comment, which is the honest output of one round.
- Nothing about which event moves either rendering.
- Nothing about the 404 beyond what was already recorded: one URL, not
  retrievable, once.

## 4. Extraction status, as a check on the instrument

```
    PRESENT      19
    UNREADABLE    1     (the 404)
```

No `ABSENT_IN_SOURCE` and no `PRESENT_BUT_UNPARSED`. After three rounds of
this script reporting absence where there was none, that distribution is
worth seeing: the date was found and parsed on every page that answered.
