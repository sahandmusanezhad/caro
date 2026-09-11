# What the browser actually does on a bama category page

Observed 2026-09-11 in a real browser with the network log open, because the
question — *is there a continuation, what is its mechanism, what does it
cost* — cannot be answered from static HTML. Four page loads total:
`robots.txt`, one category page, one detail page, and no endpoint was called
that the site did not call itself.

No listing prose, no seller contact value and no description text is
reproduced anywhere below. Listings are referred to by id.

---

## 1. robots.txt

```
User-agent: *
Disallow: /uploads/Bamalmages/CampaignBanner/
Disallow: temp.bama.ir/robots.txt
```

Plus eleven `Sitemap:` lines, one of which is `https://bama.ir/sitemap/car` —
the one this project already uses.

- Nothing disallows `/car/`, `/car/detail-…`, or `/api/`.
- There is no `Crawl-delay`.
- The second Disallow line is malformed (a host, not a path) and matches
  nothing.

**This does not make the constraint satisfied.** `caro/ingest/base.py` states
"respect the source's terms of use and robots directives" in a docstring and
nothing in the fetch path reads this file. The rules happen to be permissive
today; a policy that is checked by a human once is not a policy the program
respects. That gap is unchanged by this observation.

## 2. The listings are server-rendered. There is no data call.

Sixty-nine requests on load. Every one is a JS chunk under
`/evonex/chunks/…`, a font, an i18n bundle, or telemetry
(`POST /event/api/v1/events`, `POST /prf/api/user/recent-filters`).

**Not one request fetches listing data.** The cards are in the document the
server returned — which is why `extract_listing_links` finds anything at all,
and why the 897 KB is almost entirely application bundle.

## 3. There is no continuation through this page

Pressing `End` six times produced:

- no further network requests of any kind,
- no additional cards,
- a list that ends at the "ثبت آگهی" call to action.

Seven cards were rendered. No "load more" control, no page links, no total
count anywhere on the page.

**What this establishes:** the pinned category route exposes a small recency
window and nothing beyond it.
**What it does not establish:** that bama has no paginated route at all. A
search route might. This says the route we pin has none.

## 4. The order is recency, now measured rather than assumed

The cards carried, in rendered order:

```
1 ساعت پیش · 5 ساعت · 8 ساعت · 8 ساعت · 10 ساعت · 13 ساعت · 16 ساعت
```

Strictly ascending age. `docs/REPLICATE_2026-09-10.txt` inferred recency
ordering from 13.2% churn in under an hour; this is the same fact seen
directly.

---

## 5. The finding that reframes the whole step

**The source publishes each listing's posting date.**

On listing `thhvbl5m` the document title is:

```
پراید 131 EX فروشی - 1405/6/19 | باما
```

`1405/6/19` is an explicit Jalali date — yesterday, relative to the day of
observation — and the body independently renders «دیروز» for the same
listing. Every card on the category page carries the relative form too.

This was not looked for. It was visible in the tab title.

> **CORRECTED — see `docs/DATE_SEMANTICS_2026-09-12.md`.** Measured the
> next day: the stated date MOVES. One listing states a date after a
> day it was demonstrably live, so it is not a publication date, and
> the claim below that the axis "does not depend on observing
> appearance at all" is too strong. What survives is that the date is
> an UPPER BOUND on the spell start — the same shape as an unobserved
> appearance, which §3 of the contract already knows how to handle.

### Why it matters more than the pagination question

Every step-5 question so far has been in service of one thing: making
`observed_appearance=True` mean *we watched it appear*. That required
enumerating the slice, which required a continuation, which §3 above says
this route does not have.

If the source states when a listing was published, **none of that is needed
for the temporal axis.** `first_seen_on` is read, not observed, and it is
available on the first day of collection rather than after a series.

### What that would contradict

`docs/TEMPORAL_CONTRACT.md` §10 concludes "the prerequisite is not a clock —
it is a collector", and §9 says the projection is worth nothing until
collection runs on more than one day. On this evidence both are wrong about
the benchmark axis. The prerequisite looks like a **parser field**, not a
collector architecture.

That is the second time §10 has been corrected by measurement. It is not
rewritten here — no architecture decision is being taken in this document.

### What this does NOT give, and must not be read as giving

- **Not time-on-market.** A publication date is not a disappearance. Absence
  still requires re-fetching known ids across days, and `duration_stats`
  still needs ≥30 observed disappearances.
- **Not the original posting date, necessarily.** A relisted or renewed ad
  very likely resets this value. It is the start of the CURRENT listing
  spell — which is the right quantity for a temporal split, and the wrong
  one for "how old is this car's presence on the market".
- **Not a repair of Run 11.** Run 11 holds no such field and stays
  `UNJUDGEABLE — missing_temporal_axis`. A corpus with a posting date is a
  new corpus with a new run id and a new sha256.

### Three things to check before anything is built on it

1. Is the date in the JSON-LD block, or only in `<title>`? The parser reads
   `ld.get("name")` and never reads the title tag, so today it sees neither.
2. Is it publication or last-modification? The two differ exactly on the
   listings that matter most — reposts.
3. What is its granularity for older listings? Hours and «دیروز» are visible
   here; a listing from last month may render only a date, or only a month.

---

## 6. A second defect, confirmed by mechanism

`province` is empty on all 76 records of the run 11 snapshot. The cause is
now visible: `parse_detail_page` reads `_labelled(lines, "موقعیت")`, and the
page renders the location with no such label. It is a parser miss, not a
boundary loss and not a source limitation — the value is on the page.

It matters beyond a blank column: `province` is a blocking key in
`tracking.blocking_keys` and a scoring term in `repost_match_score`. Repost
matching has been running with one signal permanently absent.

---

## The three questions, answered

| | |
|---|---|
| **Does a continuation exist?** | Not on the pinned category route. No data request on load, no controls, no response to `End`. |
| **What does it cost?** | Unanswerable — there is nothing to cost. |
| **How big is the slice?** | Unobtainable this way. Nothing states a total. |

And the question those three were serving — *can `observed_appearance` mean
what it says?* — is answered from a different direction: on this evidence the
source states the date, so the axis does not depend on observing appearance
at all.
