"""INSEE Filosofi — данные по сетке 200 м (opendatasoft).

Это ключ к двум «мягким» критериям, которые иначе пришлось бы угадывать:
  * «поблагополучней» -> ind_snv / pop_carr = средний уровень жизни, €/чел/год
  * «не 3 дома»       -> pop_carr = реальные жители в квадрате 200 м
Плюс бонусом: доля соцжилья, доля бедных домохозяйств, средняя площадь жилья.
"""
from __future__ import annotations

import numpy as np

from .. import http
from ..cache import cached_json
from ..grid import Grid, to_l93

DATASET = "demographyref-france-donnees-carroyees-200m"
BASE = f"https://public.opendatasoft.com/api/explore/v2.1/catalog/datasets/{DATASET}"

FIELDS = ["geo_point_2d", "pop_carr", "ind_snv", "men", "men_pauv", "men_surf",
          "men_mais", "men_coll", "log_soc", "log_av45", "log_45_70", "log_70_90",
          "log_ap_90", "log_inc"]


def _download(lat: float, lon: float, radius_km: float) -> list[dict]:
    where = f"within_distance(geo_point_2d, GEOM'POINT({lon} {lat})', {radius_km:.1f}km)"
    r = http.get(f"{BASE}/exports/json",
                     params={"where": where, "select": ",".join(FIELDS), "limit": -1},
                     timeout=600)
    r.raise_for_status()
    return r.json()


def load(grid: Grid) -> dict[str, np.ndarray]:
    rad = grid.radius_m / 1000.0 + 2
    key = f"{DATASET}|{grid.center_lat}|{grid.center_lon}|{rad}"
    rows = cached_json("insee", key,
                       lambda: _download(grid.center_lat, grid.center_lon, rad),
                       label="INSEE carroyage 200 м")
    print(f"  {len(rows)} населённых квадратов 200 м")

    lon = np.array([r["geo_point_2d"]["lon"] for r in rows])
    lat = np.array([r["geo_point_2d"]["lat"] for r in rows])
    x, y = to_l93(lon, lat)
    col = np.floor((x - grid.x0) / grid.cell).astype(int)
    row = np.floor((y - grid.y0) / grid.cell).astype(int)
    ok = (col >= 0) & (col < grid.nx) & (row >= 0) & (row < grid.ny)

    def acc(field, default=0.0):
        v = np.array([(r.get(field) if r.get(field) is not None else default) for r in rows],
                     dtype=np.float32)
        a = np.zeros(grid.shape, dtype=np.float32)
        np.add.at(a, (row[ok], col[ok]), v[ok])
        return a

    log_total = sum(acc(f) for f in ("log_av45", "log_45_70", "log_70_90", "log_ap_90", "log_inc"))

    return {
        "pop": acc("pop_carr"),
        "snv": acc("ind_snv"),          # сумма уровней жизни (€/год) по жителям
        "households": acc("men"),
        "poor_households": acc("men_pauv"),
        "living_area": acc("men_surf"),  # суммарная жилая площадь, м²
        "houses": acc("men_mais"),
        "flats": acc("men_coll"),
        "social_housing": acc("log_soc"),
        "dwellings": log_total,
    }
