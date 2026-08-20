"""Поиск одного и того же дома в объявлениях разных агентств.

Один дом легко висит у трёх агентств сразу: тексты переписаны, фотографии
пережаты и заклеймены логотипом, цены отличаются на комиссию. Ни один сигнал
поодиночке не надёжен, поэтому собираем несколько и связываем в граф.

    фото       — сильнейший сигнал. Агентства часто публикуют снимки
                 собственника, то есть буквально одни и те же кадры.
    атрибуты   — площадь ±2 м², те же комнаты, та же коммуна. Само по себе
                 слабо: типовых «120 м², 4 комнаты» в коммуне бывает несколько.
    цена       — с допуском ~8%: часть агентств показывает цену FAI
                 (с комиссией), часть — без неё, отсюда законное расхождение.
    текст      — Жаккар по 3-словным шинглам. Куски описаний выживают
                 переписывание («belle vue sur les vignes»).

Правило связи:
    совпали фото                                     -> дубликат (уверенно);
    фото есть у обоих, но не совпали                 -> нужен ещё и почти
                                                        совпадающий текст;
    у кого-то фото нет                               -> хватает цифр и текста.

Компонента связности графа = один физический дом.
"""
from __future__ import annotations

import itertools
from collections import defaultdict

from . import imagehash
from .normalize import slug

PHOTO_MAX_DIST = 8       # бит из 64 — уверенное совпадение кадра
PHOTO_MIN_PAIRS = 1      # сколько совпавших снимков достаточно
AREA_TOL = 2.0           # м²
LAND_TOL = 0.10          # участок: расхождение доли площади
PRICE_TOL = 0.08         # доля
TEXT_MIN_JACCARD = 0.30
TEXT_STRICT_JACCARD = 0.45   # когда фото не подтверждают совпадение
SHINGLE = 3


def shingles(text: str, n: int = SHINGLE) -> set[str]:
    words = slug(text).split()
    if len(words) < n:
        return set(words)
    return {" ".join(words[i:i + n]) for i in range(len(words) - n + 1)}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    return inter / (len(a) + len(b) - inter)


def photos_match(pa: list[dict], pb: list[dict]) -> tuple[bool, int]:
    """Сколько снимков совпало перцептивно."""
    hits = 0
    for x in pa:
        for y in pb:
            if (imagehash.distance(x.get("phash"), y.get("phash")) <= PHOTO_MAX_DIST
                    or imagehash.distance(x.get("dhash"), y.get("dhash")) <= PHOTO_MAX_DIST):
                hits += 1
                break
    return hits >= PHOTO_MIN_PAIRS, hits


def _attrs_match(a: dict, b: dict) -> bool:
    if a.get("commune_code") and b.get("commune_code"):
        if a["commune_code"] != b["commune_code"]:
            return False
    elif slug(a.get("commune_name", "")) != slug(b.get("commune_name", "")):
        return False

    aa, ab = a.get("area_m2"), b.get("area_m2")
    if aa and ab and abs(aa - ab) > AREA_TOL:
        return False
    if not (aa and ab):
        return False

    ra, rb = a.get("rooms"), b.get("rooms")
    if ra and rb and ra != rb:
        return False

    la, lb = a.get("land_m2"), b.get("land_m2")
    if la and lb and abs(la - lb) / max(la, lb) > LAND_TOL:
        return False
    return True


def _price_match(a: dict, b: dict) -> bool:
    pa, pb = a.get("price"), b.get("price")
    if not (pa and pb):
        return False
    return abs(pa - pb) / max(pa, pb) <= PRICE_TOL


def compare(a: dict, b: dict) -> dict | None:
    """Решение по паре. -> {method, confidence, details} либо None.

    Осторожность здесь важнее полноты. Лишний дубль в списке родители просто
    пролистают, а вот склеенные по ошибке разные дома означают, что один из
    них исчез из выдачи навсегда и никто об этом не узнает.

    Отсюда ключевое правило: если фотографии есть у обоих объявлений и ни
    одна не совпала — это довод ПРОТИВ склейки, и одних совпавших цифр
    («145 м², 5 комнат, та же цена») уже недостаточно: типовых домов в
    коммуне бывает несколько.
    """
    ph_ok, ph_hits = photos_match(a.get("photos") or [], b.get("photos") or [])
    both_have_photos = bool(a.get("photos")) and bool(b.get("photos"))
    at_ok = _attrs_match(a, b)
    pr_ok = _price_match(a, b)
    tx = jaccard(a.get("_shingles") or set(), b.get("_shingles") or set())

    if ph_ok:
        conf = min(0.99, 0.80 + 0.05 * ph_hits + (0.05 if at_ok else 0))
        return {"method": f"фото ({ph_hits} совпало)", "confidence": round(conf, 2),
                "text_sim": round(tx, 2)}

    if not at_ok:
        return None

    if both_have_photos:
        # фотографии не совпали — связываем только при очень похожем тексте
        if pr_ok and tx >= TEXT_STRICT_JACCARD:
            return {"method": f"цена и текст {tx:.0%} (фото разные)",
                    "confidence": 0.6, "text_sim": round(tx, 2)}
        return None

    # у одной из сторон фотографий нет — судим по цифрам и тексту
    if pr_ok and tx >= TEXT_MIN_JACCARD:
        return {"method": f"характеристики, цена и текст {tx:.0%}",
                "confidence": 0.75, "text_sim": round(tx, 2)}
    if tx >= TEXT_STRICT_JACCARD:
        return {"method": f"характеристики и текст {tx:.0%}",
                "confidence": 0.65, "text_sim": round(tx, 2)}
    return None


def _blocks(items: list[dict]) -> dict[tuple, list[int]]:
    """Не сравниваем каждое с каждым: бьём на корзины по коммуне и площади.

    Площадь кладём в две соседние корзины, иначе 119.9 и 120.1 никогда
    не встретятся.
    """
    buckets: dict[tuple, list[int]] = defaultdict(list)
    for i, it in enumerate(items):
        com = it.get("commune_code") or slug(it.get("commune_name", "")) or "?"
        area = it.get("area_m2")
        if area:
            base = int(area // 10)
            for b in (base - 1, base, base + 1):
                buckets[(com, b)].append(i)
        else:
            buckets[(com, None)].append(i)
    return buckets


def near_miss(a: dict, b: dict) -> dict | None:
    """Пара, которая почти дотянула до склейки.

    Раз правило намеренно строгое, часть настоящих дубликатов оно пропустит.
    Молча терять их нельзя — такие сомнения уходят на вкладку ручной проверки.
    """
    _, ph_hits = photos_match(a.get("photos") or [], b.get("photos") or [])
    if ph_hits:
        return None                       # это уже не «почти», это совпадение

    best = 999
    for x in a.get("photos") or []:
        for y in b.get("photos") or []:
            best = min(best,
                       imagehash.distance(x.get("phash"), y.get("phash")),
                       imagehash.distance(x.get("dhash"), y.get("dhash")))

    tx = jaccard(a.get("_shingles") or set(), b.get("_shingles") or set())
    at_ok = _attrs_match(a, b)
    pr_ok = _price_match(a, b)

    if best <= PHOTO_MAX_DIST + 6:
        return {"reason": f"похожие фото (расхождение {best} бит)", "score": 0.5}
    if at_ok and pr_ok:
        return {"reason": "совпали площадь, комнаты и цена, но фото разные", "score": 0.45}
    if at_ok and tx >= TEXT_MIN_JACCARD:
        return {"reason": f"совпали характеристики, текст похож на {tx:.0%}", "score": 0.4}
    return None


def group(items: list[dict], decisions: dict[tuple[str, str], int] | None = None):
    """items — объявления как dict (с ключами key, photos, ...).

    decisions — ручные вердикты {(ключ_a, ключ_b): 1 один дом | 0 разные}.
    Человек всегда прав: его решение перекрывает автоматику.

    -> (index -> group_id, связи, сомнительные пары)
    """
    decisions = decisions or {}
    for it in items:
        it["_shingles"] = shingles(f"{it.get('title','')} {it.get('description','')}")

    by_key = {it.get("key"): i for i, it in enumerate(items)}
    edges: dict[tuple[int, int], dict] = {}
    candidates = []

    for idxs in _blocks(items).values():
        for i, j in itertools.combinations(sorted(set(idxs)), 2):
            if (i, j) in edges or items[i].get("key") == items[j].get("key"):
                continue
            res = compare(items[i], items[j])
            if res:
                edges[(i, j)] = res
            else:
                nm = near_miss(items[i], items[j])
                if nm:
                    candidates.append({"a": items[i].get("key"),
                                       "b": items[j].get("key"), **nm})

    # ручные решения поверх автоматических
    for (ka, kb), same in decisions.items():
        i, j = by_key.get(ka), by_key.get(kb)
        if i is None or j is None:
            continue
        pair = (min(i, j), max(i, j))
        if same:
            edges[pair] = {"method": "подтверждено вручную", "confidence": 1.0}
        else:
            edges.pop(pair, None)

    parent = list(range(len(items)))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for (i, j) in edges:
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    groups = {i: items[find(i)].get("key") or f"g{find(i)}" for i in range(len(items))}
    links = [{"a": items[i].get("key"), "b": items[j].get("key"), **v}
             for (i, j), v in edges.items()]

    manual = {(min(a, b), max(a, b)) for a, b in decisions}
    candidates = [c for c in candidates
                  if (min(c["a"], c["b"]), max(c["a"], c["b"])) not in manual]

    for it in items:
        it.pop("_shingles", None)
    return groups, links, candidates


def pick_canonical(members: list[dict]) -> dict:
    """Какое из объявлений группы показывать основным.

    Берём самое информативное: больше фотографий и длиннее описание. При
    прочих равных — то, где цена ниже: у одного дома разница обычно в том,
    включена комиссия или нет.
    """
    def rank(m):
        return (len(m.get("photos") or []),
                len(m.get("description") or ""),
                -(m.get("price") or 10**9))
    return max(members, key=rank)
