"""
CARO W2 — the decision layer.

Built ON TOP of frozen W0 (`tracking.py`) and W1 (`appraisal.py`). Nothing in
those modules is modified.

The one design decision that matters here:

    THE ADVERSARIAL REVIEWER IS DETERMINISTIC.

A reviewer implemented as an LLM prompt can be talked out of a finding, can
invent one that is not there, and gives a different answer on a rerun. A
reviewer implemented as a set of checks over the evidence packet cannot do
any of those. For a product whose entire pitch is "we do not overclaim", the
component that polices overclaiming is the last place to put a language
model.

Consequence: everything here runs offline with no API key. An LLM is
optional and enters at exactly one point — turning the finished, frozen
verdict into prose (`ExplanationAgent`). It cannot alter a number, a
confidence level, or a decision; it receives a frozen object and renders it.

Priority order the Judge enforces, highest first:
    1. data integrity        (a suspect snapshot beats everything)
    2. hard contradictions   (a veto is a veto)
    3. benchmark acceptance  (an unbenchmarked estimator cannot serve)
    4. statistical estimate
    5. comparable evidence
    6. language interpretation   ← can never overturn 1-5
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Any, Literal, Sequence

import numpy as np

from caro.appraisal import (
    QUANTILES, ComparableEvidence, ComparableQuantiles, MarketEstimator,
    NotBenchmarked, Row, Split, distribution_shift,
)
from caro.tracking import TrackedListing, TrackingState


# ---------------------------------------------------------------------------
# Evidence ledger — every claim resolves to observations
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EvidenceItem:
    evidence_id: str
    kind: Literal["observation", "comparable", "snapshot", "benchmark", "derived"]
    summary: str
    source_ref: str          # snapshot id, listing id, benchmark run id
    observed_on: date | None = None


@dataclass(frozen=True)
class Claim:
    """A statement the product may show a user, plus what backs it.

    A claim with no evidence ids cannot be rendered. That is checked, not
    trusted — see `EvidenceLedger.unsupported_claims`.
    """
    claim_id: str
    text_fa: str
    evidence_ids: tuple[str, ...]
    kind: Literal["observed", "estimated", "derived"] = "observed"


@dataclass
class EvidenceLedger:
    items: dict[str, EvidenceItem] = field(default_factory=dict)
    claims: list[Claim] = field(default_factory=list)

    def add(self, item: EvidenceItem) -> str:
        self.items[item.evidence_id] = item
        return item.evidence_id

    def claim(self, claim_id: str, text_fa: str, evidence_ids: Sequence[str],
              kind: str = "observed") -> Claim:
        c = Claim(claim_id, text_fa, tuple(evidence_ids), kind)  # type: ignore[arg-type]
        self.claims.append(c)
        return c

    def unsupported_claims(self) -> list[Claim]:
        """Claims citing no evidence, or evidence that does not exist.

        The grounding guard, at the ledger level. Anything returned here is a
        bug: it means the product was about to say something it cannot back.
        """
        bad = []
        for c in self.claims:
            if not c.evidence_ids or any(e not in self.items for e in c.evidence_ids):
                bad.append(c)
        return bad

    def trace(self, claim_id: str) -> list[EvidenceItem]:
        for c in self.claims:
            if c.claim_id == claim_id:
                return [self.items[e] for e in c.evidence_ids if e in self.items]
        return []


# ---------------------------------------------------------------------------
# Confidence policy — a PUBLISHED RULEBOOK, not a learned score
#
# Every number below is a stated policy with a name and a rationale, printable
# via ConfidencePolicy.explain(). That matters more than it looks: the honest
# answer to "why 0.65?" is "because that is the published band for 3-4 days of
# confirmed observation, and here is the table" — not "the scorer said so".
# A confidence system nobody can audit is exactly the fake precision this
# product exists to avoid.
#
# These are calibrated by judgement, not fitted to data. When real data
# arrives they should be revisited against observed decision quality; until
# then they are policy, and they are labelled as policy.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Band:
    at_least: float
    score: float
    label_fa: str


def _band(bands: Sequence[Band], value: float) -> Band:
    for b in bands:
        if value >= b.at_least:
            return b
    return bands[-1]


@dataclass(frozen=True)
class ConfidencePolicy:
    """Named bands, in descending order of the quantity they read."""

    # How many days did we CONFIRM the listing present?
    evidence_days: tuple[Band, ...] = (
        Band(5, 1.00, "قوی — پنج روز یا بیشتر مشاهده‌ی تأییدشده"),
        Band(3, 0.65, "متوسط — سه تا چهار روز"),
        Band(1, 0.35, "ضعیف — یک تا دو روز"),
        Band(0, 0.00, "هیچ مشاهده‌ی تأییدشده‌ای نداریم"),
    )

    # What FRACTION of the observed span was unknown to us? (lower is better)
    known_ratio: tuple[Band, ...] = (
        Band(0.90, 1.00, "پوشش کامل — کمتر از ۱۰٪ نامعلوم"),
        Band(0.70, 0.60, "شکاف متوسط — ۱۰ تا ۳۰٪ نامعلوم"),
        Band(0.50, 0.30, "شکاف زیاد — ۳۰ تا ۵۰٪ نامعلوم"),
        Band(0.00, 0.10, "بیشتر بازه نامعلوم بوده"),
    )

    # A tier sets the CEILING; the count decides how much of it is earned.
    # This ordering is deliberate: no amount of loosely-matched listings can
    # score above a tightly-matched set, which the earlier arithmetic allowed.
    tier_ceiling: dict[str, float] = field(default_factory=lambda: {
        "strict": 1.00, "relaxed_mileage": 0.70,
        "relaxed_year": 0.45, "model_only": 0.20, "global": 0.0})

    # Count saturates: past this many, more listings add nothing.
    count_saturation: int = 30
    count_floor: float = 0.35          # a tiny sample still earns some credit

    # Dispersion penalty: wide spread among comparables means they are not
    # really comparable, whatever the tier says.
    dispersion_penalty_above: float = 0.40
    dispersion_penalty: float = 0.25

    severity_risk: dict[str, float] = field(default_factory=lambda: {
        "low": 0.10, "medium": 0.25, "high": 0.50})

    weights: dict[str, float] = field(default_factory=lambda: {
        "comparable": 0.25, "evidence": 0.20, "calibration": 0.20,
        "data_quality": 0.20, "temporal": 0.15})
    anomaly_weight: float = 0.30

    high_at: float = 0.68
    medium_at: float = 0.42
    insufficient_below: float = 0.20   # on any of the three core dimensions

    def evidence_strength(self, confirmed_days: int) -> tuple[float, str]:
        b = _band(self.evidence_days, confirmed_days)
        return b.score, b.label_fa

    def temporal_strength(self, span_days: int, unknown_days: int) -> tuple[float, str]:
        if span_days <= 0:
            return 0.0, "بازه‌ی مشاهده‌ای وجود ندارد"
        known = 1.0 - unknown_days / max(span_days + 1, 1)
        b = _band(self.known_ratio, known)
        return b.score, b.label_fa

    def comparable_strength(self, tier: str, count: int,
                            dispersion: float) -> tuple[float, str]:
        ceiling = self.tier_ceiling.get(tier, 0.0)
        if ceiling == 0.0 or count == 0:
            return 0.0, "پایه‌ی مقایسه‌ای وجود ندارد"
        earned = self.count_floor + (1 - self.count_floor) * min(
            1.0, count / self.count_saturation)
        score = ceiling * earned
        note = f"سقف رده‌ی {tier} × {count} آگهی"
        if dispersion == dispersion and dispersion > self.dispersion_penalty_above:
            score *= (1 - self.dispersion_penalty)
            note += " (جریمه‌ی پراکندگی)"
        return score, note

    def explain(self) -> str:
        """The whole rulebook, printable. Put this in EVAL.md and on screen."""
        L = ["CONFIDENCE POLICY (published rules, not a fitted model)", "─" * 58,
             "evidence_strength — by days CONFIRMED present"]
        L += [f"    >= {b.at_least:>4.0f} days → {b.score:.2f}   {b.label_fa}"
              for b in self.evidence_days]
        L.append("temporal_strength — by fraction of span that was KNOWN")
        L += [f"    >= {b.at_least:>4.0%}      → {b.score:.2f}   {b.label_fa}"
              for b in self.known_ratio]
        L.append("comparable_strength — tier ceiling x count, minus dispersion")
        L += [f"    {k:<16} ceiling {v:.2f}" for k, v in self.tier_ceiling.items()]
        L.append(f"    count saturates at {self.count_saturation}; "
                 f"floor {self.count_floor:.2f}")
        L.append(f"    dispersion > {self.dispersion_penalty_above:.0%} "
                 f"→ x{1 - self.dispersion_penalty:.2f}")
        L.append("overall status")
        L.append(f"    >= {self.high_at:.2f} HIGH · >= {self.medium_at:.2f} MEDIUM "
                 f"· else LOW")
        L.append(f"    any core dimension < {self.insufficient_below:.2f} "
                 "→ INSUFFICIENT_EVIDENCE")
        return "\n".join(L)


DEFAULT_POLICY = ConfidencePolicy()


# ---------------------------------------------------------------------------
# Multi-dimensional confidence — never one opaque number
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConfidenceProfile:
    evidence_strength: float      # how much observation history we hold
    comparable_strength: float    # tier ceiling x count, less dispersion
    temporal_strength: float      # what fraction of the span we actually saw
    model_calibration: float      # did the estimator pass the gate
    data_quality: float           # snapshot integrity, distribution shift
    anomaly_risk: float           # higher is WORSE
    notes: tuple[str, ...] = ()   # the band label behind each dimension
    policy: ConfidencePolicy = field(default_factory=lambda: DEFAULT_POLICY)

    @property
    def score(self) -> float:
        w = self.policy.weights
        return (w["comparable"] * self.comparable_strength
                + w["evidence"] * self.evidence_strength
                + w["calibration"] * self.model_calibration
                + w["data_quality"] * self.data_quality
                + w["temporal"] * self.temporal_strength
                - self.policy.anomaly_weight * self.anomaly_risk)

    @property
    def status(self) -> str:
        if min(self.evidence_strength, self.comparable_strength,
               self.data_quality) < self.policy.insufficient_below:
            return "INSUFFICIENT_EVIDENCE"
        s = self.score
        return ("HIGH" if s >= self.policy.high_at
                else "MEDIUM" if s >= self.policy.medium_at else "LOW")

    def weakest(self) -> tuple[str, float]:
        d = {"شواهد مشاهده‌شده": self.evidence_strength,
             "آگهی‌های مشابه": self.comparable_strength,
             "تازگی داده": self.temporal_strength,
             "کالیبراسیون مدل": self.model_calibration,
             "کیفیت داده": self.data_quality}
        k = min(d, key=d.get)
        return k, d[k]


def _downgrade(status: str) -> str:
    return {"HIGH": "MEDIUM", "MEDIUM": "LOW",
            "LOW": "INSUFFICIENT_EVIDENCE"}.get(status, status)


# ---------------------------------------------------------------------------
# Findings
# ---------------------------------------------------------------------------

Severity = Literal["low", "medium", "high"]
Action = Literal["approve", "downgrade", "reject", "request_more_evidence"]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: Severity
    text_fa: str
    evidence_ids: tuple[str, ...]
    recommended_action: Action
    hard: bool = False       # a hard finding is a veto no score can outvote


# ---------------------------------------------------------------------------
# 1. EvidenceAgent — assemble what we actually observed
# ---------------------------------------------------------------------------

@dataclass
class EvidencePacket:
    listing_id: str
    tracked: TrackedListing | None
    observed_span_days: int
    confirmed_present_days: int
    unknown_days: int
    repost_count: int
    price_changes: list[tuple[date, int, int]]
    evidence_ids: list[str]


class EvidenceAgent:
    def run(self, tracked: TrackedListing | None, listing_id: str,
            as_of: date, ledger: EvidenceLedger) -> EvidencePacket:
        if tracked is None:
            eid = ledger.add(EvidenceItem(
                f"obs:{listing_id}:none", "observation",
                "no tracking history for this listing", listing_id))
            return EvidencePacket(listing_id, None, 0, 0, 0, 0, [], [eid])

        ids: list[str] = []
        for o in tracked.observations:
            ids.append(ledger.add(EvidenceItem(
                f"obs:{tracked.tracking_id}:{o.on.isoformat()}", "observation",
                f"{o.on.isoformat()}: {o.status}", tracked.tracking_id, o.on)))

        changes = [(e.on, e.old_asking_price_toman, e.new_asking_price_toman)
                   for e in tracked.price_changes
                   if e.old_asking_price_toman and e.new_asking_price_toman]

        span = tracked.observed_span_days(as_of)
        ledger.claim(
            "claim:observed_span",
            (f"از شروع رصد ما حداقل {span} روز در بازار بوده"
             if not tracked.observed_appearance
             else f"{span} روز است که در بازار است"),
            ids, kind="observed")

        return EvidencePacket(
            listing_id, tracked, span, tracked.confirmed_present_days(),
            tracked.unknown_days(as_of), tracked.repost_count, changes, ids)


# ---------------------------------------------------------------------------
# 2. ComparableAgent
# ---------------------------------------------------------------------------

@dataclass
class ComparablePacket:
    evidence: ComparableEvidence
    evidence_ids: list[str]


class ComparableAgent:
    def __init__(self, cq: ComparableQuantiles):
        self.cq = cq

    def run(self, row: Row, ledger: EvidenceLedger) -> ComparablePacket:
        ev = self.cq.evidence(row)
        eid = ledger.add(EvidenceItem(
            f"comp:{row.listing_id}", "comparable",
            f"tier={ev.tier} n={ev.count} dispersion={ev.dispersion:.3f}",
            row.listing_id))
        # The claim is worded by TIER, so the product cannot call
        # model-only listings "comparable".
        ledger.claim("claim:comparables", ev.claim_fa(), [eid], kind="observed")
        return ComparablePacket(ev, [eid])


# ---------------------------------------------------------------------------
# 3. EstimationAgent — the gate is upstream of this
# ---------------------------------------------------------------------------

@dataclass
class EstimatePacket:
    served: bool
    quantiles: dict[float, float]
    reason_unavailable: str | None
    estimator_name: str
    evidence_ids: list[str]


class EstimationAgent:
    def __init__(self, estimator: MarketEstimator, name: str):
        self.estimator, self.name = estimator, name

    def run(self, row: Row, ledger: EvidenceLedger) -> EstimatePacket:
        try:
            p = self.estimator.predict([row])[0]
        except NotBenchmarked as e:
            eid = ledger.add(EvidenceItem(
                f"bench:{self.name}", "benchmark",
                f"estimator not accepted: {e}", self.name))
            return EstimatePacket(False, {}, str(e), self.name, [eid])
        eid = ledger.add(EvidenceItem(
            f"bench:{self.name}:accepted", "benchmark",
            f"{self.name} passed AcceptanceGate", self.name))
        q = {t: float(v) for t, v in zip(QUANTILES, p)}
        ledger.claim(
            "claim:estimate",
            f"محدوده‌ی تخمینی قیمت پیشنهادی: "
            f"{q[0.15] / 1e9:.2f} تا {q[0.85] / 1e9:.2f} میلیارد",
            [eid], kind="estimated")
        return EstimatePacket(True, q, None, self.name, [eid])


# ---------------------------------------------------------------------------
# 4. RiskAgent — deterministic
# ---------------------------------------------------------------------------

class RiskAgent:
    def run(self, ep: EvidencePacket, cp: ComparablePacket,
            est: EstimatePacket, ledger: EvidenceLedger) -> list[Finding]:
        out: list[Finding] = []
        ev = cp.evidence

        if ev.tier in ("model_only", "global"):
            out.append(Finding(
                "weak_comparable_tier", "high",
                "تخمین بر پایه‌ی آگهی‌های واقعاً مشابه نیست؛ فقط همین مدل.",
                tuple(cp.evidence_ids), "downgrade"))
        elif ev.tier == "relaxed_year":
            out.append(Finding(
                "relaxed_year", "medium",
                "برای رسیدن به نمونه‌ی کافی، محدودیت سال ساخت شل شد.",
                tuple(cp.evidence_ids), "downgrade"))

        if ev.count < 8:
            out.append(Finding(
                "sparse_comparables", "high",
                f"فقط {ev.count} آگهی مشابه پیدا شد.",
                tuple(cp.evidence_ids), "downgrade"))

        if ev.dispersion == ev.dispersion and ev.dispersion > 0.55:
            out.append(Finding(
                "high_dispersion", "medium",
                f"پراکندگی قیمت آگهی‌های مشابه زیاد است "
                f"({ev.dispersion:.0%} نسبت به میانه).",
                tuple(cp.evidence_ids), "downgrade"))

        if ep.unknown_days > 0:
            out.append(Finding(
                "observation_gap", "medium" if ep.unknown_days > 2 else "low",
                f"{ep.unknown_days} روز وضعیت این آگهی برای ما نامعلوم بوده.",
                tuple(ep.evidence_ids[:3]), "downgrade"))

        if ep.repost_count:
            out.append(Finding(
                "reposted", "low",
                f"این خودرو {ep.repost_count} بار تجدید آگهی شده؛ "
                "تاریخ نمایش‌داده‌شده سن واقعی آگهی نیست.",
                tuple(ep.evidence_ids[:3]), "approve"))

        if not est.served:
            out.append(Finding(
                "estimator_not_accepted", "high",
                "هیچ برآوردگری از دروازه‌ی پذیرش عبور نکرده است.",
                tuple(est.evidence_ids), "reject", hard=True))
        return out


# ---------------------------------------------------------------------------
# 5. AdversarialAgent — deterministic, and tries to break the answer
# ---------------------------------------------------------------------------

class AdversarialAgent:
    """Attempts to invalidate the conclusion using only evidence on hand.

    Every challenge is a reproducible check. When it finds nothing it says
    so plainly rather than manufacturing a concern — a reviewer that always
    objects is as useless as one that never does.
    """

    def run(self, row: Row, ep: EvidencePacket, cp: ComparablePacket,
            est: EstimatePacket, train_rows: Sequence[Row],
            ledger: EvidenceLedger) -> list[Finding]:
        out: list[Finding] = []
        if not est.served:
            return out

        q = est.quantiles
        lo, hi = q[QUANTILES[0]], q[QUANTILES[-1]]

        # Challenge 1: is the answer driven by a handful of listings?
        if cp.evidence.count and cp.evidence.count < 12:
            out.append(Finding(
                "estimate_dominated_by_few", "high",
                f"کل بازه از {cp.evidence.count} آگهی درآمده؛ "
                "یک آگهی پرت می‌تواند آن را جابه‌جا کند.",
                tuple(cp.evidence_ids), "downgrade"))

        # Challenge 2: is the listing outside the observed market at all?
        prices = np.array([r.asking_price_toman for r in train_rows
                           if r.model_key == row.model_key], dtype=float)
        if prices.size >= 10:
            p1, p99 = np.quantile(prices, [0.01, 0.99])
            eid = ledger.add(EvidenceItem(
                f"adv:range:{row.listing_id}", "derived",
                f"observed {row.model_key} range {p1:,.0f}–{p99:,.0f} "
                f"from {prices.size} listings", row.model_key))
            if row.asking_price_toman < p1 or row.asking_price_toman > p99:
                out.append(Finding(
                    "outside_observed_distribution", "high",
                    "قیمت این آگهی بیرون از محدوده‌ی مشاهده‌شده‌ی این مدل است؛ "
                    "برآورد ما برای چنین موردی اعتبار ندارد.",
                    (eid,), "reject", hard=True))

        # Challenge 3: is the interval so wide it says nothing?
        if lo > 0 and (hi - lo) / lo > 0.60:
            out.append(Finding(
                "interval_too_wide", "medium",
                "بازه‌ی برآورد آن‌قدر پهن است که برای تصمیم‌گیری کمک چندانی نمی‌کند.",
                tuple(est.evidence_ids), "downgrade"))

        # Challenge 4: could the repost link itself be wrong?
        if ep.repost_count and ep.tracked and any(
                e.match_confidence is not None and e.match_confidence < 0.85
                for e in ep.tracked.events if e.type == "reposted"):
            out.append(Finding(
                "repost_link_uncertain", "medium",
                "پیوند تجدید آگهی قطعی نیست؛ ممکن است دو خودروی متفاوت باشند.",
                tuple(ep.evidence_ids[:3]), "downgrade"))

        # Challenge 5: is the evidence stale?
        if ep.tracked and ep.confirmed_present_days == 0:
            out.append(Finding(
                "never_confirmed_present", "high",
                "این آگهی در هیچ اسنپ‌شاتی حاضر مشاهده نشده است.",
                tuple(ep.evidence_ids[:3]), "reject", hard=True))

        return out


# ---------------------------------------------------------------------------
# 6. Judge — resolves by priority, never by vote
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Verdict:
    decision: Action
    confidence: ConfidenceProfile
    status: str                       # after any downgrades
    status_before_review: str         # before them — the demo beat
    downgrade_reasons: tuple[str, ...]
    findings: tuple[Finding, ...]
    estimate: dict[float, float]
    headline_fa: str


class Judge:
    def __init__(self, policy: ConfidencePolicy = DEFAULT_POLICY):
        self.policy = policy

    def run(self, ep: EvidencePacket, cp: ComparablePacket, est: EstimatePacket,
            risk: Sequence[Finding], adversarial: Sequence[Finding],
            shift_severe: bool) -> Verdict:
        findings = tuple(list(risk) + list(adversarial))
        ev = cp.evidence

        p = self.policy
        es, es_note = p.evidence_strength(ep.confirmed_present_days)
        ts, ts_note = p.temporal_strength(ep.observed_span_days, ep.unknown_days)
        cs, cs_note = p.comparable_strength(ev.tier, ev.count, ev.dispersion)
        conf = ConfidenceProfile(
            evidence_strength=es,
            comparable_strength=cs,
            temporal_strength=ts,
            model_calibration=1.0 if est.served else 0.0,
            data_quality=0.3 if shift_severe else (1.0 if est.served else 0.4),
            anomaly_risk=min(1.0, sum(p.severity_risk[f.severity]
                                      for f in findings)),
            notes=(es_note, ts_note, cs_note),
            policy=p,
        )

        status_before = conf.status
        status = status_before
        reasons: list[str] = []

        # Priority 1-3: any hard finding vetoes. No score overturns this.
        hard = [f for f in findings if f.hard]
        if hard:
            return Verdict(
                "reject", conf, "INSUFFICIENT_EVIDENCE", status_before,
                tuple(f.text_fa for f in hard), findings, est.quantiles,
                "برای این آگهی برآورد قابل اتکایی نداریم.")

        if not est.served:
            return Verdict(
                "insufficient_evidence", conf, "INSUFFICIENT_EVIDENCE",
                status_before, (est.reason_unavailable or "",), findings,
                {}, "برآورد بازار در دسترس نیست.")

        # Priority 4-5: soft findings downgrade, one step per high finding.
        for f in findings:
            if f.recommended_action == "downgrade" and f.severity == "high":
                status = _downgrade(status)
                reasons.append(f.text_fa)
        if any(f.severity == "medium" and f.recommended_action == "downgrade"
               for f in findings) and status == status_before:
            status = _downgrade(status)
            reasons.append(next(f.text_fa for f in findings
                                if f.severity == "medium"
                                and f.recommended_action == "downgrade"))

        decision: Action = "approve" if status == status_before else "downgrade"
        if status == "INSUFFICIENT_EVIDENCE":
            decision = "insufficient_evidence"

        q = est.quantiles
        headline = (f"جایگاه این آگهی در توزیع قیمت‌های پیشنهادی مشاهده‌شده: "
                    f"{q[QUANTILES[0]] / 1e9:.2f} تا {q[QUANTILES[-1]] / 1e9:.2f} میلیارد")
        return Verdict(decision, conf, status, status_before,
                       tuple(reasons), findings, q, headline)


# ---------------------------------------------------------------------------
# 7. ExplanationAgent — renders a FROZEN verdict. Cannot change it.
# ---------------------------------------------------------------------------

class ExplanationAgent:
    """Turns the verdict into Persian prose.

    Template-based, so the demo needs no API key. An LLM may replace the
    templating, but it receives a frozen `Verdict` and the ledger and can
    only phrase them — it has no path to alter a number, a confidence level
    or a decision, because those are already decided and immutable by the
    time this runs.
    """

    def run(self, v: Verdict, ep: EvidencePacket, cp: ComparablePacket,
            ledger: EvidenceLedger) -> str:
        L: list[str] = [v.headline_fa, ""]

        if v.decision in ("reject", "insufficient_evidence"):
            L.append("چرا برآورد نمی‌دهیم:")
            L += [f"  • {r}" for r in v.downgrade_reasons if r]
            L.append("")
            L.append("کاری که می‌توانیم بکنیم: آگهی‌های موجود را نشان دهیم، "
                     "ریسک‌های متن آگهی را دربیاوریم، و بگوییم چه چیزی را "
                     "باید از فروشنده بپرسید.")
            return "\n".join(L)

        L.append(f"شواهد: {cp.evidence.claim_fa()}")
        if ep.tracked:
            span = ep.observed_span_days
            s = (f"از شروع رصد ما حداقل {span} روز در بازار بوده"
                 if not ep.tracked.observed_appearance
                 else f"{span} روز است که در بازار است")
            if ep.repost_count:
                s += f" و {ep.repost_count} بار تجدید آگهی شده"
            if ep.unknown_days:
                s += f"؛ {ep.unknown_days} روز وضعیتش نامعلوم بوده"
            L.append(f"تاریخچه: {s}")
        if ep.price_changes:
            d = [(a, b) for _, a, b in ep.price_changes if b < a]
            if d:
                L.append(f"قیمت {len(d)} بار کاهش یافته "
                         f"(از {d[0][0] / 1e9:.2f} به {d[-1][1] / 1e9:.2f} میلیارد).")

        L.append("")
        if v.status != v.status_before_review:
            L.append(f"اطمینان: {v.status_before_review} ← {v.status} "
                     "(پس از بازبینی انتقادی)")
            L += [f"  • {r}" for r in v.downgrade_reasons]
        else:
            L.append(f"اطمینان: {v.status}")
            L.append("  • بازبینی انتقادی تناقض مهمی پیدا نکرد.")

        w, val = v.confidence.weakest()
        L.append(f"ضعیف‌ترین بُعد: {w} ({val:.0%})")
        L.append("")
        L.append("این برآورد از قیمت‌های پیشنهادی مشاهده‌شده ساخته شده، "
                 "نه از قیمت معامله.")
        return "\n".join(L)


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

@dataclass
class AgentTraceEntry:
    agent: str
    summary: str


@dataclass
class CAROResponse:
    verdict: Verdict
    explanation_fa: str
    ledger: EvidenceLedger
    trace: list[AgentTraceEntry]
    unsupported_claims: list[Claim]


class CAROOrchestrator:
    def __init__(self, cq: ComparableQuantiles, estimator: MarketEstimator,
                 estimator_name: str, train_rows: Sequence[Row],
                 split: Split | None = None,
                 policy: ConfidencePolicy = DEFAULT_POLICY):
        self.evidence = EvidenceAgent()
        self.comparables = ComparableAgent(cq)
        self.estimation = EstimationAgent(estimator, estimator_name)
        self.risk = RiskAgent()
        self.adversarial = AdversarialAgent()
        self.judge = Judge(policy)
        self.explain = ExplanationAgent()
        self.train_rows = list(train_rows)
        self.shift_severe = bool(split and distribution_shift(split).severe)

    def run(self, row: Row, tracked: TrackedListing | None,
            as_of: date) -> CAROResponse:
        ledger = EvidenceLedger()
        trace: list[AgentTraceEntry] = []

        ep = self.evidence.run(tracked, row.listing_id, as_of, ledger)
        trace.append(AgentTraceEntry(
            "Evidence", f"{len(ep.evidence_ids)} مشاهده · "
                        f"{ep.unknown_days} روز نامعلوم · "
                        f"{ep.repost_count} تجدید آگهی"))

        cp = self.comparables.run(row, ledger)
        trace.append(AgentTraceEntry(
            "Comparables", f"رده‌ی {cp.evidence.tier} · {cp.evidence.count} آگهی"))

        est = self.estimation.run(row, ledger)
        trace.append(AgentTraceEntry(
            "Estimation",
            f"{est.estimator_name} پذیرفته شد" if est.served
            else "هیچ برآوردگری پذیرفته نشده"))

        risk = self.risk.run(ep, cp, est, ledger)
        trace.append(AgentTraceEntry(
            "Risk", f"{len(risk)} نشانه" if risk else "نشانه‌ی مهمی نبود"))

        adv = self.adversarial.run(row, ep, cp, est, self.train_rows, ledger)
        trace.append(AgentTraceEntry(
            "Adversarial",
            f"{len(adv)} چالش" if adv else "تناقض مهمی پیدا نشد"))

        v = self.judge.run(ep, cp, est, risk, adv, self.shift_severe)
        trace.append(AgentTraceEntry(
            "Judge",
            f"{v.decision.upper()} · اطمینان "
            + (f"{v.status_before_review} ← {v.status}"
               if v.status != v.status_before_review else v.status)))

        text = self.explain.run(v, ep, cp, ledger)
        trace.append(AgentTraceEntry("Explanation", "پاسخ فارسی تولید شد"))

        return CAROResponse(v, text, ledger, trace, ledger.unsupported_claims())


def format_response(r: CAROResponse) -> str:
    L = ["AGENT TRACE", "─" * 58]
    L += [f"  ● {e.agent:<14}{e.summary}" for e in r.trace]
    L += ["", "ANSWER", "─" * 58, r.explanation_fa, "",
          "EVIDENCE LEDGER", "─" * 58,
          f"  claims: {len(r.ledger.claims)} · "
          f"evidence items: {len(r.ledger.items)} · "
          f"unsupported: {len(r.unsupported_claims)}"]
    for c in r.ledger.claims:
        L.append(f"  · {c.text_fa}")
        L.append(f"      ← {len(c.evidence_ids)} evidence "
                 f"({', '.join(list(c.evidence_ids)[:2])}…)")
    return "\n".join(L)
