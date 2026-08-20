"""Разбор французских объявлений: цены, площади, комнаты, признаки.

Всё это приходит текстом в десятке форматов — «349 000 €», «349000€ FAI»,
«120 m²», «120m2», «T4», «4 pièces». Держим разбор в одном месте, чтобы
адаптеры источников оставались тонкими.
"""
from __future__ import annotations

import re
import unicodedata

# --- цена ------------------------------------------------------------------
_PRICE = re.compile(r"(\d[\d\s  .,]{2,})\s*(?:€|eur|euros)", re.I)
_FAI = re.compile(r"\b(f\.?a\.?i\.?|frais\s+d.agence\s+inclus|honoraires\s+inclus"
                  r"|charge\s+vendeur)\b", re.I)
_HORS = re.compile(r"\b(hors\s+honoraires|honoraires\s+(?:à\s+la\s+)?charge\s+"
                   r"(?:de\s+l.)?acqu[ée]reur|hors\s+frais)\b", re.I)


def strip_spaces(s: str) -> str:
    """Убирает все виды пробелов, которыми французы делят разряды.

    Кроме обычного, встречаются U+00A0 (nbsp), U+202F (narrow nbsp) и
    U+2009 (thin space). Из-за последнего «220 000 €» на safti.fr долго не
    распознавалось как цена: визуально пробел, а для регулярки — нет.
    """
    for ch in (" ", " ", " ", " ", " "):
        s = s.replace(ch, "")
    return s


def price(text: str) -> int | None:
    """Цена объявления.

    Только явная сумма с символом валюты. Раньше был запасной вариант «любое
    пятизначное число», и на нём система принимала почтовый индекс за цену:
    «Chénas (69840)» становилось домом за 69 840 €, а такие дома всплывали
    первыми как самые дешёвые.
    """
    if not text:
        return None
    m = _PRICE.search(text)
    if not m:
        return None
    raw = strip_spaces(m.group(1))
    # французский формат: точка/пробел — разряды, запятая — дробь
    raw = raw.replace(".", "").split(",")[0]
    try:
        v = int(raw)
    except ValueError:
        return None
    return v if 10_000 <= v <= 5_000_000 else None


def fees_included(text: str) -> bool | None:
    """FAI ли цена. Важно для дедупликации: у одного дома цены разойдутся на 3-6%."""
    if not text:
        return None
    if _HORS.search(text):
        return False
    if _FAI.search(text):
        return True
    return None


# --- площади и комнаты -----------------------------------------------------
# число с французскими разделителями разрядов: «1 200», «1.200», «1 200,5»
# Число не должно начинаться сразу после буквы или цифры, иначе «T6 210m2»
# читается как «6 210» м² — пробел принимается за разделитель разрядов.
_NUM = r"(?<![\w.,])(?:\d{1,3}(?:[\s  .]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)"
_AREA = re.compile(rf"({_NUM})\s*(?:m²|m2|m\s?carr[ée]s?|mètres?\s+carr[ée]s?)", re.I)
_LAND = re.compile(rf"(?:terrain|parcelle|jardin)[^.\d]{{0,30}}({_NUM})\s*(?:m²|m2|ha\b)", re.I)
_LAND_HA = re.compile(rf"(?:terrain|parcelle)[^.\d]{{0,30}}({_NUM})\s*ha\b", re.I)
# «850 m² de terrain» — то же самое, но слово стоит после числа
# Предлог обязателен: «850 m² DE terrain» — это про участок, а вот
# «210 m2 terrain de 1,5 ha» — жильё, у участка тут своё число.
_LAND_POST = re.compile(
    rf"({_NUM})\s*(?:m²|m2)\s+(?:de\s+|d.)(?:terrain|jardin|parcelle)", re.I)
_LAND_POST_HA = re.compile(rf"({_NUM})\s*ha\s+(?:de\s+|d.)(?:terrain|jardin|parcelle)", re.I)
_NOT_LIVING = ("terrain", "parcelle", "jardin", "cave", "garage", "grange",
               "d[ée]pendance", "combles", "sous-sol")
_ROOMS = re.compile(r"(\d{1,2})\s*(?:pi[èe]ces?|p\.\b)|(?:^|\W)T\s?(\d)\b", re.I)
_BEDROOMS = re.compile(r"(\d{1,2})\s*chambres?", re.I)


def _num(s: str) -> float:
    s = strip_spaces(s)
    # точка тут разделитель разрядов («1.200»), а запятая — дробная часть
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(?:\.\d{3})+", s):
        s = s.replace(".", "")
    return float(s)


def area_m2(text: str) -> float | None:
    if not text:
        return None
    best = None
    for m in _AREA.finditer(text):
        v = _num(m.group(1))
        before = text[max(0, m.start() - 40):m.start()].lower()
        after = text[m.end():m.end() + 30].lower()
        # слово-маркер может стоять и до числа, и после него
        if any(re.search(w, before) for w in _NOT_LIVING):
            continue
        if re.match(r"\s*(?:de\s+|d.)(?:" + "|".join(_NOT_LIVING) + ")", after):
            continue
        if 20 <= v <= 1000 and (best is None or v > best):
            best = v
    return best


def land_m2(text: str) -> float | None:
    if not text:
        return None
    for pat in (_LAND_HA, _LAND_POST_HA):
        m = pat.search(text)
        if m:
            return _num(m.group(1)) * 10_000
    m = _LAND.search(text) or _LAND_POST.search(text)
    if m:
        v = _num(m.group(1))
        if "ha" in m.group(0).lower():
            v *= 10_000
        return v if 50 <= v <= 500_000 else None
    return None


def rooms(text: str) -> int | None:
    if not text:
        return None
    m = _ROOMS.search(text)
    if not m:
        return None
    v = m.group(1) or m.group(2)
    try:
        n = int(v)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 20 else None


def bedrooms(text: str) -> int | None:
    if not text:
        return None
    m = _BEDROOMS.search(text)
    if not m:
        return None
    n = int(m.group(1))
    return n if 1 <= n <= 15 else None


# --- признаки --------------------------------------------------------------
FEATURES = {
    "has_terrace": r"\bterrasse[s]?\b",
    "has_pool": r"\bpiscine\b",
    "has_garage": r"\b(garage|box\s+ferm[ée])\b",
}
_NEGATED = r"(?:sans|pas\s+de|aucune?)\s+"


def feature(text: str, name: str) -> bool | None:
    pat = FEATURES.get(name)
    if not pat or not text:
        return None
    if re.search(_NEGATED + pat, text, re.I):
        return False
    return True if re.search(pat, text, re.I) else None


# --- состояние -------------------------------------------------------------
# Коды, а не готовый текст: интерфейс двуязычный, и русское «нужен ремонт»
# в французской карточке выглядит ошибкой.
CONDITION_WORDS = [
    ("needs_work", r"\b(à\s+r[ée]nover|travaux\s+[àa]\s+pr[ée]voir|gros\s+œuvre"
                   r"|rafra[îi]chir|[àa]\s+rafra[îi]chissement|restaurer)\b"),
    ("renovated", r"\b(r[ée]nov[ée]e?|refait[e]?\s+[àa]\s+neuf|remis\s+au\s+go[ûu]t)\b"),
    ("good_state", r"\b(bon\s+[ée]tat|excellent\s+[ée]tat|tr[èe]s\s+bon\s+[ée]tat)\b"),
    ("recent", r"\b(neuf|neuve|r[ée]cent[e]?)\b"),
]


def condition_hint(text: str) -> str:
    if not text:
        return ""
    found = [name for name, pat in CONDITION_WORDS if re.search(pat, text, re.I)]
    return ",".join(found)


_DPE = re.compile(r"\bDPE\W{0,12}([A-G])\b|classe\s+[ée]nerg[ée]tique\W{0,12}([A-G])\b", re.I)


def dpe(text: str) -> str:
    if not text:
        return ""
    m = _DPE.search(text)
    if not m:
        return ""
    return (m.group(1) or m.group(2) or "").upper()


# --- текст для сравнения ---------------------------------------------------
def slug(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()
