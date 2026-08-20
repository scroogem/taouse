"""Сборка всех метрик на сетке: рельеф + OSM + INSEE -> словарь numpy-слоёв."""
from __future__ import annotations

import numpy as np

from . import rasterize as rz
from . import terrain
from .grid import Grid
from .sources import communes as communes_src
from .sources import insee, overpass

# Только то, что мама действительно не хочет видеть вокруг: пашня и луга.
# ВАЖНО: landuse=grass — это газоны, обочины и зелень внутри посёлков, а вовсе
# не пастбище; allotments — дачные огороды. Раньше они шли сюда и без причины
# резали нормальные места (в Hurigny — 9% территории).
FARM_TAGS = {"farmland", "meadow"}
FOREST_LANDUSE = {"forest"}
FOREST_NATURAL = {"wood", "scrub", "heath"}
NUISANCE_LANDUSE = {"industrial", "military", "construction"}
BIG_INDUSTRY_M2 = 30_000  # 3 га — граница между заводом и «зоной ремесленников»


def _area(coords: np.ndarray) -> float:
    x, y = coords[:, 0], coords[:, 1]
    return 0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1)))


def _is_active_rail(t: dict) -> bool:
    if t.get("railway") not in ("rail", "light_rail", "narrow_gauge"):
        return False
    if any(t.get(k) in ("yes", "rail") for k in ("disused", "abandoned", "razed")):
        return False
    if t.get("service") in ("siding", "spur", "yard", "crossover"):
        return False
    if t.get("usage") in ("industrial", "military", "tourism"):
        return False
    return True


def _is_highspeed(t: dict) -> bool:
    return t.get("highspeed") == "yes" or t.get("usage") == "highspeed"


def build(grid: Grid, cfg: dict) -> dict:
    L: dict[str, np.ndarray] = {}

    print("• Рельеф (SRTM 30 м)")
    L.update(terrain.build(grid))

    print("• Дороги и железные дороги (OSM)")
    mot = overpass.lines(overpass.fetch("motorway", grid))
    trunk = overpass.lines(overpass.fetch("trunk_primary", grid))
    rail_all = overpass.lines(overpass.fetch("rail", grid), keep=_is_active_rail)
    rail_hs = [(c, t) for c, t in rail_all if _is_highspeed(t)]
    junc = overpass.points(overpass.fetch("junction", grid))

    L["dist_motorway"] = rz.dist_to_geoms(grid, mot)
    L["dist_trunk_primary"] = rz.dist_to_geoms(grid, trunk)
    L["dist_rail"] = rz.dist_to_geoms(grid, rail_all)
    L["dist_rail_highspeed"] = rz.dist_to_geoms(grid, rail_hs)
    L["dist_junction"] = rz.dist_to_points(grid, junc)
    print(f"  автомагистрали {len(mot)}, нац/деп {len(trunk)}, ж/д {len(rail_all)} "
          f"(из них LGV {len(rail_hs)}), съездов {len(junc)}")

    print("• Землепользование (OSM)")
    nature = overpass.fetch("nature", grid)
    built = overpass.fetch("built", grid)

    def lu(data, landuse=None, natural=None):
        return overpass.polygons(data, keep=lambda t: (
            (landuse and t.get("landuse") in landuse) or
            (natural and t.get("natural") in natural)))

    farm = lu(nature, landuse=FARM_TAGS, natural={"grassland"})
    vine = lu(nature, landuse={"vineyard"})
    orch = lu(nature, landuse={"orchard"})
    forest = lu(nature, landuse=FOREST_LANDUSE, natural=FOREST_NATURAL)
    water = lu(nature, natural={"water", "wetland"})
    resid = lu(built, landuse={"residential"})
    print(f"  поля/луга {len(farm)}, виноградники {len(vine)}, сады {len(orch)}, "
          f"лес {len(forest)}, жилая застройка {len(resid)}")

    farm_r = rz.rasterize(grid, farm)
    L["farm_share_800m"] = rz.focal_mean(farm_r, grid, 800)
    L["vineyard_share_1km"] = rz.focal_mean(rz.rasterize(grid, vine), grid, 1000)
    L["orchard_share_1km"] = rz.focal_mean(rz.rasterize(grid, orch), grid, 1000)
    L["forest_share_1km"] = rz.focal_mean(rz.rasterize(grid, forest), grid, 1000)
    L["water_share_500m"] = rz.focal_mean(rz.rasterize(grid, water), grid, 500)
    L["resid_share_1km"] = rz.focal_mean(rz.rasterize(grid, resid), grid, 1000)

    print("• Источники беспокойства (OSM)")
    farmyard = overpass.polygons(built, keep=lambda t: t.get("landuse") == "farmyard")

    # Карьер, свалка, очистные, аэродром, электростанция — плохи в любом размере.
    heavy = overpass.polygons(built, keep=lambda t: (
        t.get("landuse") in ("quarry", "landfill")
        or t.get("man_made") == "wastewater_plant"
        or t.get("amenity") in ("waste_transfer_station", "waste_disposal")
        or t.get("aeroway") == "aerodrome"
        or t.get("power") == "plant"))
    # А вот landuse=industrial — это и завод, и «зона ремесленников» на три ангара
    # при въезде в деревню. Разводим по площади, иначе фильтр съедает всё подряд.
    indus = overpass.polygons(built, keep=lambda t: t.get("landuse") in NUISANCE_LANDUSE)
    big = [p for p in indus if _area(p[0]) >= BIG_INDUSTRY_M2]
    small = [p for p in indus if _area(p[0]) < BIG_INDUSTRY_M2]

    nuis_pt = overpass.points(built, keep=lambda t: (
        t.get("power") == "plant" or t.get("generator:source") == "wind"))
    L["dist_farmyard"] = rz.dist_to_polys(grid, farmyard)
    L["dist_nuisance"] = np.minimum.reduce([
        rz.dist_to_polys(grid, heavy),
        rz.dist_to_polys(grid, big),
        rz.dist_to_points(grid, nuis_pt)])
    L["dist_light_industry"] = rz.dist_to_polys(grid, small)
    print(f"  скотных дворов {len(farmyard)}, карьеров/свалок/очистных {len(heavy)}, "
          f"крупных промзон {len(big)}, мелких ремесленных зон {len(small)}")

    print("• Услуги (OSM)")
    svc = overpass.fetch("services", grid)
    schools = overpass.points(svc, keep=lambda t: t.get("amenity") in ("school", "kindergarten"))
    bakery = overpass.points(svc, keep=lambda t: t.get("shop") == "bakery")
    market = overpass.points(svc, keep=lambda t: t.get("shop") in ("supermarket", "convenience"))
    pharm = overpass.points(svc, keep=lambda t: t.get("amenity") == "pharmacy")
    L["dist_school"] = rz.dist_to_points(grid, schools)
    L["dist_bakery"] = rz.dist_to_points(grid, bakery)
    L["dist_market"] = rz.dist_to_points(grid, market)
    L["dist_pharmacy"] = rz.dist_to_points(grid, pharm)
    L["dist_services"] = np.maximum.reduce([L["dist_school"], L["dist_bakery"], L["dist_market"]])
    print(f"  школ {len(schools)}, булочных {len(bakery)}, магазинов {len(market)}, "
          f"аптек {len(pharm)}")

    places = overpass.points(overpass.fetch("places", grid))
    vill = [p for p in places if p[1].get("place") in ("village", "town", "city")]
    L["dist_village"] = rz.dist_to_points(grid, vill)

    print("• Демография и доходы (INSEE)")
    ins = insee.load(grid)
    pop2 = rz.focal_sum(ins["pop"], grid, 2000)
    L["pop_2km"] = pop2
    L["pop_1km"] = rz.focal_sum(ins["pop"], grid, 1000)

    snv1 = rz.focal_sum(ins["snv"], grid, 1000)
    pop1 = np.maximum(L["pop_1km"], 1e-6)
    income = np.where(L["pop_1km"] > 30, snv1 / pop1, np.nan)
    # там, где мало людей в 1 км, смотрим шире — иначе вся деревня получит NaN
    snv3 = rz.focal_sum(ins["snv"], grid, 3000)
    pop3 = rz.focal_sum(ins["pop"], grid, 3000)
    wide = np.where(pop3 > 30, snv3 / np.maximum(pop3, 1e-6), np.nan)
    L["income_1km"] = np.where(np.isnan(income), wide, income)

    hh = np.maximum(rz.focal_sum(ins["households"], grid, 1000), 1e-6)
    dw = np.maximum(rz.focal_sum(ins["dwellings"], grid, 1000), 1e-6)
    L["social_housing_share_1km"] = np.clip(
        rz.focal_sum(ins["social_housing"], grid, 1000) / dw, 0, 1)
    L["poor_share_1km"] = np.clip(rz.focal_sum(ins["poor_households"], grid, 1000) / hh, 0, 1)
    L["house_share_1km"] = np.clip(rz.focal_sum(ins["houses"], grid, 1000) / hh, 0, 1)
    L["mean_house_m2"] = rz.focal_sum(ins["living_area"], grid, 1000) / hh

    print("• Границы коммун")
    coms = communes_src.load(grid)
    L["_communes"] = coms
    L["commune_idx"] = _commune_index(grid, coms)

    return L


def _commune_index(grid: Grid, coms: list[dict]) -> np.ndarray:
    """Для каждой ячейки — индекс коммуны (или -1)."""
    idx = np.full(grid.shape, -1, dtype=np.int32)
    for i, c in enumerate(coms):
        rings = communes_src.contour_rings(c)
        if not rings:
            continue
        mask = rz.rasterize(grid, [(r, {}) for r in rings], ss=1) > 0.5
        idx[mask & (idx < 0)] = i
    # ячейки без контура (дырки растеризации) — по ближайшему центру коммуны
    miss = (idx < 0) & grid.inside
    if miss.any() and coms:
        cx = np.array([c["_xy"][0] for c in coms])
        cy = np.array([c["_xy"][1] for c in coms])
        px = grid.X[miss][:, None]
        py = grid.Y[miss][:, None]
        idx[miss] = np.argmin((px - cx) ** 2 + (py - cy) ** 2, axis=1)
    return idx
