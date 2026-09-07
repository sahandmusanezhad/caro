"""
Cross-source identity — the same physical car listed on more than one site.

Why this needs its own matcher
------------------------------
`caro.tracking.repost_match_score` links a car to its own repost on ONE site.
It leans hard on `seller_fingerprint` (0.35 of the score) — and that signal is
worthless across sites, because a seller has a different account, and
therefore a different salted hash, on each. Reusing that matcher across
sources would push nearly every genuine cross-site pair below threshold and
silently find nothing.

So the weights are different here: images dominate, because photos are the
one artefact sellers copy verbatim between sites. The threshold is also
HIGHER (0.80 vs 0.70), and that direction is deliberate. A false same-source
merge fabricates one car's history; a false cross-source merge destroys a
genuine independent market observation, shrinking the sample the appraiser
learns from. The second error is worse, so the bar is higher.

What a cross-source match actually tells you
--------------------------------------------
It is tempting to call three sites listing one car "corroboration from three
sources". It is not. If the prices differ — and they usually do — then it is
the opposite: the same seller is quoting different numbers in different
places, which is *inconsistency*, and inconsistency is the more useful
finding of the two.

Three things follow from a confirmed cross-source cluster, and none of them
is corroboration:

1. **An observable price gap.** One car carries different numbers in
   different places. That is a fact worth showing. It is NOT evidence that
   the seller would accept the lowest of them — a price published somewhere
   may be stale, channel-specific, or since raised. The observation is
   stated; the conclusion is the reader's.
2. **A supply correction.** Counting listings without cross-source dedup
   overstates how many cars are actually for sale, which inflates every
   liquidity estimate downstream.
3. **A seller-behaviour signal.** Systematic cross-site price gaps say
   something about who you are dealing with.

Corroboration would require independent *observers* of one fact. Here there
is one observer — the seller — publishing to several places.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Literal, Sequence

from caro.ingest.persian import normalize

# ---------------------------------------------------------------------------
# Source roles — what each site is FOR, not merely that it exists
# ---------------------------------------------------------------------------

Role = Literal["primary_offers", "breadth", "corroboration", "taxonomy_only"]


@dataclass(frozen=True)
class SourceProfile:
    """A source's role, and what it can actually be trusted to provide.

    `taxonomy_only` matters: a specs or price-guide site is a reference for
    normalising model and trim names. Its pages are not offers and must never
    enter the corpus as listings, or the appraiser learns from prices nobody
    is actually asking.
    """
    name: str
    role: Role
    # Which fields this source publishes as structured data rather than prose.
    # Anything absent has to be parsed out of free text, with the lower
    # confidence that implies.
    structured_fields: frozenset[str] = frozenset()
    publishes_images: bool = True
    notes: str = ""

    @property
    def contributes_offers(self) -> bool:
        return self.role != "taxonomy_only"


# Starting roster. Deliberately three offer sources, not ten: the interesting
# claim is "I reconciled independent sources into one canonical market", and
# that claim is not made stronger by a fourth site.
DEFAULT_SOURCES: tuple[SourceProfile, ...] = (
    SourceProfile(
        "bama", "primary_offers",
        structured_fields=frozenset({"price", "year", "mileage", "gearbox",
                                     "fuel", "color", "body_condition"}),
        notes="Car-specialist. Richest structured fields, so it sets the "
              "canonical schema; other sources are mapped onto it."),
    SourceProfile(
        "divar", "breadth",
        structured_fields=frozenset({"price", "year", "mileage"}),
        notes="Largest volume and the widest price range, including private "
              "sellers the specialist sites never see. Condition lives in "
              "prose, so extraction quality matters most here."),
    SourceProfile(
        "sheypoor", "corroboration",
        structured_fields=frozenset({"price", "year", "mileage"}),
        notes="Independent overlap with Divar. Its value is the cross-source "
              "clusters it creates, not the listings it adds."),
)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------

CROSS_SOURCE_THRESHOLD = 0.80
AMBIGUOUS_FLOOR = 0.62
AMBIGUITY_MARGIN = 0.10
MILEAGE_TOLERANCE = 0.03

# A single shared photo is not evidence. Dealers reuse one showroom shot
# across their whole inventory, stock images appear on many listings, and a
# listing with one photo scores jaccard 1.0 or 0.0 with nothing in between.
# Full image weight requires more than one shared hash.
MIN_SHARED_IMAGES_FOR_FULL_WEIGHT = 2


class MatchVerdict(str, Enum):
    MATCH = "match"
    AMBIGUOUS = "ambiguous"      # never merged, always recorded
    NO_MATCH = "no_match"


@dataclass(frozen=True)
class MatchResult:
    verdict: MatchVerdict
    score: float
    reasons: tuple[str, ...]

    @property
    def may_merge(self) -> bool:
        return self.verdict is MatchVerdict.MATCH


def _jaccard(a: Sequence[str], b: Sequence[str]) -> float:
    sa, sb = set(a), set(b)
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def _shingles(text: str, n: int = 4) -> set[str]:
    """Character n-grams over normalised text.

    Word tokens are too brittle for Persian listing prose — sellers vary
    spacing, ZWNJ and half-spaces constantly, and a copied description
    survives all of that at the character level.
    """
    s = re.sub(r"[^\w\s]", " ", normalize(text))
    s = re.sub(r"\s+", " ", s)
    return {s[i:i + n] for i in range(max(0, len(s) - n + 1))}


@dataclass(frozen=True)
class CrossSourceCandidate:
    """One listing, reduced to what can be compared across sites."""
    source: str
    listing_id: str
    make: str | None
    model: str | None
    trim: str | None
    year_jalali: int | None
    mileage_km: int | None
    color: str | None
    province: str | None
    asking_price_toman: int | None
    description: str = ""
    image_phashes: tuple[str, ...] = ()


def cross_source_contradictions(a: CrossSourceCandidate,
                                b: CrossSourceCandidate) -> list[str]:
    """Vetoes. Same shape as the same-source rules, and the same reasoning:
    only facts that cannot be a normalisation artefact."""
    out: list[str] = []
    if a.source == b.source:
        out.append("same source — use the repost matcher, not this one")
    if a.make and b.make and normalize(a.make) != normalize(b.make):
        out.append(f"different make: {a.make} vs {b.make}")
    if a.model and b.model and normalize(a.model) != normalize(b.model):
        out.append(f"different model: {a.model} vs {b.model}")
    if a.year_jalali and b.year_jalali and a.year_jalali != b.year_jalali:
        out.append(f"different year: {a.year_jalali} vs {b.year_jalali}")
    if a.mileage_km and b.mileage_km:
        hi = max(a.mileage_km, b.mileage_km)
        lo = min(a.mileage_km, b.mileage_km)
        if lo and (hi - lo) / lo > MILEAGE_TOLERANCE:
            out.append(f"mileage differs: {a.mileage_km:,} vs {b.mileage_km:,}")
    return out


def cross_source_match_score(a: CrossSourceCandidate,
                             b: CrossSourceCandidate) -> tuple[float, list[str]]:
    """Score that `a` and `b` are the same physical car on two sites.

    Price is not scored at all here. Across sites it is the field most likely
    to differ *because* they are the same car — the seller is testing prices —
    so using it as evidence of identity would systematically reject exactly
    the clusters worth finding.
    """
    vetoes = cross_source_contradictions(a, b)
    if vetoes:
        return 0.0, vetoes

    score = 0.0
    reasons: list[str] = []

    # Photos are the only artefact that crosses sites unchanged — but a
    # single shared photo is weak evidence, not strong. See the constant.
    shared = len(set(a.image_phashes) & set(b.image_phashes))
    img = _jaccard(a.image_phashes, b.image_phashes)
    if img > 0:
        weight = 0.50 if shared >= MIN_SHARED_IMAGES_FOR_FULL_WEIGHT else 0.20
        score += weight * img
        reasons.append(f"image overlap {img:.2f} ({shared} shared)")
        if shared < MIN_SHARED_IMAGES_FOR_FULL_WEIGHT:
            reasons.append("only one shared photo — dealers reuse stock shots")

    spec_hits = sum([
        bool(a.make and a.make == b.make),
        bool(a.model and a.model == b.model),
        bool(a.year_jalali and a.year_jalali == b.year_jalali),
        bool(a.mileage_km and b.mileage_km),
        bool(a.color and normalize(a.color) == normalize(b.color or "")),
        bool(a.trim and normalize(a.trim) == normalize(b.trim or "")),
    ])
    if spec_hits:
        score += 0.30 * (spec_hits / 6)
        reasons.append(f"spec agreement {spec_hits}/6")

    if a.description and b.description:
        sh = _jaccard(list(_shingles(a.description)), list(_shingles(b.description)))
        if sh > 0.25:
            score += 0.15 * sh
            reasons.append(f"description similarity {sh:.2f}")

    if a.province and normalize(a.province) == normalize(b.province or ""):
        score += 0.05
        reasons.append("same province")

    return min(1.0, score), reasons


# ---------------------------------------------------------------------------
# Clusters
# ---------------------------------------------------------------------------

@dataclass
class CrossSourceCluster:
    cluster_id: str
    members: list[CrossSourceCandidate] = field(default_factory=list)
    match_confidence: float = 1.0
    reasons: list[str] = field(default_factory=list)
    ambiguous_with: list[tuple[str, str, float]] = field(default_factory=list)

    @property
    def sources(self) -> list[str]:
        return sorted({m.source for m in self.members})

    @property
    def prices(self) -> list[int]:
        return sorted(m.asking_price_toman for m in self.members if m.asking_price_toman)

    @property
    def min_ask_irr(self) -> int | None:
        return self.prices[0] if self.prices else None

    @property
    def price_spread_irr(self) -> int:
        p = self.prices
        return (p[-1] - p[0]) if len(p) > 1 else 0

    @property
    def is_cross_source(self) -> bool:
        return len(self.sources) > 1

    def counts_as_supply(self) -> int:
        """One physical car is one unit of supply, however many times it is
        listed. Counting listings instead inflates every liquidity estimate."""
        return 1

    def claim_fa(self) -> str:
        """Deliberately not the word «تأیید».

        Several sites carrying one seller's car is not several observers
        confirming a fact. When the prices differ it is the seller quoting
        different numbers in different places, and the honest phrasing says
        so — which is also the more useful thing for the buyer to know.
        """
        if not self.is_cross_source:
            return f"در {len(self.members)} آگهی از یک منبع دیده شده"
        n = len(self.sources)
        if self.price_spread_irr == 0:
            return f"همین خودرو در {n} سایت با قیمت یکسان آگهی شده"
        return (f"همین خودرو در {n} سایت آگهی شده، با "
                f"{self.price_spread_irr / 1e6:.0f} میلیون اختلاف قیمت — "
                f"کمترین قیمت اعلام‌شده {self.min_ask_irr / 1e9:.2f} میلیارد است")

    def price_gap_fa(self) -> str | None:
        """What was OBSERVED, and nothing about the seller's state of mind.

        An earlier version said "the seller has already accepted this price,
        so there is room to negotiate above it". That is an inference, and a
        weak one: a price published somewhere is not a price still on offer,
        nor one the seller would accept today, nor necessarily their current
        number at all. It could be stale, or a channel-specific listing they
        have since raised.

        The observation is worth stating. The conclusion is the user's to
        draw, and the wording now stops where the evidence does.
        """
        if not self.is_cross_source or self.price_spread_irr == 0:
            return None
        return (f"همین خودرو با قیمت {self.min_ask_irr / 1e9:.2f} میلیارد نیز "
                f"منتشر شده؛ اختلاف قیمت بین کانال‌ها "
                f"{self.price_spread_irr / 1e6:.0f} میلیون تومان است. "
                "این اختلاف یک نکته‌ی قابل بررسی برای مذاکره است.")


def classify_cross_source(a: CrossSourceCandidate,
                          b: CrossSourceCandidate) -> MatchResult:
    """Three states, because two is not enough.

    A binary matcher forces every uncertain pair into either a merge or a
    silent discard. In CARO a false merge destroys a genuine independent
    market observation, so the uncertain cases get their own outcome:
    AMBIGUOUS is recorded, shown, and never merged.

    A MATCH additionally requires CORROBORATION — evidence from more than
    one family. Images alone can be a dealer's reused showroom photo; specs
    alone can be two identical cars in the same city, which is common for
    high-volume models and exactly where a naive matcher fails.
    """
    score, reasons = cross_source_match_score(a, b)
    if score == 0.0:
        return MatchResult(MatchVerdict.NO_MATCH, 0.0, tuple(reasons))

    families = sum([
        any(r.startswith("image overlap") for r in reasons),
        any(r.startswith("spec agreement") for r in reasons),
        any(r.startswith("description similarity") for r in reasons),
    ])
    corroborated = families >= 2

    if score >= CROSS_SOURCE_THRESHOLD and corroborated:
        return MatchResult(MatchVerdict.MATCH, score, tuple(reasons))
    if score >= CROSS_SOURCE_THRESHOLD:
        return MatchResult(
            MatchVerdict.AMBIGUOUS, score,
            tuple(reasons) + ("scores high on one evidence family only — "
                              "not merged",))
    if score >= AMBIGUOUS_FLOOR:
        return MatchResult(MatchVerdict.AMBIGUOUS, score, tuple(reasons))
    return MatchResult(MatchVerdict.NO_MATCH, score, tuple(reasons))


def cluster_across_sources(
        candidates: Sequence[CrossSourceCandidate],
        threshold: float = CROSS_SOURCE_THRESHOLD) -> list[CrossSourceCluster]:
    """Greedy clustering with an ambiguity guard.

    Candidates are compared only against listings from OTHER sources. A
    listing that ties between two possible partners joins neither — the same
    precision-first rule as the repost matcher, applied where the cost of a
    false merge is higher.
    """
    clusters: list[CrossSourceCluster] = []
    assigned: set[tuple[str, str]] = set()

    for i, cand in enumerate(candidates):
        key = (cand.source, cand.listing_id)
        if key in assigned:
            continue

        scored: list[tuple[float, CrossSourceCandidate, list[str]]] = []
        ambiguous: list[tuple[float, CrossSourceCandidate, tuple[str, ...]]] = []
        for other in candidates[i + 1:]:
            if (other.source, other.listing_id) in assigned:
                continue
            if other.source == cand.source:
                continue
            res = classify_cross_source(cand, other)
            if res.verdict is MatchVerdict.MATCH and res.score >= threshold:
                scored.append((res.score, other, list(res.reasons)))
            elif res.verdict is MatchVerdict.AMBIGUOUS:
                ambiguous.append((res.score, other, res.reasons))

        cid = f"xs_{len(clusters):05d}"
        cluster = CrossSourceCluster(cid, [cand])
        assigned.add(key)
        # Recorded, not merged. An unexplained near-match is information —
        # it belongs in the run log so the matcher can be tuned against real
        # failure modes rather than guessed at.
        cluster.ambiguous_with = [
            (o.source, o.listing_id, round(sc, 3)) for sc, o, _ in ambiguous]

        if scored:
            scored.sort(key=lambda x: x[0], reverse=True)
            best, partner, why = scored[0]
            # Two equally plausible partners means we cannot tell them apart.
            same_source_rivals = [s for s, o, _ in scored[1:]
                                  if o.source == partner.source]
            if same_source_rivals and (best - same_source_rivals[0]) < AMBIGUITY_MARGIN:
                cluster.reasons.append(
                    f"ambiguous: {best:.2f} vs {same_source_rivals[0]:.2f} — not merged")
            else:
                cluster.members.append(partner)
                cluster.match_confidence = best
                cluster.reasons = why
                assigned.add((partner.source, partner.listing_id))

        clusters.append(cluster)

    return clusters


def supply_correction(clusters: Sequence[CrossSourceCluster]) -> dict[str, int]:
    """How much raw listing counts overstate real supply.

    Liquidity feeds the ranker, so an uncorrected count does not just look
    wrong in a report — it moves recommendations.
    """
    listings = sum(len(c.members) for c in clusters)
    cars = sum(c.counts_as_supply() for c in clusters)
    return {"listings": listings, "distinct_cars": cars,
            "inflation": listings - cars,
            "inflation_pct": round(100 * (listings - cars) / max(cars, 1))}
