"""Оценка места объявления по карте Слоя 1.

Главная ценность связки: объявление не просто «дом в Бургундии за 300k», а
«дом в зоне №12 с баллом 74» либо «дом в пойме с баллом 8» — и это видно до
того, как кто-то откроет фотографии.

Точность зависит от того, что дал адрес:
  * есть номер дома или улица -> балл берётся в самой точке;
  * есть только коммуна       -> берём лучший балл коммуны и честно помечаем
                                 это как «ориентировочно»: в одной коммуне
                                 бывает и гребень с виноградниками, и низина
                                 у железной дороги.
"""
from __future__ import annotations

import json
import pathlib

import numpy as np

from housemap.grid import to_l93

OUT = pathlib.Path(__file__).resolve().parent.parent / "out"

PRECISE = {"housenumber", "street"}


class PlaceMap:
    def __init__(self, outdir: pathlib.Path | None = None):
        d = outdir or OUT
        z = np.load(d / "field.npz", allow_pickle=False)
        self.field = z["field"]
        self.mask = z["mask"]
        self.parts = z["parts"]
        (self.x0, self.y0, self.cell, nx, ny,
         self.cx, self.cy, self.radius) = z["meta"]
        self.nx, self.ny = int(nx), int(ny)

        self.zones = json.loads((d / "clusters.json").read_text(encoding="utf-8"))
        self.by_part = {z["id"]: z for z in self.zones}
        wl = json.loads((d / "whitelist.json").read_text(encoding="utf-8"))
        self.communes = wl["communes"]

    # -- точка -------------------------------------------------------------
    def at(self, lat: float, lon: float) -> dict | None:
        x, y = to_l93(lon, lat)
        if np.hypot(x - self.cx, y - self.cy) > self.radius:
            return None
        c = int((x - self.x0) // self.cell)
        r = int((y - self.y0) // self.cell)
        if not (0 <= r < self.ny and 0 <= c < self.nx):
            return None
        part = int(self.parts[r, c])
        zone = self.by_part.get(part)
        return {
            "score": round(float(self.field[r, c]), 1),
            "in_zone": bool(self.mask[r, c]),
            "zone_rank": zone["rank"] if zone else None,
            "zone_communes": zone["communes"] if zone else [],
        }

    # -- коммуна -----------------------------------------------------------
    def for_commune(self, code: str) -> dict | None:
        c = self.communes.get(code)
        if not c:
            return None
        return {"score": c["score_p90"], "status": c["status"],
                "area_good_ha": c["area_good_ha"], "hotspot": c["hotspot"],
                "nom": c["nom"], "dist_macon_km": c.get("dist_macon_km")}

    # -- главное: оценить объявление ---------------------------------------
    def evaluate(self, lat, lon, precision: str, commune_code: str) -> dict:
        """-> {score, zone_rank, communes, note, approximate}

        note — код вердикта, а не текст: перевод делается при показе,
        потому что интерфейс двуязычный.
        """
        if lat and lon and precision in PRECISE:
            hit = self.at(lat, lon)
            if hit:
                kind = ("exact_zone" if hit["zone_rank"]
                        else "exact_ok" if hit["in_zone"] else "exact_out")
                return {"score": hit["score"], "zone_rank": hit["zone_rank"],
                        "communes": ", ".join(hit["zone_communes"]),
                        "note": kind, "approximate": False}

        com = self.for_commune(commune_code) if commune_code else None
        if com:
            return {"score": com["score"], "zone_rank": None,
                    "communes": com["nom"],
                    "note": f"commune:{com['status']}:{com['area_good_ha']:.0f}",
                    "approximate": True}

        # коммуна вне радиуса поиска либо не распознана
        if lat and lon:
            hit = self.at(lat, lon)
            if hit:
                return {"score": hit["score"], "zone_rank": hit["zone_rank"],
                        "communes": ", ".join(hit["zone_communes"]),
                        "note": "approx_coords", "approximate": True}
        return {"score": None, "zone_rank": None, "communes": "",
                "note": "outside", "approximate": True}
