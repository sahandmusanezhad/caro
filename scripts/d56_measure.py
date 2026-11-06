#!/usr/bin/env python3
"""D56's three conditions, measured rather than anticipated (docs/DECISIONS.md,
D56; docs/REARCHITECTURE.md, phase 7; docs/D56_REVIEW.md).

D56 keeps CARO in one language until one of three is demonstrated. Each is
a subcommand here, and none of them sends a request anywhere:

    window     1. Whether a crawl finishes in its window: each Tehran day's
                  collected runs from the runs' database (CARO_OPS_URL, or
                  --ops), how long each source's took, and how long the day
                  took run one after another and side by side.
    durations  2. Whether duration_stats is genuinely running: the snapshots
                  under a directory folded into tracking state day by day,
                  the observed disappearances against D56's thirty, the
                  censored and the left-truncated apart, and what folding
                  them cost.
    stages     3. Which stage, if any, is a bottleneck: the free-text parser,
                  canonicalisation, the index build, serialisation, the
                  comparison of two runs and the search, timed on the served
                  corpus grown to 500, 5,000 and 50,000 listings.
    profile       The search's hot path: the eight questions perf/search.js
                  asks, through the API in this process, under cProfile, by
                  stage.

The first two read the owner's data, on the owner's machine (or the
server's database); the last two need nothing but this checkout. The
decision is the owner's: this says what was measured.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# perf/search.js's questions, the ones the site's own checks ask.
QUESTIONS = ("سمند زیر ۲ میلیارد", "پژو ۲۰۶ تیپ ۲", "پراید کم کارکرد", "دنا پلاس اتوماتیک",
             "تیبا ۲ مدل ۱۴۰۰", "پژو پارس بدون رنگ", "ساینا زیر یک میلیارد", "هایما اس ۷")
SIZES = (500, 5_000, 50_000)
DISAPPEARANCES_D56 = 30


# ---------------------------------------------------------------------------
# 1. The window
# ---------------------------------------------------------------------------
def window_days(records: list[dict]) -> list[dict]:
    """Each Tehran day's collected runs: per source the longest run, and the
    day run one after another (the sum) and side by side (the longest)."""
    from caro.runs import tehran_day
    days: dict[str, dict[str, int]] = {}
    for r in records:
        if r.get("outcome") != "collected":
            continue
        took = int(r["finished_at"]) - int(r["started_at"])
        if took < 0:
            continue
        day = days.setdefault(r.get("collected_on") or tehran_day(r["started_at"]), {})
        day[r["source"]] = max(day.get(r["source"], 0), took)
    out = []
    for day in sorted(days):
        per = days[day]
        out.append({"day": day, "sources": dict(sorted(per.items())),
                    "one_after_another": sum(per.values()), "side_by_side": max(per.values())})
    return out


def cmd_window(a) -> int:
    from caro import runs as runs_mod
    url = (a.ops or os.environ.get(runs_mod.OPS_ENV, "")).strip()
    if not url:
        print(f"window: no runs' database: set {runs_mod.OPS_ENV} or --ops", file=sys.stderr)
        return 2
    try:
        db = runs_mod.open_runs(url, migrate=False)
        try:
            records = db.runs(limit=10_000)
        finally:
            db.close()
    except Exception as e:      # noqa: BLE001 -- say what, never the address
        print(f"window: the runs' database could not be read ({type(e).__name__})", file=sys.stderr)
        return 1
    days = window_days(records)
    limit = a.window_hours * 3600
    print(f"window   {len(days)} day(s) with a collected run; the window is {a.window_hours:g} h")
    for d in days:
        per = ", ".join(f"{s} {t / 60:.1f} min" for s, t in d["sources"].items())
        over = " OVER" if d["one_after_another"] > limit else ""
        print(f"  {d['day']}  {per}; one after another {d['one_after_another'] / 60:.1f} min, "
              f"side by side {d['side_by_side'] / 60:.1f} min{over}")
    multi = [d for d in days if len(d["sources"]) > 1]
    if not days:
        verdict = "not measured: no collected run has been recorded"
    elif not multi:
        verdict = "not met: no day has collected more than one source"
    elif any(d["side_by_side"] > limit for d in multi):
        verdict = "MET: a day's sources, side by side, did not finish in the window"
    else:
        verdict = "not met: every day's sources finished in the window"
    print(f"condition 1: {verdict}")
    return 0


# ---------------------------------------------------------------------------
# 2. duration_stats
# ---------------------------------------------------------------------------
def snapshots_under(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.json") if p.is_file())


def load_snapshot(path: Path):
    """A snapshot as write_snapshot wrote it, every outcome kept: a listing
    gone is an outcome `absent`, and it is what duration_stats counts. Keys
    this version of FetchOutcome does not have are dropped, so a snapshot
    from a later or an earlier one still reads."""
    from dataclasses import fields as dc_fields

    from caro.tracking import FetchOutcome, FetchStatus, Integrity, Snapshot
    raw = json.loads(path.read_text(encoding="utf-8"))
    known = {f.name for f in dc_fields(FetchOutcome)}
    outcomes = []
    for r in raw.get("outcomes") or []:
        if not isinstance(r, dict) or r.get("status") not in {s.value for s in FetchStatus}:
            continue
        kw = {k: v for k, v in r.items() if k in known}
        kw["status"] = FetchStatus(r["status"])
        if "image_phashes" in kw:
            kw["image_phashes"] = tuple(kw["image_phashes"] or ())
        outcomes.append(FetchOutcome(**kw))
    return Snapshot(snapshot_id=str(raw.get("snapshot_id") or path.stem),
                    taken_on=date.fromisoformat(raw["taken_on"]),
                    outcomes=outcomes,
                    integrity=Integrity(raw.get("integrity") or "ok"),
                    notes=list(raw.get("notes") or []))


def fold(paths: list[Path]):
    """The snapshots, oldest day first, folded into one tracking state."""
    from caro.tracking import TrackingState, apply_snapshot
    snaps = sorted((load_snapshot(p) for p in paths), key=lambda s: (s.taken_on, s.snapshot_id))
    state = TrackingState()
    for i, s in enumerate(snaps):
        apply_snapshot(state, s, is_first=(i == 0))
    return state, snaps


def cmd_durations(a) -> int:
    from caro.tracking import duration_stats
    root = Path(a.snapshots)
    paths = snapshots_under(root) if root.is_dir() else []
    if not paths:
        print(f"durations: no snapshot under {root}", file=sys.stderr)
        return 2
    t0 = time.perf_counter()
    state, snaps = fold(paths)
    as_of = snaps[-1].taken_on
    st = duration_stats(state, as_of)
    took = time.perf_counter() - t0
    size = sum(p.stat().st_size for p in paths)
    days = sorted({s.taken_on for s in snaps})
    print(f"durations {len(snaps)} snapshot(s) over {len(days)} day(s), {days[0]} to {days[-1]}; "
          f"{size / 1e6:.1f} MB, folded in {took:.2f} s")
    print(f"  usable {st.n_usable}: disappeared {st.n_disappeared}, still listed (censored) {st.n_censored}; "
          f"listed before tracking began (left out) {st.n_excluded_left_truncated}")
    print(f"  Kaplan-Meier median {st.km_median_days if st.km_median_days is not None else '-'} day(s)")
    for w in st.warnings:
        print(f"  warning: {w}")
    met = st.n_disappeared >= DISAPPEARANCES_D56
    print(f"condition 2: {'MET in count' if met else 'not met'}: {st.n_disappeared} of the "
          f"{DISAPPEARANCES_D56} observed disappearances D56 asks for"
          + ("; whether its cost is significant is the line above" if met else ""))
    return 0


# ---------------------------------------------------------------------------
# 3. The stages
# ---------------------------------------------------------------------------
def grown(artifact: dict, n: int) -> dict:
    """The served corpus grown to `n` listings: its own listings, copied
    under new ids until there are n. Every copy is a listing the gate and
    the parser have already read, so the stages do the work real ones ask."""
    base = artifact["listings"]
    listings = [{**base[i % len(base)], "listing_id": f"{base[i % len(base)]['listing_id']}~{i // len(base)}"}
                for i in range(n)]
    return {**artifact, "listings": listings}


def _texts(rec: dict) -> tuple[str, str]:
    """A title and a description of the kind sellers write, from a record."""
    title = " ".join(str(x) for x in (rec.get("make"), rec.get("model"), rec.get("trim")) if x)
    year = rec.get("year_jalali")
    km = rec.get("mileage_km")
    desc = (f"مدل {year} " if year else "") + (f"کارکرد {int(km):,} کیلومتر " if km else "") + \
        "بدنه سالم، فنی عالی، بیمه دارد"
    return title, desc


def _timed(fn, *args):
    t0 = time.perf_counter()
    out = fn(*args)
    return time.perf_counter() - t0, out


def stage_times(artifact: dict, n: int) -> dict[str, float]:
    from caro.corpus_reader import rows_from_corpus
    from caro.ingest.divar_car import extract_make_model, parse_listing
    from scripts.replicate_check import index

    from webapp.api import corpus as corpus_mod
    a = grown(artifact, n)
    recs = a["listings"]
    t = {}
    texts = [_texts(r) for r in recs]
    t["parser"], _ = _timed(lambda: [parse_listing(r["listing_id"], "", ti, de)
                                      for r, (ti, de) in zip(recs, texts)])
    t["canonicalisation"], _ = _timed(lambda: [extract_make_model(ti) for ti, _ in texts])
    t["serialisation"], blob = _timed(lambda: json.dumps(a, ensure_ascii=False))
    t["read back"], _ = _timed(json.loads, blob)
    t["index build"], (_, rows) = _timed(rows_from_corpus, a)
    other = {"outcomes": [{**r, "status": "ok"} for r in recs[: n - n // 20]]}
    snap = {"outcomes": [{**r, "status": "ok"} for r in recs]}
    def compare():
        x, y = index(snap), index(other)
        kx, ky = set(x), set(y)
        return kx & ky, kx - ky, ky - kx
    t["comparison"], _ = _timed(compare)
    pipe = corpus_mod.active().pipeline
    def search_all():
        from caro.ranking import retrieve
        return [retrieve(rows, pipe.parser.parse(q)) for q in QUESTIONS]
    took, _ = _timed(search_all)
    t["search (one)"] = took / len(QUESTIONS)
    return t


def slope(t_small: float, t_big: float, n_small: int, n_big: int) -> float | None:
    if t_small <= 0 or t_big <= 0:
        return None
    return math.log(t_big / t_small) / math.log(n_big / n_small)


def cmd_stages(a) -> int:
    from caro.corpus_reader import load_corpus
    from webapp.api import corpus as corpus_mod
    run = corpus_mod.active().identity.run_id
    artifact = load_corpus(run)
    sizes = tuple(int(x) for x in a.sizes.split(","))
    table = {n: stage_times(artifact, n) for n in sizes}
    names = list(table[sizes[0]])
    print(f"stages   {run} ({len(artifact['listings'])} listings) grown to " + ", ".join(f"{n:,}" for n in sizes))
    print("  " + "stage".ljust(18) + "".join(f"{n:>12,}" for n in sizes) + "   slope")
    for s in names:
        sl = slope(table[sizes[-2]][s], table[sizes[-1]][s], sizes[-2], sizes[-1]) if len(sizes) > 1 else None
        print("  " + s.ljust(18) + "".join(f"{table[n][s]:>11.3f}s" for n in sizes)
              + (f"   {sl:.2f}" if sl is not None else ""))
    big = table[sizes[-1]]
    worst = max(big, key=big.get)
    print(f"slowest at {sizes[-1]:,}: {worst}, {big[worst]:.2f} s")
    return 0


# ---------------------------------------------------------------------------
# The hot path
# ---------------------------------------------------------------------------
# What one search costs inside the server, stage by stage, each timed on
# its own over the eight questions, with no profiler in the way: a
# profiler's own cost lands on the small functions, and an async one hides
# the time it awaits. The whole is what the API itself counts for
# /api/search (webapp/api/metrics.py): from the outermost middleware in to
# the last byte of the answer out, the test client's own work left outside.

def _each(fn, rounds: int) -> float:
    """Seconds per call of fn(q), over `rounds` passes of the eight."""
    t0 = time.perf_counter()
    for _ in range(rounds):
        for q in QUESTIONS:
            fn(q)
    return (time.perf_counter() - t0) / (rounds * len(QUESTIONS))


def hot_path(rounds: int) -> list[tuple[str, float]]:
    os.environ.setdefault("CARO_INBOX", "off")
    from fastapi.encoders import jsonable_encoder
    from fastapi.testclient import TestClient

    from webapp.api import corpus as corpus_mod
    from webapp.api import main as api
    from webapp.api import metrics as metrics_mod
    client = TestClient(api.app)
    for q in QUESTIONS:                       # warm: the corpus loads once
        client.get("/api/search", params={"q": q})
    c = corpus_mod.active()
    specs = {q: c.pipeline.parser.parse(q) for q in QUESTIONS}
    answers = {q: api.search(q=q, k=6) for q in QUESTIONS}

    rows = [
        ("the intent parser", _each(lambda q: c.pipeline.parser.parse(q), rounds)),
        ("the evidence", _each(lambda q: api._evidence(c, specs[q], [], 6), rounds)),
        ("the endpoint, whole", _each(lambda q: api.search(q=q, k=6), rounds)),
        ("the answer encoded as JSON", _each(lambda q: json.dumps(jsonable_encoder(answers[q]),
                                                                  ensure_ascii=False), rounds)),
    ]
    reg = metrics_mod.REGISTRY
    _, s0, n0 = reg.seconds.get("/api/search", ([], 0.0, 0))
    _each(lambda q: client.get("/api/search", params={"q": q}), rounds)
    _, s1, n1 = reg.seconds.get("/api/search", ([], 0.0, 0))
    whole = (s1 - s0) / max(n1 - n0, 1)
    endpoint, encoded = rows[2][1], rows[3][1]
    rows.append(("the request, inside the server", whole))
    rows.append(("  of which routing, the middlewares and validation", max(whole - endpoint - encoded, 0.0)))
    return rows


def cmd_profile(a) -> int:
    rows = hot_path(a.rounds)
    whole = dict(rows)["the request, inside the server"] or 1.0
    print(f"profile  the eight questions, {a.rounds} times each, in this process, no profiler")
    for label, t in rows:
        print(f"  {label.ljust(52)} {t * 1000:7.3f} ms  {t / whole * 100:5.1f}%")
    stages = {k: v for k, v in rows if k in ("the intent parser", "the evidence", "the answer encoded as JSON",
                                             "  of which routing, the middlewares and validation")}
    print(f"slowest stage: {max(stages, key=stages.get).strip()}")
    return 0


def parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    w = sub.add_parser("window", help="1: the crawl's window, from the runs' records")
    w.add_argument("--ops", default="", help=f"the runs' database (default: $CARO_OPS_URL)")
    w.add_argument("--window-hours", type=float, default=6.0)
    d = sub.add_parser("durations", help="2: duration_stats over the snapshots")
    d.add_argument("--snapshots", default=str(ROOT / "data" / "snapshots"))
    s = sub.add_parser("stages", help="3: each stage on the corpus grown")
    s.add_argument("--sizes", default=",".join(str(n) for n in SIZES))
    p = sub.add_parser("profile", help="the search's hot path")
    p.add_argument("--rounds", type=int, default=50)
    return ap


def main(argv: list[str] | None = None) -> int:
    a = parser().parse_args(argv)
    return {"window": cmd_window, "durations": cmd_durations, "stages": cmd_stages,
            "profile": cmd_profile}[a.cmd](a)


if __name__ == "__main__":
    raise SystemExit(main())
