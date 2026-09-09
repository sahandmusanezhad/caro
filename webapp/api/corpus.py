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
                missing provenance — so on today's artifacts this yields a
                corpus that can be listed but not appraised (D46 + the
                eligibility fix).

    SYNTHETIC   the corpus tests/test_ranking.py generates. Real code, real
                ranking, known true prices — which is why the gate passes on
                it and a shortlist can actually be served.

    UNUSABLE    an artifact EXISTS and would not load. Serves nothing and
                reports what broke.

The synthetic fallback is deliberate and is not a workaround: with no real
corpus present the product should still be usable and should say, on every
screen, that what it is showing is a demonstration.

The third state exists because the first two used to absorb it. D49: absence
is a fallback, failure is not. A corpus that fails validate(), a volume that
cannot be addressed, a truncated write, a tampered file — every one of them
used to return None from `_real()` and come back as a working site serving
generated data under a SYNTHETIC badge that was, in each case, displayed
correctly. Nothing lied, nobody was told, and there was no error to notice.
"""

from __future__ import annotations

import contextlib
import io
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


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
    # two counts diverge completely on a published artifact — promotion runs
    # after parsing and cannot carry price/mileage provenance, so
    # `eligibility()` fails closed on all of it and `rows` is empty while the
    # corpus holds hundreds of listings. Reporting only `rows` there would
    # tell a buyer we looked at nothing.
    listings: list = field(default_factory=list)
    # Set only on the UNUSABLE state: what went wrong loading an artifact that
    # exists. Travels in the envelope because the person who needs to see it
    # is looking at the site (D49).
    fault: str | None = None

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
                "fault": self.fault}


def _synthetic() -> Corpus:
    # Importing the suite builds the corpus and gates the estimator. It prints
    # its own check lines, which must not land in the server log.
    with contextlib.redirect_stdout(io.StringIO()):
        import tests.test_ranking as T          # noqa: PLC0415

    return Corpus(
        kind="SYNTHETIC",
        label_fa="پیکره‌ی ساختگی",
        rows=list(T.POOL),
        pipeline=T.PIPE,
        gated=bool(T.OK),
        source="tests/test_ranking.py",
        note_fa="این نتایج روی پیکره‌ای اجرا می‌شوند که خود پروژه تولید کرده و "
                "قیمت‌های واقعی‌اش معلوم است. رفتار سامانه را نشان می‌دهد، نه "
                "بازار ایران را.",
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
def active(run_id: str = "run3") -> Corpus:
    """The corpus this process serves. Real if one exists, synthetic if not."""
    return _real(run_id) or _synthetic()
