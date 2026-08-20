"""Данные OpenStreetMap через Overpass API.

Каждый набор — отдельный запрос с отдельным кэшем: если один упадёт по таймауту,
остальные не пропадут. Геометрия сразу приводится к Lambert-93 (метры).
"""
from __future__ import annotations

import time

import numpy as np

from .. import http
from ..cache import cached_json
from ..grid import to_l93

ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]

TIMEOUT = 300

# Насколько выходить за границы сетки в каждом запросе, м.
# Съезд с автострады ищем далеко, а землепользование нужно лишь на радиус
# сглаживания — иначе «природный» запрос раздувается в разы без пользы.
PAD = {
    "motorway": 8000,
    "trunk_primary": 6000,
    "rail": 6000,
    "junction": 22000,
    "places": 8000,
    "services": 8000,
    "nature": 2500,
    "built": 2500,
}

QUERIES = {
    # --- линейные объекты ---
    "motorway": 'way[highway~"^(motorway|motorway_link)$"];',
    "trunk_primary": 'way[highway~"^(trunk|trunk_link|primary|primary_link)$"];',
    "rail": 'way[railway~"^(rail|light_rail|narrow_gauge)$"];',

    # --- точки ---
    "junction": 'node[highway=motorway_junction];',
    "places": 'node[place~"^(city|town|village|hamlet|isolated_dwelling|suburb)$"];',
    "services": (
        '('
        'nwr[amenity~"^(school|kindergarten|college|pharmacy|doctors)$"];'
        'nwr[shop~"^(bakery|supermarket|convenience|butcher)$"];'
        ');'
    ),

    # --- площадные: природа и сельское хозяйство ---
    "nature": (
        '('
        'wr[landuse~"^(vineyard|farmland|meadow|orchard|forest|allotments'
        '|greenhouse_horticulture|plant_nursery|grass)$"];'
        'wr[natural~"^(wood|scrub|water|wetland|grassland|heath)$"];'
        ');'
    ),

    # --- площадные: застройка и источники неприятностей ---
    "built": (
        '('
        'wr[landuse~"^(residential|industrial|commercial|retail|quarry|farmyard'
        '|landfill|military|construction|cemetery)$"];'
        'wr[man_made=wastewater_plant];'
        'wr[amenity~"^(waste_transfer_station|waste_disposal)$"];'
        'wr[aeroway=aerodrome];'
        'nwr[power=plant];'
        'nwr["generator:source"=wind];'
        ');'
    ),
}


def _post(ql: str) -> dict:
    last = None
    for ep in ENDPOINTS:
        for attempt in range(2):
            try:
                r = http.post(ep, data={"data": ql}, timeout=TIMEOUT + 30)
                if r.status_code in (429, 502, 503, 504):
                    time.sleep(8 * (attempt + 1))
                    continue
                r.raise_for_status()
                return r.json()
            except Exception as e:  # сеть/таймаут/лимит — идём к следующему зеркалу
                last = e
                time.sleep(4)
    raise RuntimeError(f"Overpass недоступен: {last}")


def fetch(name: str, grid) -> dict:
    s, w, n, e = grid.bbox_wgs(pad_m=PAD.get(name, 5000))
    body = QUERIES[name]
    ql = (f"[out:json][timeout:{TIMEOUT}][bbox:{s:.5f},{w:.5f},{n:.5f},{e:.5f}];"
          f"{body}out geom;")
    key = ql
    return cached_json("overpass", key, lambda: _post(ql), label=f"OSM: {name}")


# ---------------------------------------------------------------------------
# Разбор геометрии
# ---------------------------------------------------------------------------

def _xy(geom) -> np.ndarray:
    lon = np.array([g["lon"] for g in geom])
    lat = np.array([g["lat"] for g in geom])
    x, y = to_l93(lon, lat)
    return np.column_stack([x, y])


def points(data: dict, keep=None) -> list[tuple[np.ndarray, dict]]:
    """Точки (node), а также центроиды way/relation — чтобы школа-полигон тоже считалась."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        if keep and not keep(tags):
            continue
        if el["type"] == "node" and "lon" in el:
            x, y = to_l93(el["lon"], el["lat"])
            out.append((np.array([x, y]), tags))
        elif "geometry" in el and el["geometry"]:
            c = _xy(el["geometry"])
            out.append((c.mean(axis=0), tags))
        elif "bounds" in el:
            b = el["bounds"]
            x, y = to_l93((b["minlon"] + b["maxlon"]) / 2, (b["minlat"] + b["maxlat"]) / 2)
            out.append((np.array([x, y]), tags))
    return out


def lines(data: dict, keep=None) -> list[tuple[np.ndarray, dict]]:
    out = []
    for el in data.get("elements", []):
        if el["type"] != "way" or not el.get("geometry"):
            continue
        tags = el.get("tags", {}) or {}
        if keep and not keep(tags):
            continue
        out.append((_xy(el["geometry"]), tags))
    return out


def _assemble_rings(members) -> list[np.ndarray]:
    """Склейка кусков outer-ways мультиполигона в замкнутые кольца."""
    chunks = [_xy(m["geometry"]) for m in members if m.get("geometry")]
    rings, pending = [], list(chunks)
    while pending:
        cur = pending.pop(0)
        changed = True
        while changed and not np.allclose(cur[0], cur[-1], atol=0.5):
            changed = False
            for i, c in enumerate(pending):
                if np.allclose(cur[-1], c[0], atol=0.5):
                    cur = np.vstack([cur, c[1:]]); pending.pop(i); changed = True; break
                if np.allclose(cur[-1], c[-1], atol=0.5):
                    cur = np.vstack([cur, c[::-1][1:]]); pending.pop(i); changed = True; break
                if np.allclose(cur[0], c[-1], atol=0.5):
                    cur = np.vstack([c[:-1], cur]); pending.pop(i); changed = True; break
                if np.allclose(cur[0], c[0], atol=0.5):
                    cur = np.vstack([c[::-1][:-1], cur]); pending.pop(i); changed = True; break
        if len(cur) >= 3:
            rings.append(cur)
    return rings


def polygons(data: dict, keep=None) -> list[tuple[np.ndarray, dict]]:
    """Внешние контуры. Дырки игнорируем — для долей землепользования не критично."""
    out = []
    for el in data.get("elements", []):
        tags = el.get("tags", {}) or {}
        if keep and not keep(tags):
            continue
        if el["type"] == "way" and el.get("geometry") and len(el["geometry"]) >= 3:
            out.append((_xy(el["geometry"]), tags))
        elif el["type"] == "relation":
            outer = [m for m in el.get("members", [])
                     if m.get("role") in ("outer", "") and m.get("geometry")]
            for ring in _assemble_rings(outer):
                out.append((ring, tags))
    return out
