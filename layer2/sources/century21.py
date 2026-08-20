"""Адаптер Century 21.

Отличается от прочих: в ссылке нет ни коммуны, ни типа объекта —
только числовой идентификатор (/trouver_logement/detail/14987480342/).
Зато они есть в тексте карточки на странице выдачи:

    «GRIEGES 01  245 000 €  83 m2 , Maison , 4 pcs»

Поэтому отбираем по тексту карточки, а коммуну потом всё равно перепроверяем
по описанию — как и у остальных источников.
"""
from __future__ import annotations

import re

from .. import normalize as N
from ..models import Listing, Photo
from .base import Source, own_section, register, text_of, unescape

BASE = "https://www.century21.fr"

# Города, вокруг которых лежат наши зоны.
SEARCH_CITIES = ["macon", "cluny", "belleville-en-beaujolais",
                 "villefranche-sur-saone", "tournus", "charnay-les-macon",
                 "romaneche-thorins", "saint-amour-bellevue"]

DETAIL_RE = re.compile(r"/trouver_logement/detail/(?P<id>\d{6,})/?", re.I)
META_RE = re.compile(
    r'<meta[^>]+(?:property|name)=["\'](og:[\w:]+)["\'][^>]*content=["\']([^"\']*)', re.I)


def meta_tags(html: str) -> dict:
    return {k.lower(): unescape(v) for k, v in META_RE.findall(html)}


@register
class Century21(Source):
    name = "century21"
    transport = "browser"

    def search_urls(self) -> list[str]:
        return [f"{BASE}/annonces/achat-maison/v-{c}/" for c in SEARCH_CITIES]

    def parse_list(self, page: str, url: str) -> list[str]:
        """Берём только карточки домов: тип написан рядом со ссылкой."""
        out = []
        for m in DETAIL_RE.finditer(page):
            around = page[max(0, m.start() - 1200):m.end() + 1200]
            if not re.search(r"\bMaison\b", around, re.I):
                continue
            if re.search(r"\b(Appartement|Terrain|Local|Immeuble|Parking)\b", around, re.I) \
                    and not re.search(r"Maison", around, re.I):
                continue
            out.append(f"{BASE}/trouver_logement/detail/{m.group('id')}/")
        return sorted(set(out))

    def prepare_page(self, page):
        """Пролистываем карусель фотографий.

        Кнопки «Voir plus» тут нет: снимки подгружаются по одному при нажатии
        стрелки «Image suivante». Без этого в разметке остаётся ровно один кадр.
        """
        nxt = page.query_selector("button[aria-label='Image suivante']")
        if not nxt:
            return
        for _ in range(14):
            try:
                nxt.click(timeout=2000)
                page.wait_for_timeout(450)
            except Exception:
                break

    def parse_listing(self, page: str, url: str) -> Listing | None:
        meta = meta_tags(page)
        title = meta.get("og:title", "")
        page_full = page
        page = own_section(page)
        body = text_of(page)
        # У Century 21 og:description — нормальный текст объявления, а вот
        # блоки страницы почти сплошь рекламные, поэтому порядок обратный
        # остальным адаптерам.
        desc = meta.get("og:description", "") or _description(page)
        own = f"{title} {desc}"

        price = (N.price(title) or N.price(meta.get("og:description", ""))
                 or _price_in(body))
        if not price:
            return None
        if not re.search(r"\bmaison\b", own + " " + body[:600], re.I):
            return None            # квартира или коммерция

        m = DETAIL_RE.search(url)
        return Listing(
            source=self.name, url=url, source_id=m.group("id") if m else "",
            title=re.sub(r"\s*[|-]\s*CENTURY\s*21.*$", "", title, flags=re.I).strip(),
            description=desc, price=price,
            fees_included=N.fees_included(own),
            area_m2=N.area_m2(title) or N.area_m2(own) or N.area_m2(body),
            land_m2=N.land_m2(own) or N.land_m2(body),
            rooms=N.rooms(title) or N.rooms(own),
            bedrooms=N.bedrooms(own),
            commune_name=_commune_from_title(title) or _commune(title, body),
            dpe=N.dpe(own) or N.dpe(body),
            has_terrace=N.feature(own, "has_terrace"),
            has_pool=N.feature(own, "has_pool"),
            has_garage=N.feature(own, "has_garage"),
            condition_hint=N.condition_hint(own),
            agency="Century 21",
            photos=[Photo(url=u, order=i) for i, u in enumerate(_images(page_full)[:12])],
            raw={"og_title": title},
        )


# Рядом с ценой стоят и номер объявления, и код департамента: «6298 245 000 €»,
# «01 230 000 €». Жадный разбор склеивал их в одно число и выдавал дома по
# 1 230 000 €. Поэтому берём максимум две группы разрядов — «245 000».
PRICE_RE = re.compile(r"((?:\d{1,3}[\s   ])?\d{3})\s*€")


def _price_in(body: str) -> int | None:
    for m in PRICE_RE.finditer(body):
        v = N.price(m.group(0))
        if v and 40_000 <= v <= 2_000_000:
            return v
    return None


def _commune_from_title(title: str) -> str:
    """«Maison à vendre - 4 pièces - 83 m2 - Grieges - 01 - RHONE-ALPES»."""
    parts = [p.strip() for p in title.split(" - ")]
    for i, p in enumerate(parts):
        if re.fullmatch(r"\d{2}", p) and i > 0:      # номер департамента
            return parts[i - 1].title()
    return ""


def _commune(title: str, body: str) -> str:
    """Коммуна из заголовка: «Maison 4 pièces GRIEGES (01290)»."""
    for src in (title, body[:400]):
        m = re.search(r"\b([A-ZÀ-Ÿ][A-ZÀ-Ÿ' \-]{2,30})\s*\(?\d{5}\)?", src)
        if m:
            return m.group(1).strip().title()
        m = re.search(r"\b([A-ZÀ-Ÿ]{3,}(?:[ \-][A-ZÀ-Ÿ]{2,}){0,3})\b", src)
        if m and m.group(1) not in ("CENTURY", "MAISON", "VENTE"):
            return m.group(1).title()
    return ""


# Кроме юридических блоков у Century 21 в разметку попадают рекламные врезки
# («Ventes Privées», «complétez votre profil») и куски кода Alpine.js —
# именно они уезжали в карточку вместо описания дома.
JUNK = re.compile(r"cookie|donn[ée]es personnelles|newsletter|RGPD|mentions l[ée]gales"
                  r"|frais de notaire|politique de confidentialit|capacit[ée] d.emprunt"
                  r"|ventes?\s+priv[ée]es|avant-premi[èe]re|compl[ée]ter\s+le\s+profil"
                  r"|souhaite\s+[êe]tre\s+informé|actualit[ée]s|pixel\s+de\s+suivi"
                  r"|votre\s+compte|setAttribute|x-title|\$el\b|=>", re.I)


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


def _images(html: str) -> list[str]:
    seen, urls = set(), []
    for u in re.findall(r'https://[^\s"\'<>\\]+\.(?:jpe?g|webp)(?:\?[^\s"\'<>\\]*)?', html, re.I):
        low = u.lower()
        if any(b in low for b in ("logo", "icon", "avatar", "placeholder", "sprite", "picto")):
            continue
        key = re.sub(r"[?&](w|h|width|height|size)=[^&]*", "", u)
        if key in seen:
            continue
        seen.add(key)
        urls.append(u)
    return urls
