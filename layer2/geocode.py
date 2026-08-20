"""Геокодирование через api-adresse.data.gouv.fr — официальный бесплатный
сервис Base Adresse Nationale. Без ключей и лимитов в разумных пределах.

Объявления редко дают точный адрес, поэтому важно понимать, что именно мы
получили: дом, улицу или только коммуну. От этого зависит, можно ли доверять
баллу места в конкретной точке.
"""
from __future__ import annotations

import json
import pathlib
import time

from housemap import http

CACHE = pathlib.Path(__file__).resolve().parent.parent / "data" / "geocode.json"
_cache: dict | None = None


def _load() -> dict:
    global _cache
    if _cache is None:
        try:
            _cache = json.loads(CACHE.read_text(encoding="utf-8"))
        except Exception:
            _cache = {}
    return _cache


def _save():
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps(_cache, ensure_ascii=False), encoding="utf-8")


def geocode(query: str, postcode: str = "", commune: str = "") -> dict | None:
    """-> {lat, lon, precision, commune_code, commune_name, label} или None.

    precision: housenumber | street | locality | municipality
    """
    q = " ".join(x for x in (query, commune) if x).strip()
    if not q:
        return None
    key = f"{q}|{postcode}"
    cache = _load()
    if key in cache:
        return cache[key]

    params = {"q": q, "limit": 1}
    if postcode:
        params["postcode"] = postcode
    try:
        r = http.get("https://api-adresse.data.gouv.fr/search/", params=params, timeout=20)
        r.raise_for_status()
        feats = r.json().get("features") or []
    except Exception:
        return None
    time.sleep(0.12)  # вежливость к бесплатному сервису

    if not feats:
        cache[key] = None
        _save()
        return None
    f = feats[0]
    p = f["properties"]
    out = {
        "lat": f["geometry"]["coordinates"][1],
        "lon": f["geometry"]["coordinates"][0],
        "precision": p.get("type", ""),
        "commune_code": p.get("citycode", ""),
        "commune_name": p.get("city", ""),
        "postcode": p.get("postcode", ""),
        "label": p.get("label", ""),
        "score": p.get("score"),
    }
    cache[key] = out
    _save()
    return out


def commune(name: str, postcode: str = "") -> dict | None:
    """Только коммуна — когда точнее в объявлении ничего нет."""
    if not name:
        return None
    key = f"__commune__{name}|{postcode}"
    cache = _load()
    if key in cache:
        return cache[key]
    params = {"q": name, "type": "municipality", "limit": 1}
    if postcode:
        params["postcode"] = postcode
    try:
        r = http.get("https://api-adresse.data.gouv.fr/search/", params=params, timeout=20)
        r.raise_for_status()
        feats = r.json().get("features") or []
    except Exception:
        return None
    time.sleep(0.12)
    out = None
    if feats:
        f = feats[0]
        p = f["properties"]
        out = {"lat": f["geometry"]["coordinates"][1],
               "lon": f["geometry"]["coordinates"][0],
               "precision": "municipality",
               "commune_code": p.get("citycode", ""),
               "commune_name": p.get("city") or p.get("name", ""),
               "postcode": p.get("postcode", ""),
               "label": p.get("label", "")}
    cache[key] = out
    _save()
    return out
