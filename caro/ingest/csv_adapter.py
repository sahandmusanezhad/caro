"""A working adapter over a CSV/Parquet export.

This is the adapter to point at a public dataset, or at the output of an
external scraper — write the scraper's rows to CSV and CARO consumes them
unchanged. It is also the reference implementation: a new adapter for a live
source needs the same `fetch_all` signature and nothing else.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable

from caro.tracking import FetchOutcome, FetchStatus
from caro.ingest.base import salted_fingerprint

# Column name -> the FetchOutcome field it fills. Override per dataset.
DEFAULT_MAPPING = {
    "id": "listing_id", "price": "price_irr", "make": "make", "model": "model",
    "trim": "trim", "year": "year_jalali", "color": "color",
    "province": "province", "mileage": "mileage_km", "seller": "seller_raw",
}


@dataclass
class CsvAdapter:
    path: Path
    name: str = "csv"
    mapping: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_MAPPING))
    salt: str | None = None

    def _int(self, v: str | None) -> int | None:
        if v is None or v == "":
            return None
        try:
            return int(float(str(v).replace(",", "").replace("٬", "")))
        except ValueError:
            return None

    def fetch_all(self, on: date) -> Iterable[FetchOutcome]:
        with open(self.path, newline="", encoding="utf-8") as fh:
            for raw in csv.DictReader(fh):
                r = {self.mapping[k]: v for k, v in raw.items() if k in self.mapping}
                seller = r.pop("seller_raw", None)
                yield FetchOutcome(
                    listing_id=f"{self.name}:{r.get('listing_id','')}",
                    status=FetchStatus.OK,
                    price_irr=self._int(r.get("price_irr")),
                    make=r.get("make"), model=r.get("model"), trim=r.get("trim"),
                    year_jalali=self._int(r.get("year_jalali")),
                    color=r.get("color"), province=r.get("province"),
                    mileage_km=self._int(r.get("mileage_km")),
                    # A raw seller value never leaves this function unhashed.
                    seller_fingerprint=(salted_fingerprint(seller, self.salt)
                                        if seller else None),
                )
