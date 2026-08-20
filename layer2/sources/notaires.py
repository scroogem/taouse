"""Адаптер immobilier.notaires.fr — annonces notariales.

Источник: API immobilier.notaires.fr (публичный JSON, без ключа).
Преимущества: структурированные данные, фото, DPE, official notary listings.
Транспорт: http (обычный запрос, данные в JSON).

Особенность: API уже содержит все данные (price, area, rooms, bedrooms,
commune, photo). Детальные страницы — Angular SPA, данные в HTML нет.
Адаптер берёт данные напрямую из API, без запроса детальных страниц.
"""
from __future__ import annotations

import json

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, register

BASE = "https://www.immobilier.notaires.fr"
API = f"{BASE}/pub-services/inotr-www-annonces/v1/annonces"

DEPARTMENTS = ["71", "69", "01"]


@register
class NotairesFr(Source):
    name = "notaires"
    transport = "http"

    def __init__(self, area, fetcher):
        super().__init__(area, fetcher)
        self._cache: dict[str, Listing] = {}

    def search_urls(self) -> list[str]:
        urls = []
        for dept in DEPARTMENTS:
            for page in range(1, 8):
                urls.append(
                    f"{API}?departement={dept}&typeBien=MAI"
                    f"&typeTransaction=VENTE&page={page}&parPage=20"
                )
        return urls

    def parse_list(self, page: str, url: str) -> list[str]:
        try:
            data = json.loads(page)
        except (json.JSONDecodeError, TypeError):
            return []

        out = []
        for a in data.get("annonceResumeDto", []):
            if a.get("typeBien") != "MAI":
                continue
            if a.get("typeTransaction") not in ("VENTE", "VNI"):
                continue
            detail_url = a.get("urlDetailAnnonceFr", "")
            if not detail_url:
                continue
            listing = _from_api(a, detail_url)
            if listing:
                self._cache[detail_url] = listing
                out.append(detail_url)
        return out

    def prepare_page(self, page):
        return None

    def parse_listing(self, page: str, url: str) -> Listing | None:
        if url in self._cache:
            return self._cache.pop(url)
        return None


def _from_api(a: dict, url: str) -> Listing | None:
    price = a.get("prixAffiche")
    if price:
        try:
            price = int(float(price))
        except (ValueError, TypeError):
            price = None
    else:
        price = None

    if not price or price <= 0:
        return None

    area = a.get("surface")
    if area:
        try:
            area = float(area)
        except (ValueError, TypeError):
            area = None
    else:
        area = None

    desc = a.get("descriptionFr", "") or ""
    title = desc.split("\n")[0][:120] if desc else ""

    text = f"{title} {desc}"
    rooms = a.get("nbPieces") or N.rooms(text)
    bedrooms = a.get("nbChambres") or N.bedrooms(text)

    commune = a.get("communeNom", "")
    if not commune:
        commune = a.get("localiteNom", "").replace("MACON", "Mâcon")

    photos = []
    main_photo = a.get("urlPhotoPrincipale", "")
    if main_photo:
        photos.append(Photo(url=main_photo, order=0))

    land = a.get("surfaceTerrain")
    if land:
        try:
            land = float(land)
        except (ValueError, TypeError):
            land = None
    else:
        land = None

    return Listing(
        source="notaires", url=url,
        title=title,
        description=desc,
        price=price,
        area_m2=area,
        land_m2=land,
        rooms=rooms,
        bedrooms=bedrooms,
        commune_name=commune,
        has_terrace=N.feature(text, "has_terrace"),
        has_pool=N.feature(text, "has_pool"),
        has_garage=N.feature(text, "has_garage"),
        condition_hint=N.condition_hint(text),
        dpe=N.dpe(text),
        agency="Notaire",
        photos=photos,
    )
