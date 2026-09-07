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

1. **A negotiation floor.** The lowest ask is a price the seller has already
   publicly accepted. They cannot credibly refuse it elsewhere.
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
AMBIGUITY_MARGIN = 0.10
MILEAGE_TOLERANCE = 0.03


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
    price_irr: int | None
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

    # Photos are the only artefact that crosses sites unchanged.
    img = _jaccard(a.image_phashes, b.image_phashes)
    if img > 0:
        score += 0.50 * img
        reasons.append(f"image overlap {img:.2f}")

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

    @property
    def sources(self) -> list[str]:
        return sorted({m.source for m in self.members})

    @property
    def prices(self) -> list[int]:
        return sorted(m.price_irr for m in self.members if m.price_irr)

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

    def negotiation_floor_fa(self) -> str | None:
        """The lowest public ask is a number the seller already accepted."""
        if not self.is_cross_source or self.price_spread_irr == 0:
            return None
        return (f"فروشنده خودش این خودرو را جایی "
                f"{self.min_ask_irr / 1e9:.2f} میلیارد گذاشته؛ "
                "بالاتر از این عدد جای چانه‌زنی دارد.")


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
        for other in candidates[i + 1:]:
            if (other.source, other.listing_id) in assigned:
                continue
            if other.source == cand.source:
                continue
            s, why = cross_source_match_score(cand, other)
            if s >= threshold:
                scored.append((s, other, why))

        cid = f"xs_{len(clusters):05d}"
        cluster = CrossSourceCluster(cid, [cand])
        assigned.add(key)

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
