"""Отрисовка непрерывного поля пригодности в растр для карты.

Leaflet растягивает картинку линейно в Web Mercator, поэтому и рисовать надо
в Mercator, иначе на 50 км набегает сдвиг в сотни метров. Заодно в этой же
сетке отдаём в браузер данные для клика — тогда пересчёт координат в JS
сводится к двум формулам вместо реализации Lambert-93.
"""
from __future__ import annotations

import base64
import io
import math

import numpy as np
from PIL import Image

from .grid import Grid, to_l93

# Плавная шкала: от тёплого «так себе» к холодному «отлично».
STOPS = [
    (0.00, (140, 150, 160)),
    (0.30, (196, 168, 100)),
    (0.45, (233, 220, 110)),
    (0.60, (150, 205, 110)),
    (0.72, (60, 165, 110)),
    (0.85, (30, 120, 130)),
    (1.00, (40, 70, 120)),
]


def _ramp(t: np.ndarray) -> np.ndarray:
    t = np.clip(t, 0, 1)
    out = np.zeros(t.shape + (3,), dtype=np.float32)
    for (a, ca), (b, cb) in zip(STOPS[:-1], STOPS[1:]):
        m = (t >= a) & (t <= b)
        if not m.any():
            continue
        f = ((t[m] - a) / (b - a))[:, None]
        out[m] = np.array(ca, dtype=np.float32) * (1 - f) + np.array(cb, dtype=np.float32) * f
    return out


def merc_xy(lat, lon):
    """Нормализованные координаты Web Mercator в [0,1]."""
    lat = np.clip(lat, -85.05, 85.05)
    x = lon / 360.0 + 0.5
    s = np.sin(np.radians(lat))
    y = 0.5 - np.log((1 + s) / (1 - s)) / (4 * math.pi)
    return x, y


def merc_bounds(grid: Grid):
    s, w, n, e = grid.bbox_wgs()
    x0, y1 = merc_xy(s, w)   # юг -> больший y
    x1, y0 = merc_xy(n, e)
    return (s, w, n, e), (float(x0), float(y0), float(x1), float(y1))


def _sample_to_merc(field: np.ndarray, grid: Grid, W: int, H: int) -> np.ndarray:
    """Пересэмплирование поля из Lambert-93 в равномерную Mercator-сетку."""
    (s, w, n, e), (mx0, my0, mx1, my1) = merc_bounds(grid)
    mx = mx0 + (np.arange(W) + 0.5) / W * (mx1 - mx0)
    my = my0 + (np.arange(H) + 0.5) / H * (my1 - my0)
    MX, MY = np.meshgrid(mx, my)

    lon = (MX - 0.5) * 360.0
    lat = np.degrees(2 * np.arctan(np.exp((0.5 - MY) * 2 * math.pi)) - math.pi / 2)
    x, y = to_l93(lon, lat)

    fc = (x - grid.x0) / grid.cell - 0.5
    fr = (y - grid.y0) / grid.cell - 0.5
    c0 = np.clip(np.floor(fc).astype(int), 0, grid.nx - 2)
    r0 = np.clip(np.floor(fr).astype(int), 0, grid.ny - 2)
    dx = np.clip(fc - c0, 0, 1)
    dy = np.clip(fr - r0, 0, 1)
    v = (field[r0, c0] * (1 - dx) * (1 - dy) + field[r0, c0 + 1] * dx * (1 - dy)
         + field[r0 + 1, c0] * (1 - dx) * dy + field[r0 + 1, c0 + 1] * dx * dy)
    inside = ((x - grid.cx) ** 2 + (y - grid.cy) ** 2) <= grid.radius_m ** 2
    return np.where(inside, v, np.nan)


def field_png(field: np.ndarray, grid: Grid, size: int = 900,
              vmin: float = 15, vmax: float = 85, fade_below: float = 10) -> str:
    """PNG непрерывного поля -> data URI.

    Непригодные места не исчезают совсем, а остаются бледным фоном: карта
    должна читаться как непрерывное поле, а не как острова в пустоте.
    """
    v = _sample_to_merc(field, grid, size, size)
    t = (v - vmin) / (vmax - vmin)
    rgb = _ramp(np.nan_to_num(t, nan=0.0))

    alpha = np.clip((v - fade_below) / 28.0, 0, 1) * 185 + 48
    alpha = np.where(np.isnan(v), 0, alpha)

    img = np.dstack([rgb.astype(np.uint8), alpha.astype(np.uint8)])
    buf = io.BytesIO()
    Image.fromarray(img, mode="RGBA").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def quantized(field: np.ndarray, grid: Grid, size: int, lo: float, hi: float) -> str:
    """Поле -> uint8 в Mercator-сетке -> base64 (для клика в любую точку)."""
    v = _sample_to_merc(field, grid, size, size)
    q = np.clip((v - lo) / (hi - lo) * 254 + 1, 0, 255)
    q = np.where(np.isnan(v), 0, q).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode()


def quantized_int(field: np.ndarray, grid: Grid, size: int) -> str:
    """Целочисленный слой (индекс критерия) без масштабирования."""
    v = _sample_to_merc(field.astype(np.float32), grid, size, size)
    q = np.where(np.isnan(v), 255, np.round(v)).astype(np.uint8)
    return base64.b64encode(q.tobytes()).decode()
