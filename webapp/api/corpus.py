"""Which corpus the site is serving, and the honesty that follows from it.

The platform has to answer one question before it answers any other: *what is
this data?* CARO's whole claim is that a number never travels without the
grade of the evidence behind it, and a website is the easiest place in the
world to lose that — a listing card looks identical whether it came from a
real Bama page or from a generated fixture.

So the corpus is loaded through here, it always reports which kind it is, and
every API response carries that label. `docs/DEMO_SCRIPT.md` makes the same
rule for the video: the SYNTHETIC / REAL DATA marker is persistent, not a
title card. This is that rule, in the product.

Three states, and which one you are in is chosen here:

    REAL        data/corpora/<run>.json, if a published artifact exists.
                Loaded through caro.corpus_reader, which fails closed on
                missing provenance: how much of it reaches W1 depends on
                whether the artifact carries price and mileage provenance,
                and on an artifact that does not, `rows` is empty while
                `listings` is not. Either way `gated` is False — D43, no
                estimator has cleared the gate on a real corpus — so what is
                served is evidence, never a ranking.

    SYNTHETIC   the corpus tests/test_ranking.py generates. Real code, real
                ranking, known true prices — which is why the gate passes on
                it and a shortlist can actually be served.

    UNUSABLE    nothing may be served and this is not the documented absence.
                Two ways in, kept apart by `fault`: an artifact that EXISTS
                and would not load, and a run an operator ASKED FOR that is
                not on disk.

The synthetic fallback is deliberate and is not a workaround: with no real
corpus present the product should still be usable and should say, on every
screen, that what it is showing is a demonstration.

The third state exists because the first two used to absorb it. D49: absence
is a fallback, failure is not. A corpus that fails validate(), a volume that
cannot be addressed, a truncated write, a tampered file — every one of them
used to return None from `_real()` and come back as a working site serving
generated data under a SYNTHETIC badge that was, in each case, displayed
correctly. Nothing lied, nobody was told, and there was no error to notice.

## Which run, and why the default was never reached

`active()` defaulted to `run3` and `data/corpora/run3.json` has not existed
since D46 — that corpus was never committed and is not recoverable. So the
existence check at the top of `_real()` failed on every request of every
deployment, and the site served SYNTHETIC unconditionally. It did so while
labelling itself correctly, which is why nobody noticed: the badge said
SYNTHETIC and it was.

That is the same defect D49 was written about, one level up. D49 closed the
case where a real artifact failed to LOAD; this was the case where a real
artifact was never LOOKED FOR. The fix is `CARO_RUN` — an explicit name, a
default that points at an artifact that actually exists, and no path where
the run in force is unstated:

    CARO_RUN set, artifact present    → REAL
    CARO_RUN set, artifact absent     → UNUSABLE / RUN_NOT_FOUND. An operator
                                        named a run; serving a different
                                        corpus instead is the silent
                                        substitution this module exists to
                                        prevent.
    unset, DEFAULT_RUN present        → REAL
    unset, DEFAULT_RUN absent         → SYNTHETIC, and `note_fa` NAMES the
                                        path it looked for.

The last line is D49 applied rather than softened. On a fresh clone there is
no corpus, because none is committed; that is absence, absence is a fallback,
and a fault that fires on the documented normal state is a fault nobody reads.
What was wrong before was not the fallback — it was that the fallback said
nothing about what it had looked for. It says so now.
"""

from __future__ import annotations

import contextlib
import io
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

# The run served when nothing says otherwise. It is a constant rather than a
# literal in a signature so that the tests can follow it: a suite that hardcodes
# "run11" keeps passing on the day the default stops existing, which is exactly
# the failure this replaces.
DEFAULT_RUN = "run11"
RUN_ENV = "CARO_RUN"


def configured() -> tuple[str, bool]:
    """(the run to serve, whether an operator named it).

    The flag is the whole reason this is not one `os.environ.get` at the call
    site. A missing artifact means two different things depending on it — a
    misconfiguration to report, or the documented absence to fall back from —
    and those two cases are indistinguishable once the name has been resolved.
    """
    named = os.environ.get(RUN_ENV, "").strip()
    return (named, True) if named else (DEFAULT_RUN, False)


@dataclass(frozen=True)
class Corpus:
    kind: str                 # "SYNTHETIC" | "REAL" | "UNUSABLE"
    label_fa: str
    rows: list                # caro.appraisal.Row — the APPRAISABLE subset
    pipeline: object          # caro.ranking.RankingPipeline
    gated: bool               # may an estimate be served at all?
    source: str
    note_fa: str
    # Present only when the numbers rest on a published artifact. `source` is
    # a path and a path is not an identity: two deployments can serve
    # different files from `data/corpora/run3.json` and both report that
    # string honestly. The digest is what makes a served number traceable to
    # exact bytes a reviewer can fetch and re-hash.
    identity: object | None = None      # caro.corpus_reader.CorpusIdentity
    # Every parsed listing, not only the appraisable ones. Kept because the
    # two counts diverge on a published artifact: `eligibility()` fails closed
    # on a listing whose price or mileage arrives without provenance, so how
    # far `rows` falls short of `listings` is a property of the artifact — on
    # one that carries no provenance at all, `rows` is empty while the corpus
    # holds hundreds of listings. Reporting only `rows` there would tell a
    # buyer we looked at nothing.
    listings: list = field(default_factory=list)
    # Set only on the UNUSABLE state: what went wrong. Travels in the envelope
    # because the person who needs to see it is looking at the site (D49).
    #
    # `fault_code` is what a client branches on and `fault` is what a person
    # reads. They are two fields because UNUSABLE now has two causes — a file
    # that will not load, and a run that is not there — and those need
    # different actions from whoever sees them: fix the artifact, or fix the
    # configuration. Deriving the code by matching on the message would make
    # the branch depend on wording.
    fault: str | None = None
    fault_code: str | None = None

    def as_dict(self) -> dict:
        return {"kind": self.kind, "label_fa": self.label_fa,
                "rows": len(self.listings) or len(self.rows),
                "appraisable": len(self.rows), "gated": self.gated,
                "source": self.source, "note_fa": self.note_fa,
                # null, not a placeholder. A synthetic corpus has no artifact,
                # and minting a digest for it — of the generating module, say
                # — would put a number that LOOKS like evidence identity next
                # to a corpus that has none. The client renders the absence.
                "identity": (self.identity.as_dict()
                             if self.identity is not None else None),
                "fault": self.fault, "fault_code": self.fault_code}


def _synthetic(sought: str | None = None) -> Corpus:
    """The generated corpus. `sought` is the run that was looked for and was
    not there — named in the note, because a fallback that does not say what
    it fell back FROM is the silent substitution one level down."""
    # Importing the suite builds the corpus and gates the estimator. It prints
    # its own check lines, which must not land in the server log.
    with contextlib.redirect_stdout(io.StringIO()):
        import tests.test_ranking as T          # noqa: PLC0415

    note = ("این نتایج روی پیکره‌ای اجرا می‌شوند که خود پروژه تولید کرده و "
            "قیمت‌های واقعی‌اش معلوم است. رفتار سامانه را نشان می‌دهد، نه "
            "بازار ایران را.")
    if sought is not None:
        note += (f" پیکره‌ی واقعی بارگذاری نشد چون data/corpora/{sought}.json "
                 "روی دیسک نیست. پیکره‌ها در مخزن نگهداری نمی‌شوند (D46)؛ "
                 f"با CARO_RUN می‌شود run دیگری را صریحاً انتخاب کرد.")

    return Corpus(
        kind="SYNTHETIC",
        label_fa="پیکره‌ی ساختگی",
        rows=list(T.POOL),
        pipeline=T.PIPE,
        gated=bool(T.OK),
        source="tests/test_ranking.py",
        note_fa=note,
        identity=None,      # generated, not collected: there is no artifact
    )


def _unusable(run_id: str, fault: BaseException) -> Corpus:
    """An artifact exists and will not load. D49: this is not a fallback.

    Serves nothing, in the state the product already knows how to render, and
    carries the fault so the site can show it rather than leaving it in a log
    nobody reads.
    """
    return Corpus(
        kind="UNUSABLE",
        label_fa="پیکره‌ی معیوب",
        rows=[], listings=[], pipeline=_synthetic().pipeline,
        gated=False,
        source=f"data/corpora/{run_id}.json",
        note_fa="یک پیکره‌ی واقعی روی دیسک هست و خوانده نمی‌شود. تا وقتی این "
                "خطا برطرف نشده، چیزی سرو نمی‌شود — و به‌جای آن به داده‌ی "
                "ساختگی برنمی‌گردیم، چون آن‌وقت سایت سالم به‌نظر می‌رسید و "
                "کسی نمی‌فهمید شواهد واقعی رد شده است.",
        fault=f"{type(fault).__name__}: {fault}",
        fault_code="CORPUS_INVALID",
    )


def _missing(run_id: str) -> Corpus:
    """`CARO_RUN` names a run and there is no artifact for it.

    Not the same thing as having no corpus at all, which is the SYNTHETIC
    fallback and stays one. Somebody stated which evidence this deployment
    serves; the honest answers are that run or nothing, and serving a
    generated corpus instead would be a substitution nobody asked for and
    nobody would see — the badge would read SYNTHETIC and be correct.

    It is UNUSABLE rather than a fourth kind because `kind` answers "what may
    be shown on this screen", and the answer is identical to the broken-file
    case: nothing, plus a reason. The difference between the two causes is
    what `fault_code` is for, and a fourth kind every client switch handled
    exactly like UNUSABLE would put one distinction in two places.
    """
    return Corpus(
        kind="UNUSABLE",
        label_fa="پیکره‌ی انتخاب‌شده پیدا نشد",
        rows=[], listings=[], pipeline=_synthetic().pipeline,
        gated=False,
        source=f"data/corpora/{run_id}.json",
        note_fa=f"متغیر {RUN_ENV} روی «{run_id}» تنظیم شده و فایل آن روی دیسک "
                "نیست. به‌جای این‌که بی‌صدا پیکره‌ی ساختگی سرو شود، چیزی سرو "
                "نمی‌شود: وقتی کسی صریحاً گفته کدام شواهد باید سرو شود، "
                "جایگزین‌کردن آن با داده‌ی تولیدشده همان اشتباهی است که "
                "برچسب پیکره برای جلوگیری از آن ساخته شده.",
        fault=f"{RUN_ENV}={run_id!r} names a run with no artifact at "
              f"data/corpora/{run_id}.json",
        fault_code="RUN_NOT_FOUND",
    )


def _real(run_id: str) -> Corpus | None:
    from caro.corpus_reader import (            # noqa: PLC0415
        corpus_identity, corpus_path, load_corpus, rows_from_corpus,
    )
    # Absence is a fallback; failure is not (D49). The existence check is made
    # HERE, before anything can raise, so the two cases can never collapse into
    # one `except`. Everything after this line runs with an artifact on disk,
    # and no error below is allowed to end in a synthetic success.
    if not corpus_path(run_id).exists():
        return None

    try:
        artifact = load_corpus(run_id)
        identity = corpus_identity(run_id)
        listings, rows = rows_from_corpus(artifact)
    except Exception as e:                      # noqa: BLE001 — deliberate
        # Broad on purpose. The catalogue of ways a file fails to load is not
        # closeable — ValueError from the guards, OSError from a volume,
        # UnicodeDecodeError from a truncated write, a TypeError from a schema
        # change — and narrowing this would silently re-open the exact hole
        # D49 exists to close, because the uncaught ones would propagate out
        # of `active()` and 500 the site instead of reporting the fault.
        return _unusable(run_id, e)

    # An estimator that has never been benchmarked. `MarketEstimator.predict`
    # raises `NotBenchmarked` until `benchmark()` approves it, so `Ranker` can
    # physically not produce a number here — which is the refusal the product
    # shows, arrived at through the shipped mechanism rather than through a
    # flag that says "pretend it refused".
    #
    # `PartialPoolingQuantiles` is named rather than left abstract because it
    # is the candidate that would be fitted the day a corpus can judge one.
    # It is constructed but never fitted and never called.
    from caro.appraisal import MarketEstimator      # noqa: PLC0415
    from caro.hierarchical import PartialPoolingQuantiles  # noqa: PLC0415
    from caro.ranking import (                      # noqa: PLC0415
        RankingPipeline, Ranker, RuleIntentParser,
    )
    return Corpus(
        kind="REAL",
        label_fa="داده‌ی واقعی",
        rows=rows,
        listings=listings,
        # No estimator has ever cleared the acceptance gate on a real corpus
        # (D43), so `Ranker.score` raises and no shortlist exists. The product
        # shows evidence and refuses the ranking rather than inventing one.
        pipeline=RankingPipeline(
            parser=RuleIntentParser(),
            ranker=Ranker(estimator=MarketEstimator(
                PartialPoolingQuantiles()))),
        gated=False,
        source=f"data/corpora/{run_id}.json",
        note_fa="آگهی‌های واقعی. هیچ برآوردگری روی پیکره‌ی واقعی از دروازه‌ی "
                "پذیرش عبور نکرده، پس رتبه‌بندی سرو نمی‌شود و آنچه می‌بینید "
                "شواهد است، نه توصیه.",
        identity=identity,
    )


@lru_cache(maxsize=1)
def active() -> Corpus:
    """The corpus this process serves, and never one it was not asked for.

    Takes no argument on purpose. The run was a default parameter, every call
    site omitted it, and the default named an artifact that does not exist —
    so the choice was made in a signature nobody read. It is made here, from
    the environment, once, and `configured()` is the only place that answers
    "which run".
    """
    run_id, explicit = configured()
    real = _real(run_id)
    if real is not None:
        return real
    return _missing(run_id) if explicit else _synthetic(sought=run_id)
