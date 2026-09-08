"""The only adapter between a published corpus and this project's domain types.

    data/corpora/<run>.json          the artifact, per DATA_CONTRACT
            ↓  caro.ingest.corpus    schema + content guards
            ↓  THIS MODULE           the named mapping, in one place
    CarListing / Row                 what W1 and W3 consume

It sits above `caro/ingest/` on purpose. `Row` is a W1 type and `appraisal`
already imports `ingest.quality`, so an ingest module that mapped to `Row`
would close the dependency loop the architecture keeps open. The mapping lives
here, once, so that six consumers cannot each invent their own version of it —
which is how two callers end up disagreeing about what a corpus field means.

## What this module deliberately does not do

**It does not reconstruct prose.** `CarListing` requires `title` and
`description`; a published artifact carries neither, because the contract
forbids publishing seller-authored text. Both are set to `""` explicitly
rather than through a fallback that would blur the difference between "the
seller wrote nothing" and "this representation does not carry it". A consumer
that needs the raw description gets nothing from a corpus, and that is
visible rather than papered over.

**It does not invent price or mileage provenance.** `price_status` records how
the price was READ — the D20 cross-check between the structured block and the
number rendered to buyers — and that is parse-time knowledge. Promotion runs
after parsing and cannot recover it, so both status fields are passed as
`None`: not recorded in this representation. `eligibility()` fails closed on
that, which means a corpus-backed listing is refused entry to W1 until
promotion can carry provenance.

That is the intended behaviour and not a defect to route around. The property
this migration must preserve is not that a corpus row equals its legacy row —
the corpus deliberately holds less — but that **a corpus can never make a
listing more W1-eligible than the legacy path did.** Stricter is allowed.
More permissive is the failure.
"""

from __future__ import annotations

import json
from pathlib import Path

from caro.appraisal import Row
from caro.ingest.corpus import SCHEMA, validate
from caro.ingest.divar_car import CarListing
from caro.ingest.quality import eligibility
from caro.ranking import features_from_listing

ROOT = Path(__file__).resolve().parent.parent
CORPORA = ROOT / "data" / "corpora"


class CorpusUnavailable(FileNotFoundError):
    """No published artifact exists for this run.

    A distinct type because the cause is a prerequisite, not a bug: D46
    records that the Run 3 and Run 5 corpora were never committed and are not
    recoverable, so their scripts have nothing to read and no amount of
    fixing the reader changes that. Raising FileNotFoundError with a bare
    path invites the opposite conclusion.
    """


def corpus_path(run_id: str) -> Path:
    return CORPORA / f"{run_id}.json"


def load_corpus(run_id: str) -> dict:
    """Read and validate the published artifact for `run_id`."""
    p = corpus_path(run_id)
    if not p.exists():
        raise CorpusUnavailable(
            f"no publishable corpus for {run_id!r} at "
            f"{p.relative_to(ROOT)}.\n"
            f"  This is an acquisition prerequisite, not a code fault: see "
            f"D46 in docs/DECISIONS.md.\n"
            f"  A corpus is produced by scripts/promote_corpus.py from an "
            f"operational snapshot; it is not\n"
            f"  reconstructable from the run transcripts in docs/.")

    text = p.read_text(encoding="utf-8")
    artifact = json.loads(text)
    problems = validate(artifact, text)
    if problems:
        raise ValueError(
            f"{p.relative_to(ROOT)} is not a valid {SCHEMA} artifact:\n"
            + "\n".join(str(v) for v in problems))
    return artifact


def listing_from_record(rec: dict) -> CarListing:
    """One published row -> one CarListing. The whole mapping is here."""
    return CarListing(
        listing_id=rec["listing_id"],
        url=rec.get("url", ""),
        # Not carried by a published artifact, and not invented here. See the
        # module docstring: the contract forbids publishing seller prose, so
        # a consumer that needs it gets nothing, visibly.
        title="",
        description="",
        asking_price_toman=rec.get("asking_price_toman"),
        make=rec.get("make"),
        model=rec.get("model"),
        trim=rec.get("trim"),
        year_jalali=rec.get("year_jalali"),
        mileage_km=rec.get("mileage_km"),
        gearbox=rec.get("gearbox"),
        fuel=rec.get("fuel"),
        color=rec.get("color"),
        body_condition=rec.get("condition", "unknown"),
        document_issue=rec.get("document_issue"),
        city=rec.get("province"),
        price_currency_raw=rec.get("price_currency_raw"),
        # Parse-time provenance the artifact cannot carry. None means "not
        # recorded", and eligibility() fails closed on it.
        price_status=None,
        mileage_status=None,
    )


def listings_from_corpus(artifact: dict) -> list[CarListing]:
    return [listing_from_record(r) for r in artifact.get("listings", [])]


def rows_from_corpus(artifact: dict) -> tuple[list[CarListing], list[Row]]:
    """(every parsed listing, the appraisal-eligible subset as Rows).

    Mirrors what each consumer used to do inline: keep the full listing set
    for counting and coverage, and admit only eligible ones to W1.
    """
    listings = listings_from_corpus(artifact)
    rows = []
    for got in listings:
        if not eligibility(got)[0]:
            continue
        rows.append(Row(
            listing_id=got.listing_id, cluster_id=got.listing_id,
            first_seen_ordinal=0,
            model_key=f"{got.make}|{got.model}|{got.trim or ''}",
            year_jalali=int(got.year_jalali),
            mileage_km=float(got.mileage_km),
            asking_price_toman=float(got.asking_price_toman),
            features=features_from_listing(got)))
    return listings, rows
