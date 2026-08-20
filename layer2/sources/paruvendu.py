"""Адаптер ParuVendu.fr — агрегатор агентств.

Парсит серверный HTML (без JS). Цена и основные данные берутся из
meta-тегов и JavaScript dataLayer — в видимом тексте их нет.
"""
from __future__ import annotations

import json
import re

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, register, text_of, unescape, find_images

BASE = "https://www.paruvendu.fr"

SEARCH_CITIES = [
    ("macon", "71000"),
    ("cluny", "71250"),
    ("saint-amour-bellevue", "71570"),
    ("fleurie", "69820"),
    ("belleville-en-beaujolais", "69220"),
    ("villefranche-sur-saone", "69000"),
    ("tournus", "71290"),
    ("charnay-les-macon", "71100"),
    ("romaneche-thorins", "69510"),
    ("germolles-sur-grosne", "69730"),
    ("villié-morgon", "69910"),
    ("morgon", "69170"),
    ("pierreclos", "71700"),
    ("clessé", "71260"),
    ("uze", "71120"),
]


def _search_urls() -> list[str]:
    urls = []
    for city, cp in SEARCH_CITIES:
        urls.append(
            f"{BASE}/immobilier/vente/maison/{city}-{cp}/"
            f"?price=50000-400000"
        )
    return urls


DETAIL_RE = re.compile(
    r'/immobilier/vente/maison/(\d{8,}[A-Z0-9]+)', re.I)


def _extract_from_meta(html: str) -> dict:
    """Извлечь price/area/rooms/bedrooms/commune из meta-тегов и dataLayer."""
    data = {}

    # Meta description: "...maison à vendre de 154m2 au prix de 399 000€..."
    meta_m = re.search(
        r'<meta[^>]+name="description"[^>]+content="([^"]+)"', html, re.I)
    if meta_m:
        desc = unescape(meta_m.group(1))
        p = re.search(r'(\d[\d\s]*\d)\s*€', desc)
        if p:
            try:
                data["price"] = int(p.group(1).replace(" ", ""))
            except ValueError:
                pass
        a = re.search(r'(\d+)\s*m[²2]', desc)
        if a:
            try:
                data["area"] = float(a.group(1))
            except ValueError:
                pass

    # dataLayer: 'gtm_var_prix':'399000','gtm_var_id_pa':'1294203342',...
    dl_m = re.search(r"dataLayer\s*=\s*(\[.*?\]);", html, re.S)
    if dl_m:
        try:
            raw = dl_m.group(1).replace("'", '"')
            dl = json.loads(raw)
            if dl and isinstance(dl, list) and isinstance(dl[0], dict):
                d = dl[0]
                if "gtm_var_prix" in d:
                    try:
                        data["price"] = int(d["gtm_var_prix"])
                    except (ValueError, TypeError):
                        pass
                if "gtm_lib_ville" in d:
                    data["commune"] = d["gtm_lib_ville"]
        except (json.JSONDecodeError, KeyError):
            pass

    # Targeting: 'nbpces': ['60'],'surfmax': ['154'],'DPE': ['C']
    targeting_m = re.search(
        r"setTargeting\('nbpces',\s*\['(\d+)'\]\)", html)
    if targeting_m:
        try:
            data["rooms"] = int(targeting_m.group(1)) // 10
        except ValueError:
            pass

    targeting_s = re.search(
        r"setTargeting\('surfmax',\s*\['(\d+)'\]\)", html)
    if targeting_s:
        try:
            data["area"] = float(targeting_s.group(1))
        except ValueError:
            pass

    targeting_d = re.search(
        r"setTargeting\('DPE',\s*\['([A-G])'\]\)", html)
    if targeting_d:
        data["dpe"] = targeting_d.group(1)

    return data


@register
class ParuvenduFr(Source):
    name = "paruvendu"
    transport = "http"

    def search_urls(self) -> list[str]:
        return _search_urls()

    def parse_list(self, page: str, url: str) -> list[str]:
        out = []
        seen = set()
        for m in DETAIL_RE.finditer(page):
            uid = m.group(1)
            if uid in seen:
                continue
            seen.add(uid)
            around = page[max(0, m.start() - 2000):m.end() + 2000]
            if not re.search(r"\b[Mm]aison\b|\b[Vv]illa\b", around):
                continue
            detail = BASE + m.group(0)
            if detail not in out:
                out.append(detail)
        return out

    def prepare_page(self, page):
        return None

    def parse_listing(self, page: str, url: str) -> Listing | None:
        meta = _extract_from_meta(page)
        price = meta.get("price")
        if not price:
            return None

        title_m = re.search(r"<title>([^<]+)</title>", page, re.I)
        title_raw = unescape(title_m.group(1).strip()) if title_m else ""
        title = re.sub(r"\s*[-|].*paruvendu.*$", "", title_raw, flags=re.I).strip()

        area = meta.get("area")
        rooms = meta.get("rooms")
        bedrooms = N.bedrooms(title + " " + text_of(page)[:2000])
        commune = meta.get("commune", "")

        photos = []
        for i, u in enumerate(find_images(page, url,
                patterns=("paruvendu", "photo", "annonce"))[:12]):
            photos.append(Photo(url=u, order=i))

        if not photos:
            for i, u in enumerate(re.findall(
                    r'https?://img\.paruvendu\.fr/[^\s"\'<>\\]+\.(?:jpe?g|png|webp)',
                    page, re.I)[:12]):
                photos.append(Photo(url=u, order=i))

        body = text_of(page)[:3000]

        desc_m = re.search(
            r'<meta[^>]+name="description"[^>]+content="([^"]+)"', page, re.I)
        desc = unescape(desc_m.group(1)) if desc_m else title

        agency = ""
        agency_m = re.search(
            r'Agence immobilière\s*(?:à|:)\s*([A-Z][\w\s\-&]+?)(?:\s*\(|\s*$|\s*Agence)',
            body, re.I)
        if agency_m:
            agency = agency_m.group(1).strip()[:60]

        return Listing(
            source="paruvendu", url=url,
            title=title,
            description=desc[:2000],
            price=price,
            area_m2=area,
            land_m2=N.land_m2(body),
            rooms=rooms,
            bedrooms=bedrooms,
            commune_name=commune,
            has_terrace=N.feature(body, "has_terrace"),
            has_pool=N.feature(body, "has_pool"),
            has_garage=N.feature(body, "has_garage"),
            condition_hint=N.condition_hint(body),
            dpe=meta.get("dpe") or N.dpe(body),
            agency=agency or "ParuVendu",
            photos=photos,
        )
