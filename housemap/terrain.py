"""Метрики рельефа: «на горе, повыше, не в низине» в числах.

TPI (Topographic Position Index) = высота точки минус средняя высота вокруг.
Положительный TPI = холм/гребень, отрицательный = дно долины. Именно это, а не
абсолютная высота, отвечает на вопрос «в низине или нет».
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from .grid import Grid, to_wgs
from .sources import dem

PAD_M = 5200  # запас по краям, чтобы окна сглаживания не упирались в границу


def _fill_nan(a: np.ndarray) -> np.ndarray:
    if not np.isnan(a).any():
        return a
    idx = ndimage.distance_transform_edt(np.isnan(a), return_distances=False,
                                         return_indices=True)
    return a[tuple(idx)]


def _box_mean(a: np.ndarray, r: int) -> np.ndarray:
    return ndimage.uniform_filter(a, size=2 * r + 1, mode="nearest")


def _box_min(a: np.ndarray, r: int) -> np.ndarray:
    # separable: два прохода дешевле квадратного footprint
    a = ndimage.minimum_filter1d(a, size=2 * r + 1, axis=0, mode="nearest")
    return ndimage.minimum_filter1d(a, size=2 * r + 1, axis=1, mode="nearest")


def build(grid: Grid) -> dict[str, np.ndarray]:
    pad = int(np.ceil(PAD_M / grid.cell))
    n = 2 * pad
    xs = grid.x0 + (np.arange(-pad, grid.nx + pad) + 0.5) * grid.cell
    ys = grid.y0 + (np.arange(-pad, grid.ny + pad) + 0.5) * grid.cell
    X, Y = np.meshgrid(xs, ys)
    lon, lat = to_wgs(X, Y)

    print(f"  сетка рельефа {X.shape[0]}×{X.shape[1]} (с запасом {pad} яч.)")
    z = _fill_nan(dem.sample(lat, lon).astype(np.float32))

    r1 = grid.px(1000)
    r2 = grid.px(2000)
    r5 = grid.px(5000)

    tpi1 = z - _box_mean(z, r1)
    tpi3 = z - _box_mean(z, grid.px(3000))
    rel2 = z - _box_min(z, r2)
    rel5 = z - _box_min(z, r5)

    # Градиент: ось 0 — на север, ось 1 — на восток
    gy, gx = np.gradient(z, grid.cell)
    slope_pct = np.hypot(gx, gy) * 100.0
    mag = np.hypot(gx, gy)
    # южная экспозиция: высота растёт к северу => склон обращён на юг
    southness = np.where(mag > 1e-6, gy / np.maximum(mag, 1e-6), 0.0)
    # сглаживаем — интересует экспозиция участка, а не одного пикселя
    southness = ndimage.uniform_filter(southness, size=2 * grid.px(400) + 1, mode="nearest")
    slope_pct = ndimage.uniform_filter(slope_pct, size=2 * grid.px(300) + 1, mode="nearest")

    def crop(a):
        return np.ascontiguousarray(a[pad:pad + grid.ny, pad:pad + grid.nx])

    return {
        "elev": crop(z),
        "tpi_1km": crop(tpi1),
        "tpi_3km": crop(tpi3),
        "rel_elev_2km": crop(rel2),
        "rel_elev_5km": crop(rel5),
        "slope_pct": crop(slope_pct),
        "southness": crop(southness),
    }
