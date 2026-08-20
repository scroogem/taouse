"""Нормализованное объявление — общий язык для всех источников.

Каждый адаптер приводит свою страницу к этой структуре, дальше система не знает
и не хочет знать, откуда объявление пришло.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone


@dataclass
class Photo:
    url: str
    order: int = 0
    phash: str | None = None
    dhash: str | None = None
    width: int | None = None
    height: int | None = None


@dataclass
class Listing:
    source: str                 # 'notaires', 'orpi', ...
    url: str
    source_id: str = ""
    title: str = ""
    description: str = ""

    price: int | None = None            # €, как показано
    fees_included: bool | None = None   # FAI или «hors honoraires»
    area_m2: float | None = None        # жилая площадь
    land_m2: float | None = None        # участок
    rooms: int | None = None            # pièces
    bedrooms: int | None = None         # chambres

    commune_name: str = ""
    commune_code: str = ""              # код INSEE
    postcode: str = ""
    address: str = ""
    lat: float | None = None
    lon: float | None = None
    geo_precision: str = ""             # address | street | commune | none

    dpe: str = ""                       # A..G
    year_built: int | None = None
    has_terrace: bool | None = None
    has_pool: bool | None = None
    has_garage: bool | None = None
    condition_hint: str = ""            # что сказано о состоянии в тексте

    agency: str = ""
    agency_ref: str = ""

    photos: list[Photo] = field(default_factory=list)
    raw: dict = field(default_factory=dict)
    seen_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def key(self) -> str:
        """Стабильный идентификатор в рамках источника."""
        base = self.source_id or self.url
        return hashlib.sha1(f"{self.source}|{base}".encode()).hexdigest()[:20]

    def price_per_m2(self) -> float | None:
        if self.price and self.area_m2:
            return self.price / self.area_m2
        return None

    def as_dict(self) -> dict:
        d = asdict(self)
        d["photos"] = [asdict(p) for p in self.photos]
        return d
