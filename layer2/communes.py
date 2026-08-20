"""Определение настоящей коммуны объявления.

Порталы регулярно указывают не ту коммуну. Живой пример из первого же сбора:

    URL и метатеги:  .../annonce-vente-maison-t10-cluny-71250-...
    описание:        «Grande maison au coeur du village de SAINT POINT»

Cluny и Saint-Point — разные коммуны в 12 км друг от друга, и балл места у них
разный. Причина обычная: объявление привязывают к известному городу, чтобы его
находили по популярному запросу.

Поэтому коммуну из ссылки считаем лишь предположением и проверяем по тексту:
если в описании прямо названа другая коммуна из нашего справочника, верим
описанию.
"""
from __future__ import annotations

import gzip
import json
import pathlib
import re

from .normalize import slug

DATA = pathlib.Path(__file__).resolve().parent.parent / "data" / "communes"

# «sur la commune de X», «au coeur du village de X», «situé à X»
PATTERNS = [
    r"(?:sur\s+la\s+)?commune\s+d[eu']\s*([A-ZÀ-Ÿ][\wÀ-ÿ' \-]{2,32})",
    r"village\s+d[eu']\s*([A-ZÀ-Ÿ][\wÀ-ÿ' \-]{2,32})",
    r"(?:situ[ée]e?|sise?)\s+[àa]\s+([A-ZÀ-Ÿ][\wÀ-ÿ' \-]{2,32})",
    r"bourg\s+d[eu']\s*([A-ZÀ-Ÿ][\wÀ-ÿ' \-]{2,32})",
]

_index: dict[str, dict] | None = None


def index() -> dict[str, dict]:
    """{slug имени: {code, nom}} по всем коммунам, скачанным Слоем 1."""
    global _index
    if _index is not None:
        return _index
    out: dict[str, dict] = {}
    for f in sorted(DATA.glob("*.json.gz")):
        try:
            rows = json.loads(gzip.decompress(f.read_bytes()).decode())
        except Exception:
            continue
        for c in rows:
            nom = c.get("nom")
            if nom:
                out.setdefault(slug(nom), {"code": c.get("code"), "nom": nom})
    _index = out
    return out


def find_in_text(text: str, limit_chars: int = 700) -> dict | None:
    """Коммуна, прямо названная в начале описания.

    Смотрим только начало: дальше в тексте попадаются «в 20 минутах от Макона»
    и прочие ориентиры, которые коммуной объявления не являются.
    """
    if not text:
        return None
    head = text[:limit_chars]
    known = index()

    for pat in PATTERNS:
        for m in re.finditer(pat, head, re.I):
            cand = _lookup(m.group(1), known)
            if cand:
                return cand

    # Объявления часто начинаются с названия: «HURIGNY – Chalet suisse…»
    m = re.match(r"\s*([A-ZÀ-Ÿ][A-ZÀ-Ÿ' \-]{2,32})\s*[–—\-:,]", head)
    if m:
        cand = _lookup(m.group(1), known)
        if cand:
            return cand
    return None


def _lookup(raw: str, known: dict) -> dict | None:
    s = slug(raw)
    if s in known:
        return known[s]
    # «SAINT POINT» -> «saint-point»
    s2 = s.replace(" ", "-")
    for key in (s2, s.replace("st ", "saint ")):
        if key in known:
            return known[key]
    return None


def reconcile(claimed_name: str, text: str) -> tuple[dict | None, bool]:
    """-> (коммуна из текста, есть ли расхождение с заявленной)."""
    found = find_in_text(text)
    if not found:
        return None, False
    if claimed_name and slug(found["nom"]) == slug(claimed_name):
        return found, False
    return found, bool(claimed_name)
