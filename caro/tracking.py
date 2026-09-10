"""
CARO — longitudinal listing tracking.

The one capability that cannot be reconstructed later. Source-agnostic:
you supply FetchOutcome records from whatever fetcher you write; this module
owns snapshot integrity, repost linking, event derivation, and
censoring-aware time-on-market statistics.

Stdlib only. No network. Run test_tracking.py before trusting it.

Design invariants (do not "simplify" these away):
  1. A listing that disappears is NOT sold. There is no `sold` field.
  2. A failed fetch is NOT an absence. 403/429/5xx/timeout => UNKNOWN.
  3. A snapshot with too many disappearances is SUSPECT and is excluded
     from every longitudinal statistic. A block looks exactly like a
     mass disappearance.
  4. Reposts are linked by blocking + scoring, never by a single hash.
     Precision over recall: a false link fabricates history.
  5. Age is only computable for listings we OBSERVED appear. Everything
     else gets a lower bound. Still-active listings are censored, not
     complete.
"""

from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from enum import Enum
from pathlib import Path
from typing import Iterable, Literal, Sequence

# ---------------------------------------------------------------------------
# Tunables. Revisit after two clean snapshots; do not tune to make numbers
# look better.
# ---------------------------------------------------------------------------

SUSPECT_ABSENT_RATE = 0.20   # > this share absent in one snapshot => SUSPECT
PARTIAL_UNKNOWN_RATE = 0.30  # > this share unresolved => PARTIAL
REPOST_MATCH_THRESHOLD = 0.70
REPOST_WINDOW_DAYS = 14      # a repost must appear within N days of vanishing

# A rate is meaningless on a handful of listings: with 3 tracked cars, one
# ordinary disappearance is a 33% "disappearance rate" and would trip the
# guard on every clean snapshot. Below this many resolved fetches we record
# what we saw and let the human read the counts.
MIN_SAMPLE_FOR_RATE_CHECK = 20


# ---------------------------------------------------------------------------
# Fetch layer — what your crawler hands us
# ---------------------------------------------------------------------------

class FetchStatus(str, Enum):
    OK = "ok"           # fetched, listing present
    ABSENT = "absent"   # fetched, listing definitively gone (404 / removed page)
    UNKNOWN = "unknown" # blocked, throttled, timed out, 5xx — we learned nothing


def classify_http(status_code: int | None, *, removed_marker: bool = False) -> FetchStatus:
    """Map an HTTP result to a fetch status.

    The whole point: only a definitive 404/removed page counts as absence.
    Everything else that isn't a clean 200 is UNKNOWN, because a block and a
    sold-out car are indistinguishable from a non-200 alone.
    """
    if status_code == 200:
        return FetchStatus.ABSENT if removed_marker else FetchStatus.OK
    if status_code in (404, 410):
        return FetchStatus.ABSENT
    return FetchStatus.UNKNOWN


@dataclass
class FetchOutcome:
    listing_id: str
    status: FetchStatus
    http_status: int | None = None
    asking_price_toman: int | None = None
    # Identity signals, only needed for listings seen as OK
    make: str | None = None
    model: str | None = None
    trim: str | None = None
    year_jalali: int | None = None
    color: str | None = None
    province: str | None = None
    seller_fingerprint: str | None = None
    mileage_km: int | None = None
    image_phashes: tuple[str, ...] = ()
    payload_sha: str | None = None

    # Body condition, carried because a snapshot is what survives the run.
    # Everything the parser knew and did not put in a FetchOutcome is gone the
    # moment the process exits, and `promote_corpus` then has nothing to
    # promote. This field was exactly that: extracted on every page, dropped
    # at this boundary, and re-derived downstream as `unknown` for every row —
    # which `ranking.risk_from_condition` prices at 0.35. A corpus in which
    # every car carries the same invented risk cannot rank on risk at all.
    #
    # `None` means this adapter did not record the field. `"unknown"` means it
    # was looked for and not found. Those are different facts and neither is
    # a guess, so they get different values.
    body_condition: str | None = None
    condition_source: str | None = None      # field | description | none

    # Lost at the same boundary, for the same reason, and worth naming
    # separately because each fails differently downstream.
    #
    # `document_issue` is the paperwork flag. Absent, the corpus publishes no
    # value and every consumer treats the car as though its papers are clean.
    #
    # `seller_type` is D26's business-badge inference and the corpus's only
    # proxy for sample independence: thirty listings from one dealer are not
    # thirty observations of a market. `None` and `"unknown"` both mean the
    # badge was not seen — which under D26 must never be read as `private`.
    document_issue: bool | None = None
    seller_type: str | None = None           # dealer | private | unknown


# ---------------------------------------------------------------------------
# Snapshots
# ---------------------------------------------------------------------------

class Integrity(str, Enum):
    OK = "ok"
    PARTIAL = "partial"   # too many unresolved fetches to trust absences
    SUSPECT = "suspect"   # implausible disappearance rate — probably blocked


@dataclass
class Snapshot:
    snapshot_id: str
    taken_on: date
    outcomes: list[FetchOutcome]
    integrity: Integrity = Integrity.OK
    notes: list[str] = field(default_factory=list)

    @property
    def by_id(self) -> dict[str, FetchOutcome]:
        return {o.listing_id: o for o in self.outcomes}

    def counts(self) -> dict[str, int]:
        c = {s.value: 0 for s in FetchStatus}
        for o in self.outcomes:
            c[o.status.value] += 1
        c["total"] = len(self.outcomes)
        return c


def assess_integrity(snapshot: Snapshot) -> Snapshot:
    """Flag snapshots we must not draw longitudinal conclusions from.

    A crawler that gets throttled on day 3 will report hundreds of 404s or
    timeouts at once. Without this guard those become hundreds of fake
    'disappearances' on a single date and the whole time-on-market analysis
    is quietly destroyed.
    """
    c = snapshot.counts()
    total = c["total"]
    if total == 0:
        snapshot.integrity = Integrity.SUSPECT
        snapshot.notes.append("empty snapshot")
        return snapshot

    unknown_rate = c["unknown"] / total
    resolved = c["ok"] + c["absent"]
    absent_rate = (c["absent"] / resolved) if resolved else 1.0

    if total < MIN_SAMPLE_FOR_RATE_CHECK:
        snapshot.notes.append(
            f"n={total} below {MIN_SAMPLE_FOR_RATE_CHECK}; rate-based integrity "
            "checks skipped (a rate on a handful of listings is noise)"
        )
        return snapshot

    if unknown_rate > PARTIAL_UNKNOWN_RATE:
        snapshot.integrity = Integrity.PARTIAL
        snapshot.notes.append(
            f"unknown_rate={unknown_rate:.0%} > {PARTIAL_UNKNOWN_RATE:.0%}; "
            "absences in this snapshot are not trustworthy"
        )
    if absent_rate > SUSPECT_ABSENT_RATE:
        snapshot.integrity = Integrity.SUSPECT
        snapshot.notes.append(
            f"absent_rate={absent_rate:.0%} > {SUSPECT_ABSENT_RATE:.0%}; "
            "probable block or source-side purge, excluded from analysis"
        )
    return snapshot


def write_snapshot(root: Path, snapshot: Snapshot) -> Path:
    """Persist raw, schema-light. Raw snapshots are replayable; a schema
    mistake later then costs nothing."""
    d = root / snapshot.taken_on.isoformat()
    d.mkdir(parents=True, exist_ok=True)
    payload = {
        "snapshot_id": snapshot.snapshot_id,
        "taken_on": snapshot.taken_on.isoformat(),
        "integrity": snapshot.integrity.value,
        "notes": snapshot.notes,
        "counts": snapshot.counts(),
        "outcomes": [
            {**asdict(o), "status": o.status.value,
             "image_phashes": list(o.image_phashes)}
            for o in snapshot.outcomes
        ],
    }
    # Never over a file that is already there. A snapshot is the evidence a
    # later claim rests on, and a writer that can replace one silently makes
    # every such claim uncheckable — which is what happened when two runs on
    # one day shared a name and the second destroyed the first.
    #
    # The guard lives here rather than in the caller that names the file,
    # because only this function knows the directory it is about to write
    # into. The caller's version of this check looked in `today`'s directory
    # while the write went to `taken_on`'s, so a snapshot dated anything but
    # today was unprotected — found by the test, not by reading it.
    p = d / f"{snapshot.snapshot_id}.json"
    n = 2
    while p.exists():
        p = d / f"{snapshot.snapshot_id}-{n}.json"
        n += 1
    p.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


# ---------------------------------------------------------------------------
# Repost identity — blocking + scoring, never a single hash
# ---------------------------------------------------------------------------

def _norm(s: str | None) -> str:
    return (s or "").strip().lower()


def _h(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]


def blocking_keys(o: FetchOutcome) -> list[str]:
    """Several keys of decreasing tightness; a candidate matches on ANY of them.

    A single composite key destroys recall the moment normalisation is
    imperfect — and it will be. "206 Type 5" vs "206 تیپ ۵", or "سفید" vs
    "سفید صدفی", would put a car and its own repost in different blocks and
    the pair would never even reach the scorer.

    So candidate generation is deliberately generous and the DECISION stays
    strict: hard vetoes, then scoring, then the ambiguity gate. Precision is
    enforced where the link is made, not by starving the candidate set.

    All keys exclude price, description, listing id and posted date — the
    fields a seller edits when relisting.
    """
    base = (_norm(o.make), _norm(o.model), str(o.year_jalali or ""))
    return [
        _h(*base, _norm(o.trim), _norm(o.color), _norm(o.province)),  # tightest
        _h(*base, _norm(o.province)),
        _h(*base, _norm(o.color)),
        _h(*base),                                                    # loosest
    ]


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def hard_contradictions(old: FetchOutcome, new: FetchOutcome) -> list[str]:
    """Disqualifying facts. If any hold, these are not the same car — no
    amount of similarity elsewhere may override them.

    Kept separate from scoring on purpose: a contradiction is a veto, not a
    negative weight that a strong image match could outvote.
    """
    out: list[str] = []
    # Only facts that CANNOT be a renormalisation artefact are vetoes.
    # Trim and colour are excluded on purpose — "تیپ ۵"/"Type 5" and
    # "سفید"/"سفید صدفی" are the same car described twice, so they belong in
    # scoring as soft evidence, never here.
    if _norm(old.make) != _norm(new.make):
        out.append(f"different make: {old.make} vs {new.make}")
    if _norm(old.model) != _norm(new.model):
        out.append(f"different model: {old.model} vs {new.model}")
    if old.year_jalali and new.year_jalali and old.year_jalali != new.year_jalali:
        out.append(f"different year: {old.year_jalali} vs {new.year_jalali}")
    # Odometers do not run backwards. Either it is a different car, or the
    # reading was tampered with; both are reasons to refuse the link.
    if (old.mileage_km and new.mileage_km
            and new.mileage_km < old.mileage_km * 0.95):
        out.append(
            f"mileage decreased {old.mileage_km:,} → {new.mileage_km:,}")
    return out


def repost_match_score(old: FetchOutcome, new: FetchOutcome) -> tuple[float, list[str]]:
    """Score the hypothesis that `new` is `old` relisted.

    Returns (score in [0,1], reasons). Tuned for PRECISION: a false link
    fabricates listing history, which is worse than missing a repost.

    Price participates as weak evidence only — a seller who drops the price
    on relisting is the normal case, so a large drop must not by itself
    prove a different car.
    """
    vetoes = hard_contradictions(old, new)
    if vetoes:
        return 0.0, vetoes

    score = 0.0
    reasons: list[str] = []

    # Photos are reused verbatim on reposts — the strongest single signal.
    img = _jaccard(old.image_phashes, new.image_phashes)
    if img > 0:
        score += 0.45 * img
        reasons.append(f"image overlap {img:.2f}")

    if old.seller_fingerprint and old.seller_fingerprint == new.seller_fingerprint:
        score += 0.35
        reasons.append("same seller")

    if (old.mileage_km and new.mileage_km
            and new.mileage_km <= old.mileage_km * 1.10):
        score += 0.15
        reasons.append("mileage consistent")

    # Soft evidence — these are the fields most likely to be renormalised
    # between postings, so agreement counts for something but disagreement
    # is never fatal.
    if _norm(old.trim) and _norm(old.trim) == _norm(new.trim):
        score += 0.05
        reasons.append("trim matches")
    if _norm(old.color) and _norm(old.color) == _norm(new.color):
        score += 0.05
        reasons.append("colour matches")
    if _norm(old.province) and _norm(old.province) != _norm(new.province):
        score -= 0.15
        reasons.append(f"province changed {old.province} → {new.province}")

    # Weak evidence in both directions; never decisive on its own.
    if old.asking_price_toman and new.asking_price_toman:
        ratio = new.asking_price_toman / old.asking_price_toman
        if 0.80 <= ratio <= 1.10:
            score += 0.10
            reasons.append(f"price ratio {ratio:.2f}")
        elif ratio < 0.55 or ratio > 1.45:
            score -= 0.10
            reasons.append(f"price ratio {ratio:.2f} unusual for a repost")

    return max(0.0, min(1.0, score)), reasons


# ---------------------------------------------------------------------------
# Tracked state and events
# ---------------------------------------------------------------------------

EventType = Literal["appeared", "disappeared", "reappeared", "price_change", "reposted"]


@dataclass
class TrackingEvent:
    on: date
    type: EventType
    source_listing_id: str
    snapshot_id: str
    old_asking_price_toman: int | None = None
    new_asking_price_toman: int | None = None
    match_confidence: float | None = None
    reasons: list[str] = field(default_factory=list)


@dataclass
class Observation:
    """One snapshot's verdict on one listing. UNKNOWN is recorded, not
    dropped — a day we could not check is a day we must not fill in."""
    on: date
    status: Literal["present", "absent", "unknown"]


@dataclass
class TrackedListing:
    tracking_id: str
    source_listing_ids: list[str]
    status: Literal["active", "absent"]
    first_observed_at: date
    last_observed_at: date
    # True only if we watched it appear. If it already existed when tracking
    # began, its true age is unknown and every age we report is a lower bound.
    observed_appearance: bool
    observations: list[Observation] = field(default_factory=list)
    current_asking_price_toman: int | None = None
    events: list[TrackingEvent] = field(default_factory=list)
    last_signals: FetchOutcome | None = None

    @property
    def repost_count(self) -> int:
        return sum(1 for e in self.events if e.type == "reposted")

    @property
    def price_changes(self) -> list[TrackingEvent]:
        return [e for e in self.events if e.type == "price_change"]

    # Four different durations. Conflating them is how a frontend or an agent
    # ends up publishing a number that means something other than what it
    # says, so they are named separately and none is called "age".
    #
    #   observed_span      first sighting → last sighting (or now)
    #   confirmed_present  days we actually SAW it listed
    #   confirmed_absent   days we actually saw it gone
    #   unknown            days inside the span we could not check at all
    #
    # The last one is the honest one and the reason this is not just a
    # cosmetic split: if the crawler was blocked on days 1-2, or simply did
    # not run, we must not report those days as "active". A listing could
    # have been pulled and reposted inside a gap and we would never know.
    #
    #   observed_span + 1 == confirmed_present + confirmed_absent + unknown

    def observed_span_days(self, as_of: date) -> int:
        end = self.last_observed_at if self.status == "absent" else as_of
        return (end - self.first_observed_at).days

    def _days_with(self, status: str) -> int:
        return len({o.on for o in self.observations if o.status == status})

    def confirmed_present_days(self) -> int:
        return self._days_with("present")

    def confirmed_absent_days(self) -> int:
        return self._days_with("absent")

    def unknown_days(self, as_of: date) -> int:
        """Calendar days in the span with no usable observation.

        Covers both an UNKNOWN fetch (blocked, throttled, timed out) and a
        day on which no snapshot ran at all. Both are ignorance, and they
        are counted as ignorance.
        """
        span_inclusive = self.observed_span_days(as_of) + 1
        return max(0, span_inclusive
                   - self.confirmed_present_days()
                   - self.confirmed_absent_days())

    def has_unknown_gap(self, as_of: date) -> bool:
        return self.unknown_days(as_of) > 0

    # Deliberately absent: `sold`, `days_to_sale`, `sold_price`, and anything
    # named `age`. We never observed a transaction, so we never name one.


@dataclass
class TrackingState:
    listings: dict[str, TrackedListing] = field(default_factory=dict)
    _seq: int = 0

    def _new_id(self) -> str:
        self._seq += 1
        return f"trk_{self._seq:06d}"

    def active(self) -> list[TrackedListing]:
        return [t for t in self.listings.values() if t.status == "active"]

    def recently_absent(self, as_of: date, window_days: int = REPOST_WINDOW_DAYS):
        cutoff = as_of - timedelta(days=window_days)
        return [t for t in self.listings.values()
                if t.status == "absent" and t.last_observed_at >= cutoff]

    def find_by_source_id(self, sid: str) -> TrackedListing | None:
        for t in self.listings.values():
            if sid in t.source_listing_ids:
                return t
        return None


# ---------------------------------------------------------------------------
# The differ
# ---------------------------------------------------------------------------

def apply_snapshot(state: TrackingState, snapshot: Snapshot, *,
                   is_first: bool = False) -> list[TrackingEvent]:
    """Fold one snapshot into tracking state, returning the events derived.

    SUSPECT snapshots are ignored entirely — we would rather have a gap in
    the series than hundreds of fabricated disappearances. PARTIAL snapshots
    contribute appearances and price changes but never absences.
    """
    if snapshot.integrity is Integrity.SUSPECT:
        return []

    trust_absences = snapshot.integrity is Integrity.OK
    day, sid_snap = snapshot.taken_on, snapshot.snapshot_id
    events: list[TrackingEvent] = []

    for outcome in snapshot.outcomes:
        existing = state.find_by_source_id(outcome.listing_id)

        # ---- known listing --------------------------------------------------
        if existing is not None:
            existing.observations.append(Observation(day, {
                FetchStatus.OK: "present",
                FetchStatus.ABSENT: "absent" if trust_absences else "unknown",
                FetchStatus.UNKNOWN: "unknown",
            }[outcome.status]))
            if outcome.status is FetchStatus.OK:
                if existing.status == "absent":
                    ev = TrackingEvent(day, "reappeared", outcome.listing_id, sid_snap)
                    existing.status = "active"
                    existing.events.append(ev)
                    events.append(ev)
                if (outcome.asking_price_toman is not None
                        and existing.current_asking_price_toman is not None
                        and outcome.asking_price_toman != existing.current_asking_price_toman):
                    ev = TrackingEvent(day, "price_change", outcome.listing_id, sid_snap,
                                       old_asking_price_toman=existing.current_asking_price_toman,
                                       new_asking_price_toman=outcome.asking_price_toman)
                    existing.events.append(ev)
                    events.append(ev)
                if outcome.asking_price_toman is not None:
                    existing.current_asking_price_toman = outcome.asking_price_toman
                existing.last_observed_at = day
                existing.last_signals = outcome

            elif outcome.status is FetchStatus.ABSENT and trust_absences:
                if existing.status == "active":
                    ev = TrackingEvent(day, "disappeared", outcome.listing_id, sid_snap)
                    existing.status = "absent"
                    existing.events.append(ev)
                    events.append(ev)
            # UNKNOWN: learned nothing. Leave state untouched, on purpose.
            continue

        # ---- unknown listing id --------------------------------------------
        if outcome.status is not FetchStatus.OK:
            continue

        match, conf, reasons = _best_repost_match(state, outcome, day)
        if match is not None:
            ev = TrackingEvent(day, "reposted", outcome.listing_id, sid_snap,
                               old_asking_price_toman=match.current_asking_price_toman,
                               new_asking_price_toman=outcome.asking_price_toman,
                               match_confidence=conf, reasons=reasons)
            match.source_listing_ids.append(outcome.listing_id)
            match.observations.append(Observation(day, "present"))
            match.status = "active"
            match.last_observed_at = day
            if outcome.asking_price_toman is not None:
                match.current_asking_price_toman = outcome.asking_price_toman
            match.last_signals = outcome
            match.events.append(ev)
            events.append(ev)
            continue

        tid = state._new_id()
        ev = TrackingEvent(day, "appeared", outcome.listing_id, sid_snap,
                           new_asking_price_toman=outcome.asking_price_toman)
        state.listings[tid] = TrackedListing(
            tracking_id=tid,
            source_listing_ids=[outcome.listing_id],
            status="active",
            first_observed_at=day,
            last_observed_at=day,
            # Anything present in the very first snapshot already existed for
            # an unknown time. Its age is left-truncated, forever.
            observed_appearance=not is_first,
            current_asking_price_toman=outcome.asking_price_toman,
            observations=[Observation(day, "present")],
            events=[ev],
            last_signals=outcome,
        )
        events.append(ev)

    return events


# If the two best candidates are this close, we cannot tell them apart, so
# we link neither. Precision first: an arbitrary pick fabricates history.
AMBIGUITY_MARGIN = 0.10


def _best_repost_match(state: TrackingState, outcome: FetchOutcome, day: date):
    """Blocking, then scoring, then an ambiguity guard.

    The blocking key exists to avoid scoring every absent listing against
    every new one, so it is used as an index here rather than as a filter
    inside the scorer.
    """
    keys = set(blocking_keys(outcome))
    scored: list[tuple[float, TrackedListing, list[str]]] = []
    for cand in state.recently_absent(day):
        if cand.last_signals is None:
            continue
        if not keys & set(blocking_keys(cand.last_signals)):
            continue
        score, reasons = repost_match_score(cand.last_signals, outcome)
        if score > 0:
            scored.append((score, cand, reasons))

    if not scored:
        return None, 0.0, []

    scored.sort(key=lambda x: x[0], reverse=True)
    best_score, best, best_reasons = scored[0]

    if best_score < REPOST_MATCH_THRESHOLD:
        return None, 0.0, []

    if len(scored) > 1 and (best_score - scored[1][0]) < AMBIGUITY_MARGIN:
        # Two plausible parents. Refuse rather than guess.
        return None, 0.0, [
            f"ambiguous: {best_score:.2f} vs {scored[1][0]:.2f} — not linked"]

    return best, best_score, best_reasons


# ---------------------------------------------------------------------------
# Censoring-aware statistics
#
# Two traps, both of which silently bias the median downward:
#   left truncation  — listings that predate tracking have unknown true age
#   right censoring  — listings still active have not finished their life
# Kaplan-Meier handles the second correctly. Nothing handles the first, so
# those listings are excluded and reported separately as lower bounds.
# ---------------------------------------------------------------------------

@dataclass
class DurationStats:
    n_usable: int
    n_disappeared: int
    n_censored: int
    n_excluded_left_truncated: int
    observed_disappearance_rate: float
    km_median_days: float | None
    naive_median_disappeared_days: float | None
    warnings: list[str] = field(default_factory=list)


def duration_stats(state: TrackingState, as_of: date) -> DurationStats:
    usable, excluded = [], 0
    for t in state.listings.values():
        if not t.observed_appearance:
            excluded += 1
            continue
        usable.append((t.observed_span_days(as_of), t.status == "absent"))

    disappeared = [d for d, ev in usable if ev]
    censored = [d for d, ev in usable if not ev]
    warnings: list[str] = []

    if excluded:
        warnings.append(
            f"{excluded} listings predate tracking; their age is a LOWER BOUND "
            "and they are excluded from these statistics")
    if len(disappeared) < 30:
        warnings.append(
            f"only {len(disappeared)} observed disappearances — too few to publish "
            "a time-on-market claim; collect more days before using this")

    return DurationStats(
        n_usable=len(usable),
        n_disappeared=len(disappeared),
        n_censored=len(censored),
        n_excluded_left_truncated=excluded,
        observed_disappearance_rate=(len(disappeared) / len(usable)) if usable else 0.0,
        km_median_days=kaplan_meier_median(usable),
        naive_median_disappeared_days=(statistics.median(disappeared) if disappeared else None),
        warnings=warnings,
    )


def kaplan_meier_curve(observations: Iterable[tuple[int, bool]]
                       ) -> list[tuple[int, float, int, int]]:
    """Kaplan-Meier survival curve from (duration, event_observed) pairs.

    `event_observed=True` means the listing disappeared; False means it was
    still active when we last looked (right-censored).

    Returns [(t, S(t), n_at_risk_at_t, events_at_t), ...] at each distinct
    time. O(n log n): one sort, one pass, ties grouped as we go.

    Tie convention (the standard one): observations censored at exactly time
    t are counted as at risk at t, and leave the risk set only afterwards.
    So a car that disappeared on day 7 and one still listed on day 7 both
    contribute to the denominator for day 7's event.
    """
    obs = sorted(observations, key=lambda x: x[0])
    curve: list[tuple[int, float, int, int]] = []
    n_at_risk = len(obs)
    survival = 1.0
    i = 0
    while i < len(obs):
        t = obs[i][0]
        j = i
        events = 0
        while j < len(obs) and obs[j][0] == t:
            if obs[j][1]:
                events += 1
            j += 1
        if events and n_at_risk > 0:
            survival *= (1 - events / n_at_risk)
        curve.append((t, survival, n_at_risk, events))
        n_at_risk -= (j - i)
        i = j
    return curve


def kaplan_meier_median(observations: Iterable[tuple[int, bool]]) -> float | None:
    """Smallest t where S(t) <= 0.5.

    Returns None when survival never reaches 0.5 inside the observed window —
    which is the honest answer, not a number. Under heavy right censoring
    (the normal case for a short crawl) this will legitimately be None, and
    a naive median over observed disappearances would have invented one.
    """
    for t, s, _, _ in kaplan_meier_curve(observations):
        if s <= 0.5:
            return float(t)
    return None


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def observed_age_claim_fa(t: TrackedListing, as_of: date) -> str:
    """Persian phrasing that never overstates what we observed.

    This is the product's flagship line. It must stay literally true:
    we report OUR observation window, never the listing's true age, and
    never a sale.
    """
    span = t.observed_span_days(as_of)
    if not t.observed_appearance:
        base = f"از شروع رصد ما حداقل {span} روز در بازار بوده"
    else:
        base = f"{span} روز است که در بازار است"
    if t.repost_count:
        base += f" و {t.repost_count} بار تجدید آگهی شده"
        gap = t.confirmed_absent_days()
        if gap > 0:
            base += f" ({gap} روز بین آگهی‌ها حذف بوده)"
    unknown = t.unknown_days(as_of)
    if unknown > 0:
        base += f"؛ {unknown} روز وضعیتش برای ما نامعلوم بوده"
    drops = [e for e in t.price_changes
             if e.old_asking_price_toman and e.new_asking_price_toman and e.new_asking_price_toman < e.old_asking_price_toman]
    if drops:
        total = drops[0].old_asking_price_toman - drops[-1].new_asking_price_toman
        base += f"؛ {len(drops)} بار کاهش قیمت (مجموع {total / 1_000_000:.0f} میلیون)"
    return base


def w0_report(state: TrackingState, snapshots: Sequence[Snapshot], as_of: date) -> str:
    ds = duration_stats(state, as_of)
    reposts = sum(t.repost_count for t in state.listings.values())
    changes = sum(len(t.price_changes) for t in state.listings.values())
    lines = [
        "TRACKING", "─" * 40,
        f"snapshots ingested : {sum(1 for s in snapshots if s.integrity is Integrity.OK)}"
        f" ok / {sum(1 for s in snapshots if s.integrity is Integrity.PARTIAL)} partial"
        f" / {sum(1 for s in snapshots if s.integrity is Integrity.SUSPECT)} suspect",
        f"tracked listings   : {len(state.listings)}",
        f"active / absent    : {len(state.active())} / "
        f"{len(state.listings) - len(state.active())}",
        f"probable reposts   : {reposts}",
        f"price changes      : {changes}",
        "",
        "TIME ON MARKET (observed window only — not time to sale)", "─" * 40,
        f"usable             : {ds.n_usable}",
        f"disappeared        : {ds.n_disappeared}  (disappeared ≠ sold)",
        f"still tracked      : {ds.n_censored}",
        f"left-truncated     : {ds.n_excluded_left_truncated} (excluded)",
        f"disappearance rate : {ds.observed_disappearance_rate:.0%}",
        f"KM median days     : {ds.km_median_days if ds.km_median_days is not None else 'not reached'}",
        f"naive median       : {ds.naive_median_disappeared_days} (biased low — do not publish)",
    ]
    for w in ds.warnings:
        lines.append(f"  ⚠ {w}")
    return "\n".join(lines)
