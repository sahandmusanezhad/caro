"""Tests for CARO longitudinal tracking.

Synthetic data is used here ONLY to exercise differ logic — this is the
unit-test-fixture carve-out, not product data. The product's corpus must be
real listings.

Run: python3 test_tracking.py
"""

from datetime import date, timedelta

from caro.tracking import (
    Observation, blocking_keys, hard_contradictions,
    FetchOutcome, FetchStatus, Snapshot, Integrity, TrackingState,
    assess_integrity, apply_snapshot, classify_http, repost_match_score,
    duration_stats, kaplan_meier_median, observed_age_claim_fa, w0_report,
)

D0 = date(2026, 9, 6)
FAILS: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name}  {detail}")
        FAILS.append(name)


def car(lid, price, *, mileage=80_000, seller="s1", phashes=("p1", "p2"),
        status=FetchStatus.OK):
    return FetchOutcome(
        listing_id=lid, status=status, asking_price_toman=price,
        make="Peugeot", model="206", trim="Type 5", year_jalali=1399,
        color="white", province="Tehran", seller_fingerprint=seller,
        mileage_km=mileage, image_phashes=phashes,
    )


def snap(sid, day, outcomes):
    return assess_integrity(Snapshot(sid, day, outcomes))


# ---------------------------------------------------------------------------
print("\nhttp classification — a block is not an absence")
check("200 => ok", classify_http(200) is FetchStatus.OK)
check("404 => absent", classify_http(404) is FetchStatus.ABSENT)
check("200 + removed marker => absent", classify_http(200, removed_marker=True) is FetchStatus.ABSENT)
for code in (403, 429, 500, 502, 503, None):
    check(f"{code} => unknown", classify_http(code) is FetchStatus.UNKNOWN)


# ---------------------------------------------------------------------------
print("\nsnapshot integrity — the guard that saves the dataset")
ok = snap("s", D0, [car(f"l{i}", 100) for i in range(20)])
check("clean snapshot is OK", ok.integrity is Integrity.OK)

blocked = snap("s", D0, [
    *[car(f"l{i}", 100) for i in range(5)],
    *[FetchOutcome(f"l{i}", FetchStatus.ABSENT) for i in range(5, 20)],
])
check("mass disappearance flagged SUSPECT", blocked.integrity is Integrity.SUSPECT,
      f"got {blocked.integrity}")

throttled = snap("s", D0, [
    *[car(f"l{i}", 100) for i in range(10)],
    *[FetchOutcome(f"l{i}", FetchStatus.UNKNOWN) for i in range(10, 20)],
])
check("heavy unknowns flagged PARTIAL", throttled.integrity is Integrity.PARTIAL,
      f"got {throttled.integrity}")

check("empty snapshot is SUSPECT", snap("s", D0, []).integrity is Integrity.SUSPECT)


# ---------------------------------------------------------------------------
print("\nsuspect snapshots must not corrupt state")
st = TrackingState()
apply_snapshot(st, snap("s0", D0, [car(f"l{i}", 100) for i in range(20)]), is_first=True)
before = len(st.active())
apply_snapshot(st, blocked)
check("SUSPECT snapshot ignored entirely", len(st.active()) == before,
      f"{before} -> {len(st.active())}")

st2 = TrackingState()
apply_snapshot(st2, snap("s0", D0, [car(f"l{i}", 100) for i in range(20)]), is_first=True)
partial = snap("s1", D0 + timedelta(days=1), [
    *[car(f"l{i}", 100) for i in range(10)],
    FetchOutcome("l10", FetchStatus.ABSENT),
    *[FetchOutcome(f"l{i}", FetchStatus.UNKNOWN) for i in range(11, 20)],
])
apply_snapshot(st2, partial)
check("PARTIAL snapshot does not record absences",
      st2.find_by_source_id("l10").status == "active")


# ---------------------------------------------------------------------------
print("\nunknown fetch leaves state untouched")
st = TrackingState()
apply_snapshot(st, snap("s0", D0, [car("a", 100)]), is_first=True)
apply_snapshot(st, snap("s1", D0 + timedelta(days=1), [FetchOutcome("a", FetchStatus.UNKNOWN)]))
t = st.find_by_source_id("a")
check("still active after an unknown fetch", t.status == "active")
check("last_observed_at not advanced by an unknown", t.last_observed_at == D0)


# ---------------------------------------------------------------------------
print("\nprice changes")
st = TrackingState()
apply_snapshot(st, snap("s0", D0, [car("a", 1_500_000_000)]), is_first=True)
apply_snapshot(st, snap("s1", D0 + timedelta(days=1), [car("a", 1_450_000_000)]))
apply_snapshot(st, snap("s2", D0 + timedelta(days=2), [car("a", 1_400_000_000)]))
t = st.find_by_source_id("a")
check("two price changes recorded", len(t.price_changes) == 2, f"got {len(t.price_changes)}")
check("current price updated", t.current_asking_price_toman == 1_400_000_000)


# ---------------------------------------------------------------------------
print("\nrepost linking — precision over recall")
old = car("old", 1_500_000_000, mileage=80_000, seller="s1", phashes=("p1", "p2", "p3"))

same = car("new", 1_450_000_000, mileage=81_000, seller="s1", phashes=("p1", "p2", "p3"))
s, _ = repost_match_score(old, same)
check("identical car relisted scores high", s >= 0.70, f"score={s:.2f}")

other_seller = car("new", 1_480_000_000, mileage=95_000, seller="s2", phashes=("z1",))
s, _ = repost_match_score(old, other_seller)
check("different seller + photos + mileage scores low", s < 0.70, f"score={s:.2f}")

rolled_back = car("new", 1_500_000_000, mileage=40_000, seller="s1", phashes=("p1", "p2", "p3"))
s, reasons = repost_match_score(old, rolled_back)
check("mileage running backwards blocks the link", s < 0.70, f"score={s:.2f}")
check("  and says why", any("mileage decreased" in r for r in reasons))

different_model = FetchOutcome("new", FetchStatus.OK, asking_price_toman=1_450_000_000,
                               make="Peugeot", model="405", trim="GLX",
                               year_jalali=1399, color="white", province="Tehran",
                               seller_fingerprint="s1", mileage_km=81_000,
                               image_phashes=("p1", "p2", "p3"))
s, _ = repost_match_score(old, different_model)
check("different model never links", s == 0.0)


# ---------------------------------------------------------------------------
print("\nrepost detection end to end — the flagship")

def background(n=25):
    """Unrelated stable listings, so integrity rates are computed on a real
    sample rather than on one car."""
    return [FetchOutcome(f"bg{i}", FetchStatus.OK, asking_price_toman=900_000_000 + i,
                         make="Saipa", model="Pride", trim="111",
                         year_jalali=1396, color="silver", province="Karaj",
                         seller_fingerprint=f"bg_s{i}", mileage_km=150_000,
                         image_phashes=(f"bg{i}a",))
            for i in range(n)]

st = TrackingState()
apply_snapshot(st, snap("s0", D0, [car("div_1", 1_500_000_000), *background()]), is_first=True)
apply_snapshot(st, snap("s1", D0 + timedelta(days=3),
                        [FetchOutcome("div_1", FetchStatus.ABSENT), *background()]))
apply_snapshot(st, snap("s2", D0 + timedelta(days=4),
                        [car("div_2", 1_460_000_000), *background()]))

check("integrity stays OK with a realistic sample",
      snap("s1", D0, [FetchOutcome("div_1", FetchStatus.ABSENT), *background()]).integrity is Integrity.OK)
check("one tracked car, not two", len(st.listings) == 26, f"got {len(st.listings)}")
t = st.find_by_source_id("div_2")
check("both source ids linked", set(t.source_listing_ids) == {"div_1", "div_2"})
check("repost counted", t.repost_count == 1)
check("active again", t.status == "active")
check("span covers the delisted gap", t.observed_span_days(D0 + timedelta(days=4)) == 4)

stale = TrackingState()
apply_snapshot(stale, snap("s0", D0, [car("div_1", 1_500_000_000), *background()]), is_first=True)
apply_snapshot(stale, snap("s1", D0 + timedelta(days=1),
                           [FetchOutcome("div_1", FetchStatus.ABSENT), *background()]))
apply_snapshot(stale, snap("s2", D0 + timedelta(days=40),
                           [car("div_2", 1_460_000_000), *background()]))
check("repost outside the window is a new listing", len(stale.listings) == 27,
      f"got {len(stale.listings)}")

print("\nsmall samples do not trip the rate guard")
tiny = snap("s", D0, [car("a", 100), FetchOutcome("b", FetchStatus.ABSENT)])
check("2-listing snapshot is not SUSPECT", tiny.integrity is Integrity.OK,
      f"got {tiny.integrity}")
check("  but says the check was skipped", any("below" in n for n in tiny.notes))


# ---------------------------------------------------------------------------
print("\nleft truncation — pre-existing listings are lower bounds only")
st = TrackingState()
apply_snapshot(st, snap("s0", D0, [car("pre", 100)]), is_first=True)
apply_snapshot(st, snap("s1", D0 + timedelta(days=1), [car("pre", 100), car("fresh", 200, seller="s9", phashes=("q1",))]))
check("first-snapshot listing marked unobserved", st.find_by_source_id("pre").observed_appearance is False)
check("later arrival marked observed", st.find_by_source_id("fresh").observed_appearance is True)

ds = duration_stats(st, D0 + timedelta(days=1))
check("truncated listing excluded from stats", ds.n_excluded_left_truncated == 1)
check("only the observed one is usable", ds.n_usable == 1)
check("truncation warned", any("LOWER BOUND" in w for w in ds.warnings))


# ---------------------------------------------------------------------------
print("\nkaplan-meier handles right censoring")
km = kaplan_meier_median([(5, True), (7, True), (9, True), (11, True), (13, True)])
check("all-complete median is sane", km in (9.0, 11.0), f"got {km}")

censored_only = kaplan_meier_median([(5, False), (7, False), (9, False)])
check("all-censored returns None, not a number", censored_only is None)

mixed_naive = [d for d, ev in [(3, True), (4, True), (60, False), (70, False), (80, False)] if ev]
km_mixed = kaplan_meier_median([(3, True), (4, True), (60, False), (70, False), (80, False)])
check("heavy censoring => KM refuses a median", km_mixed is None,
      f"got {km_mixed}; naive would have said {sum(mixed_naive)/len(mixed_naive)}")

ds = duration_stats(TrackingState(), D0)
check("empty state does not crash", ds.n_usable == 0)


# ---------------------------------------------------------------------------
print("\npersian claim never overstates")
st = TrackingState()
apply_snapshot(st, snap("s0", D0, [car("div_1", 1_500_000_000), *background()]), is_first=True)
apply_snapshot(st, snap("s1", D0 + timedelta(days=2), [car("div_1", 1_450_000_000), *background()]))
apply_snapshot(st, snap("s2", D0 + timedelta(days=5),
                        [FetchOutcome("div_1", FetchStatus.ABSENT), *background()]))
apply_snapshot(st, snap("s3", D0 + timedelta(days=6), [car("div_2", 1_400_000_000), *background()]))
t = st.find_by_source_id("div_2")
claim = observed_age_claim_fa(t, D0 + timedelta(days=6))
print(f"     → {claim}")
check("says 'at least' for a truncated listing", "حداقل" in claim)
check("mentions the repost", "تجدید آگهی" in claim)
check("mentions the price drop", "کاهش قیمت" in claim)
check("never claims a sale", "فروخته" not in claim)

check("no `sold` field exists anywhere", not hasattr(t, "sold"))


# ---------------------------------------------------------------------------
print("\nambiguity guard — refuse rather than guess")
amb = TrackingState()
twin_a = FetchOutcome("twin_a", FetchStatus.OK, asking_price_toman=1_500_000_000,
                      make="Peugeot", model="206", trim="Type 5", year_jalali=1399,
                      color="white", province="Tehran", seller_fingerprint="dealer",
                      mileage_km=80_000, image_phashes=("shared1", "shared2"))
twin_b = FetchOutcome("twin_b", FetchStatus.OK, asking_price_toman=1_500_000_000,
                      make="Peugeot", model="206", trim="Type 5", year_jalali=1399,
                      color="white", province="Tehran", seller_fingerprint="dealer",
                      mileage_km=80_000, image_phashes=("shared1", "shared2"))
apply_snapshot(amb, snap("s0", D0, [twin_a, twin_b, *background()]), is_first=True)
apply_snapshot(amb, snap("s1", D0 + timedelta(days=1), [
    FetchOutcome("twin_a", FetchStatus.ABSENT),
    FetchOutcome("twin_b", FetchStatus.ABSENT), *background()]))
n_before = len(amb.listings)
apply_snapshot(amb, snap("s2", D0 + timedelta(days=2), [
    FetchOutcome("twin_c", FetchStatus.OK, asking_price_toman=1_480_000_000,
                 make="Peugeot", model="206", trim="Type 5", year_jalali=1399,
                 color="white", province="Tehran", seller_fingerprint="dealer",
                 mileage_km=80_000, image_phashes=("shared1", "shared2")),
    *background()]))
check("two equally good parents => no link, new listing",
      len(amb.listings) == n_before + 1, f"{n_before} -> {len(amb.listings)}")
check("  and no repost was claimed",
      sum(t.repost_count for t in amb.listings.values()) == 0)


print("\nspan vs active vs gap are three different numbers")
t = st.find_by_source_id("div_2")   # appeared D0, gone D0+5, reposted D0+6
as_of = D0 + timedelta(days=6)
# Snapshots ran on D0, D0+2, D0+5, D0+6 only. Days 1, 3 and 4 were never
# checked, so they are ignorance — not "active".
check(f"span = 6 (got {t.observed_span_days(as_of)})", t.observed_span_days(as_of) == 6)
check(f"confirmed present = 3 (got {t.confirmed_present_days()})",
      t.confirmed_present_days() == 3)
check(f"confirmed absent = 1 (got {t.confirmed_absent_days()})",
      t.confirmed_absent_days() == 1)
check(f"unknown = 3 (got {t.unknown_days(as_of)})", t.unknown_days(as_of) == 3)
check("span+1 == present + absent + unknown",
      t.observed_span_days(as_of) + 1 ==
      t.confirmed_present_days() + t.confirmed_absent_days() + t.unknown_days(as_of))
check("unknown gap is flagged", t.has_unknown_gap(as_of))
check("no attribute called `age` survives", not hasattr(t, "observed_age_days"))
check("no attribute called `active_observed_days` survives",
      not hasattr(t, "active_observed_days"))

# The exact scenario the review raised: OK, UNKNOWN, UNKNOWN, OK.
gapst = TrackingState()
apply_snapshot(gapst, snap("g0", D0, [car("g", 100)]), is_first=True)
apply_snapshot(gapst, snap("g1", D0 + timedelta(days=1), [FetchOutcome("g", FetchStatus.UNKNOWN)]))
apply_snapshot(gapst, snap("g2", D0 + timedelta(days=2), [FetchOutcome("g", FetchStatus.UNKNOWN)]))
apply_snapshot(gapst, snap("g3", D0 + timedelta(days=3), [car("g", 100)]))
g = gapst.find_by_source_id("g")
gas = D0 + timedelta(days=3)
check(f"blocked days counted as unknown, not active (got {g.unknown_days(gas)})",
      g.unknown_days(gas) == 2)
check("only the two days we actually saw it count as present",
      g.confirmed_present_days() == 2, f"got {g.confirmed_present_days()}")
check("claim discloses the unknown gap",
      "نامعلوم" in observed_age_claim_fa(g, gas))

print("\nmulti-key blocking recovers recall lost to normalisation drift")
a = car("a", 1_500_000_000, phashes=("i1", "i2"))
b = FetchOutcome("b", FetchStatus.OK, asking_price_toman=1_460_000_000,
                 make="Peugeot", model="206", trim="تیپ ۵",      # re-normalised
                 year_jalali=1399, color="سفید صدفی",            # re-normalised
                 province="Tehran", seller_fingerprint="s1",
                 mileage_km=81_000, image_phashes=("i1", "i2"))
check("trim/colour drift no longer vetoes", hard_contradictions(a, b) == [])
check("  candidates still share a block", bool(set(blocking_keys(a)) & set(blocking_keys(b))))
sc, _ = repost_match_score(a, b)
check(f"  and the pair still links (score={sc:.2f})", sc >= 0.70)
check("different year is still a hard veto",
      any("year" in r for r in hard_contradictions(
          a, FetchOutcome("c", FetchStatus.OK, make="Peugeot", model="206",
                          year_jalali=1401))))


print("\nkaplan-meier tie handling")
from caro.tracking import kaplan_meier_curve
# 4 listings, 2 disappear on day 5, 2 censored on day 5
curve = kaplan_meier_curve([(5, True), (5, True), (5, False), (5, False)])
t5, s5, at_risk, events = curve[0]
check("censored-at-t counted in the day-5 risk set", at_risk == 4, f"got {at_risk}")
check("both day-5 events counted", events == 2, f"got {events}")
check("S(5) = 1 - 2/4 = 0.5", abs(s5 - 0.5) < 1e-9, f"got {s5}")
check("median is 5 (first t where S<=0.5)",
      kaplan_meier_median([(5, True), (5, True), (5, False), (5, False)]) == 5.0)
check("curve is monotone non-increasing",
      all(curve[i][1] >= curve[i + 1][1] for i in range(len(curve) - 1)))

big = kaplan_meier_curve([(i % 30, i % 3 == 0) for i in range(2000)])
check("scales without quadratic blowup", len(big) == 30)


print("\nreport renders")
print()
print(w0_report(st, [snap("s0", D0, []), blocked], D0 + timedelta(days=6)))

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
