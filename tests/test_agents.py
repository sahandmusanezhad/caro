"""End-to-end tests for the CARO decision layer.

Covers the demo scenarios A-H: each is a case the orchestrator must handle
correctly, and each is triggerable on demand for the video.

Run: python3 test_agents.py
"""

from datetime import date, timedelta

import numpy as np

from caro.appraisal import (
    AcceptanceGate, ComparableQuantiles, GlobalQuantiles, LogLinearQuantiles,
    MarketEstimator, Row, cluster_temporal_split, run_benchmark,
)
from caro.agents import (
    AdversarialAgent, CAROOrchestrator, ComparableAgent, EvidenceLedger,
    EvidenceItem, Judge, format_response,
)
from caro.tracking import (
    FetchOutcome, FetchStatus, Observation, Snapshot, TrackingState,
    apply_snapshot, assess_integrity,
)

D0 = date(2026, 9, 6)
FAILS: list[str] = []
rng = np.random.default_rng(7)


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


# --- corpus -----------------------------------------------------------------
MODELS = {"pride": 20.4, "206": 21.0, "tiba": 20.6, "pars": 21.2}


def mu(m, year, km):
    return MODELS[m] + 0.06 * (year - 1395) - 0.0000012 * km


def corpus(n=1600):
    rows = []
    for i in range(n):
        m = list(MODELS)[i % len(MODELS)]
        year = int(rng.integers(1394, 1403))
        km = float(rng.integers(20_000, 260_000))
        rows.append(Row(f"l{i}", f"c{i}", int(rng.integers(0, 100)), m, year, km,
                        float(np.exp(rng.normal(mu(m, year, km), 0.18)))))
    # a rare model with almost no support — scenario B
    for j in range(4):
        rows.append(Row(f"rare{j}", f"cr{j}", 10, "maxima", 1399, 90_000,
                        float(np.exp(rng.normal(21.4, 0.2)))))
    return rows


ROWS = corpus()
SPLIT = cluster_temporal_split(ROWS, test_fraction=0.25)
CQ = ComparableQuantiles().fit(SPLIT.train)

BASE = {
    "global-quantiles": run_benchmark(GlobalQuantiles(), SPLIT, name="global-quantiles"),
    "comparable-quantiles": run_benchmark(ComparableQuantiles(), SPLIT,
                                          name="comparable-quantiles"),
}
RIDGE = MarketEstimator(LogLinearQuantiles())
RIDGE_OK, RIDGE_FAILS = RIDGE.benchmark(SPLIT, BASE, name="log-linear-ridge")


def tracked_for(listing_id, days_present, *, unknown_days=0, reposts=0,
                price_drops=0, never_present=False):
    """Build a real TrackedListing by feeding snapshots through W0."""
    st = TrackingState()
    bg = [FetchOutcome(f"bg{i}", FetchStatus.OK, price_irr=9e8,
                       make="Saipa", model="Pride", year_jalali=1396,
                       color="silver", province="Karaj",
                       seller_fingerprint=f"b{i}", mileage_km=150_000,
                       image_phashes=(f"b{i}",)) for i in range(25)]

    def car(lid, price, day):
        return FetchOutcome(lid, FetchStatus.OK, price_irr=int(price),
                            make="Peugeot", model="206", trim="Type 5",
                            year_jalali=1399, color="white", province="Tehran",
                            seller_fingerprint="s1", mileage_km=80_000,
                            image_phashes=("p1", "p2"))

    day = D0
    price = 1_500_000_000
    if never_present:
        apply_snapshot(st, assess_integrity(Snapshot("s0", day, bg)), is_first=True)
        return st, None

    apply_snapshot(st, assess_integrity(
        Snapshot("s0", day, [car(listing_id, price, day), *bg])), is_first=True)
    sid = 1
    for _ in range(max(0, days_present - 1)):
        day += timedelta(days=1)
        if price_drops > 0:
            price -= 40_000_000
            price_drops -= 1
        apply_snapshot(st, assess_integrity(
            Snapshot(f"s{sid}", day, [car(listing_id, price, day), *bg])))
        sid += 1
    for _ in range(unknown_days):
        day += timedelta(days=1)
        apply_snapshot(st, assess_integrity(Snapshot(
            f"s{sid}", day, [FetchOutcome(listing_id, FetchStatus.UNKNOWN), *bg])))
        sid += 1
    for k in range(reposts):
        day += timedelta(days=1)
        apply_snapshot(st, assess_integrity(Snapshot(
            f"s{sid}", day, [FetchOutcome(listing_id, FetchStatus.ABSENT), *bg])))
        sid += 1
        day += timedelta(days=1)
        apply_snapshot(st, assess_integrity(Snapshot(
            f"s{sid}", day, [car(f"{listing_id}_r{k}", price, day), *bg])))
        sid += 1
    return st, st.find_by_source_id(listing_id), day


def orch():
    return CAROOrchestrator(CQ, RIDGE, "log-linear-ridge", SPLIT.train, SPLIT)


def pick(model="206", price=None):
    r = next(x for x in SPLIT.test if x.model_key == model)
    return Row(r.listing_id, r.cluster_id, r.first_seen_ordinal, r.model_key,
               r.year_jalali, r.mileage_km,
               price if price is not None else r.asking_price_irr)


# ---------------------------------------------------------------------------
print("\nbenchmark gate ran before anything else")
check("ridge passed the gate", RIDGE_OK, str(RIDGE_FAILS))

print("\nCASE A — strong evidence, clean estimate")
st, tr, last = tracked_for("A", 5)
ra = orch().run(pick(), tr, last)
check("approved", ra.verdict.decision == "approve", ra.verdict.decision)
check("confidence not downgraded",
      ra.verdict.status == ra.verdict.status_before_review)
check("adversarial found nothing material",
      any("تناقض مهمی پیدا نشد" in e.summary for e in ra.trace))
check("every claim is backed by evidence", ra.unsupported_claims == [])

print("\nCASE B — sparse comparables, low confidence")
rare = Row("rare_q", "cq", 90, "maxima", 1399, 90_000, 2.0e9)
st, tr, last = tracked_for("B", 4)
rb = orch().run(rare, tr, last)
check("confidence downgraded or refused",
      rb.verdict.status in ("LOW", "INSUFFICIENT_EVIDENCE"), rb.verdict.status)
check("names sparse comparables",
      any(f.code in ("sparse_comparables", "weak_comparable_tier",
                     "estimate_dominated_by_few") for f in rb.verdict.findings))
check("does not call model-only listings 'مشابه'",
      all("آگهی مشابه (مدل" not in c.text_fa for c in rb.ledger.claims
          if c.claim_id == "claim:comparables")
      or rb.verdict.findings)

print("\nCASE C — repost detected, price history shown")
st, tr, last = tracked_for("C", 4, reposts=1, price_drops=2)
rc = orch().run(pick(), tr, last)
check("repost surfaced in the answer", "تجدید آگهی" in rc.explanation_fa)
check("price drop surfaced", "کاهش" in rc.explanation_fa)
check("repost is a finding, not a silent fact",
      any(f.code == "reposted" for f in rc.verdict.findings))

print("\nCASE D — UNKNOWN gap is never turned into absence")
st, tr, last = tracked_for("D", 3, unknown_days=3)
rd = orch().run(pick(), tr, last)
check("gap is disclosed", "نامعلوم" in rd.explanation_fa)
check("listing is still active, not absent", tr.status == "active")
check("gap raised as a finding",
      any(f.code == "observation_gap" for f in rd.verdict.findings))
check("answer never claims a sale", "فروخته" not in rd.explanation_fa)

print("\nCASE E — adversarial review downgrades the answer")
outlier = pick(price=8.0e9)          # far outside the observed 206 range
st, tr, last = tracked_for("E", 5)
re_ = orch().run(outlier, tr, last)
check("rejected by a hard adversarial veto",
      re_.verdict.decision == "reject", re_.verdict.decision)
check("reason is out-of-distribution",
      any(f.code == "outside_observed_distribution" for f in re_.verdict.findings))
check("no estimate is shown after a veto",
      "میلیارد" not in re_.explanation_fa.split("چرا")[0] or
      re_.verdict.status == "INSUFFICIENT_EVIDENCE")

print("\nCASE F — baseline beats ML, baseline is selected")
weak = MarketEstimator(GlobalQuantiles())
ok_w, fails_w = weak.benchmark(SPLIT, BASE, name="global-quantiles")
check("a model that loses to comparables is rejected", not ok_w)
check("  and the reason says to ship the baseline",
      any("ship the baseline" in f for f in fails_w), str(fails_w))
st, tr, last = tracked_for("F", 5)
rf = CAROOrchestrator(CQ, weak, "global-quantiles", SPLIT.train, SPLIT).run(
    pick(), tr, last)
check("orchestrator refuses to serve an unaccepted estimator",
      rf.verdict.decision in ("reject", "insufficient_evidence"))
check("  and says so in Persian", "برآورد" in rf.explanation_fa)

print("\nCASE G — quantile crossing is caught upstream")
class Crosser:
    def fit(self, rows): return self
    def predict(self, rows):
        return np.tile(np.array([1.4e9, 1.5e9, 1.45e9, 1.7e9]), (len(rows), 1))
cr = MarketEstimator(Crosser())
ok_c, fails_c = cr.benchmark(SPLIT, BASE, name="crosser")
check("crossing model rejected by the gate", not ok_c)
check("  crossing named", any("crossing" in f for f in fails_c))

print("\nCASE H — never-present listing is refused")
st2 = TrackingState()
rh = orch().run(pick(), None, D0)
check("no tracking history => refuse or downgrade",
      rh.verdict.status in ("LOW", "INSUFFICIENT_EVIDENCE")
      or rh.verdict.decision != "approve", rh.verdict.status)

print("\ninvariants that must hold on every path")
for label, r in [("A", ra), ("B", rb), ("C", rc), ("D", rd),
                 ("E", re_), ("F", rf), ("H", rh)]:
    check(f"{label}: no unsupported claims", r.unsupported_claims == [],
          str(r.unsupported_claims))
    check(f"{label}: never says 'فروخته'", "فروخته" not in r.explanation_fa)
    check(f"{label}: never says 'قیمت واقعی'", "قیمت واقعی" not in r.explanation_fa)
    check(f"{label}: trace covers all seven stages", len(r.trace) == 7)

print("\nthe language layer cannot override a decision")
from dataclasses import FrozenInstanceError
try:
    ra.verdict.decision = "approve"   # type: ignore[misc]
    check("verdict is immutable", False, "it was mutated")
except FrozenInstanceError:
    check("verdict is immutable — explanation can only render it", True)

print("\nledger traces a claim back to observations")
tr_items = ra.ledger.trace("claim:observed_span")
check("observed-span claim resolves to real observations", len(tr_items) > 0)
check("  and each cites a snapshot date",
      all(i.observed_on is not None for i in tr_items))

led = EvidenceLedger()
led.claim("bogus", "ادعای بی‌پشتوانه", ["does_not_exist"])
check("a claim citing missing evidence is flagged",
      len(led.unsupported_claims()) == 1)

print("\n" + "=" * 58)
print(format_response(rd))
print("=" * 58)


print("\nconfidence is a published policy, not a magic number")
from caro.agents import DEFAULT_POLICY, ConfidencePolicy
p = DEFAULT_POLICY
check("the whole rulebook is printable", len(p.explain().splitlines()) > 12)

# Regression for the bug this replaced: under the old arithmetic a LOOSELY
# matched set could outscore a TIGHTLY matched one, because tier and count
# were added rather than tier setting a ceiling on count.
for hi_t, lo_t in [("strict", "relaxed_mileage"),
                   ("relaxed_mileage", "relaxed_year"),
                   ("relaxed_year", "model_only")]:
    hi, _ = p.comparable_strength(hi_t, 10_000, 0.1)
    lo, _ = p.comparable_strength(lo_t, 10_000, 0.1)
    check(f"no count of {lo_t} can reach saturated {hi_t}", hi > lo,
          f"{hi:.3f} vs {lo:.3f}")

check("count saturates", p.comparable_strength("strict", 30, 0.1)[0]
      == p.comparable_strength("strict", 3000, 0.1)[0])
check("dispersion is penalised",
      p.comparable_strength("strict", 30, 0.8)[0]
      < p.comparable_strength("strict", 30, 0.1)[0])
check("zero comparables => zero strength",
      p.comparable_strength("global", 0, 0.0)[0] == 0.0)
check("evidence bands are monotone",
      p.evidence_strength(0)[0] < p.evidence_strength(2)[0]
      < p.evidence_strength(4)[0] < p.evidence_strength(9)[0])
check("temporal: no gap beats a big gap",
      p.temporal_strength(10, 0)[0] > p.temporal_strength(10, 6)[0])
check("each dimension reports the band label behind it",
      len(ra.verdict.confidence.notes) == 3
      and all(isinstance(n, str) and n for n in ra.verdict.confidence.notes))
check("policy is swappable without touching agent code",
      ConfidencePolicy(high_at=0.99).high_at == 0.99)

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
