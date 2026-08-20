"""Рельеф: SRTM 1" (~30 м) из открытого зеркала AWS elevation-tiles-prod.

Формат skadi: тайл 1°×1°, 3601×3601 int16 big-endian, строка 0 — северный край.
Никаких GDAL/rasterio — читаем numpy'ем напрямую.
"""
from __future__ import annotations

import gzip
import math
import pathlib

import numpy as np
from .. import http
from ..cache import DATA

BASE = "https://s3.amazonaws.com/elevation-tiles-prod/skadi"
SIZE = 3601
VOID = -32768

_tiles: dict[tuple[int, int], np.ndarray] = {}


def _tile_name(lat: int, lon: int) -> str:
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{ns}{abs(lat):02d}{ew}{abs(lon):03d}"


def _load_tile(lat: int, lon: int) -> np.ndarray | None:
    key = (lat, lon)
    if key in _tiles:
        return _tiles[key]

    name = _tile_name(lat, lon)
    d = DATA / "dem"
    d.mkdir(parents=True, exist_ok=True)
    local = d / f"{name}.hgt.gz"

    if not local.exists():
        url = f"{BASE}/{_tile_name(lat, lon)[:3]}/{name}.hgt.gz"
        print(f"  [fetch] DEM {name} ...", end="", flush=True)
        r = http.get(url, timeout=180)
        if r.status_code == 404:
            print(" нет тайла (океан?)")
            _tiles[key] = None
            return None
        r.raise_for_status()
        local.write_bytes(r.content)
        print(f" {len(r.content) / 1e6:.1f} МБ")

    raw = gzip.decompress(local.read_bytes())
    arr = np.frombuffer(raw, dtype=">i2").astype(np.float32)
    if arr.size != SIZE * SIZE:
        raise ValueError(f"{name}: неожиданный размер {arr.size}")
    arr = arr.reshape(SIZE, SIZE).copy()
    arr[arr == VOID] = np.nan
    _tiles[key] = arr
    return arr


def sample(lats: np.ndarray, lons: np.ndarray) -> np.ndarray:
    """Билинейная выборка высот. lats/lons — массивы любой формы."""
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    out = np.full(lats.shape, np.nan, dtype=np.float32)

    tlat = np.floor(lats).astype(int)
    tlon = np.floor(lons).astype(int)

    for la in np.unique(tlat):
        for lo in np.unique(tlon[tlat == la]):
            m = (tlat == la) & (tlon == lo)
            tile = _load_tile(int(la), int(lo))
            if tile is None:
                continue
            # доля внутри тайла; строка 0 = северный край => инвертируем по широте
            fy = (la + 1 - lats[m]) * (SIZE - 1)
            fx = (lons[m] - lo) * (SIZE - 1)
            r0 = np.clip(np.floor(fy).astype(int), 0, SIZE - 2)
            c0 = np.clip(np.floor(fx).astype(int), 0, SIZE - 2)
            dy = fy - r0
            dx = fx - c0
            v = (tile[r0, c0] * (1 - dx) * (1 - dy)
                 + tile[r0, c0 + 1] * dx * (1 - dy)
                 + tile[r0 + 1, c0] * (1 - dx) * dy
                 + tile[r0 + 1, c0 + 1] * dx * dy)
            out[m] = v
    return out
