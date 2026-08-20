"""Универсальный адаптер по разметке schema.org.

Сайты, которым важно попадать в Google, кладут в страницу JSON-LD с типами
RealEstateListing / Product / Offer / Residence. Это ровно те же данные, что
показаны человеку, только уже структурированные, — и один разбор работает для
всех таких сайтов сразу, без подгонки под каждую вёрстку.

Там, где разметки нет, остаётся текстовый разбор через normalize.py.
"""
from __future__ import annotations

import json
import re

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, absolutize, find_images, register, text_of

LD_RE = re.compile(r'(?is)<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>')

WANTED = {"realestatelisting", "product", "offer", "house", "residence",
          "singlefamilyresidence", "apartment", "accommodation"}


def json_ld_blocks(html: str) -> list[dict]:
    out = []
    for m in LD_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except Exception:
            continue
        out.extend(_flatten(data))
    return out


def _flatten(node) -> list[dict]:
    """@graph и массивы разворачиваем, чтобы не гадать о форме документа."""
    res = []
    if isinstance(node, list):
        for n in node:
            res.extend(_flatten(n))
    elif isinstance(node, dict):
        if "@graph" in node:
            res.extend(_flatten(node["@graph"]))
        res.append(node)
    return res


def _types(block: dict) -> set[str]:
    t = block.get("@type") or block.get("type") or ""
    if isinstance(t, list):
        return {str(x).lower() for x in t}
    return {str(t).lower()}


def _price(block: dict):
    for path in (("offers", "price"), ("offers", "lowPrice"), ("price",)):
        cur = block
        for k in path:
            cur = cur.get(k) if isinstance(cur, dict) else None
            if cur is None:
                break
        if isinstance(cur, list) and cur:
            cur = cur[0]
        if isinstance(cur, dict):
            cur = cur.get("price")
        if cur is not None:
            try:
                return int(float(str(cur).replace(" ", "").replace(",", ".")))
            except ValueError:
                pass
    return None


def _area(block: dict):
    fs = block.get("floorSize") or block.get("size")
    if isinstance(fs, dict):
        v = fs.get("value") or fs.get("maxValue")
        if v is not None:
            try:
                return float(str(v).replace(",", "."))
            except ValueError:
                return None
    return None


def _images(block: dict) -> list[str]:
    img = block.get("image") or block.get("photo") or []
    if isinstance(img, (str, dict)):
        img = [img]
    out = []
    for i in img:
        if isinstance(i, dict):
            i = i.get("url") or i.get("contentUrl")
        if isinstance(i, str):
            out.append(i)
    return out


def _address(block: dict) -> dict:
    a = block.get("address")
    if isinstance(a, list) and a:
        a = a[0]
    if not isinstance(a, dict):
        return {}
    return {
        "street": a.get("streetAddress") or "",
        "city": a.get("addressLocality") or "",
        "postcode": str(a.get("postalCode") or ""),
    }


def from_html(html: str, url: str, source_name: str) -> Listing | None:
    """Собирает объявление из разметки, добирая недостающее из текста."""
    blocks = [b for b in json_ld_blocks(html) if _types(b) & WANTED]
    text = text_of(html)

    block = {}
    for b in blocks:
        if _price(b) or _area(b):
            block = b
            break
    if not block and blocks:
        block = blocks[0]

    title = str(block.get("name") or "")[:300]
    desc = str(block.get("description") or "")
    body = f"{title} {desc}" if desc else text[:4000]

    price = _price(block) or N.price(text)
    area = _area(block) or N.area_m2(body) or N.area_m2(text)
    if not price and not area:
        return None                      # страница не про объявление

    addr = _address(block)
    geo = block.get("geo") if isinstance(block.get("geo"), dict) else {}

    imgs = [absolutize(url, u) for u in _images(block)] or find_images(html, url)

    ls = Listing(
        source=source_name,
        url=url,
        source_id=str(block.get("sku") or block.get("productID") or block.get("@id") or ""),
        title=title or text[:120],
        description=desc or text[:2000],
        price=price,
        fees_included=N.fees_included(body) or N.fees_included(text),
        area_m2=area,
        land_m2=N.land_m2(body) or N.land_m2(text),
        rooms=N.rooms(body) or N.rooms(text),
        bedrooms=N.bedrooms(body) or N.bedrooms(text),
        commune_name=addr.get("city", ""),
        postcode=addr.get("postcode", ""),
        address=addr.get("street", ""),
        lat=_f(geo.get("latitude")),
        lon=_f(geo.get("longitude")),
        dpe=N.dpe(body) or N.dpe(text),
        has_terrace=N.feature(body, "has_terrace"),
        has_pool=N.feature(body, "has_pool"),
        has_garage=N.feature(body, "has_garage"),
        condition_hint=N.condition_hint(body),
        photos=[Photo(url=u, order=i) for i, u in enumerate(imgs[:12])],
        raw={"ld_types": sorted(_types(block)) if block else []},
    )
    if ls.lat and ls.lon:
        ls.geo_precision = "address"
    return ls


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


@register
class GenericJsonLd(Source):
    """Работает с любым сайтом, где есть разметка schema.org.

    Конкретные сайты подключаются подклассами: у них меняются только
    search_urls и способ достать ссылки со страницы выдачи.
    """
    name = "jsonld"

    def parse_listing(self, page: str, url: str) -> Listing | None:
        return from_html(page, url, self.name)
