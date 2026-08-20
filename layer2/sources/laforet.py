"""Адаптер Laforêt — ещё одна сеть агентств.

Ссылка карточки говорящая, коммуна и тип объекта берутся прямо из неё:

    /agence-immobiliere/macon/acheter/prisse/maison-5-pieces-1234

Поэтому участки, магазины и «fonds de commerce» отсеиваются, не открывая
страницу: в выдаче агентства их обычно больше половины.
"""
from __future__ import annotations

import re

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, own_section, register, text_of, unescape

BASE = "https://www.laforet.com"

# Агентства сети рядом с нашими зонами.
AGENCIES = ["macon", "belleville-en-beaujolais", "villefranche-sur-saone",
            "cluny", "tournus", "bourg-en-bresse"]

CARD_RE = re.compile(
    r"/agence-immobiliere/(?P<agency>[a-z0-9-]+)/acheter/(?P<commune>[a-z0-9-]+)/"
    r"(?P<kind>maison|appartement|terrain|immeuble|local-commercial|fonds-de-commerce)"
    r"[a-z0-9-]*-(?P<id>\d{3,})", re.I)

META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:[\w:]+)["\'][^>]*content=["\']([^"\']*)', re.I)


def meta_tags(html: str) -> dict:
    return {k.lower(): unescape(v) for k, v in META_RE.findall(html)}


def parse_url(url: str) -> dict | None:
    m = CARD_RE.search(url)
    if not m:
        return None
    d = m.groupdict()
    d["commune_name"] = d["commune"].replace("-", " ").title()
    return d


@register
class Laforet(Source):
    name = "laforet"
    transport = "browser"

    def search_urls(self) -> list[str]:
        return [f"{BASE}/agence-immobiliere/{a}/acheter" for a in AGENCIES]

    def parse_list(self, page: str, url: str) -> list[str]:
        out = []
        for m in CARD_RE.finditer(page):
            info = parse_url(m.group(0))
            if not info or info["kind"] not in ("maison", "immeuble"):
                continue
            out.append(BASE + m.group(0))
        return sorted(set(out))

    def parse_listing(self, page: str, url: str) -> Listing | None:
        info = parse_url(url) or {}
        meta = meta_tags(page)
        title = meta.get("og:title", "")
        page_full = page
        page = own_section(page)
        body = text_of(page)
        desc = _description(page) or meta.get("og:description", "")
        own = f"{title} {desc}"

        price = N.price(title) or N.price(meta.get("og:description", "")) or N.price(body[:2500])
        if not price:
            return None

        return Listing(
            source=self.name, url=url, source_id=info.get("id", ""),
            title=re.sub(r"\s*[|-]\s*Laforêt.*$", "", title).strip() or f"Maison {info.get('commune_name','')}",
            description=desc, price=price,
            fees_included=N.fees_included(own),
            area_m2=N.area_m2(title) or N.area_m2(own) or N.area_m2(body),
            land_m2=N.land_m2(own) or N.land_m2(body),
            rooms=N.rooms(title) or N.rooms(own),
            bedrooms=N.bedrooms(own),
            commune_name=info.get("commune_name", ""),
            dpe=N.dpe(own) or N.dpe(body),
            has_terrace=N.feature(own, "has_terrace"),
            has_pool=N.feature(own, "has_pool"),
            has_garage=N.feature(own, "has_garage"),
            condition_hint=N.condition_hint(own),
            agency="Laforêt",
            photos=[Photo(url=u, order=i)
                    for i, u in enumerate(_images(page_full, info.get("id", ""))[:12])],
            raw={"og_title": title},
        )


JUNK = re.compile(r"cookie|donn[ée]es personnelles|newsletter|RGPD|mentions l[ée]gales"
                  r"|frais de notaire|politique de confidentialit", re.I)


def _description(html: str) -> str:
    best = ""
    for m in re.finditer(r"<(div|section|article|p)[^>]*>(.*?)</\1>", html, re.S | re.I):
        txt = text_of(m.group(2))
        if not (120 < len(txt) < 4000) or JUNK.search(txt):
            continue
        if txt.count(".") < len(txt) / 400:
            continue
        if len(txt) > len(best):
            best = txt
    return best


def _images(html: str, listing_id: str) -> list[str]:
    """Снимки объявления. Обратный слэш исключаем: ссылки бывают в
    экранированном JSON, и URL с «\\» на конце отдаёт ошибку."""
    seen, urls = set(), []
    for u in re.findall(r'https://[^\s"\'<>\\]+\.(?:jpe?g|webp)(?:\?[^\s"\'<>\\]*)?', html, re.I):
        low = u.lower()
        if any(b in low for b in ("logo", "icon", "avatar", "placeholder", "sprite",
                                  "agence", "picto")):
            continue
        if listing_id and listing_id not in u:
            continue
        key = re.sub(r"[?&](w|h|width|height|size)=[^&]*", "", u)
        if key in seen:
            continue
        seen.add(key)
        urls.append(u)
    return urls
