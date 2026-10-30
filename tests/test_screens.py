"""What a reader is shown: a listing that is not a car, the car page in each
state its two requests can leave it in, a year that stays apart from the name
it follows, search's matches kept apart from listings that could not be
checked, where the closed inbox sends a reader, and an odometer drawn only
with its grade.

Run: PYTHONPATH=. python3 tests/test_screens.py

The contract for detail and compare, chosen after both were measured: they
answer 200 with the listing and its class, and the SCREEN is obliged to say
what the listing is. `tests/test_api_contract.py` §11 checks the API half —
every non-vehicle reaches the screen with its class. This is the other half,
and the one that matters: whether the screen then draws it as a car.

HOW. The two components the pages draw with, `ListingFile` (detail) and
`EvidenceRows` (compare), are rendered with what the API really returns,
through `tests/render_view.cjs` — the web app's own TypeScript and react-dom,
no browser, nothing the app does not already depend on. The assertions are
about the markup a reader gets, not about which fields a component mentions:
a component can read `product_class` and draw a car anyway, which is the
failure this suite exists for.

THE CAR PAGE'S STATE (§3). The car page asks two things — the listing, then
a decision for it — and which screen a reader gets is decided from what the
two requests came to by one pure function, `detailScreen`. §3 hands it real
API answers, and failures shaped the way the page records them, and checks
what it decides; then it draws `CarDetailView` from the same inputs and checks
what a reader gets. Among the cases are the ones a deployment found: a
decision that fails after its listing arrived — no answer, something that is
not this API, or this API's own 404 — leaves the listing's file on the page,
and only the decision says it did not come.

WHAT IT CANNOT SEE. The wiring from `useEffect` to the component. The pages
fetch; these draw; this feeds the drawing half what the fetching half would
get. For the car page that half is now thin, but it is not empty: whether the
effect records what each request came to — `failure()` in CarDetail.tsx,
`json()` in lib/api.ts — and asks for a decision exactly when
`asksForDecision` says so. §1 draws every listing WITH a decision's refusal,
vehicle or not: a non-car file must not turn into a car file because
somebody asked for an estimate.

THE CONTROL. A vehicle, drawn the same way, must carry every one of the car
file's own claims. Without it the negative checks below could pass on a
page whose wording had merely changed. §3 keeps the same rule for the other
screens: a sentence it checks is absent is one it first finds where it
belongs.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import caro.corpus_reader as corpus_reader                         # noqa: E402
from caro.ingest.corpus import SCHEMA                              # noqa: E402

with contextlib.redirect_stdout(io.StringIO()):
    import webapp.api.corpus as corpus_mod                         # noqa: E402
    from webapp.api import main as api                             # noqa: E402
from webapp.api import schemas                                     # noqa: E402

FAILS: list[str] = []
_OUT = sys.stdout


def check(name, cond, detail=""):
    if cond:
        print(f"  ✓ {name}", file=_OUT)
    else:
        print(f"  ✗ {name}  {detail}", file=_OUT)
        FAILS.append(name)


RUN = corpus_mod.DEFAULT_RUN
WEB = ROOT / "webapp" / "web"

# What the car file says about the thing it shows. Every phrase must appear
# when a vehicle is drawn (the control), and none may appear when anything
# else is.
CAR_CLAIMS = ("پرونده‌ی خودرو", "برای این خودرو", "قیمت پیشنهادی")


@contextlib.contextmanager
def serving(directory: Path, run: str | None = None):
    """Point the reader at `directory` for the block, and put it back. With
    `run`, that run is served as the configured one; without, the default."""
    was, was_run = corpus_reader.CORPORA, os.environ.get(corpus_mod.RUN_ENV)
    corpus_reader.CORPORA = directory
    if run:
        os.environ[corpus_mod.RUN_ENV] = run
    else:
        os.environ.pop(corpus_mod.RUN_ENV, None)
    corpus_mod.active.cache_clear()
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            yield
    finally:
        corpus_reader.CORPORA = was
        if was_run is None:
            os.environ.pop(corpus_mod.RUN_ENV, None)
        else:
            os.environ[corpus_mod.RUN_ENV] = was_run
        corpus_mod.active.cache_clear()


def classless(n: int = 2) -> str:
    """An artifact whose rows carry no `product_class`, as the schema allows —
    the loader records them as `unknown`. Written to a temp directory, never
    under data/corpora/, for the reason test_api_contract gives."""
    return json.dumps({
        "schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
        "collected_on": "2026-09-09",
        "listings": [{"listing_id": f"b{i}", "asking_price_toman": 500_000_000,
                      "year_jalali": 1392, "mileage_km": 90_000,
                      "make": "peugeot", "model": "206", "trim": "TU5"}
                     for i in range(n)]}, ensure_ascii=False)


def node(req: dict) -> tuple[dict | None, str]:
    """One request to tests/render_view.cjs: draw, read constants, call."""
    try:
        p = subprocess.run(
            ["node", str(ROOT / "tests" / "render_view.cjs"), str(WEB)],
            input=json.dumps(req, ensure_ascii=False), capture_output=True,
            text=True, timeout=180)
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, str(e)[:160]
    if p.returncode != 0:
        # node ends a thrown error with its own version line; the line worth
        # printing is the error, not the footer.
        lines = p.stderr.strip().splitlines() or ["no output"]
        err = next((ln for ln in lines if re.match(r"\s*\w*Error:", ln)),
                   lines[-1])
        return None, err.strip()[:160]
    return json.loads(p.stdout), ""


def render(component: str, export: str, props: list) -> tuple[dict | None, str]:
    return node({"component": component, "export": export, "props": props,
                 "consts": {"module": "lib/format.ts",
                            "names": ["NOT_A_CAR_FA", "PRODUCT_CLASS_FA"]}})


def call(module: str, name: str, args: list) -> tuple[list | None, str]:
    """`name` from `module`, once per argument list; what each call returned."""
    out, why = node({"call": {"module": module, "name": name, "args": args}})
    return (out["calls"] if out is not None else None), why


def as_json(model) -> dict:
    return model.model_dump(mode="json")


# ---------------------------------------------------------------------------
print("0 — what there is to draw with, and to draw")
# ---------------------------------------------------------------------------
check("node, and the web app's own node_modules",
      shutil.which("node") is not None
      and (WEB / "node_modules" / "typescript").is_dir()
      and (WEB / "node_modules" / "react-dom").is_dir(),
      "run_all skips this suite when they are absent; reaching here without "
      "them means it was run by hand — `cd webapp/web && npm install`")

# Sections 0 to 3 draw a listing that is not a car beside one that is. The
# one real non-vehicle any published corpus holds is run11's assignment, so
# they read run11 by name, served as the configured run, whatever the default
# is. Every other section draws what the default serves.
ART = ROOT / "data" / "corpora" / f"{RUN}.json"
NV_RUN = "run11"
NV_ART = ROOT / "data" / "corpora" / f"{NV_RUN}.json"
CLS = {x["listing_id"]: x.get("product_class")
       for x in json.loads(NV_ART.read_text(encoding="utf-8"))["listings"]}
NVS = sorted(i for i, c in CLS.items() if c != "vehicle")
_served0 = json.loads(ART.read_text(encoding="utf-8"))["listings"]
print(f"    the default corpus ({RUN}) holds "
      f"{sum(x.get('product_class') != 'vehicle' for x in _served0)}"
      f" non-vehicle(s); sections 0 to 3 draw {NV_RUN}'s")
check(f"  {NV_RUN} holds {len(NVS)} non-vehicle(s)", len(NVS) > 0,
      "nothing to draw — said, not passed")

with serving(NV_ART.parent, NV_RUN):
    VEH = next(r.listing_id for r in corpus_mod.active().rows)
    refusal = api.compare(schemas.CompareRequest(ids=[VEH], q="خودرو"))
    files = [(i, CLS[i], api.listing(i)) for i in [VEH] + NVS]
    tables = [((i,), api.compare(schemas.CompareRequest(ids=[i], q="خودرو")))
              for i in NVS]
    tables += [((i, VEH), api.compare(schemas.CompareRequest(
                   ids=[i, VEH], q="خودرو"))) for i in NVS]

with tempfile.TemporaryDirectory() as d:
    (Path(d) / f"{RUN}.json").write_text(classless(), encoding="utf-8")
    with serving(Path(d)):
        files.append(("b0", "unknown", api.listing("b0")))
        tables.append((("b0",), api.compare(schemas.CompareRequest(
            ids=["b0"], q="۲۰۶"))))
WANT = {**CLS, "b0": "unknown"}
REFUSED = (refusal.fault.message if refusal.fault
           else "no estimator is gated on this corpus")


# ---------------------------------------------------------------------------
print("\n1 — the detail page: a listing file, never a car file")
# ---------------------------------------------------------------------------
drawn = [(i, c, d) for i, c, d in files if d.listing is not None]
check(f"every listing asked for came back to be drawn ({len(drawn)} of "
      f"{len(files)})", len(drawn) == len(files),
      "a withheld listing is §11's failure; nothing to draw here")
out, why = render("components/CarDetail.tsx", "ListingFile", [
    {"id": i, "listing": as_json(d.listing), "corpus": as_json(d.corpus),
     "scored": None, "refused": REFUSED} for i, c, d in drawn])
check("  ListingFile could be drawn", out is not None, why)
if out is not None:
    SAY, LABEL = out["consts"]["NOT_A_CAR_FA"], out["consts"]["PRODUCT_CLASS_FA"]
    for (i, c, _), html in zip(drawn, out["markup"]):
        if c == "vehicle":
            missing = [x for x in CAR_CLAIMS if x not in html]
            check(f"  control: {i}, a vehicle, is drawn as a car file",
                  not missing and SAY not in html,
                  f"missing {missing}" if missing else "it says it is not a car")
            continue
        claims = [x for x in CAR_CLAIMS if x in html]
        check(f"  {i} ({c}) is not drawn as a car file", not claims,
              f"it carries {claims}")
        check(f"    and says so, naming it «{LABEL.get(c, c)}»",
              SAY in html and LABEL.get(c, c) in html,
              "the page does not say what the listing is")


# ---------------------------------------------------------------------------
print("\n2 — compare: every row it was asked for, a non-car said to be one")
# ---------------------------------------------------------------------------
tout, why = render("components/CompareTable.tsx", "EvidenceRows", [
    {"evidence": [as_json(x) for x in r.evidence]} for _, r in tables])
check("EvidenceRows could be drawn", tout is not None, why)
if tout is not None:
    SAY = tout["consts"]["NOT_A_CAR_FA"]
    LABEL = tout["consts"]["PRODUCT_CLASS_FA"]
    for (ids, _), html in zip(tables, tout["markup"]):
        rows = dict(re.findall(r'<tr data-listing="([^"]+)">(.*?)</tr>',
                               html, re.S))
        for i in ids:
            row = rows.get(i)
            if WANT[i] == "vehicle":
                check(f"  {' + '.join(ids)}: {i} is drawn as a car",
                      row is not None and SAY not in row
                      and not any(v in row for v in LABEL.values()),
                      "no row" if row is None else "it is labelled")
            else:
                lab = LABEL.get(WANT[i], WANT[i])
                check(f"  {' + '.join(ids)}: {i} says it is «{lab}», not a car",
                      row is not None and SAY in row and lab in row,
                      "no row" if row is None else "drawn like a car")


# ---------------------------------------------------------------------------
print("\n3 — the car page: which screen each pair of answers gets")
# ---------------------------------------------------------------------------
# The car page asks for the listing, then — for a car — for a decision, and
# what a reader gets is decided from what the two requests came to. Each case
# below is such a pair: answers the API really gives, and failures shaped the
# way the page records a request that failed (`Outcome` in CarDetail.tsx).
GONE = "bama:not-in-any-corpus"
car = files[0][2]                            # VEH, first entry of §0's files
nv_id, nv_cls, nv = files[1]                 # a listing that is not a car
b0 = files[-1][2]                            # the classless fixture's row
with serving(NV_ART.parent, NV_RUN):
    missing = api.listing(GONE)
    none_of = api.compare(schemas.CompareRequest(ids=[GONE], q="خودرو"))
    # A configured run that is not on disk: nothing is read, so the page may
    # not even say the car is absent. `serving` puts the variable back.
    os.environ[corpus_mod.RUN_ENV] = "run_no_such_thing"
    corpus_mod.active.cache_clear()
    unread = api.listing(VEH)
check("  the API's own answers for the cases below: "
      f"{missing.fault.code if missing.fault else None}, "
      f"{none_of.fault.code if none_of.fault else None}, "
      f"{unread.fault.code if unread.fault else None}",
      missing.fault is not None and missing.fault.code == "LISTING_NOT_FOUND"
      and none_of.fault is not None
      and none_of.fault.code == "COMPARE_IDS_NOT_FOUND"
      and unread.listing is None and unread.fault is not None
      and unread.fault.code == "RUN_NOT_FOUND",
      "the fixtures are not what the cases below say they are")

PENDING = {"k": "pending"}


def ok(model) -> dict:
    return {"k": "ok", "body": as_json(model)}


def failed(status: int, fault=None) -> dict:
    """A request that failed, as the page records it: the status, the message
    it would show under «جزئیات فنی», and the fault when this API sent one."""
    f = as_json(fault) if fault is not None else None
    return {"k": "failed", "status": status,
            "message": f["message"] if f else str(status), "fault": f}


STATES = [
    # what happened; the listing's outcome, the decision's; screen, and the
    # decision it holds (a file) or the fault it shows (blocked)
    ("nothing has come back yet", PENDING, None, "loading", None),
    ("the listing got no answer", failed(0), None, "no_answer", None),
    ("the listing got a 500 that is not this API's", failed(500), None,
     "no_answer", None),
    ("the API says the listing is not in its corpus",
     failed(404, missing.fault), None, "blocked", "LISTING_NOT_FOUND"),
    ("the API read no corpus at all", ok(unread), None,
     "blocked", "RUN_NOT_FOUND"),
    (f"{VEH}, a car, before its decision is asked for", ok(car), None,
     "file", "deciding"),
    (f"{VEH}, its decision on the way", ok(car), PENDING, "file", "deciding"),
    (f"{VEH}, its decision refused", ok(car), ok(refusal), "file", "refused"),
    # A decision that failed after its listing arrived. The file stays; the
    # decision says it did not come — whatever the failure was.
    (f"{VEH}, its decision got no answer", ok(car), failed(0),
     "file", "unanswered"),
    (f"{VEH}, its decision got a 500 that is not this API's", ok(car),
     failed(500), "file", "unanswered"),
    (f"{VEH}, its decision got a 504", ok(car), failed(504),
     "file", "unanswered"),
    (f"{VEH}, its decision answered 404 with this API's own fault", ok(car),
     failed(404, none_of.fault), "file", "unanswered"),
    (f"{nv_id} ({nv_cls}), for which no decision is asked", ok(nv), None,
     "file", "not_asked"),
    ("b0 (unknown), for which no decision is asked", ok(b0), None,
     "file", "not_asked"),
]


def held(s: dict):
    if s.get("k") == "file":
        return (s.get("decision") or {}).get("k")
    if s.get("k") == "blocked":
        return (s.get("fault") or {}).get("code")
    return None


got, why = call("components/CarDetail.tsx", "detailScreen",
                [[lo, co] for _, lo, co, _, _ in STATES])
check("detailScreen could be called", got is not None, why)
if got is not None:
    for (what, _, _, k, h), s in zip(STATES, got):
        check(f"  {what} → {k}{' · ' + h if h else ''}",
              (s.get("k"), held(s)) == (k, h),
              f"got {s.get('k')} · {held(s)}")

ASKS = [("a car", car, True), (f"{nv_id} ({nv_cls})", nv, False),
        ("b0 (unknown)", b0, False), ("no corpus read", unread, False)]
asks, why = call("components/CarDetail.tsx", "asksForDecision",
                 [[as_json(r)] for _, r, _ in ASKS])
check("asksForDecision could be called", asks is not None, why)
if asks is not None:
    for (what, _, want), a in zip(ASKS, asks):
        check(f"  a decision is asked for {what}: {want}", a is want,
              f"got {a}")

# What a reader gets. The sentences are recognised the way CAR_CLAIMS
# recognises the car file, and each is first found where it belongs — the
# controls — so a reworded screen fails here instead of letting a check that
# it is absent pass.
KNOW_NOTHING = "هیچ چیزی نمی‌دانیم"
NOT_IN_CORPUS = "این آگهی در پیکره‌ی جاری نیست"
DECIDING = "در حال محاسبه‌ی تصمیم"
NO_DECISION = "تصمیمی به این صفحه نرسید"


def car_file(html: str) -> bool:
    """The listing's own file: its heading, its id, its asking price."""
    return CAR_CLAIMS[0] in html and VEH in html and CAR_CLAIMS[2] in html


DRAWN = [("no answer", failed(0), None),
         ("not in corpus", failed(404, missing.fault), None),
         ("deciding", ok(car), PENDING),
         ("refused", ok(car), ok(refusal)),
         ("no answer to the decision", ok(car), failed(0)),
         ("a 500 to the decision", ok(car), failed(500)),
         ("a 504 to the decision", ok(car), failed(504)),
         ("this API's 404 to the decision", ok(car),
          failed(404, none_of.fault))]
dout, why = render("components/CarDetail.tsx", "CarDetailView", [
    {"id": VEH, "listingOutcome": lo, "compareOutcome": co}
    for _, lo, co in DRAWN])
check("CarDetailView could be drawn", dout is not None, why)
if dout is not None:
    page = dict(zip((n for n, _, _ in DRAWN), dout["markup"]))
    check(f"  control: a listing that got no answer says «{KNOW_NOTHING}»",
          KNOW_NOTHING in page["no answer"] and not car_file(page["no answer"]),
          "the sentence the checks below look for is not where it belongs")
    check(f"  control: a listing the corpus does not hold says "
          f"«{NOT_IN_CORPUS}»", NOT_IN_CORPUS in page["not in corpus"],
          "the sentence the checks below look for is not where it belongs")
    check(f"  {VEH}, its decision on the way: its file, and «{DECIDING}…»",
          car_file(page["deciding"]) and DECIDING in page["deciding"])
    check(f"  {VEH}, its decision refused: its file, with every claim",
          all(x in page["refused"] for x in CAR_CLAIMS)
          and VEH in page["refused"])
    for n in ("no answer to the decision", "a 500 to the decision",
              "a 504 to the decision", "this API's 404 to the decision"):
        html = page[n]
        check(f"  {VEH}, {n}: its file is still drawn", car_file(html),
              "the listing that arrived is not on the page")
        said = [x for x in (KNOW_NOTHING, NOT_IN_CORPUS) if x in html]
        check(f"    and only the decision says it did not come",
              NO_DECISION in html and not said,
              f"it says «{'», «'.join(said)}»" if said
              else "the decision's panel does not say so")


# ---------------------------------------------------------------------------
print("\n4 — the year beside a car's name is a unit of its own")
# ---------------------------------------------------------------------------
# A name that ends in a trim code or a number — «۱۳۱ SE», «manualr ۲۰۲۲» — is
# a left-to-right run, and a year drawn after it in a plain span joined that
# run: on the name's wrong side with no gap, «SE۱۳۹۶», or read as one number
# with it, «۲۰۲۲۱۴۰۱». Measured in a browser on run11's car pages, 69 of 75
# headings did that. How a browser lays a line out is not visible from here;
# the cause is. So the check is that the year is drawn isolated, in a <bdi>,
# on each surface this suite can draw that puts a year after a name: the car
# file for every vehicle in run11, and the card a gated corpus serves.
# Compare's scored header does the same, but is drawn only inside the page's
# effect, and is not checked here.
_FA = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def isolated_year(html: str, tag: str, year) -> bool:
    m = re.search(rf"<{tag}[^>]*>(.*?)</{tag}>", html, re.S)
    y = str(year).translate(_FA)
    return bool(m and re.search(rf"<bdi[^>]*>\s*{y}\s*</bdi>", m.group(1)))


_CLS4 = {x["listing_id"]: x.get("product_class")
         for x in json.loads(ART.read_text(encoding="utf-8"))["listings"]}
with serving(ART.parent):
    _cars = [(x.listing_id, api.listing(x.listing_id))
             for x in corpus_mod.active().listings
             if _CLS4.get(x.listing_id) == "vehicle"]
_cout, why = render("components/CarDetail.tsx", "ListingFile", [
    {"id": i, "listing": as_json(d.listing), "corpus": as_json(d.corpus),
     "scored": None, "refused": REFUSED} for i, d in _cars])
check(f"every vehicle in {RUN} drawn as its car file ({len(_cars)})",
      _cout is not None and len(_cars) > 0, why or "no vehicles to draw")
if _cout is not None:
    _run = [i for (i, d), html in zip(_cars, _cout["markup"])
            if not isolated_year(html, "h1", d.listing.year_jalali)]
    check(f"  the year beside the name is isolated in all "
          f"{len(_cars) - len(_run)} of {len(_cars)}", not _run,
          f"a plain span in {len(_run)}, e.g. {_run[:3]}")

with tempfile.TemporaryDirectory() as d:
    with serving(Path(d)):
        _found = api.search(q="پراید", k=8)
_items = list(_found.items)
_kout, why = render("components/ListingCard.tsx", "default",
                    [{"item": as_json(x)} for x in _items])
check(f"the cards a gated corpus serves could be drawn ({len(_items)})",
      _kout is not None and len(_items) > 0, why or "no cards to draw")
if _kout is not None:
    _run = [x.id for x, html in zip(_items, _kout["markup"])
            if not isolated_year(html, "h3", x.year_jalali)]
    check(f"  the year beside the name is isolated on all "
          f"{len(_items) - len(_run)} of {len(_items)}", not _run,
          f"a plain span on {len(_run)}")


# ---------------------------------------------------------------------------
print("\n5 — search: a match is drawn as one only where it was checked")
# ---------------------------------------------------------------------------
# The API now sends the evidence in two lists: listings every stated
# constraint was checked against and met, and listings that broke none but
# could not be checked against some (`webapp/api/constraints.py`). The
# second kind is not a match, and the reader must not be told it is one. So
# `SearchEvidence` is drawn with what search really returns for every example
# chip on the default corpus, at the k=8 the results page asks for; for
# queries that match nothing — with listings apart, and without; and for one
# whose listings apart are more than a table holds. The checks read the
# markup: which table each row is in, and what it says is missing.
#
# The case with nothing matched and nothing apart was reached by
# «تیبا زیر ۱۰ میلیون» while no Tiba lacked a price. run13 has one, held apart
# on the budget, and the case went unreached (2026-10-06). «پژو ۲۰۶» names a
# model no published corpus holds, so it reaches the case whatever lacks a
# price.
#
# A province is the first constraint a whole corpus can lack for most of its
# cars (D82). The served corpus holds one for every car, so none of its answers
# has a car apart on it: «پراید در تهران» there is 18 matches and nothing else,
# and draws the province's control — a match never says it went unchecked. The
# first published corpus whose answer to it has both a match and a car apart is
# drawn beside them (run13: 3 matches, 31 apart, each saying «استان ثبت‌نشده»).
_BOX5 = (WEB / "components" / "SearchBox.tsx").read_text(encoding="utf-8")
_m5 = re.search(r"const EXAMPLES = \[(.*?)\];", _BOX5, re.S)
_Q5 = (re.findall(r"'([^']+)'", _m5.group(1)) if _m5 else []) \
    + ["پراید زیر ۱۰ میلیون", "تیبا زیر ۱۰ میلیون", "پراید سند آزاد",
       "پژو ۲۰۶", "پراید در تهران"]
with serving(ART.parent):
    _found5 = [(q, api.search(q=q, k=8)) for q in _Q5]
_held5, _run5 = [], None
for _p5 in sorted(ART.parent.glob("*.json")):
    with serving(ART.parent, _p5.stem):
        _try5 = api.search(q="پراید در تهران", k=8)
        if _try5.evidence_total and _try5.evidence_unchecked_total:
            _run5 = _p5.stem
            _held5 = [(f"{q} · {_run5}", api.search(q=q, k=8))
                      for q in ("پراید در تهران", "در تهران")]
            break

_eout, why = node({"component": "components/SearchEvidence.tsx",
                   "export": "SearchEvidence",
                   "props": [{"data": as_json(r)} for _, r in _found5 + _held5],
                   "consts": {"module": "components/SearchEvidence.tsx",
                              "names": ["MATCHED_FA", "APART_FA", "NONE_FA"]}})
_fout, why2 = node({"consts": {"module": "lib/format.ts",
                               "names": ["UNCHECKED_FA", "ODOMETER_FA"]}})
_from5 = _run5 or "no corpus that holds a car apart on the province"
check(f"SearchEvidence could be drawn for {len(_found5 + _held5)} answers "
      f"({len(_held5)} from {_from5})",
      _eout is not None and _fout is not None, why or why2)


def _sections(html: str) -> dict[str, str]:
    return dict(re.findall(
        r'<section[^>]*data-evidence="(\w+)"[^>]*>(.*?)</section>', html, re.S))


def _rows(html: str) -> dict[str, str]:
    return dict(re.findall(r'<tr data-listing="([^"]+)">(.*?)</tr>', html,
                           re.S))


def _text(html: str) -> str:
    """What a reader reads: no tags, no React's text-node comments."""
    t = re.sub(r"<!--.*?-->", "", html, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", t))


_reach5 = {"matched beyond k": False, "apart": False,
           "apart beyond k": False, "none+apart": False, "none": False,
           "apart on the province": False}
if _eout is not None and _fout is not None:
    MATCHED, APART, NONE = (_eout["consts"][n]
                            for n in ("MATCHED_FA", "APART_FA", "NONE_FA"))
    PHRASE = _fout["consts"]["UNCHECKED_FA"]
    ODO = _fout["consts"]["ODOMETER_FA"]

    def _stated5(intent) -> list[str]:
        """The constraints a query stated, by the keys UNCHECKED_FA names:
        the reading `webapp/api/constraints.judge` makes of an intent,
        written again here so that the two are compared."""
        keys = []
        if (intent.budget_max_toman is not None
                or intent.budget_min_toman is not None):
            keys.append("budget")
        if intent.year_min is not None:
            keys.append("year")
        if intent.max_mileage_km is not None:
            keys.append("mileage")
        if intent.provinces:
            keys.append("province")
        return keys + [k for k in intent.deal_breakers if k in PHRASE]

    def _why5(item, key: str) -> str:
        """What a row apart must say for `key`. On the odometer, the grade
        the reading carries (D67): a number that is there and not believed is
        «کارکرد مشکوک», not unrecorded. run11 held no row apart on such a
        number, so this section said one phrase for every reason until run13
        held one apart, a 4,200 km 1401 Quik."""
        if key == "mileage" and item.mileage_status in ODO:
            return ODO[item.mileage_status]
        return PHRASE[key]

    for (q, r), html in zip(_found5 + _held5, _eout["markup"]):
        sec = _sections(html)
        got_m = _rows(sec.get("matched", ""))
        got_a = _rows(sec.get("apart", ""))
        want_m = [x.id for x in r.evidence]
        want_a = {x.id: x.unchecked for x in r.evidence_unchecked}
        check(f"  «{q[:30]}» — {len(want_m)} drawn as matches, "
              f"{len(want_a)} apart, each in its own table",
              list(got_m) == want_m and set(got_a) == set(want_a)
              and not set(got_m) & set(want_a),
              f"matches drawn {list(got_m)} · apart drawn {list(got_a)}")
        _items = {x.id: x for x in r.evidence_unchecked}
        _named = [i for i, keys in want_a.items()
                  if not all(_why5(_items[i], k) in got_a.get(i, "")
                             for k in keys)]
        check("    each row apart says what is missing",
              not _named, f"not said for {_named}")
        # Held to what the query stated. A car with no odometer reading may
        # match a query that asks nothing of the odometer — a match is checked
        # against the constraints stated and no others (D65) — and its row
        # then says «کارکرد ثبت‌نشده», as every surface says it of a car with
        # no reading (D67). That is UNCHECKED_FA's phrase for the mileage
        # too, so forbidding every phrase in every match failed on the first
        # served corpus with such a car among the matches: run16's
        # bama:0o9rpjba, a 1405 Pride, under «پراید» (2026-10-15). What a
        # match may never say is that a constraint the buyer stated went
        # unchecked.
        _quiet = [i for i, row in got_m.items()
                  if any(PHRASE[k] in row for k in _stated5(r.intent))]
        check("    and no match carries such a phrase for a constraint "
              "stated (the control)", not _quiet, f"on {_quiet}")
        check("    the heading that says «منطبق» is over matches alone",
              (MATCHED in sec.get("matched", "")) == (r.evidence_total > 0)
              and MATCHED not in sec.get("apart", "")
              and (APART in sec.get("apart", "")) == bool(want_a),
              f"sections drawn: {sorted(sec)}")
        check(f"    «{NONE}» exactly when nothing matched "
              f"({r.evidence_total})",
              (NONE in html) == (r.evidence_total == 0)
              and ("none" in sec) == (r.evidence_total == 0))
        for kind, shown, total in (
                ("matched", len(r.evidence), r.evidence_total),
                ("apart", len(r.evidence_unchecked),
                 r.evidence_unchecked_total)):
            if total > shown:
                _of = (f"{shown} از {total}").translate(_FA)
                check(f"    {kind}: says it shows {shown} of {total}",
                      _of in _text(sec.get(kind, "")),
                      "a table of the first k reads as all of them")
                _reach5[f"{kind} beyond k"] = True
        if want_a:
            _reach5["apart"] = True
        if any("province" in keys for keys in want_a.values()):
            _reach5["apart on the province"] = True
        if r.evidence_total == 0:
            _reach5["none+apart" if want_a else "none"] = True

for _case, _hit in _reach5.items():
    check(f"  the answers reach the case «{_case}»", _hit,
          "nothing drawn for it — said, not passed")


# ---------------------------------------------------------------------------
print("\n6 — the closed inbox: where to go, and what it takes")
# ---------------------------------------------------------------------------
# With CARO_INBOX=off the contact page draws no form, only the place to write
# instead — GitHub Issues, from `contact.ELSEWHERE` by way of
# /api/contact/status. Drawn with that constant: the link must be it, and the
# page must say that writing there needs a GitHub account and reading does
# not, before anyone arrives at a sign-in page.
from webapp.api import contact as _contact                        # noqa: E402

_iout, why = node({"component": "components/ContactForm.tsx",
                   "export": "InboxClosed",
                   "props": [{"elsewhere": _contact.ELSEWHERE}],
                   "consts": {"module": "components/ContactForm.tsx",
                              "names": ["ACCOUNT_FA"]}})
check("InboxClosed could be drawn", _iout is not None, why)
if _iout is not None:
    _ihtml = _iout["markup"][0]
    check(f"  its one link is {_contact.ELSEWHERE}",
          re.findall(r'href="([^"]+)"', _ihtml) == [_contact.ELSEWHERE],
          str(re.findall(r'href="([^"]+)"', _ihtml)))
    check("  and it says what writing there takes",
          bool(_iout["consts"]["ACCOUNT_FA"])
          and _iout["consts"]["ACCOUNT_FA"] in _text(_ihtml),
          "the sentence is not on the page")



# ---------------------------------------------------------------------------
print("\n7 — an odometer is drawn with its grade, on every surface")
# ---------------------------------------------------------------------------
# The API sends `mileage_status` beside `mileage_km`, and the constraint lets
# only a plausible reading decide (test_api_contract §13, §15). This is the
# page's half: search's two tables, the car file and compare's evidence rows,
# each drawn with what the API returns for the same eight cases contract §15
# sends — from a temporary artifact, because run11 holds no suspicious or
# impossible reading. A number is drawn only where it is plausible; every
# other grade is said in its place, in one of the phrases that keep D22's
# three cases apart.
_ODO7 = [   # id, odometer, grade (None: the record states none), year
    ("o_ok", 100_000, "plausible", 1398), ("o_hi", 200_000, "plausible", 1398),
    ("o_none", None, "unknown", 1398), ("o_low", 1, "suspicious", 1385),
    ("o_ph", 999_990, "suspicious", 1398), ("o_neg", -5_000, "impossible", 1398),
    ("o_huge", 2_000_000, "impossible", 1398), ("o_bare", 90_000, None, 1398),
]
_rows7 = []
for _i, _km, _ms, _y in _ODO7:
    _r = {"listing_id": _i, "product_class": "vehicle",
          "asking_price_toman": 500_000_000, "price_kind": "cash",
          "price_status": "display_confirmed", "year_jalali": _y,
          "make": "peugeot", "model": "206", "trim": "TU5"}
    if _km is not None:
        _r["mileage_km"] = _km
    if _ms is not None:
        _r["mileage_status"] = _ms
    _rows7.append(_r)

with tempfile.TemporaryDirectory() as d:
    (Path(d) / f"{RUN}.json").write_text(json.dumps(
        {"schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
         "collected_on": "2026-10-05", "listings": _rows7},
        ensure_ascii=False), encoding="utf-8")
    with serving(Path(d)):
        _search7 = api.search(q="۲۰۶ کم‌کارکرد", k=24)
        _detail7 = [(i, api.listing(i)) for i, *_ in _ODO7]
        _cmp7 = api.compare(schemas.CompareRequest(
            ids=[i for i, *_ in _ODO7], q="۲۰۶"))

_c7, why = node({"consts": {"module": "lib/format.ts",
                            "names": ["ODOMETER_FA", "ODOMETER_UNGRADED_FA"]}})
check("the phrases could be read", _c7 is not None, why)
if _c7 is not None:
    _FA7 = _c7["consts"]["ODOMETER_FA"]
    _phr = {"unknown": _FA7["unknown"], "suspicious": _FA7["suspicious"],
            "impossible": _FA7["impossible"],
            None: _c7["consts"]["ODOMETER_UNGRADED_FA"]}
    check("  three grades, three different phrases, and a fourth for none",
          len(set(_phr.values())) == 4, str(_phr))

    def _expect7(km, ms):
        """Exactly what goes where the odometer is drawn: the number where
        the grade is plausible, the grade's phrase everywhere else."""
        if ms == "plausible":
            return (f"{km:,}".replace(",", "٬").translate(_FA) + " کیلومتر")
        return _phr[ms]

    def _cells(row_html):
        return [_text(c).strip()
                for c in re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.S)]

    _sout, why = node({"component": "components/SearchEvidence.tsx",
                       "export": "SearchEvidence",
                       "props": [{"data": as_json(_search7)}]})
    _fout, why2 = render("components/CarDetail.tsx", "ListingFile", [
        {"id": i, "listing": as_json(r.listing), "corpus": as_json(r.corpus),
         "scored": None, "refused": REFUSED} for i, r in _detail7])
    _eout, why3 = render("components/CompareTable.tsx", "EvidenceRows",
                         [{"evidence": [as_json(x) for x in _cmp7.evidence]}])
    check("search, the car file and compare could be drawn",
          None not in (_sout, _fout, _eout), why or why2 or why3)
    if None not in (_sout, _fout, _eout):
        _srows = _rows(_sout["markup"][0])
        _erows = _rows(_eout["markup"][0])
        for (_i, _km, _ms, _y), _fhtml in zip(_ODO7, _fout["markup"]):
            _want = _expect7(_km, _ms)
            _seen, _bad = [], []
            if _i in _srows:
                # A match: name, year, odometer, price, then what follows.
                # Held apart: name, why, year, odometer, price, then what
                # follows — and the why is the odometer's own grade, since
                # the cap is all it was asked. Which kind a row is comes from
                # the payload. It came from counting the row's cells, which
                # holds only while no cell is added after the price.
                _c = _cells(_srows[_i])
                _held = _i in {x.id for x in _search7.evidence_unchecked}
                _odo = _c[3] if _held else _c[2]
                _why = _c[1] if _held else None
                _seen.append("search")
                if _odo != _want or (_why is not None and _why != _want):
                    _bad.append(f"search: {_odo!r} / why {_why!r}")
            _dd = re.search(r"<dt[^>]*>کارکرد</dt><dd[^>]*>(.*?)</dd>", _fhtml,
                            re.S)
            _seen.append("car file")
            if (not _dd or _text(_dd.group(1)).strip() != _want
                    or (_ms != "plausible" and "کیلومتر" in _text(_fhtml))):
                _bad.append(f"car file: "
                            f"{_text(_dd.group(1)).strip() if _dd else None!r}")
            if _i in _erows:
                _odo = _cells(_erows[_i])[2]
                _seen.append("compare")
                if _odo != _want:
                    _bad.append(f"compare: {_odo!r}")
            check(f"  {_i} ({_ms or 'no grade'}, {_km}) → «{_want}» on "
                  f"{' · '.join(_seen)}", not _bad, "; ".join(_bad))
        _apart = {x.id for x in _search7.evidence_unchecked}
        check("  search holds every grade but plausible apart, and draws the "
              "plausible one under the cap as its match",
              _apart == {"o_none", "o_low", "o_ph", "o_neg", "o_huge", "o_bare"}
              and [x.id for x in _search7.evidence] == ["o_ok"],
              f"apart {sorted(_apart)} · matched {[x.id for x in _search7.evidence]}")


# ---------------------------------------------------------------------------
print("\n8 — the car page says a price the way search and compare do")
# ---------------------------------------------------------------------------
# FIELD_PROVENANCE.md's rule for a price — `price_kind` cash and a
# `price_status` that is not unusable, or the figure is not an asking price —
# is `askingPrice()` in lib/format.ts. Search and compare drew with it; the
# car page drew `toman()`, so on run11 its heading and its «قیمت پیشنهادی»
# cell said «ثبت‌نشده» for the two listings search and compare call
# «توافقی». Drawn here: six listings, one for each kind of price, served from
# a temporary artifact the way the API sends them; an appraisal row, which
# carries neither field; and run11's own «توافقی» listings beside a cash one.
# Both places must say exactly the expected thing, and an amount that is not
# an asking price must be nowhere on the page.
_P8 = [   # id, kind, status, amount, what both places say
    ("p_cash", "cash", "display_confirmed", 500_000_000, "amount"),
    ("p_so", "cash", "structured_only", 450_000_000, "amount"),
    ("p_neg", "negotiable", "absent", None, ("kind", "negotiable")),
    ("p_fin", "financing_total", "display_confirmed", 900_000_000,
     ("kind", "financing_total")),
    ("p_amb", "cash", "ambiguous", 500_000_000, ("status", "ambiguous")),
    ("p_abs", "absent", "absent", None, ("kind", "absent")),
]
_rows8 = []
for _i, _k, _s, _a, _ in _P8:
    _r = {"listing_id": _i, "product_class": "vehicle", "price_kind": _k,
          "price_status": _s, "year_jalali": 1398, "mileage_km": 90_000,
          "mileage_status": "plausible", "make": "peugeot", "model": "206",
          "trim": "TU5"}
    if _a is not None:
        _r["asking_price_toman"] = _a
    _rows8.append(_r)

with tempfile.TemporaryDirectory() as d:
    (Path(d) / f"{RUN}.json").write_text(json.dumps(
        {"schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
         "collected_on": "2026-10-06", "listings": _rows8},
        ensure_ascii=False), encoding="utf-8")
    with serving(Path(d)):
        _built8 = [(i, api.listing(i)) for i, *_ in _P8]

_L11 = json.loads(ART.read_text(encoding="utf-8"))["listings"]
_neg11 = sorted(x["listing_id"] for x in _L11
                if x.get("product_class") == "vehicle"
                and x.get("price_kind") == "negotiable")
_cash11 = next(x for x in _L11 if x.get("product_class") == "vehicle"
               and x.get("price_kind") == "cash"
               and x.get("price_status") == "display_confirmed"
               and x.get("asking_price_toman"))
with serving(ART.parent):
    _run8 = [(i, api.listing(i)) for i in _neg11 + [_cash11["listing_id"]]]

check("the API sends each built listing's price fields as the artifact "
      "holds them",
      all(r.listing is not None
          and (r.listing.price_kind, r.listing.price_status,
               r.listing.asking_price_toman) == (k, s, a)
          for (_, r), (_i, k, s, a, _w) in zip(_built8, _P8)),
      str([(r.listing.price_kind, r.listing.price_status,
            r.listing.asking_price_toman) if r.listing else None
           for _, r in _built8]))
check(f"{RUN} holds «توافقی» listings to draw, and a cash one",
      len(_neg11) > 0, "nothing to draw — said, not passed")

_row8 = {"id": "p_row", "url": "", "model_key": "peugeot 206 TU5",
         "make": "peugeot", "model": "206", "trim": "TU5",
         "year_jalali": 1398, "mileage_km": 90_000,
         "asking_price_toman": 500_000_000, "product_class": "vehicle",
         "price_status": None, "price_kind": None, "mileage_status": None}
_props8 = ([{"id": i, "listing": as_json(r.listing), "corpus": as_json(r.corpus),
             "scored": None, "refused": REFUSED} for i, r in _built8]
           + [{"id": "p_row", "listing": _row8,
               "corpus": as_json(_built8[0][1].corpus), "scored": None,
               "refused": REFUSED}]
           + [{"id": i, "listing": as_json(r.listing),
               "corpus": as_json(r.corpus), "scored": None,
               "refused": REFUSED} for i, r in _run8])
_out8, why = node({"component": "components/CarDetail.tsx",
                   "export": "ListingFile", "props": _props8,
                   "consts": {"module": "lib/format.ts",
                              "names": ["PRICE_KIND_FA", "PRICE_STATUS_FA"]}})
check("the car file could be drawn for each", _out8 is not None, why)
if _out8 is not None:
    _KIND8 = _out8["consts"]["PRICE_KIND_FA"]
    _STAT8 = _out8["consts"]["PRICE_STATUS_FA"]

    def _toman8(a):
        return f"{a:,}".replace(",", "٬").translate(_FA) + " تومان"

    _cases8 = ([(i, a, w) for i, _k, _s, a, w in _P8]
               + [("p_row", 500_000_000, "amount")]
               + [(i, None, ("kind", "negotiable")) for i in _neg11]
               + [(_cash11["listing_id"], _cash11["asking_price_toman"],
                   "amount")])
    for (_i, _a, _w), _html in zip(_cases8, _out8["markup"]):
        _want = (_toman8(_a) if _w == "amount"
                 else (_KIND8 if _w[0] == "kind" else _STAT8)[_w[1]])
        _head = re.search(r'class="mt-2 mb-0[^"]*"><span class="fig">(.*?)'
                          r'</span>', _html, re.S)
        _cell = re.search(r"<dt[^>]*>قیمت پیشنهادی</dt><dd[^>]*>(.*?)</dd>",
                          _html, re.S)
        _got = [_text(m.group(1)).strip() if m else None
                for m in (_head, _cell)]
        _shown = (_a is not None and _w != "amount"
                  and _toman8(_a).split(" ")[0] in _text(_html))
        check(f"  {_i} → «{_want}» in the heading and under «قیمت پیشنهادی»"
              + ("" if _w == "amount" or _a is None
                 else ", its amount nowhere"),
              _got == [_want, _want] and not _shown,
              f"heading {_got[0]!r} · cell {_got[1]!r}"
              + (" · the amount is on the page" if _shown else ""))


# ---------------------------------------------------------------------------
print("\n9 — the car page says the province, and how it was read")
# ---------------------------------------------------------------------------
# A province read from a city's name — «تهران، آذری» names Tehran the city —
# is CARO's inference, and drawn alone it would read as the listing's own
# statement. So the cell is read out of every car file section 4 drew, and
# held to what the payload says: the province alone where it was stated, the
# province and «از روی نام شهر» where the city gave it, «ثبت‌نشده» where
# there is none. The expected text is written here again rather than taken
# from the renderer, so the two are compared, not one with itself.
_out9, why9 = node({"consts": {"module": "lib/format.ts",
                               "names": ["PROVINCE_FROM_CITY_FA",
                                         "PROVINCE_SOURCE_UNRECORDED_FA"]}})
check("the province's phrases could be read from lib/format.ts",
      _out9 is not None, why9)
if _out9 is not None and _cout is not None:
    _CITY9 = _out9["consts"]["PROVINCE_FROM_CITY_FA"]
    _UNREC9 = _out9["consts"]["PROVINCE_SOURCE_UNRECORDED_FA"]

    def _prov9(p, src):
        if not p:
            return "ثبت‌نشده"
        if src == "stated":
            return p
        return f"{p} — {_CITY9 if src == 'city' else _UNREC9}"

    _off9 = []
    for (i, d), html in zip(_cars, _cout["markup"]):
        m = re.search(r"<dt[^>]*>استان</dt><dd[^>]*>(.*?)</dd>", html, re.S)
        got = _text(m.group(1)).strip() if m else None
        want = _prov9(d.listing.province, d.listing.province_source)
        if got != want:
            _off9.append((i, got, want))
    check(f"  every car file in {RUN} says it as the payload has it "
          f"({len(_cars) - len(_off9)} of {len(_cars)})",
          not _off9, f"e.g. {_off9[:2]}")
    _kinds9 = {k: sum(1 for _, d in _cars
                      if (d.listing.province_source if d.listing.province
                          else "none") == k)
               for k in ("stated", "city", "none")}
    for _k, _label in (("stated", "a province the listing states"),
                       ("city", "a province read from a city's name")):
        check(f"  the files reach {_label} ({_kinds9[_k]})", _kinds9[_k] > 0,
              "none drawn — said, not passed")

    # A listing with no province. run14 held one, the province spelled as the
    # source spells it, and the files above reached it; a corpus read by the
    # rule of f82efec may hold none — run16 has a province on every row. So
    # the case is drawn from a temporary artifact, as section 7 draws the
    # odometer's grades no real corpus holds: a vehicle of the served corpus
    # with its province taken off, as promotion writes such a row — no
    # `province`, and `province_source` `none`. Counted in `_kinds9` it
    # would only say what the corpus holds; drawn, it says what the page does.
    _row9 = next(dict(x) for x in json.loads(
        ART.read_text(encoding="utf-8"))["listings"]
        if x.get("product_class") == "vehicle")
    _row9.pop("province", None)
    _row9["province_source"] = "none"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / f"{RUN}.json").write_text(json.dumps(
            {"schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
             "collected_on": "2026-10-15", "listings": [_row9]},
            ensure_ascii=False), encoding="utf-8")
        with serving(Path(d)):
            _d9 = api.listing(_row9["listing_id"])
    _nout9, why = render("components/CarDetail.tsx", "ListingFile", [
        {"id": _row9["listing_id"], "listing": as_json(_d9.listing),
         "corpus": as_json(_d9.corpus), "scored": None, "refused": REFUSED}])
    _m9 = (re.search(r"<dt[^>]*>استان</dt><dd[^>]*>(.*?)</dd>",
                     _nout9["markup"][0], re.S) if _nout9 else None)
    _got9 = _text(_m9.group(1)).strip() if _m9 else None
    check(f"  and a listing with no province, drawn from a temporary "
          f"artifact, says «{_prov9(None, 'none')}» (got «{_got9}»)",
          _d9.listing is not None and _d9.listing.province is None
          and _got9 == _prov9(None, "none"), why or "")


# ---------------------------------------------------------------------------
print("\n10 — the lists say the province, and how it was read")
# ---------------------------------------------------------------------------
# Search's two tables and compare's evidence rows draw the province in a
# cell of its own (D81), in the car page's words, read here with the same
# expectation as section 9. Search is drawn with what it really answers on
# the served corpus for section 5's queries; compare with three listings of
# the served corpus, one stated, one read from a city's name, and one with
# its province taken off — served from a temporary artifact, as section 9
# draws it, since a corpus read by the rule of f82efec may hold none.
def _pcell(row_html: str) -> str | None:
    m = re.search(r'<td[^>]*data-cell="province"[^>]*>(.*?)</td>', row_html,
                  re.S)
    return _text(m.group(1)).strip() if m else None


if _out9 is not None and _cout is not None:
    _sout10, why = node({"component": "components/SearchEvidence.tsx",
                         "export": "SearchEvidence",
                         "props": [{"data": as_json(r)} for _, r in _found5]})
    _seen10, _off10, _kinds10 = 0, [], {"stated": 0, "city": 0}
    if _sout10 is not None:
        for (_q, _r), html in zip(_found5, _sout10["markup"]):
            _items = {x.id: x for x in list(_r.evidence)
                      + list(_r.evidence_unchecked)}
            for _sec in ("matched", "apart"):
                for _i, _row in _rows(_sections(html).get(_sec, "")).items():
                    _x = _items[_i]
                    _want = _prov9(_x.province, _x.province_source)
                    _seen10 += 1
                    if _pcell(_row) != _want:
                        _off10.append((_q[:20], _i, _pcell(_row), _want))
                    if _x.province and _x.province_source in _kinds10:
                        _kinds10[_x.province_source] += 1
    check(f"every row search draws says its province as the payload has it "
          f"({_seen10 - len(_off10)} of {_seen10})",
          _sout10 is not None and _seen10 > 0 and not _off10,
          why or f"e.g. {_off10[:2]}")
    for _k, _label in (("stated", "a province the listing states"),
                       ("city", "a province read from a city's name")):
        check(f"  the rows reach {_label} ({_kinds10[_k]})", _kinds10[_k] > 0,
              "none drawn — said, not passed")

    _art10 = json.loads(ART.read_text(encoding="utf-8"))["listings"]
    _pick10 = [next(dict(x) for x in _art10
                    if x.get("product_class") == "vehicle"
                    and x.get("province_source") == src)
               for src in ("stated", "city", "city")]
    _pick10[2].pop("province", None)
    _pick10[2]["province_source"] = "none"
    _pick10[2]["listing_id"] = _pick10[2]["listing_id"] + "-none"
    with tempfile.TemporaryDirectory() as d:
        (Path(d) / f"{RUN}.json").write_text(json.dumps(
            {"schema": SCHEMA, "run_id": RUN, "source": "bama.ir",
             "collected_on": "2026-10-15", "listings": _pick10},
            ensure_ascii=False), encoding="utf-8")
        with serving(Path(d)):
            _cmp10 = api.compare(schemas.CompareRequest(
                ids=[x["listing_id"] for x in _pick10], q="پراید"))
    _cout10, why = render("components/CompareTable.tsx", "EvidenceRows",
                          [{"evidence": [as_json(x) for x in _cmp10.evidence]}])
    _crow10 = _rows(_cout10["markup"][0]) if _cout10 else {}
    _coff10 = [(x.id, _pcell(_crow10.get(x.id, "")),
                _prov9(x.province, x.province_source))
               for x in _cmp10.evidence
               if _pcell(_crow10.get(x.id, ""))
               != _prov9(x.province, x.province_source)]
    check(f"compare's evidence rows say it too, for a listing of each kind "
          f"({len(_cmp10.evidence) - len(_coff10)} of "
          f"{len(_cmp10.evidence)})",
          len(_cmp10.evidence) == 3 and not _coff10
          and {x.province_source for x in _cmp10.evidence}
          == {"stated", "city", "none"},
          why or f"e.g. {_coff10[:2]}")


# ---------------------------------------------------------------------------
print("\n11 — the panel says the province the buyer named")
# ---------------------------------------------------------------------------
# A province is a constraint like the others (D82). The intent panel lists it
# under «آنچه از جمله‌ی تو فهمیدیم» when one was named, and says nothing of it
# otherwise: a line for a constraint never stated would claim a reading that
# was not made. A listing held apart for want of one says so with
# `UNCHECKED_FA`, a `Record` over `ConstraintKey` that the build holds to the
# union and this section holds to the other phrases.
def _intent11(**kw) -> schemas.Intent:
    # The parser always names a risk profile, so the panel always has a line
    # to draw; an intent without one would draw its empty sentence instead.
    return schemas.Intent(
        query="t", risk_profile="balanced", weights=schemas.Weights(
            value=0.35, risk=0.25, running_cost=0.15, liquidity=0.10,
            mileage=0.10, recency=0.05), **kw)


def _facts11(html: str) -> dict[str, str]:
    """The panel's «what we understood» list: label → value."""
    return {_text(k).strip(): _text(v).strip() for k, v in re.findall(
        r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>", html, re.S)}


_p11, why = node({"component": "components/IntentPanel.tsx",
                  "export": "default",
                  "props": [{"intent": as_json(_intent11(
                                provinces=["تهران", "اصفهان"]))},
                            {"intent": as_json(_intent11())}],
                  "consts": {"module": "lib/format.ts",
                             "names": ["UNCHECKED_FA"]}})
check("IntentPanel could be drawn for an intent with provinces and for one "
      "without", _p11 is not None, why)
if _p11 is not None:
    _two11, _none11 = (_facts11(h) for h in _p11["markup"])
    check("  a province named is listed under «استان», any-of, in the order "
          "named", _two11.get("استان") == "تهران، اصفهان", str(_two11))
    check("  none named: no line for it, and the rest of the panel is drawn",
          "استان" not in _none11 and "پروفایل ریسک" in _none11, str(_none11))
    _phrase11 = _p11["consts"]["UNCHECKED_FA"]
    check("  a listing apart for want of one has a phrase of its own",
          "استان" in _phrase11.get("province", "")
          and list(_phrase11.values()).count(_phrase11.get("province")) == 1,
          str(_phrase11.get("province")))

# And the panel as the parser's own reading draws it: the intent of a real
# answer, not one built above. The four readings a buyer can get — read as
# written, read from a bare name with the assumption said, declined and left
# in view, and not mentioned — each have to be told apart on the page.
_Q11 = (("پراید در تهران", "read as written"),
        ("پراید تهران", "a bare name, read and said so"),
        ("پراید غیر از تهران", "«غیر از», declined"),
        ("پراید پلاک تهران", "a plate, declined"),
        ("پراید", "no province named"))
with serving(ART.parent):
    _real11 = [(q, api.search(q=q, k=8)) for q, _ in _Q11]
_pr11, why = node({"component": "components/IntentPanel.tsx",
                   "export": "default",
                   "props": [{"intent": as_json(r.intent)}
                             for _, r in _real11]})
check(f"IntentPanel could be drawn for the intents of {len(_real11)} real "
      f"answers", _pr11 is not None, why)
if _pr11 is not None:
    def _assumed11(html: str) -> list[str]:
        return [_text(x).strip()
                for x in re.findall(r"<li[^>]*>(.*?)</li>", html, re.S)]

    def _unseen11(html: str) -> list[str]:
        """What sits under «نفهمیدیم»: the chips of the parts left out."""
        m = re.search(r"نفهمیدیم.*?</p>\s*<div[^>]*>(.*?)</div>", html, re.S)
        return ([_text(x).strip() for x in re.findall(
            r"<span[^>]*>(.*?)</span>", m.group(1), re.S)] if m else [])

    _got11 = {q: (_facts11(h), _assumed11(h), _unseen11(h))
              for (q, _), h in zip(_Q11, _pr11["markup"])}
    _f, _a, _u = _got11["پراید در تهران"]
    check("  «پراید در تهران»: «استان: تهران», no assumption, nothing left "
          "under «نفهمیدیم»",
          _f.get("استان") == "تهران" and not _a and not _u,
          str((_f, _a, _u)))
    _f, _a, _u = _got11["پراید تهران"]
    check("  «پراید تهران»: the same line, and the reading said as an "
          "assumption",
          _f.get("استان") == "تهران" and _a == ["«تهران» را استان تهران گرفتیم"]
          and not _u, str((_f, _a, _u)))
    for _q, _said in (("پراید غیر از تهران", "غیر از تهران"),
                      ("پراید پلاک تهران", "پلاک تهران")):
        _f, _a, _u = _got11[_q]
        check(f"  «{_q}»: no «استان» line, and «{_said}» left in view under "
              f"«نفهمیدیم»", "استان" not in _f and _u == [_said] and not _a,
              str((_f, _a, _u)))
    _f, _a, _u = _got11["پراید"]
    check("  «پراید»: no «استان» line, no assumption, nothing left out",
          "استان" not in _f and not _a and not _u, str((_f, _a, _u)))

# ---------------------------------------------------------------------------
print("\na page that is not there, and a page that broke, are told in Persian")
# ---------------------------------------------------------------------------
# Next's own pages say both in English («This page could not be found»,
# «Application error»). The site's say them in its language, and the error
# page draws the digest a reader can quote and never the error's message,
# which can carry a path or a value that is nobody's business on a screen.

def _latin(html: str, allowed: set[str]) -> list[str]:
    return [w for w in re.findall(r"[A-Za-z][A-Za-z0-9_.-]*", _text(html))
            if w not in allowed]


_LEAK = "/srv/caro/.env DATABASE_PASSWORD=hunter2 at query()"
_nf, why = node({"component": "app/not-found.tsx", "export": "default", "props": [{}],
                 "consts": {"module": "app/not-found.tsx", "names": ["NOT_FOUND_FA"]}})
_er, why2 = node({"component": "app/error.tsx", "export": "default",
                  "props": [{"error": {"message": _LEAK, "digest": "d1g3st42"}},
                            {"error": {"message": _LEAK}}],
                  "consts": {"module": "app/error.tsx",
                             "names": ["BROKE_FA", "REFERENCE_FA"]}})
if _nf is None or _er is None:
    check("the not-found and error pages could be drawn", False, why or why2)
else:
    _h = _nf["markup"][0]
    _hrefs = set(re.findall(r'href="([^"]*)"', _h))
    check("not-found: its sentence, links to /, /models and /search, and no Latin "
          "word but CARO",
          _nf["consts"]["NOT_FOUND_FA"] in _text(_h)
          and {"/", "/models", "/search"} <= _hrefs and not _latin(_h, {"CARO"}),
          f"hrefs {sorted(_hrefs)} latin {_latin(_h, {'CARO'})}")
    _with, _without = _er["markup"]
    BROKE, REF = _er["consts"]["BROKE_FA"], _er["consts"]["REFERENCE_FA"]
    check("error: its sentence, a button, a link to /, and no Latin word but CARO "
          "and the reference",
          BROKE in _text(_with) and "<button" in _with
          and 'href="/"' in _with and not _latin(_with, {"CARO", "d1g3st42"}),
          f"latin {_latin(_with, {'CARO', 'd1g3st42'})}")
    check("error: the error's message is not drawn",
          all(x not in h for h in (_with, _without)
              for x in (_LEAK, ".env", "DATABASE_PASSWORD", "hunter2")))
    check("error: the digest is drawn as the reference to quote, and no reference "
          "line without one",
          REF in _text(_with) and "d1g3st42" in _text(_with)
          and REF not in _text(_without))

# ---------------------------------------------------------------------------
print("\na model's page is titled with the model")
# ---------------------------------------------------------------------------
# One title for every model page made two tabs, or two search results, of two
# models read the same. The title is the label the page draws.
_tt, why = call("lib/format.ts", "modelTitle",
                [["Saipa", "Pride"], ["", "Pride"], ["_", "Pride"]])
_tl, why2 = call("lib/format.ts", "modelLabel", [["Saipa|Pride"], ["Pride"]])
if _tt is None or _tl is None:
    check("modelTitle could be called", False, why or why2)
else:
    check(f"modelTitle('Saipa', 'Pride') holds the label «{_tl[0]}» and ends «— CARO»",
          _tl[0] in _tt[0] and _tt[0].endswith("— CARO"), _tt[0])
    # the page hands the make over as it is in the address, `_` included
    check("with no make -- '' or the page's `_` -- the model's label alone, and no "
          "«_» and no «|»",
          all(_tl[1] in t and "_" not in t and "|" not in t and _tl[0] not in t
              for t in _tt[1:]), " / ".join(_tt[1:]))

# ---------------------------------------------------------------------------
print("\na model's listings, sorted three ways and kept to a year")
# ---------------------------------------------------------------------------
# Eight made offers, in the order the API sends them -- priced cheapest
# first, then an unusable price and none -- covering a tie, a missing year and
# every grade an odometer can carry. The ids are not in that order, so a tie
# broken by id is not mistaken for the API's.
def _offer(oid, price, status, year, km, grade):
    return {"id": oid, "asking_price_toman": price, "price_status": status,
            "price_kind": "cash" if price else None, "year_jalali": year,
            "mileage_km": km, "mileage_status": grade}


_OFFERS = [_offer("o3", 300_000_000, "ok", 1398, 90_000, "plausible"),
           _offer("o8", 350_000_000, "ok", 1401, 1_000, "suspicious"),
           _offer("o1", 400_000_000, "ok", 1401, 40_000, "plausible"),
           _offer("o6", 420_000_000, "ok", None, 20_000, "plausible"),
           _offer("o2", 450_000_000, "ok", 1395, None, None),
           _offer("o7", 500_000_000, "ok", 1398, 60_000, None),
           _offer("o4", 100_000_000, "placeholder", 1399, 5_000_000, "impossible"),
           _offer("o5", None, None, 1399, 30_000, "unknown")]


def _at(*ps):
    """The ids of the offers at these places (1-based) of the API's order."""
    return [_OFFERS[p - 1]["id"] for p in ps]


_so, why = call("lib/offers.ts", "sortOffers",
                [[_OFFERS, "price"], [_OFFERS, "year"], [_OFFERS, "mileage"]])
_oy, why2 = call("lib/offers.ts", "offersOfYear", [[_OFFERS, 1398], [_OFFERS, None]])
if _so is None or _oy is None:
    check("sortOffers and offersOfYear could be called", False, why or why2)
else:
    _ids = [[o["id"] for o in got] for got in _so]
    check("cheapest: the API's order, untouched -- an unusable 100 million stays after "
          "the priced", _ids[0] == _at(1, 2, 3, 4, 5, 6, 7, 8), str(_ids[0]))
    check("newest: by year down, no year last, a tie in the API's order",
          _ids[1] == _at(2, 3, 7, 8, 1, 6, 5, 4), str(_ids[1]))
    check("least driven: plausible or ungraded odometers up, then the rest in the "
          "API's order -- a suspicious 1,000 km after a plausible 90,000",
          _ids[2] == _at(4, 3, 6, 1, 2, 5, 7, 8), str(_ids[2]))
    check("a year keeps that year's listings in order; none keeps all",
          [o["id"] for o in _oy[0]] == _at(1, 6)
          and [o["id"] for o in _oy[1]] == [o["id"] for o in _OFFERS],
          str([[o["id"] for o in g] for g in _oy]))

# ---------------------------------------------------------------------------
print("\non a phone, a model's runs are a list; from 640 px, the chart")
# ---------------------------------------------------------------------------
_RUNS = [{"run_id": "run11", "collected_on": "2026-09-10", "priced": 54, "price_median": 613_000_000},
         {"run_id": "run13", "collected_on": "2026-10-06", "priced": 2, "price_median": None},
         {"run_id": "run14", "collected_on": "2026-10-11", "priced": 53, "price_median": 635_000_000},
         {"run_id": "run16", "collected_on": "2026-10-15", "priced": 50, "price_median": 650_000_000}]
_hv, why = node({"component": "components/ModelDetail.tsx", "export": "History",
                 "props": [{"points": _RUNS}]})
_hc, why2 = call("lib/format.ts", "compact", [[r["price_median"]] for r in _RUNS if r["price_median"]])
_hn, why3 = call("lib/format.ts", "faNum", [[r["priced"]] for r in _RUNS])
if _hv is None or _hc is None or _hn is None:
    check("History could be drawn", False, why or why2 or why3)
else:
    _hh = _hv["markup"][0]
    _ol = re.search(r'<ol[^>]*data-runs="list"[^>]*>(.*?)</ol>', _hh, re.S)
    _items = re.findall(r"<li[^>]*>(.*?)</li>", _ol.group(1), re.S) if _ol else []
    _mids = iter(_hc)
    _want = [(r["run_id"], _hn[i], next(_mids) if r["price_median"] else None)
             for i, r in enumerate(_RUNS)]
    _ok = len(_items) == len(_RUNS) and all(
        rid in _text(it) and f"{n} آگهی با قیمت" in _text(it)
        and ((mid is not None and f"میانه {mid}" in _text(it) and "کمتر از سه" not in _text(it))
             or (mid is None and "کمتر از سه آگهی با قیمت" in _text(it) and "میانه" not in _text(it)))
        for it, (rid, n, mid) in zip(_items, _want))
    check("the list: one item per run, in order, each with its id and its count; a middle where "
          "there is one, and «کمتر از سه آگهی با قیمت» and no middle where there is not",
          _ok, " | ".join(_text(it)[:60] for it in _items))
    _ol_tag = re.search(r'<ol[^>]*data-runs="list"[^>]*>', _hh)
    _svg_tag = re.search(r"<svg[^>]*>", _hh)
    _cls = lambda tag: (re.search(r'class="([^"]*)"', tag.group(0)).group(1).split()
                        if tag and re.search(r'class="([^"]*)"', tag.group(0)) else [])
    check("the chart is hidden on a phone and the list from 640 px up: one of them, never both",
          "sm:hidden" in _cls(_ol_tag) and "hidden" not in _cls(_ol_tag)
          and {"hidden", "sm:block"} <= set(_cls(_svg_tag)),
          f"ol {_cls(_ol_tag)} svg {_cls(_svg_tag)}")

# ---------------------------------------------------------------------------
print("\nthe admin page sends a code typed in Persian digits as the digits a header carries")
# ---------------------------------------------------------------------------
_ad, why = call("lib/format.ts", "asciiDigits", [["۲۸۷۰۸۲"], ["٠٧٠٨١٨"], ["123456"], ["۱۲۳abc"]])
check("asciiDigits: Persian and Arabic-Indic digits become ASCII ones; anything else is left as it is",
      _ad == ["287082", "070818", "123456", "123abc"], str(_ad) or why)

# ---------------------------------------------------------------------------
print("\n«پیش از خرید»: the seven steps the owner approved, word for word")
# ---------------------------------------------------------------------------
# B1, the owner's choice of 2026-10-30, with the draft text of
# docs/ACCOUNTS_AND_PAYMENT.md. The page and the document are one text: a step
# changed in one and not the other fails here.
_doc = (ROOT / "docs" / "ACCOUNTS_AND_PAYMENT.md").read_text(encoding="utf-8")
_draft = _doc[_doc.index("## A draft for B1"):]
_quoted = " ".join(ln[1:].strip() for ln in _draft.splitlines() if ln.startswith(">"))
_approved = [re.sub(r"\s+", " ", t).strip()
             for t in re.split(r"\s*[۰-۹]+\.\s+", _quoted) if t.strip()]
_bb, why = node({"component": "components/BeforeBuying.tsx", "export": "default", "props": [{}],
                 "consts": {"module": "components/BeforeBuying.tsx", "names": ["STEPS_FA"]}})
if _bb is None:
    check("the «پیش از خرید» page could be drawn", False, why)
else:
    _steps = [re.sub(r"\s+", " ", t).strip() for t in _bb["consts"]["STEPS_FA"]]
    check("its seven steps are the approved text, space for space",
          len(_approved) == 7 and _steps == _approved,
          f"{len(_approved)} approved, {len(_steps)} on the page; first differing: "
          + str(next(((a, b) for a, b in zip(_approved, _steps) if a != b), None)))
    _bh = _bb["markup"][0]
    _ol = re.search(r'<ol[^>]*data-steps="before-buying"[^>]*>(.*?)</ol>', _bh, re.S)
    _lis = re.findall(r"<li[^>]*>(.*?)</li>", _ol.group(1), re.S) if _ol else []
    check("drawn as seven list items in that order, the first with a link to /models, and no Latin "
          "word but CARO",
          [re.sub(r"\s+", " ", _text(x)).strip() for x in _lis] == _steps
          and 'href="/models"' in (_lis[0] if _lis else "") and not _latin(_bh, {"CARO"}),
          f"{len(_lis)} items; latin {_latin(_bh, {'CARO'})}")
if dout is not None:
    check("the car's file links to «پیش از خرید»", 'href="/before-buying"' in page["refused"])

# ---------------------------------------------------------------------------
print("\nthe way to the seller says where it goes: «تماس با فروشنده در <منبع>»")
# ---------------------------------------------------------------------------
# The owner asked (2026-10-30) that a buyer can reach the seller. CARO keeps no
# seller's number (DATA_CONTRACT); the listing's own page has it, behind the
# source's login, and the link to that page now says so.
_URLS = ["https://bama.ir/car/detail-d1hd97vo-pride-131-se-1397", "https://divar.ir/v/a/AaBbCc",
         "https://www.sheypoor.com/v/pride-131-123456.html", "https://khodro45.com/buy-car/x/tehran/abc/",
         "https://example.com/car/1", "not a url"]
_sn, why = call("lib/format.ts", "sourceName", [[u] for u in _URLS])
_cl, why2 = call("lib/format.ts", "contactLabel", [[_URLS[0]]])
check("sourceName: باما, دیوار, شیپور (a www. host), خودرو۴۵; another host and no url are «منبع»; "
      "the label on a bama url", _sn == ["باما", "دیوار", "شیپور", "خودرو۴۵", "منبع", "منبع"]
      and _cl == ["تماس با فروشنده در باما ↗"], f"{_sn} {_cl} {why or why2}")
_nf2, why3 = node({"consts": {"module": "lib/format.ts", "names": ["NUMBER_ON_SOURCE_FA"]}})
if dout is not None and _nf2 is not None:
    _car = page["refused"]
    _link = re.search(r'<a[^>]*href="(https://bama\.ir/[^"]+)"[^>]*>(.*?)</a>', _car, re.S)
    check("the car's file of a bama listing: «تماس با فروشنده در باما ↗» to its page, and the line "
          "that the number is there and CARO keeps none",
          bool(_link) and _text(_link.group(2)).strip() == "تماس با فروشنده در باما ↗"
          and _nf2["consts"]["NUMBER_ON_SOURCE_FA"] in _text(_car),
          _text(_link.group(2)).strip() if _link else "no link to bama.ir")

print("\nlistings sellers post on CARO: their pages draw the API's lists and never a number")
# Predictions SL1..SL6 (2026-10-30). The site keeps copies of lists the API
# owns -- the provinces, the colours, the classes, a report's reasons -- and
# these rows hold the copies to the originals.
from caro.ingest.divar_car import COLORS as _COLORS, FUEL as _FUEL, GEARBOX as _GEARBOX  # noqa: E402
from caro.ingest.persian import PROVINCES as _PROVINCES                          # noqa: E402

_sl, why_sl = node({"consts": {"module": "lib/seller.ts",
                               "names": ["PROVINCES_FA", "COLORS_FA", "BODY_KEYS", "GEARBOX_FA", "FUEL_FA",
                                         "REPORT_FA"]}})
_c = (_sl or {}).get("consts", {})
_api_bodies = re.search(r"BODIES = tuple\(label for label, _ in BODY_CONDITION\)",
                        (ROOT / "webapp" / "api" / "listings.py").read_text(encoding="utf-8"))
from caro.ingest.divar_car import BODY_CONDITION as _BODY_CONDITION             # noqa: E402
_reasons = re.search(r'REPORT_REASONS = \(([^)]*)\)', (ROOT / "webapp" / "api" / "review.py").read_text(encoding="utf-8"))
check("SL1: the site's provinces and colours are the API's, in its order; its body classes, gearboxes, fuels "
      "and report reasons are the API's own keys (the form lists body classes mildest first, the API most "
      "severe first)",
      _sl is not None and _c.get("PROVINCES_FA") == list(_PROVINCES) and _c.get("COLORS_FA") == list(_COLORS)
      and _api_bodies is not None and sorted(_c.get("BODY_KEYS", [])) == sorted(b for b, _ in _BODY_CONDITION)
      and sorted(_c.get("GEARBOX_FA", {})) == sorted(_GEARBOX) and sorted(_c.get("FUEL_FA", {})) == sorted(_FUEL)
      and _reasons is not None and list(_c.get("REPORT_FA", {})) == re.findall(r'"(\w+)"', _reasons.group(1)),
      why_sl or str({k: len(v) for k, v in _c.items()}))

_L = {"id": 7, "ends_at": 1_900_000_000, "make": "Saipa", "model": "Pride", "trim": None, "year_jalali": 1395,
      "mileage_km": 120000, "price_toman": 350000000, "negotiable": False, "province": "قم", "city": "قم",
      "gearbox": "manual", "fuel": None, "color": "سفید", "body": "intact", "description": "ماشین تمیز",
      "has_phone": True}
_cards, why_c = node({"component": "components/SellerListings.tsx", "export": "SellerListingCard",
                      "props": [{"listing": _L}, {"listing": {**_L, "has_phone": False}},
                                {"listing": {**_L, "price_toman": None, "negotiable": True}}]})
_m = (_cards or {}).get("markup", ["", "", ""])
check("SL2: a seller's listing is drawn with its model's Persian name, its price or «توافقی», its year and its "
      "place; «نمایش شماره» only where the seller chose it; and no phone number in the markup",
      _cards is not None and "سایپا · پراید" in _text(_m[0]) and "۳۵۰٬۰۰۰٬۰۰۰ تومان" in _text(_m[0])
      and "مدل ۱۳۹۵" in _text(_m[0]) and "قم، قم" in _text(_m[0])
      and "نمایش شماره" in _text(_m[0]) and "نمایش شماره" not in _text(_m[1])
      and "فروشنده شماره‌اش را نشان نمی‌دهد" in _text(_m[1]) and "توافقی" in _text(_m[2])
      and not any(re.search(r"0?9\d{9}|۰?۹[۰-۹]{9}|tel:", x) for x in _m), why_c or _text(_m[0])[:200])

_states, why_s = call("lib/seller.ts", "listingState", [
    [{"ended": True, "held": False, "live": {}, "pending": None, "last_review": None}],
    [{"ended": False, "held": True, "live": {}, "pending": None, "last_review": None}],
    [{"ended": False, "held": False, "live": {}, "pending": {}, "last_review": None}],
    [{"ended": False, "held": False, "live": {}, "pending": None, "last_review": None}],
    [{"ended": False, "held": False, "live": None, "pending": {}, "last_review": None}],
    [{"ended": False, "held": False, "live": None, "pending": None,
      "last_review": {"review": "rejected", "reason": "قیمت با خودرو نمی‌خواند"}}]])
check("SL3: a seller reads where each listing stands -- ended, taken down by reports, public with an edit "
      "waiting, public, waiting, rejected with the operator's reason",
      _states is not None and [s.split("؛")[0].split(":")[0] for s in _states] == [
          "تمام شده", "با گزارش‌ها پایین آمده تا مدیر نگاهش کند.", "منتشر شده", "منتشر شده.",
          "در انتظار تأیید.", "رد شد"] and _states[5].endswith("قیمت با خودرو نمی‌خواند"), why_s or str(_states))

_ex, why_e = call("lib/seller.ts", "explain", [
    [422, {"detail": {"faults": {"description": "بدون عدد"}}}],
    [503, {"detail": {"code": "SMS_OFF", "fa": "سرویس پیامک هنوز تعیین نشده است."}}],
    [401, {"detail": "کد درست نیست یا دیگر اعتبار ندارد. کد تازه بگیر."}],
    [429, None]])
check("SL4: a refusal reads as the server said it: each refused field by name, the server's Persian sentence, "
      "and a sentence of its own for a bare 429",
      _ex is not None and _ex[0]["faults"] == {"description": "بدون عدد"}
      and _ex[1]["message"] == "سرویس پیامک هنوز تعیین نشده است." and _ex[2]["message"].startswith("کد درست نیست")
      and "زیاد" in (_ex[3]["message"] or ""), why_e or str(_ex))

_ints, why_i = call("components/SellForm.tsx", "toInt", [["۱۲۰٬۰۰۰"], ["350,000,000"], ["٣٥٠ ٠٠٠"], [""]])
_empty, why_m = node({"consts": {"module": "components/SellForm.tsx", "names": ["EMPTY"]}})
check("SL5: a number typed in Persian or Arabic-Indic digits, with separators, is read as its value; a new "
      "form does not show the seller's number unless the seller ticks it",
      _ints == [120000, 350000000, 350000, None]
      and (_empty or {}).get("consts", {}).get("EMPTY", {}).get("show_phone") is False,
      why_i or why_m or str(_ints))

_mine = {"id": 3, "ends_at": 4_000_000_000, "ended": False, "held": False, "live": None,
         "pending": {k: v for k, v in _L.items() if k not in ("id", "ends_at", "has_phone")} | {"show_phone": True},
         "last_review": None, "reveals": 4}
_mc, why_mc = node({"component": "components/MyListings.tsx", "export": "MineCard",
                    "props": [{"item": _mine, "onChange": None}]})
_mt = _text((_mc or {}).get("markup", [""])[0])
check("SL6: «آگهی‌های من» draws each listing with where it stands, how many times its number was revealed, "
      "and the seller's edit, renewal and two-step delete",
      _mc is not None and "در انتظار تأیید." in _mt and "شماره ۴ بار دیده شده" in _mt
      and all(w in _mt for w in ("ویرایش", "تمدید ۳۰ روزه", "حذف آگهی")) and "/sell?edit=3" in _mc["markup"][0],
      why_mc or _mt[:200])

print()
if FAILS:
    print(f"FAILED ({len(FAILS)}): " + ", ".join(FAILS))
    raise SystemExit(1)
print("all tests passed")
