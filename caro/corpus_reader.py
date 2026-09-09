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

import hashlib
import json
from dataclasses import dataclass
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


def sha256_of(path: Path) -> str:
    """The digest of the FILE'S BYTES. Not of anything parsed out of them.

    The distinction is the entire value of the number. Hashing
    `json.dumps(load_corpus(run))` would digest this process's re-encoding —
    its key order, its separators, its `ensure_ascii` setting, its float
    repr — and two machines could then publish different digests for one
    unmodified artifact, or the same digest for two files that differ in
    whitespace. A reviewer who recomputes it reaches for `sha256sum` on the
    file, and this must be the number that comes back.
    """
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass(frozen=True)
class CorpusIdentity:
    """Which exact evidence a served number rests on.

    `run_id` names the collection; `sha256` names the bytes. The second is
    what makes the first checkable — D46 is what a published number without a
    retrievable input artifact costs, and a path alone is not an identity:
    two deployments can serve different files from `data/corpora/run3.json`
    and both report that string truthfully.
    """

    run_id: str
    path: str            # repository-relative, so it is quotable
    sha256: str
    bytes: int

    def as_dict(self) -> dict:
        return {"run_id": self.run_id, "path": self.path,
                "sha256": self.sha256, "bytes": self.bytes}

    @property
    def short(self) -> str:
        """`8f3a…c21d` — for a screen. The full digest travels in the API."""
        return f"{self.sha256[:4]}…{self.sha256[-4:]}"


def corpus_identity(run_id: str) -> CorpusIdentity:
    """Identity of the published artifact for `run_id`.

    Raises `CorpusUnavailable` for the same reason `load_corpus` does: an
    artifact that does not exist has no identity, and inventing a placeholder
    digest for one would be worse than having none.
    """
    p = corpus_path(run_id)
    if not p.exists():
        raise CorpusUnavailable(
            f"no publishable corpus for {run_id!r} at {_display(p)} — "
            f"see D46 in docs/DECISIONS.md")
    return CorpusIdentity(run_id=run_id, path=_display(p),
                          sha256=sha256_of(p), bytes=p.stat().st_size)


def _display(p: Path) -> str:
    """Repository-relative when it can be, absolute when it cannot.

    `relative_to` RAISES on a path outside the root, and a corpus directory
    outside the root is a normal deployment — a mounted volume under Docker
    Compose is the case this project just committed to. Letting that
    ValueError escape made `_real()` swallow it and fall back to the synthetic
    corpus, so a real artifact sitting on disk would have been silently
    ignored: the label stays truthful, which is exactly why nobody would have
    noticed the evidence was not being served.
    """
    try:
        return str(p.relative_to(ROOT))
    except ValueError:
        return str(p)


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
        condition_source=rec.get("condition_source", "none"),
        document_issue=rec.get("document_issue"),
        # D26 again, at the last boundary: a corpus that recorded no seller
        # type yields `unknown`, which is the dataclass default. Absence never
        # becomes `private` here either.
        seller_type=rec.get("seller_type") or "unknown",
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
