"""Метрическая сетка над зоной поиска.

Работаем в Lambert-93 (EPSG:2154) — официальной французской проекции в метрах.
Все расстояния в коде — честные метры, без тригонометрии по месту.
"""
from __future__ import annotations

import numpy as np
from pyproj import CRS, Transformer

WGS84 = CRS.from_epsg(4326)
L93 = CRS.from_epsg(2154)

to_l93 = Transformer.from_crs(WGS84, L93, always_xy=True).transform
to_wgs = Transformer.from_crs(L93, WGS84, always_xy=True).transform


class Grid:
    """Регулярная сетка cell_m × cell_m, центрированная на точке поиска."""

    def __init__(self, center_lat: float, center_lon: float, radius_km: float, cell_m: int):
        self.center_lat = center_lat
        self.center_lon = center_lon
        self.radius_m = radius_km * 1000.0
        self.cell = float(cell_m)

        cx, cy = to_l93(center_lon, center_lat)
        # Привязываем к круглым координатам, чтобы сетка была стабильна между запусками
        self.x0 = np.floor((cx - self.radius_m) / self.cell) * self.cell
        self.y0 = np.floor((cy - self.radius_m) / self.cell) * self.cell
        self.nx = int(np.ceil(2 * self.radius_m / self.cell)) + 1
        self.ny = int(np.ceil(2 * self.radius_m / self.cell)) + 1
        self.cx, self.cy = cx, cy

        # Центры ячеек
        self.xs = self.x0 + (np.arange(self.nx) + 0.5) * self.cell
        self.ys = self.y0 + (np.arange(self.ny) + 0.5) * self.cell
        # ГЕОМЕТРИЯ: [row, col] = [y, x]; строка 0 — юг.
        self.X, self.Y = np.meshgrid(self.xs, self.ys)

        d = np.hypot(self.X - cx, self.Y - cy)
        self.inside = d <= self.radius_m
        self.dist_center = d

    @property
    def shape(self):
        return (self.ny, self.nx)

    def px(self, radius_m: float) -> int:
        """Радиус в метрах -> в ячейках (минимум 1)."""
        return max(1, int(round(radius_m / self.cell)))

    def bbox_l93(self, pad_m: float = 0.0):
        return (self.x0 - pad_m, self.y0 - pad_m,
                self.x0 + self.nx * self.cell + pad_m,
                self.y0 + self.ny * self.cell + pad_m)

    def bbox_wgs(self, pad_m: float = 0.0):
        """(south, west, north, east) — формат, который любит Overpass."""
        x1, y1, x2, y2 = self.bbox_l93(pad_m)
        corners = [to_wgs(x, y) for x in (x1, x2) for y in (y1, y2)]
        lons = [c[0] for c in corners]
        lats = [c[1] for c in corners]
        return (min(lats), min(lons), max(lats), max(lons))

    def latlon_arrays(self):
        """lat/lon центров всех ячеек (для сэмплинга растров в WGS84)."""
        lon, lat = to_wgs(self.X, self.Y)
        return lat, lon

    def world_to_px(self, x, y):
        """Координаты L93 -> дробные пиксельные (col, row)."""
        return (np.asarray(x) - self.x0) / self.cell, (np.asarray(y) - self.y0) / self.cell

    def cell_bounds_wgs(self, row: int, col: int):
        x1 = self.x0 + col * self.cell
        y1 = self.y0 + row * self.cell
        x2, y2 = x1 + self.cell, y1 + self.cell
        lon1, lat1 = to_wgs(x1, y1)
        lon2, lat2 = to_wgs(x2, y2)
        return lat1, lon1, lat2, lon2
