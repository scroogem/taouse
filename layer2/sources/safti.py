"""Адаптер Safti — сети независимых агентов (mandataires).

Устроена удобнее Orpi: в выдаче уже есть всё для отсева — тип, площадь,
коммуна с индексом, цена, участок и число спален:

    «Maison - 5 pièces - 88m² Anglure-Sous-Dun (71170) 220 000 € Terrain 2 352m² bedroom 3»

Поэтому страницу конкретного дома открываем только для тех, кто прошёл фильтр
по коммуне и цене. Одна страница выдачи — это 24 объявления и один запрос.

Ссылка тоже говорящая: /annonces/achat/maison/<коммуна>-<индекс>/<id>
"""
from __future__ import annotations

import re

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, own_section, register, text_of, unescape

BASE = "https://www.safti.fr"

# Департаменты, в которых лежат наши зоны: Сона и Луара, Рона (Божоле), Эн.
DEPARTMENTS = [("saone-et-loire", "71"), ("rhone", "69"), ("ain", "01")]
MAX_PAGES = 10         # фильтр по коммунам режет почти всё, так что идём глубже

CARD_RE = re.compile(
    r"/annonces/achat/(?P<kind>maison|appartement|terrain)/"
    r"(?P<commune>[a-z0-9-]+?)-(?P<cp>\d{5})/(?P<id>\d+)", re.I)


def parse_url(url: str) -> dict | None:
    m = CARD_RE.search(url)
    if not m:
        return None
    d = m.groupdict()
    d["commune_name"] = d["commune"].replace("-", " ").title()
    return d


@register
class Safti(Source):
    name = "safti"
    transport = "browser"

    def search_urls(self) -> list[str]:
        out = []
        for slug, num in DEPARTMENTS:
            for page in range(1, MAX_PAGES + 1):
                out.append(f"{BASE}/annonces/achat/maison/{slug}-{num}?page={page}")
        return out

    def parse_list(self, page: str, url: str) -> list[str]:
        out = []
        for m in CARD_RE.finditer(page):
            info = parse_url(m.group(0))
            if not info or info["kind"] != "maison":
                continue
            if self.area.postcodes and info["cp"] not in self.area.postcodes:
                continue
            out.append(BASE + m.group(0))
        return sorted(set(out))

    def prepare_page(self, page):
        """Открываем полную галерею.

        В превью показывают пять кадров, остальные лежат за кнопкой
        «Voir plus de photos» и подгружаются по мере прокрутки уже внутри
        открытого окна.
        """
        for sel in ("button:has-text('Voir plus de photos')",
                    "button:has-text('photos')"):
            el = page.query_selector(sel)
            if not el:
                continue
            el.click()
            page.wait_for_timeout(2000)
            for _ in range(8):
                page.mouse.wheel(0, 1400)
                page.wait_for_timeout(500)
            return

    def parse_listing(self, page: str, url: str) -> Listing | None:
        info = parse_url(url) or {}
        meta = _meta(page)
        title = meta.get("og:title", "")
        # дальше работаем только со «своей» частью страницы
        page_own = own_section(page)
        body = text_of(page_own)
        desc = _description(page_own) or meta.get("og:description", "")
        own = f"{title} {desc}"

        price = N.price(title) or N.price(meta.get("og:description", "")) or _price_in(body)
        if not price:
            return None

        return Listing(
            source=self.name, url=url, source_id=info.get("id", ""),
            title=re.sub(r"\s*[|-]\s*SAFTI\s*$", "", title).strip() or f"Maison {info.get('commune_name','')}",
            description=desc,
            price=price,
            fees_included=N.fees_included(own),
            area_m2=N.area_m2(title) or _spec(body, 'Surface habitable') or N.area_m2(own),
            land_m2=N.land_m2(own) or N.land_m2(body),
            rooms=N.rooms(title) or N.rooms(own),
            bedrooms=_spec(body, 'Chambres') or N.bedrooms(desc),
            commune_name=info.get("commune_name", ""),
            postcode=info.get("cp", ""),
            dpe=N.dpe(own) or N.dpe(body),
            has_terrace=N.feature(own, "has_terrace"),
            has_pool=N.feature(own, "has_pool"),
            has_garage=N.feature(own, "has_garage"),
            condition_hint=N.condition_hint(own),
            agency="Safti",
            # Фотографии ищем по ВСЕЙ странице: окно галереи дописывается в
            # конец разметки, за блоком чужих объявлений, и обрезка его теряла.
            # Отбор по идентификатору объявления и так не пускает чужие кадры.
            photos=[Photo(url=u, order=i)
                    for i, u in enumerate(_images(page, info.get('id', ''))[:12])],
            raw={"og_title": title},
        )


META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:[\w:]+)["\'][^>]*content=["\']([^"\']*)', re.I)
META_RE2 = re.compile(
    r'<meta[^>]+content=["\']([^"\']*)["\'][^>]*(?:property|name)=["\'](og:[\w:]+)["\']', re.I)


def _meta(html: str) -> dict:
    out = {}
    for k, v in META_RE.findall(html):
        out.setdefault(k.lower(), unescape(v))
    for v, k in META_RE2.findall(html):
        out.setdefault(k.lower(), unescape(v))
    return out


def _price_in(body: str) -> int | None:
    """Цена из текста — но только первая крупная сумма рядом со словом о продаже.

    Ниже по странице идут «frais de notaire» и калькулятор кредита, их суммы
    брать нельзя.
    """
    head = body[:1500]
    for m in re.finditer(r"[\d\s  .]{4,}€", head):
        v = N.price(m.group(0))
        if v and v >= 40_000:
            return v
    return None


def _spec(body: str, label: str) -> float | int | None:
    """Значение из таблицы характеристик: «Chambres : 3», «Surface habitable : 138m²».

    Это единственный надёжный источник: в свободном тексте описания попадаются
    и «3 chambres», и «une chambre de 12 m²», а внизу страницы висят карточки
    чужих домов со своими цифрами.
    """
    m = re.search(label + r"\s*:?\s*(\d{1,4})", body, re.I)
    if not m:
        return None
    v = int(m.group(1))
    return v if 0 < v < 2000 else None


JUNK = re.compile(
    r"cookie|partenaires utilisent|donn[ée]es personnelles|newsletter|RGPD"
    r"|mentions l[ée]gales|frais de notaire|capacit[ée] d.emprunt"
    r"|politique de confidentialit", re.I)


def _description(html: str) -> str:
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


# Внутри разметки ссылки встречаются в экранированном JSON, поэтому обратный
# слэш обязательно исключать: URL с «\» на конце отдаёт 403, и снимок молча
# теряется — в карточке остаётся половина галереи.
PHOTO_RE = re.compile(
    r'https://cdn\.safti\.fr/bien-photo/[\d/]+/(?P<hash>[0-9a-f]{8,})/[^\s"\'<>\\]+',
    re.I)


def _images(html: str, listing_id: str) -> list[str]:
    """Только фотографии этого объявления.

    Путь содержит его идентификатор — так отсеиваются логотипы, портреты
    агентов и снимки соседних домов. Один и тот же кадр лежит в нескольких
    размерах (rn.jpg, rg_no…), поэтому берём по одному варианту на кадр.
    """
    seen, urls = set(), []
    for m in PHOTO_RE.finditer(html):
        u = m.group(0).replace("&amp;", "&")
        if listing_id and f"/{listing_id}/" not in u:
            continue
        h = m.group("hash")
        if h in seen:
            continue
        seen.add(h)
        urls.append(u)
    return urls
