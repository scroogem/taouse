"""Адаптер Orpi — сети из тысячи агентств с общей платформой.

Один разбор работает для любого их агентства, поэтому начинаем отсюда: в наших
зонах есть Orpi в Маконе, и добавить соседние — это одна строка в AGENCIES.

Данные берём из метатегов Open Graph, а не из вёрстки. Причина простая: разметку
страницы меняют при каждом редизайне, а og:title обязан оставаться разборчивым,
потому что им живут превью в соцсетях и поисковиках:

    og:title = "Maison Cluny  m² T-10 à vendre, 320 000 € | Orpi"

Ещё половина данных лежит в самом URL — тип сделки, тип объекта, число комнат,
коммуна и почтовый индекс:

    /annonce-vente-maison-t10-cluny-71250-0c49f486-...

Это позволяет отсеять неподходящее ДО загрузки страницы: квартиры, аренду и
чужие коммуны мы просто не открываем.
"""
from __future__ import annotations

import re

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, own_section, register, text_of, unescape

# Агентства сети в наших зонах. Список расширяется без правки кода.
AGENCIES = [
    ("gl.immobilier", "https://www.orpi.com/gl.immobilier/"),
    ("immobilierdelain", "https://www.orpi.com/immobilierdelain/"),
    ("vipbresse", "https://www.orpi.com/vipbresse/"),
    ("agencecentrale", "https://www.orpi.com/agencecentrale/"),
    ("beaujolaisimmobilier", "https://www.orpi.com/beaujolaisimmobilier/"),
    ("cluny", "https://www.orpi.com/clunyimmobilier/"),
]

URL_RE = re.compile(
    r"/annonce-(?P<deal>vente|location)-(?P<kind>maison|appartement|terrain|immeuble)"
    r"-t(?P<rooms>\d+)-(?P<commune>[a-z0-9-]+?)-(?P<cp>\d{5})-(?P<id>[0-9a-f-]{8,})",
    re.I)

OG_PRICE = re.compile(r"([\d  ]{4,})\s*€")
META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:[\w:]+|twitter:[\w:]+)["\'][^>]*content=["\']([^"\']*)',
    re.I)
META_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\'](og:[\w:]+)["\']',
    re.I)


def meta_tags(html: str) -> dict:
    out = {}
    for k, v in META_RE.findall(html):
        out.setdefault(k.lower(), unescape(v))
    for v, k in META_RE2.findall(html):
        out.setdefault(k.lower(), unescape(v))
    return out


def parse_url(url: str) -> dict | None:
    m = URL_RE.search(url)
    if not m:
        return None
    d = m.groupdict()
    d["commune_name"] = d["commune"].replace("-", " ").title()
    d["rooms"] = int(d["rooms"])
    return d


@register
class Orpi(Source):
    name = "orpi"
    transport = "browser"

    def search_urls(self) -> list[str]:
        return [url for _, url in AGENCIES]

    def parse_list(self, page: str, url: str) -> list[str]:
        """Ссылки на продажу домов в наших коммунах — остальное не открываем."""
        hrefs = set(re.findall(r'href=["\'](/annonce-[^"\'#?]+)', page))
        hrefs |= set(re.findall(r'href=["\'](https://www\.orpi\.com/annonce-[^"\'#?]+)', page))
        out = []
        for h in hrefs:
            full = h if h.startswith("http") else "https://www.orpi.com" + h
            info = parse_url(full)
            if not info or info["deal"] != "vente":
                continue
            if info["kind"] not in ("maison", "immeuble"):
                continue
            if self.area.postcodes and info["cp"] not in self.area.postcodes:
                continue
            out.append(full)
        return sorted(set(out))

    def parse_listing(self, page: str, url: str) -> Listing | None:
        info = parse_url(url)
        meta = meta_tags(page)
        title = meta.get("og:title", "")
        desc_meta = meta.get("og:description", "")
        # ниже по странице висят карточки чужих домов — их данные не наши
        page_full = page          # галерея живёт в конце разметки
        page = own_section(page)
        body = text_of(page)

        # Цена живёт в og:title. В тексте страницы полно других сумм —
        # налоги, расходы на отопление, комиссия, — и брать их нельзя.
        price = None
        m = OG_PRICE.search(title) or OG_PRICE.search(desc_meta)
        if m:
            price = N.price(m.group(0))
        if not price:
            return None

        desc = _description(page) or desc_meta
        # Признаки ищем в заголовке и описании. По всей странице нельзя:
        # там формы, футер и калькулятор ипотеки — «récente» и «piscine»
        # находятся в них, и дом получает свойства, которых у него нет.
        own = f"{title} {desc}"

        area = N.area_m2(title) or N.area_m2(own) or N.area_m2(body)
        land = N.land_m2(own) or N.land_m2(body)
        if land and area and land < area:
            land = None

        photos = []
        for i, u in enumerate(_images(page_full, meta, (info or {}).get('id', ''))):
            photos.append(Photo(url=u, order=i))

        ls = Listing(
            source=self.name, url=url,
            source_id=(info or {}).get("id", ""),
            title=re.sub(r"\s*\|\s*Orpi\s*$", "", title).strip(),
            description=desc,
            price=price,
            fees_included=N.fees_included(own),
            area_m2=area, land_m2=land,
            rooms=(info or {}).get("rooms") or N.rooms(own),
            bedrooms=N.bedrooms(own),
            commune_name=(info or {}).get("commune_name", ""),
            postcode=(info or {}).get("cp", ""),
            dpe=N.dpe(own),
            has_terrace=N.feature(own, "has_terrace"),
            has_pool=N.feature(own, "has_pool"),
            has_garage=N.feature(own, "has_garage"),
            condition_hint=N.condition_hint(own),
            agency="Orpi",
            photos=photos[:10],
            raw={"og_title": title},
        )
        return ls


def _images(html: str, meta: dict, listing_id: str = "") -> list[str]:
    """Ссылки на фотографии.

    Внимание: у CDN подписанные адреса (ci_sign=...). Обрезать query нельзя —
    без подписи отдаётся 401, и хэши фотографий не посчитаются, то есть
    отвалится главный признак для склейки дубликатов.
    """
    urls, seen = [], set()
    for u in re.findall(r'https://[a-z0-9.-]*cloudimg\.io/[^\s"\'<>\\]+', html, re.I):
        u = u.replace("&amp;", "&")
        if "ci_sign=" not in u:
            continue
        if listing_id and listing_id not in u:
            continue          # чужие снимки: агенты, соседние объявления
        key = re.sub(r"[?&](w|h|width|height|func|org_if_sml)=[^&]*", "", u)
        if key in seen:
            continue          # тот же кадр в другом размере
        seen.add(key)
        urls.append(u)
    if not urls and meta.get("og:image"):
        urls.append(meta["og:image"].replace("&amp;", "&"))
    return urls


# Юридические и маркетинговые блоки, которых на странице больше, чем описания:
# без этого фильтра «самым длинным текстом» оказывается политика обработки
# персональных данных, и она уезжает в карточку вместо рассказа о доме.
JUNK = re.compile(
    r"informations recueillies|trait[ée]es par|RGPD|cookie|newsletter|d[ée]sabonn"
    r"|politique de confidentialit|mentions l[ée]gales|capacit[ée] d.emprunt"
    r"|frais de notaire|je m.inscris|communications commerciales", re.I)


def _description(html: str) -> str:
    """Описание объявления — самый длинный осмысленный блок страницы."""
    best = ""
    for m in re.finditer(r"<(div|section|article|p)[^>]*>(.*?)</\1>", html, re.S | re.I):
        txt = text_of(m.group(2))
        if not (120 < len(txt) < 4000) or JUNK.search(txt):
            continue
        # У формы со списком стран длина как у описания, но это перечисление:
        # в настоящем тексте есть предложения, то есть точки.
        if txt.count(".") < len(txt) / 400:
            continue
        if len(txt) > len(best):
            best = txt
    return best
