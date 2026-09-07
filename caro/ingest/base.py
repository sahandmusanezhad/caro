"""
Source adapters — the boundary between the outside world and CARO.

CARO is deliberately source-agnostic: nothing downstream of this module knows
or cares whether a listing came from a marketplace, a public dataset, or a
CSV export. An adapter's only job is to turn one source's rows into
`FetchOutcome` records; everything after that is CARO's problem.

Why adapters are NOT agents
---------------------------
Fetching and parsing are deterministic engineering. They are testable, they
must be reproducible, and an LLM would make them slower, costlier and less
reliable. Agents live where reasoning lives — evidence, risk, adversarial
review, explanation. That boundary is the same one enforced everywhere else
in this codebase.

Obligations on every adapter
----------------------------
1. Respect the source's terms of use and robots directives. Rate-limit, cache,
   identify yourself honestly. Build no anti-bot evasion — if a source blocks
   you, stop and record it.
2. Never emit a personal identifier. `seller_fingerprint` is a salted hash and
   nothing else; raw phone numbers must not reach CARO or disk.
3. Classify failures honestly. A timeout or a 403 is `UNKNOWN`, never
   `ABSENT` — see `caro.tracking.classify_http`. Getting this wrong silently
   fabricates disappearances and corrupts every longitudinal statistic.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Protocol

from caro.tracking import FetchOutcome, FetchStatus, Snapshot, assess_integrity


def salted_fingerprint(raw: str, salt: str | None = None) -> str:
    """Hash a seller identifier. The raw value must never be stored.

    The salt lives in the environment, not the repo, so a published corpus
    cannot be reversed even by someone holding the code.
    """
    s = salt if salt is not None else os.environ.get("CARO_SELLER_SALT", "")
    if not s:
        raise ValueError(
            "CARO_SELLER_SALT is not set. Refusing to emit an unsalted seller "
            "hash — an unsalted hash of a phone number is a phone number.")
    return hashlib.sha256(f"{s}|{raw}".encode("utf-8")).hexdigest()[:24]


class SourceAdapter(Protocol):
    """One marketplace, dataset or export.

    `name` identifies the source in provenance records. `fetch_all` yields one
    `FetchOutcome` per tracked listing for a given day — present, definitively
    absent, or unknown.
    """

    name: str

    def fetch_all(self, on: date) -> Iterable[FetchOutcome]: ...


@dataclass
class MultiSourceCollector:
    """Runs several adapters into one integrity-checked snapshot per day.

    Sources are kept as separate `FetchOutcome` streams and merged only at the
    snapshot level, so a source that goes down degrades coverage instead of
    corrupting the record. Cross-source identity — the same physical car
    listed in three places — is resolved downstream by the repost matcher in
    `caro.tracking`, which already links on vehicle, seller and image
    fingerprints while deliberately ignoring price.
    """

    adapters: list[SourceAdapter]

    def collect(self, on: date, snapshot_id: str | None = None) -> Snapshot:
        outcomes: list[FetchOutcome] = []
        for a in self.adapters:
            try:
                outcomes.extend(a.fetch_all(on))
            except Exception as exc:                      # noqa: BLE001
                # A source that fails wholesale contributes ignorance, never
                # absence. Silently dropping it would look like every one of
                # its listings vanished on the same day.
                outcomes.append(FetchOutcome(
                    listing_id=f"__source_error__:{a.name}",
                    status=FetchStatus.UNKNOWN, http_status=None))
        sid = snapshot_id or f"snap-{on.isoformat()}"
        return assess_integrity(Snapshot(sid, on, outcomes))
