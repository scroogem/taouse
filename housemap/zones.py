"""Из непрерывного поля пригодности — в зоны, на которые стоит смотреть.

Две операции, обе нужны, чтобы карта перестала быть «рваной»:

1. Сглаживание. Данные OSM размечены с точностью до полигона, а не до метра;
   граница поля не означает, что в двух шагах от неё жизнь другая. Усреднение по
   небольшому кругу убирает ложную детализацию, которой в данных и не было.

2. Отсев мелочи. Две одиночные ячейки посреди неподходящей местности — это не
   место для поиска дома, а шум растеризации. Оставляем только связные участки
   разумного размера.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage

from . import rasterize as rz
from .grid import Grid


def smooth(field: np.ndarray, grid: Grid, radius_m: float) -> np.ndarray:
    if radius_m <= 0:
        return field
    return rz.focal_mean(field, grid, radius_m)


def drop_small(mask: np.ndarray, min_cells: int) -> tuple[np.ndarray, int, int]:
    """Убирает связные группы меньше min_cells ячеек. -> (маска, было, стало)"""
    lab, n = ndimage.label(mask, structure=np.ones((3, 3)))
    if n == 0:
        return mask, 0, 0
    sizes = np.bincount(lab.ravel())
    keep = np.zeros(sizes.size, dtype=bool)
    keep[1:] = sizes[1:] >= min_cells
    return keep[lab], n, int(keep[1:].sum())


def split_by_peaks(field: np.ndarray, mask: np.ndarray, labels: np.ndarray,
                   grid: Grid, min_dist_m: float) -> np.ndarray:
    """Дробит крупные массивы на участки вокруг локальных вершин.

    Массив крю Божоле однороден на сотню км² — формально это одна зона, но
    «поезжайте смотреть в область 119 км²» не совет. Разрезаем по локальным
    максимумам поля, не давая участку перепрыгнуть в соседний массив через
    долину: разбиение идёт внутри уже найденных связных областей.
    """
    r = max(1, grid.px(min_dist_m) // 2)
    peak = (field >= ndimage.maximum_filter(field, size=2 * r + 1, mode="nearest") - 1e-6)
    peak &= mask

    out = np.zeros_like(labels)
    next_id = 1
    for cid in range(1, labels.max() + 1):
        sel = labels == cid
        if not sel.any():
            continue
        pr, pc = np.nonzero(peak & sel)
        if len(pr) == 0:
            out[sel] = next_id
            next_id += 1
            continue

        # жадно оставляем вершины, разнесённые не ближе min_dist_m
        order = np.argsort(-field[pr, pc])
        keep = []
        for i in order:
            p = (grid.X[pr[i], pc[i]], grid.Y[pr[i], pc[i]])
            if all(np.hypot(p[0] - q[0], p[1] - q[1]) >= min_dist_m for q in keep):
                keep.append(p)
        if len(keep) <= 1:
            out[sel] = next_id
            next_id += 1
            continue

        rr, cc = np.nonzero(sel)
        pts = np.array(keep)
        d = ((grid.X[rr, cc][:, None] - pts[:, 0]) ** 2
             + (grid.Y[rr, cc][:, None] - pts[:, 1]) ** 2)
        owner = np.argmin(d, axis=1)
        out[rr, cc] = next_id + owner
        next_id += len(keep)
    return out


def build(L: dict, grid: Grid, cfg: dict, feas: np.ndarray, attract: np.ndarray):
    """Итоговое поле баллов и маска зон.

    balance: пригодность (запреты) умножается на привлекательность. Место,
    которое чуть не дотянуло по одному критерию, не исчезает — оно просто
    получает балл ниже, и его видно на карте.
    """
    zc = cfg["zones"]
    raw = attract * feas
    field = smooth(raw, grid, zc["smooth_radius_m"])
    field = np.where(grid.inside, field, 0.0).astype(np.float32)

    mask = field >= zc["min_score"]
    mask, n_before, n_after = drop_small(mask, zc["min_cluster_cells"])

    lab, _ = ndimage.label(mask, structure=np.ones((3, 3)))
    parts = split_by_peaks(field, mask, lab, grid, zc["peak_min_distance_m"])
    return field, mask, parts, (n_before, n_after)


def commune_stats(grid: Grid, L: dict, field: np.ndarray, mask: np.ndarray):
    """Сводка по коммунам — но уже как справка, а не как вердикт.

    Балл принадлежит месту, а не коммуне: административная граница не меняет
    ни рельеф, ни шум. Поэтому здесь только «сколько в коммуне хорошей земли
    и насколько она хороша» — чтобы знать, где искать объявления.
    """
    ci = L["commune_idx"]
    out = []
    for i, c in enumerate(L["_communes"]):
        sel = (ci == i) & grid.inside
        n = int(sel.sum())
        if n == 0:
            continue
        good = sel & mask
        rec = {"idx": i, "cells_total": n, "cells_good": int(good.sum())}
        f = field[sel]
        rec["score_best"] = round(float(f.max()), 1)
        rec["score_p90"] = round(float(np.percentile(f, 90)), 1)
        rec["score_median"] = round(float(np.median(f)), 1)
        out.append(rec)
    return out
