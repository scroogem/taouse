"""Базовый адаптер источника и реестр.

Разведка показала неприятное: и порталы, и сайты агентств рендерятся
JavaScript'ом — в HTML, который отдаёт сервер, объявлений нет вообще. Поэтому
у адаптера есть транспорт:

    http    — обычный запрос. Работает там, где данные приходят в HTML,
              в JSON-LD или отдельным JSON-запросом.
    browser — страница открывается в настоящем Chrome и читается уже
              отрендеренной. Медленно, зато видит то же, что человек.

Адаптер отвечает только за «достать и разобрать». Дедупликация, геокод,
оценка места и хранение — общие для всех и живут в pipeline.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..models import Listing

REGISTRY: dict[str, type["Source"]] = {}


def register(cls):
    REGISTRY[cls.name] = cls
    return cls


@dataclass
class SearchArea:
    """Что искать. Формируется из whitelist Слоя 1."""
    commune_codes: list[str]
    commune_names: list[str]
    postcodes: list[str]
    max_price: int
    min_area: int
    min_bedrooms: int
    min_place_score: float = 0


class Source:
    name = "base"
    transport = "http"          # http | browser
    respects_robots = True
    # Насколько часто вообще имеет смысл ходить: это семейный поиск,
    # а не мониторинг рынка. Раз в несколько часов более чем достаточно.
    min_interval_min = 180

    def __init__(self, area: SearchArea, fetcher):
        self.area = area
        self.fetch = fetcher     # callable(url) -> str (HTML) либо dict

    def search_urls(self) -> list[str]:
        """Страницы выдачи, которые нужно обойти."""
        raise NotImplementedError

    def parse_list(self, page: str, url: str) -> list[str]:
        """Ссылки на объявления со страницы выдачи."""
        raise NotImplementedError

    def parse_listing(self, page: str, url: str) -> Listing | None:
        """Страница объявления -> нормализованное объявление."""
        raise NotImplementedError

    def prepare_page(self, page):
        """Действия в браузере до чтения разметки.

        Нужно там, где часть содержимого прячется за кнопкой: например,
        полная галерея открывается только по «Voir plus de photos».
        """
        return None


# ---------------------------------------------------------------------------
# Помощники, полезные почти всем адаптерам
# ---------------------------------------------------------------------------

def unescape(s: str) -> str:
    """HTML-сущности в текст.

    Без этого «260 000&nbsp;€» в метатеге не распознаётся как цена: между
    разрядами стоит не пробел, а буквальная строка «&nbsp;».
    """
    import html as _html
    return _html.unescape(s or "")


_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"[  \s]+")


def text_of(html: str) -> str:
    """Грубое извлечение текста — для регулярок из normalize.py этого хватает."""
    html = re.sub(r"(?is)<(script|style|noscript)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"(?i)<br\s*/?>|</p>|</div>|</li>", "\n", html)
    return _WS.sub(" ", _TAG.sub(" ", unescape(html))).strip()


# Всё, что идёт после этих слов, относится к чужим объявлениям: блоки
# «похожие», «рядом», «недавно просмотренные». Их данные утекали в карточку —
# отсюда и «5 спален» у дома с тремя, и фотографии чужих домов.
# Маркеры должны быть узкими. «À proximité» сюда не годится: это ходовая
# фраза самих описаний («à proximité des commerces»), и по ней страница
# резалась до описания — в карточку попадала рекламная строка вместо текста.
OTHER_LISTINGS = re.compile(
    r"annonces?\s+similaires|biens?\s+similaires|nos\s+autres\s+biens"
    r"|vous\s+pourriez\s+aussi\s+aimer|autres\s+annonces"
    r"|derni[èe]rement\s+consult[ée]|recherches\s+similaires"
    r"|ces\s+biens\s+pourraient", re.I)


def own_section(html: str) -> str:
    """Часть страницы, относящаяся к самому объявлению."""
    m = OTHER_LISTINGS.search(html)
    return html[:m.start()] if m and m.start() > 2000 else html


def absolutize(base: str, href: str) -> str:
    from urllib.parse import urljoin
    return urljoin(base, href)


def find_images(html: str, base: str, patterns: tuple[str, ...] = ()) -> list[str]:
    """Ссылки на фотографии. Мелочь и иконки отбрасываем."""
    urls = []
    for m in re.finditer(r'(?:src|data-src|data-lazy|content)=["\']([^"\']+\.(?:jpe?g|png|webp)[^"\']*)',
                         html, re.I):
        u = absolutize(base, m.group(1))
        low = u.lower()
        if any(bad in low for bad in ("logo", "icon", "sprite", "placeholder", "avatar",
                                      "pixel", "blank", "loader")):
            continue
        if patterns and not any(p in low for p in patterns):
            continue
        if u not in urls:
            urls.append(u)
    return urls
