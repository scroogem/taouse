"""Перевод векторной геометрии в растровые слои на сетке.

Расстояния считаем KD-деревом по уплотнённым вершинам, а не по растру: так
объекты за пределами bbox тоже учитываются и нет ступенек в 200 м.
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import cKDTree

from .grid import Grid

SS = 4  # суперсэмплинг при растеризации площадей


def densify(coords: np.ndarray, step: float = 60.0) -> np.ndarray:
    """Добавляет промежуточные точки, чтобы расстояние до линии считалось честно."""
    if len(coords) < 2:
        return coords
    out = [coords[:-1]]
    seg = coords[1:] - coords[:-1]
    d = np.hypot(seg[:, 0], seg[:, 1])
    for i in np.nonzero(d > step)[0]:
        k = int(d[i] // step)
        t = np.linspace(0, 1, k + 2)[1:-1][:, None]
        out.append(coords[i] + t * seg[i])
    out.append(coords[-1:])
    return np.vstack(out)


def _dist_from_points(grid: Grid, pts: np.ndarray) -> np.ndarray:
    if len(pts) == 0:
        return np.full(grid.shape, 1e9, dtype=np.float32)
    tree = cKDTree(pts)
    q = np.column_stack([grid.X.ravel(), grid.Y.ravel()])
    d, _ = tree.query(q, workers=-1)
    return d.reshape(grid.shape).astype(np.float32)


def dist_to_points(grid: Grid, items) -> np.ndarray:
    pts = np.array([c for c, _ in items]) if items else np.empty((0, 2))
    return _dist_from_points(grid, pts)


def dist_to_geoms(grid: Grid, items, step: float = 60.0) -> np.ndarray:
    """Расстояние до линий или контуров полигонов."""
    if not items:
        return np.full(grid.shape, 1e9, dtype=np.float32)
    pts = np.vstack([densify(c, step) for c, _ in items if len(c) >= 2])
    return _dist_from_points(grid, pts)


def rasterize(grid: Grid, polys, ss: int = SS) -> np.ndarray:
    """Доля площади ячейки, покрытая полигонами (0..1)."""
    if not polys:
        return np.zeros(grid.shape, dtype=np.float32)
    W, H = grid.nx * ss, grid.ny * ss
    img = Image.new("1", (W, H), 0)
    drw = ImageDraw.Draw(img)
    inv = ss / grid.cell
    for coords, _ in polys:
        if len(coords) < 3:
            continue
        px = (coords[:, 0] - grid.x0) * inv
        py = (coords[:, 1] - grid.y0) * inv
        if px.max() < 0 or py.max() < 0 or px.min() > W or py.min() > H:
            continue
        drw.polygon(list(zip(px.tolist(), py.tolist())), fill=1)
    a = np.asarray(img, dtype=np.float32)
    return a.reshape(grid.ny, ss, grid.nx, ss).mean(axis=(1, 3))


def dist_to_polys(grid: Grid, polys, step: float = 60.0) -> np.ndarray:
    """Расстояние до полигона: 0 внутри, до контура — снаружи."""
    d = dist_to_geoms(grid, polys, step)
    inside = rasterize(grid, polys) > 0.5
    d[inside] = 0.0
    return d


def _disk(r: int) -> np.ndarray:
    y, x = np.mgrid[-r:r + 1, -r:r + 1]
    k = (x * x + y * y <= r * r).astype(np.float32)
    return k / k.sum()


def focal_mean(a: np.ndarray, grid: Grid, radius_m: float) -> np.ndarray:
    r = grid.px(radius_m)
    return ndimage.convolve(a.astype(np.float32), _disk(r), mode="nearest")


def focal_sum(a: np.ndarray, grid: Grid, radius_m: float) -> np.ndarray:
    """Сумма значений в круге радиуса radius_m (например, людей вокруг)."""
    k = (_disk(grid.px(radius_m)) > 0).astype(np.float32)
    return ndimage.convolve(a.astype(np.float32), k, mode="constant", cval=0.0)
