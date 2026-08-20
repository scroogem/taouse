"""Границы и население коммун — geo.api.gouv.fr (официальный API)."""
from __future__ import annotations

import numpy as np

from .. import http
from ..cache import cached_json
from ..grid import Grid, to_l93

# Департаменты, попадающие в зону вокруг Макона
DEPTS = ["71", "01", "69", "39", "42"]
FIELDS = "nom,code,codesPostaux,population,surface,centre,contour,departement"


def _download(dep: str) -> list[dict]:
    r = http.get(f"https://geo.api.gouv.fr/departements/{dep}/communes",
                     params={"fields": FIELDS, "format": "json", "geometry": "contour"},
                     timeout=180)
    r.raise_for_status()
    return r.json()


def load(grid: Grid, extra_km: float = 3.0) -> list[dict]:
    """Коммуны, чей центр попадает в радиус поиска (+ запас)."""
    out = []
    limit = grid.radius_m + extra_km * 1000
    for dep in DEPTS:
        rows = cached_json("communes", f"dep{dep}|{FIELDS}", lambda d=dep: _download(d),
                           label=f"коммуны dept {dep}")
        for c in rows:
            centre = c.get("centre")
            if not centre:
                continue
            lon, lat = centre["coordinates"]
            x, y = to_l93(lon, lat)
            if np.hypot(x - grid.cx, y - grid.cy) > limit:
                continue
            c["_xy"] = (x, y)
            out.append(c)
    print(f"  {len(out)} коммун в радиусе")
    return out


def contour_rings(c: dict) -> list[np.ndarray]:
    """Внешние кольца контура коммуны в Lambert-93."""
    g = c.get("contour")
    if not g:
        return []
    polys = g["coordinates"] if g["type"] == "MultiPolygon" else [g["coordinates"]]
    rings = []
    for poly in polys:
        ring = np.asarray(poly[0], dtype=np.float64)
        x, y = to_l93(ring[:, 0], ring[:, 1])
        rings.append(np.column_stack([x, y]))
    return rings
