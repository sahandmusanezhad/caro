#!/usr/bin/env python3
"""The README's three charts, drawn from the published corpora.

    python3 scripts/readme_charts.py           # write docs/readme/*.svg
    python3 scripts/readme_charts.py --check   # say whether they are current

A number on a chart is a claim like any other, and a claim kept by hand
beside the file it describes drifts. So every figure on these charts is
read from data/corpora when the chart is drawn, and tests/test_claims.py
asserts that the committed files are what this script draws today: a corpus
published, or a rule changed, and the suite says which chart is stale.

Each chart is drawn twice, for the light and the dark scheme, in the site's
own palette (webapp/web/app/globals.css), and the README shows the one that
matches the reader's. Nothing here is an estimate: the charts count listings
and the middle of asking prices, as the site does (webapp/api/market.py).

Standard library and caro's own reader; no network.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from statistics import median
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from caro.corpus_reader import CORPORA, rows_from_corpus           # noqa: E402
from caro.ingest.quality import UNUSABLE_PRICE, eligibility          # noqa: E402

OUT = ROOT / "docs" / "readme"

# The site's tokens, both schemes (webapp/web/app/globals.css). `track` is a
# lighter step of the accent's own ramp for the light scheme and a darker one
# for the dark, each at 2:1 or more against its surface.
SCHEMES = {
    "light": {"surface": "#ffffff", "ink": "#0c0c0b", "ink2": "#55554e", "ink3": "#8b8b83",
              "line": "#e5e5e1", "line2": "#d0d0ca", "accent": "#ef4a1e", "track": "#f29a7c",
              "neutral": "#55554e"},
    "dark": {"surface": "#131312", "ink": "#f5f5f2", "ink2": "#a9a9a1", "ink3": "#74746d",
             "line": "#242422", "line2": "#34342f", "accent": "#ff6234", "track": "#7a321c",
             "neutral": "#a9a9a1"},
}
FONT = "system-ui, -apple-system, 'Segoe UI', Helvetica, Arial, sans-serif"
SOURCE_NAME = {"bama": "Bama", "khodro45": "Khodro45", "divar": "Divar", "sheypoor": "Sheypoor"}
WIDTH = 880


# --------------------------------------------------------------------------
# What the charts read
# --------------------------------------------------------------------------

def corpora() -> list[dict]:
    """Every published corpus, by collection date."""
    out = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(CORPORA.glob("*.json"))]
    return sorted(out, key=lambda a: (a["collected_on"], a["run_id"]))


def priced(x) -> int | None:
    """The site's rule for a priced listing (webapp/api/market.py, `priced`)."""
    p = getattr(x, "asking_price_toman", None)
    if p is None or p <= 0:
        return None
    status = getattr(x, "price_status", None)
    if getattr(status, "value", status) in {s.value for s in UNUSABLE_PRICE}:
        return None
    if getattr(x, "price_kind", None) not in (None, "cash"):
        return None
    return int(p)


def runs_data(arts: list[dict]) -> list[dict]:
    """Per corpus: its run, source, date, listings and appraisal-eligible."""
    out = []
    for a in arts:
        listings, eligible = rows_from_corpus(a)
        out.append({"run_id": a["run_id"], "source": a["source"], "collected_on": a["collected_on"],
                    "listings": len(listings), "eligible": len(eligible)})
    return out


def pride_data(arts: list[dict]) -> list[dict]:
    """The Saipa Prides' middle asking price in each Bama run, and its count."""
    out = []
    for a in arts:
        if a["source"] != "bama":
            continue
        listings, _ = rows_from_corpus(a)
        ps = [p for x in listings
              if getattr(x, "product_class", None) == "vehicle"
              and ((x.make or "").strip(), (x.model or "").strip()) == ("Saipa", "Pride")
              and (p := priced(x)) is not None]
        if len(ps) >= 3:
            out.append({"run_id": a["run_id"], "collected_on": a["collected_on"],
                        "priced": len(ps), "middle": median(ps)})
    return out


# The reason a listing is held back, in a buyer's words, by the first of these
# its refusals name; each listing is counted once.
REASONS = (
    ("price is a financing_total", "An instalment total, not a cash price"),
    ("price is a negotiable", "Negotiable: no price stated"),
    ("price is far_from_model", "Far from its model's middle"),
    ("no asking_price_toman", "No price stated"),
    ("price is ambiguous", "A price that cannot be read as one"),
    ("mileage is suspicious", "An odometer that cannot be true"),
    ("no mileage_km", "No odometer stated"),
)


def held_back_data(art: dict) -> tuple[int, int, list[tuple[str, int]]]:
    """(listings, appraisal-eligible, [(reason, count)]) for one corpus."""
    listings, eligible = rows_from_corpus(art)
    counts: Counter = Counter()
    for x in listings:
        ok, why = eligibility(x)
        if ok:
            continue
        label = next((fa for key, fa in REASONS if any(w.startswith(key) for w in why)), why[0])
        counts[label] += 1
    order = [fa for _key, fa in REASONS]
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], order.index(kv[0]) if kv[0] in order else 99))
    return len(listings), len(eligible), ranked


# --------------------------------------------------------------------------
# Drawing
# --------------------------------------------------------------------------

def _t(x, y, s, size=12, fill="ink", weight=400, anchor="start", c=None, extra=""):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
            f'fill="{c[fill]}" text-anchor="{anchor}"{extra}>{escape(str(s))}</text>')


def _hbar(x, y, w, h, color, r=4):
    """A bar from the baseline at x, its far end rounded, its base square."""
    if w <= 0:
        return ""
    r = min(r, w, h / 2)
    return (f'<path d="M{x:.1f},{y:.1f} H{x + w - r:.1f} Q{x + w:.1f},{y:.1f} {x + w:.1f},{y + r:.1f} '
            f'V{y + h - r:.1f} Q{x + w:.1f},{y + h:.1f} {x + w - r:.1f},{y + h:.1f} H{x:.1f} Z" '
            f'fill="{color}"/>')


def _card(height, title, subtitle, body, c, label):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{height}" '
            f'viewBox="0 0 {WIDTH} {height}" role="img" aria-labelledby="t d" '
            f'font-family="{FONT}">\n'
            f'<title id="t">{escape(title)}</title>\n<desc id="d">{escape(label)}</desc>\n'
            f'<rect x="0.5" y="0.5" width="{WIDTH - 1}" height="{height - 1}" rx="14" '
            f'fill="{c["surface"]}" stroke="{c["line"]}"/>\n'
            + _t(28, 40, title, 16, "ink", 600, c=c) + "\n"
            + _t(28, 62, subtitle, 12.5, "ink2", c=c) + "\n"
            + body + "\n</svg>\n")


def _fmt_m(v: float) -> str:
    m = v / 1e6
    return f"{m:,.1f} M".replace(".0 M", " M")


def chart_runs(runs: list[dict], c: dict) -> str:
    left, right, top, row = 230, 96, 112, 46
    plot = WIDTH - left - right
    top_n = max(r["listings"] for r in runs)
    scale_max = -(-top_n // 100) * 100
    x = lambda v: left + plot * v / scale_max              # noqa: E731
    height = top + row * len(runs) + 52
    parts = []
    # legend, top right
    lx = WIDTH - 28 - 300
    parts.append(f'<rect x="{lx}" y="{82}" width="12" height="12" rx="3" fill="{c["accent"]}"/>')
    parts.append(_t(lx + 18, 92, "appraisal-eligible", 12, "ink2", c=c))
    parts.append(f'<rect x="{lx + 150}" y="{82}" width="12" height="12" rx="3" fill="{c["track"]}"/>')
    parts.append(_t(lx + 168, 92, "listings", 12, "ink2", c=c))
    # gridlines and ticks
    base_y = top + row * len(runs) + 4
    for v in range(0, scale_max + 1, 100):
        gx = x(v)
        parts.append(f'<line x1="{gx:.1f}" y1="{top - 8}" x2="{gx:.1f}" y2="{base_y}" '
                     f'stroke="{c["line"] if v else c["line2"]}" stroke-width="1"/>')
        parts.append(_t(gx, base_y + 18, f"{v:,}", 11, "ink3", anchor="middle", c=c,
                        extra=' style="font-variant-numeric:tabular-nums"'))
    for i, r in enumerate(runs):
        y = top + i * row
        name = f'{r["run_id"]} · {SOURCE_NAME.get(r["source"], r["source"])}'
        parts.append(_t(28, y + 13, name, 13, "ink", 600, c=c))
        parts.append(_t(28, y + 30, r["collected_on"], 11.5, "ink3", c=c,
                        extra=' style="font-variant-numeric:tabular-nums"'))
        bh = 18
        parts.append(_hbar(left, y + 4, x(r["listings"]) - left, bh, c["track"]))
        parts.append(_hbar(left, y + 4, x(r["eligible"]) - left, bh, c["accent"]))
        parts.append(_t(x(r["listings"]) + 8, y + 18, f'{r["eligible"]} of {r["listings"]}', 12.5, "ink",
                        600, c=c, extra=' style="font-variant-numeric:tabular-nums"'))
    total = sum(r["listings"] for r in runs)
    title = f"{len(runs)} published runs, {total:,} listings"
    subtitle = "Per run: the listings it holds, and those the gate lets inform an estimate"
    label = "; ".join(f'{r["run_id"]} ({r["source"]}, {r["collected_on"]}): {r["listings"]} listings, '
                      f'{r["eligible"]} appraisal-eligible' for r in runs)
    return _card(height, title, subtitle, "\n".join(parts), c, label)


def chart_pride(points: list[dict], c: dict) -> str:
    left, right, top, bottom = 150, 110, 104, 84
    height = 360
    plot_w, plot_h = WIDTH - left - right, height - top - bottom
    # Runs, evenly spaced and in order: the dates are printed under each, and
    # the axis says «run by run», not a calendar.
    days = list(range(len(points)))
    span = max(len(points) - 1, 1)
    lo, hi = 550e6, 700e6
    while min(p["middle"] for p in points) < lo:
        lo -= 50e6
    while max(p["middle"] for p in points) > hi:
        hi += 50e6
    x = lambda d: left + plot_w * d / span                  # noqa: E731
    y = lambda v: top + plot_h * (hi - v) / (hi - lo)       # noqa: E731
    parts = []
    v = lo
    while v <= hi + 1:
        gy = y(v)
        parts.append(f'<line x1="{left - 56}" y1="{gy:.1f}" x2="{WIDTH - right + 56}" y2="{gy:.1f}" '
                     f'stroke="{c["line"]}" stroke-width="1"/>')
        parts.append(_t(left - 68, gy + 4, _fmt_m(v), 11, "ink3", anchor="end", c=c,
                        extra=' style="font-variant-numeric:tabular-nums"'))
        v += 50e6
    pts = [(x(d), y(p["middle"])) for d, p in zip(days, points)]
    path = " ".join(("M" if i == 0 else "L") + f"{px:.1f},{py:.1f}" for i, (px, py) in enumerate(pts))
    parts.append(f'<path d="{path}" fill="none" stroke="{c["accent"]}" stroke-width="2" '
                 f'stroke-linejoin="round" stroke-linecap="round"/>')
    for (px, py), p in zip(pts, points):
        parts.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="5" fill="{c["accent"]}" '
                     f'stroke="{c["surface"]}" stroke-width="2"/>')
        parts.append(_t(px, py - 14, _fmt_m(p["middle"]), 12.5, "ink", 600, anchor="middle", c=c,
                        extra=' style="font-variant-numeric:tabular-nums"'))
        parts.append(_t(px, height - bottom + 26, p["run_id"], 12, "ink", 600, anchor="middle", c=c))
        parts.append(_t(px, height - bottom + 44, f'{p["collected_on"]} · {p["priced"]} priced', 11,
                        "ink3", anchor="middle", c=c, extra=' style="font-variant-numeric:tabular-nums"'))
    title = "The middle asking price of the Saipa Prides, run by run"
    subtitle = ("Bama's published runs. Asking prices, not sales: each point is the median "
                "of that run's priced Pride listings")
    label = "; ".join(f'{p["run_id"]} ({p["collected_on"]}): middle {p["middle"]:,.0f} toman '
                      f'of {p["priced"]} priced' for p in points)
    return _card(height, title, subtitle, "\n".join(parts), c, label)


def chart_held_back(run_id: str, n: int, ok: int, reasons: list[tuple[str, int]], c: dict) -> str:
    left, right, top, row = 300, 80, 104, 40
    plot = WIDTH - left - right
    top_n = max(v for _k, v in reasons) if reasons else 1
    x = lambda v: left + plot * v / (max(top_n, 1) * 1.25)  # noqa: E731
    height = top + row * len(reasons) + 40
    parts = []
    for i, (label, v) in enumerate(reasons):
        y = top + i * row
        parts.append(_t(left - 16, y + 15, label, 13, "ink", anchor="end", c=c))
        parts.append(_hbar(left, y + 2, x(v) - left, 18, c["neutral"]))
        parts.append(_t(x(v) + 8, y + 16, v, 12.5, "ink", 600, c=c,
                        extra=' style="font-variant-numeric:tabular-nums"'))
    title = f"{run_id}, the corpus the site serves: {ok} of {n} listings can inform an estimate"
    subtitle = f"Why the other {n - ok} are held back, each counted once. They stay listed; they are not priced against"
    label = "; ".join(f"{k}: {v}" for k, v in reasons)
    return _card(height, title, subtitle, "\n".join(parts), c, label)


SERVED = "run17"


def draw_all() -> dict[str, str]:
    """{file name under docs/readme: its SVG}, for both schemes."""
    arts = corpora()
    runs, pride = runs_data(arts), pride_data(arts)
    served = next(a for a in arts if a["run_id"] == SERVED)
    n, ok, reasons = held_back_data(served)
    out = {}
    for scheme, c in SCHEMES.items():
        out[f"runs-{scheme}.svg"] = chart_runs(runs, c)
        out[f"pride-{scheme}.svg"] = chart_pride(pride, c)
        out[f"held-back-{scheme}.svg"] = chart_held_back(SERVED, n, ok, reasons, c)
    return out


def stale() -> list[str]:
    """The chart files that are not what draw_all() draws today."""
    return sorted(name for name, svg in draw_all().items()
                  if not (OUT / name).is_file() or (OUT / name).read_text(encoding="utf-8") != svg)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="say whether the files are current")
    a = ap.parse_args()
    if a.check:
        bad = stale()
        print("current" if not bad else "stale: " + ", ".join(bad))
        return 1 if bad else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name, svg in draw_all().items():
        (OUT / name).write_text(svg, encoding="utf-8")
        print(f"wrote docs/readme/{name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
