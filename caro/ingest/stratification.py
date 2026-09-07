"""
How the sample is distributed across the facets it was collected through —
and how much the answer would move if that distribution were different.

The failure this exists for is not degeneracy. `coverage.py` asks whether the
cars are sufficiently *different*; this module asks whether they are present
in the right *proportions*. Those are separate questions and a sample can
pass one while failing the other.

Run 3 made the problem concrete. Bama publishes ~34 trim-level category pages
under `pride`, each with its own ceiling of roughly twenty listings. Sampling
all of them yields 48 eligible Prides that are genuinely varied — and gives
`pride-111-se` roughly the same weight as `pride-131-sl`, regardless of how
many of each are actually for sale. The result is a sample stratified by the
source's published facets, with unknown and non-proportional weights.

Why that is dangerous rather than merely imprecise: if rare trims are
systematically dearer or cheaper, the price distribution shifts, and
`AcceptanceGate` cannot see it — the train and test halves are drawn from the
same skewed design, so both carry the same bias and the model calibrates
beautifully against the wrong population. Same structural blindness as D6,
D21 and D25; fourth time.

**This module deliberately does not correct anything.** A valid design weight
is `w_i ∝ 1 / P(listing i is sampled)`, and we do not know `P(inclusion)`.
Three listings under one trim slug do not imply that trim is 3% of the market,
or 10%, or anything else — the count reflects the page's ceiling at least as
much as the market's composition. Inventing a weight from the sample's own
shape would launder an assumption into a number. So: measure, report, and
make the limitation explicit (D29).
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field


def trim_key(row) -> str:
    """The facet a listing was collected through, as far as we can tell."""
    return f"{row.make} {row.model} {row.trim or '(base)'}".strip()


def herfindahl(shares) -> float:
    """Σ p². 1.0 = one trim holds everything; 1/k = perfectly even."""
    return sum(p * p for p in shares)


def normalised_entropy(shares) -> float:
    """H / ln(k) — 1.0 is a flat distribution, 0.0 is a point mass.

    Reported alongside HHI because they disagree usefully: entropy is more
    sensitive to how many trims are present at all, HHI to whether a few
    dominate.
    """
    ps = [p for p in shares if p > 0]
    if len(ps) < 2:
        return 0.0
    h = -sum(p * math.log(p) for p in ps)
    return h / math.log(len(ps))


def kish_effective_n(weights) -> float:
    """(Σw)² / Σw² — how many equally-weighted observations the weighted
    sample is worth. Under equal weights it is just n; the gap between n and
    n_eff is the price of an uneven design."""
    s1 = sum(weights)
    s2 = sum(w * w for w in weights)
    return (s1 * s1 / s2) if s2 > 0 else 0.0


@dataclass
class StratumReport:
    model: str
    counts: Counter = field(default_factory=Counter)   # trim -> eligible n
    n_eligible: int = 0

    @property
    def shares(self) -> list[float]:
        if not self.n_eligible:
            return []
        return [c / self.n_eligible for c in self.counts.values()]

    @property
    def hhi(self) -> float:
        return herfindahl(self.shares)

    @property
    def entropy(self) -> float:
        return normalised_entropy(self.shares)

    @property
    def n_eff_equal_trim(self) -> float:
        """Effective n if every trim were given equal total weight.

        This is not a proposal to weight that way — it is a diagnostic. A
        large gap between n and this number means the answer under
        equal-trim weighting rests on far fewer effective observations than
        the raw count suggests.
        """
        if not self.counts:
            return 0.0
        # each listing in a trim of size c gets weight 1/c, so trims are equal
        ws = [1.0 / c for c, n in ((c, c) for c in self.counts.values())
              for _ in range(n)]
        return kish_effective_n(ws)

    @property
    def top(self) -> tuple[str, int] | None:
        return self.counts.most_common(1)[0] if self.counts else None


def stratify(rows) -> dict[str, StratumReport]:
    from caro.ingest.quality import eligibility
    out: dict[str, StratumReport] = {}
    for r in rows:
        if not r.model or not eligibility(r)[0]:
            continue
        key = f"{r.make} {r.model}"
        rep = out.setdefault(key, StratumReport(model=key))
        rep.counts[trim_key(r)] += 1
        rep.n_eligible += 1
    return out


# ---------------------------------------------------------------------------
# Sensitivity: would a different weighting change the answer?
# ---------------------------------------------------------------------------

def weighted_quantile(pairs, q: float) -> float | None:
    """pairs: (value, weight). Linear on the cumulative weight."""
    pts = sorted((v, w) for v, w in pairs if v is not None and w > 0)
    if not pts:
        return None
    total = sum(w for _, w in pts)
    target, run = q * total, 0.0
    for v, w in pts:
        run += w
        if run >= target:
            return float(v)
    return float(pts[-1][0])


def sensitivity(rows, q: float = 0.5) -> dict:
    """The same quantile under several defensible weightings.

    Reported even though none of them enters the estimator, because the
    spread IS the finding: an estimate that moves 3% across reasonable
    sampling assumptions and one that moves 30% are different products, and
    only the second's uncertainty is dominated by the acquisition design
    rather than by model error.

    Schemes:
      observed        every listing counts once — what we actually collected
      equal_trim      every trim contributes equally, whatever its count
      drop_one_trim   min and max over removing each trim in turn
    """
    from caro.ingest.quality import eligibility
    elig = [r for r in rows if r.model and eligibility(r)[0]]
    if len(elig) < 4:
        return {}

    vals = [(r.asking_price_toman, trim_key(r)) for r in elig]
    observed = weighted_quantile([(v, 1.0) for v, _ in vals], q)

    sizes = Counter(t for _, t in vals)
    equal_trim = weighted_quantile([(v, 1.0 / sizes[t]) for v, t in vals], q)

    drops = {}
    for t in sizes:
        rest = [(v, 1.0) for v, tt in vals if tt != t]
        if len(rest) >= 4:
            drops[t] = weighted_quantile(rest, q)
    lo = min(drops.values()) if drops else None
    hi = max(drops.values()) if drops else None

    span = None
    if observed and equal_trim and lo and hi:
        span = (max(hi, equal_trim) - min(lo, equal_trim)) / observed

    return {"observed": observed, "equal_trim": equal_trim,
            "drop_one_min": lo, "drop_one_max": hi,
            "relative_span": span,
            "worst_drop": (min(drops, key=drops.get) if drops else None)}


# ---------------------------------------------------------------------------
# The preconditions that make a conditional estimand safe under this design
# ---------------------------------------------------------------------------
#
# D29 concluded that uneven trim sampling costs precision within a trim rather
# than biasing a CONDITIONAL estimate. That conclusion is not free — it holds
# only under stated conditions, and three of the four are checkable, so they
# are checked rather than asserted. The fourth (that no downstream aggregate
# silently assumes sampling weights) is a scope rule, enforced by
# `AggregateOutOfScope` in the appraisal layer.

# Below this, a trim's own estimate is being carried by the pooled
# distribution rather than by its own observations, which is precisely the
# extrapolation the conditional argument assumes is not happening.
MIN_PER_TRIM = 5


@dataclass(frozen=True)
class ScopeCheck:
    ok: bool
    failures: list[str]
    thin_trims: list[tuple[str, int]]
    covered_share: float          # fraction of listings in adequately-sized trims


def conditional_scope(rows, min_per_trim: int = MIN_PER_TRIM) -> ScopeCheck:
    """Is the conditional reading of this corpus actually supported?

    Conditions, from D29:

      1. trim is present as a conditioning value at all — a row with no trim
         cannot be conditioned on one;
      2. each trim carries enough observations to speak for itself;
      3. the share of listings sitting in adequately-sized trims is high
         enough that the estimator is not mostly extrapolating.

    Failing this does not mean the corpus is useless. It means the
    *conditional* defence of unweighted trim sampling does not apply to it,
    and the sampling span must be treated as bias rather than as precision.
    """
    from caro.ingest.quality import eligibility
    elig = [r for r in rows if r.model and eligibility(r)[0]]
    failures: list[str] = []
    if not elig:
        return ScopeCheck(False, ["no appraisal-eligible rows"], [], 0.0)

    missing_trim = sum(1 for r in elig if not r.trim)
    if missing_trim:
        failures.append(
            f"{missing_trim}/{len(elig)} eligible rows carry no trim, so they "
            "cannot be conditioned on one")

    sizes = Counter(trim_key(r) for r in elig)
    thin = sorted(((t, c) for t, c in sizes.items() if c < min_per_trim),
                  key=lambda kv: kv[1])
    covered = sum(c for c in sizes.values() if c >= min_per_trim) / len(elig)
    if covered < 0.70:
        failures.append(
            f"only {covered:.0%} of listings sit in trims with "
            f"{min_per_trim}+ observations — the rest are priced by "
            "extrapolation from the pooled distribution, which is the "
            "assumption the conditional argument rules out")
    return ScopeCheck(not failures, failures, thin, covered)


def report(rows) -> list[str]:
    strata = stratify(rows)
    if not strata:
        return []
    L = ["", "STRATIFICATION  (variation is not representativeness)", "-" * 68,
         f"  {'model':<16}{'elig':>5}{'trims':>7}{'top-trim':>10}"
         f"{'HHI':>7}{'entropy':>9}{'n_eff':>8}"]
    for key, rep in sorted(strata.items(), key=lambda kv: -kv[1].n_eligible):
        if rep.n_eligible < 10:
            continue
        top = rep.top
        L.append(f"  {key:<16}{rep.n_eligible:>5}{len(rep.counts):>7}"
                 f"{(top[1] / rep.n_eligible if top else 0):>9.0%}"
                 f"{rep.hhi:>7.2f}{rep.entropy:>9.2f}"
                 f"{rep.n_eff_equal_trim:>8.1f}")

    L += ["", "  MEDIAN ASKING PRICE UNDER DIFFERENT SAMPLING WEIGHTS",
          "  " + "-" * 66]
    for key, rep in sorted(strata.items(), key=lambda kv: -kv[1].n_eligible):
        if rep.n_eligible < 10:
            continue
        sub = [r for r in rows if r.model and f"{r.make} {r.model}" == key]
        s = sensitivity(sub)
        if not s or s.get("observed") is None:
            continue
        B = 1e9
        L.append(f"  {key:<16} observed {s['observed']/B:.2f}B   "
                 f"equal-trim {s['equal_trim']/B:.2f}B   "
                 f"drop-one {s['drop_one_min']/B:.2f}–{s['drop_one_max']/B:.2f}B")
        if s.get("relative_span") is not None:
            flag = "  ⚠" if s["relative_span"] > 0.10 else ""
            L.append(f"  {'':<16} span {s['relative_span']:.1%} of the "
                     f"median{flag}")

    L += ["",
          "  These weightings are DIAGNOSTIC. None enters the estimator: a",
          "  valid design weight is 1/P(inclusion), and P(inclusion) is not",
          "  known — a trim's listing count reflects that page's ceiling at",
          "  least as much as its share of the market. See D29.",
          "",
          "  n_eff is NOT the eligible count. Pride reaches 48 eligible for",
          "  33.3 effective; Tiba 38 for 18.1. Both clear the count gate and",
          "  they are not in the same condition — which is what 30 is: a",
          "  safety floor, never a guarantee of precision or of coverage."]

    scope = conditional_scope(rows)
    L += ["", "  CONDITIONAL-SCOPE PRECONDITIONS (D29 (C))", "  " + "-" * 66,
          f"  {'satisfied' if scope.ok else 'NOT SATISFIED'} — "
          f"{scope.covered_share:.0%} of eligible listings sit in trims with "
          f"{MIN_PER_TRIM}+ observations"]
    for f in scope.failures:
        L.append(f"      ⚠ {f}")
    if scope.thin_trims:
        thin = ", ".join(f"{t} ({c})" for t, c in scope.thin_trims[:6])
        L.append(f"      thin trims: {thin}")
    L.append("      Failing these does not make the corpus useless; it means "
             "the conditional")
    L.append("      defence of unweighted trim sampling does not cover it, "
             "and the span")
    L.append("      above must be read as bias rather than as precision.")
    return L
