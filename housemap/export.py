"""Выгрузка результатов: карта, рейтинг зон, whitelist для Слоя 2, отчёт."""
from __future__ import annotations

import json
import pathlib

import numpy as np
from scipy import ndimage

from . import render
from .grid import Grid, to_wgs

# Метрики в карточке зоны: (слой, подпись, формат в JS)
DETAIL = [
    ("elev", "высота", "m"),
    ("rel_elev_5km", "возвышается над округой", "m+"),
    ("tpi_1km", "выше окрестностей (1 км)", "m+"),
    ("slope_pct", "уклон", "pct_raw"),
    ("southness", "склон на юг", "sun"),
    ("vineyard_share_1km", "виноградники вокруг", "pct"),
    ("farm_share_800m", "поля/луга вокруг", "pct"),
    ("forest_share_1km", "лес вокруг", "pct"),
    ("dist_motorway", "до автомагистрали", "dist"),
    ("dist_junction", "до съезда на автостраду", "dist"),
    ("dist_rail", "до железной дороги", "dist"),
    ("dist_school", "до школы", "dist"),
    ("dist_bakery", "до булочной", "dist"),
    ("dist_market", "до магазина", "dist"),
    ("income_1km", "уровень жизни вокруг", "eur"),
    ("pop_2km", "жителей в 2 км", "int"),
    ("mean_house_m2", "среднее жильё в округе", "m2"),
]

CLICK_GRID = 260  # разрешение массивов для клика в произвольную точку


# ---------------------------------------------------------------------------
# Зоны (связные участки) — то, что пользователь ищет на карте
# ---------------------------------------------------------------------------

def find_clusters(grid: Grid, L: dict, field: np.ndarray, mask: np.ndarray,
                  feas: np.ndarray, limiting: np.ndarray, labels: list[str],
                  parts: np.ndarray):
    lab, n = parts, int(parts.max())
    coms = L["_communes"]
    ci = L["commune_idx"]
    out = []
    for k in range(1, n + 1):
        sel = lab == k
        cells = int(sel.sum())
        f = field[sel]
        # центр — по лучшей четверти ячеек, а не по геометрическому центру:
        # у вытянутой вдоль склона зоны середина может быть худшим её местом
        thr = np.percentile(f, 75)
        best = sel & (field >= thr)
        rr, cc = np.nonzero(best)
        lon, lat = to_wgs(grid.X[rr, cc].mean(), grid.Y[rr, cc].mean())

        idxs = ci[sel]
        names, counts = np.unique(idxs[idxs >= 0], return_counts=True)
        order = np.argsort(-counts)
        com_list = [(coms[int(names[i])]["nom"], coms[int(names[i])]["code"],
                     int(counts[i])) for i in order[:3]]

        rec = {
            "id": k,
            "cells": cells,
            "area_ha": round(cells * (grid.cell ** 2) / 10000, 1),
            "score_max": round(float(f.max()), 1),
            "score_mean": round(float(f.mean()), 1),
            "lat": round(float(lat), 5),
            "lon": round(float(lon), 5),
            "communes": [c[0] for c in com_list],
            "commune_codes": [c[1] for c in com_list],
            "dist_macon_km": round(float(np.hypot(grid.X[rr, cc].mean() - grid.cx,
                                                  grid.Y[rr, cc].mean() - grid.cy)) / 1000, 1),
        }
        # что здесь ближе всего к пределу
        # Слабое место ищем в ЯДРЕ зоны, а не по всей площади: у любой большой
        # зоны края уходят в склоны и ложбины, и по ним выходило, будто вся
        # зона «в низине», хотя её сердцевина — на гребне.
        weak = best & (feas < 0.995) & (limiting < len(labels))
        if weak.sum() >= 0.15 * best.sum():
            li, lc = np.unique(limiting[weak], return_counts=True)
            rec["limit"] = labels[int(li[np.argmax(lc)])]
            rec["limit_share"] = round(float(weak.sum() / best.sum()), 2)
        else:
            rec["limit"] = None
            rec["limit_share"] = 0.0

        for key, _, _ in DETAIL:
            if key in L:
                v = float(np.nanmean(L[key][best]))
                rec[key] = None if np.isnan(v) else round(v, 4)
        out.append(rec)

    out.sort(key=lambda r: (-r["score_max"], -r["cells"]))
    for i, r in enumerate(out, 1):
        r["rank"] = i
    return out


def commune_table(grid: Grid, L: dict, field: np.ndarray, mask: np.ndarray, cfg: dict):
    ci = L["commune_idx"]
    ccfg = cfg["communes"]
    out = []
    for i, c in enumerate(L["_communes"]):
        sel = (ci == i) & grid.inside
        n = int(sel.sum())
        if n == 0:
            continue
        good = sel & mask
        f = field[sel]
        rec = {
            "code": c["code"], "nom": c["nom"],
            "dept": (c.get("departement") or {}).get("code", ""),
            "cp": (c.get("codesPostaux") or [""])[0],
            "population": c.get("population"),
            "dist_macon_km": round(float(np.hypot(c["_xy"][0] - grid.cx,
                                                  c["_xy"][1] - grid.cy)) / 1000, 1),
            "cells_good": int(good.sum()),
            "area_good_ha": round(int(good.sum()) * grid.cell ** 2 / 10000, 1),
            "score_best": round(float(f.max()), 1),
            "score_p90": round(float(np.percentile(f, 90)), 1),
        }
        if good.any():
            rr, cc = np.nonzero(good & (field >= np.percentile(field[good], 75)))
            lon, lat = to_wgs(grid.X[rr, cc].mean(), grid.Y[rr, cc].mean())
            rec["hotspot"] = [round(float(lat), 5), round(float(lon), 5)]
            for key in ("income_1km", "vineyard_share_1km", "elev", "farm_share_800m"):
                if key in L:
                    rec[key] = round(float(np.nanmean(L[key][good])), 3)
        else:
            rec["hotspot"] = None

        if rec["cells_good"] >= ccfg["min_good_cells"] and rec["score_p90"] >= ccfg["green_score"]:
            rec["status"] = "green"
        elif rec["cells_good"] >= ccfg["min_good_cells"] and rec["score_p90"] >= ccfg["amber_score"]:
            rec["status"] = "amber"
        elif rec["cells_good"] > 0:
            rec["status"] = "marginal"
        else:
            rec["status"] = "excluded"
        out.append(rec)
    out.sort(key=lambda r: (-r["score_p90"], -r["cells_good"]))
    return out


# ---------------------------------------------------------------------------

def write_all(outdir: pathlib.Path, grid: Grid, cfg: dict, L: dict, field, mask,
              feas, limiting, labels, stats, clusters, communes, cluster_info,
              parts):
    outdir.mkdir(parents=True, exist_ok=True)

    # сырые зоны для QGIS/Google Earth
    rows, cols = np.nonzero(mask)
    x1 = grid.x0 + cols * grid.cell
    y1 = grid.y0 + rows * grid.cell
    lon1, lat1 = to_wgs(x1, y1)
    lon2, lat2 = to_wgs(x1 + grid.cell, y1 + grid.cell)
    feats = [{"type": "Feature",
              "properties": {"score": round(float(field[r, c]), 1)},
              "geometry": {"type": "Polygon", "coordinates": [[
                  [round(lon1[k], 5), round(lat1[k], 5)], [round(lon2[k], 5), round(lat1[k], 5)],
                  [round(lon2[k], 5), round(lat2[k], 5)], [round(lon1[k], 5), round(lat2[k], 5)],
                  [round(lon1[k], 5), round(lat1[k], 5)]]]}}
             for k, (r, c) in enumerate(zip(rows, cols))]
    (outdir / "zones.geojson").write_text(
        json.dumps({"type": "FeatureCollection", "features": feats}), encoding="utf-8")

    (outdir / "clusters.json").write_text(
        json.dumps(clusters, ensure_ascii=False, indent=1), encoding="utf-8")

    # Поле баллов наружу — Слой 2 по нему оценивает адрес из объявления
    np.savez_compressed(
        outdir / "field.npz", field=field.astype(np.float32),
        mask=mask, parts=parts.astype(np.int32),
        meta=np.array([grid.x0, grid.y0, grid.cell, grid.nx, grid.ny,
                       grid.cx, grid.cy, grid.radius_m], dtype=np.float64))

    wl = {
        "generated_for": {"center": [grid.center_lat, grid.center_lon],
                          "radius_km": grid.radius_m / 1000},
        "green": [r["code"] for r in communes if r["status"] == "green"],
        "amber": [r["code"] for r in communes if r["status"] == "amber"],
        "communes": {r["code"]: {k: r[k] for k in
                                 ("nom", "dept", "cp", "status", "score_p90",
                                  "area_good_ha", "hotspot", "dist_macon_km")}
                     for r in communes if r["status"] != "excluded"},
        "zones": [{k: z[k] for k in ("rank", "lat", "lon", "score_max", "area_ha",
                                     "communes", "commune_codes")} for z in clusters],
    }
    (outdir / "whitelist.json").write_text(json.dumps(wl, ensure_ascii=False, indent=1),
                                           encoding="utf-8")

    _csv(outdir / "zones.csv",
         ["rank", "score_max", "score_mean", "area_ha", "dist_macon_km", "communes",
          "elev", "rel_elev_5km", "limit", "limit_share", "vineyard_share_1km",
          "farm_share_800m", "income_1km", "dist_motorway", "dist_school",
          "lat", "lon"], clusters)
    _csv(outdir / "communes.csv",
         ["status", "nom", "cp", "dept", "code", "dist_macon_km", "population",
          "score_p90", "score_best", "area_good_ha", "income_1km",
          "vineyard_share_1km", "farm_share_800m", "elev", "hotspot"],
         [c for c in communes if c["status"] != "excluded"])

    write_map(outdir / "map.html", grid, cfg, L, field, feas, limiting, labels, clusters)
    write_report(outdir / "report.md", grid, cfg, stats, clusters, communes, mask,
                 cluster_info)


def _csv(path, cols, rows):
    lines = [";".join(cols)]
    for r in rows:
        vals = []
        for c in cols:
            v = r.get(c, "")
            if isinstance(v, list):
                v = ", ".join(str(x) for x in v)
            vals.append(str(v).replace(";", ","))
        lines.append(";".join(vals))
    path.write_text("\n".join(lines), encoding="utf-8")


def write_report(path, grid, cfg, stats, clusters, communes, mask, cluster_info):
    inside = int(grid.inside.sum())
    n_before, n_after = cluster_info
    out = []
    out.append("# Слой 1 — карта пригодности вокруг Макона\n")
    out.append(f"Радиус {grid.radius_m/1000:.0f} км, ячейка {grid.cell:.0f} м, "
               f"{inside} ячеек в круге.\n")
    out.append(f"**Зон найдено: {n_after}** (мелких отсеяно {n_before - n_after}), "
               f"суммарно {int(mask.sum())} ячеек — "
               f"{int(mask.sum())*grid.cell**2/1e6:.0f} км², "
               f"{int(mask.sum())/inside*100:.1f}% территории.\n")

    out.append("\n## Насколько критерии ограничивают территорию\n")
    out.append("«Полностью режет» — где критерий провален настолько, что место "
               "исключено. «Задевает» — где он снижает балл, но не убивает.\n")
    out.append("| критерий | тип | порог | зона допуска | режет | задевает |")
    out.append("|---|---|---|---|---|---|")
    for label, key, thr, margin, kind, killed, touched in sorted(
            stats, key=lambda s: (s[4] != "veto", -s[5])):
        out.append(f"| {label} | {'запрет' if kind=='veto' else 'предпочтение'} | "
                   f"`{key}` = {thr} | ±{margin} | "
                   f"{killed} ({killed/inside*100:.0f}%) | {touched/inside*100:.0f}% |")

    out.append(f"\n## Лучшие зоны ({len(clusters)})\n")
    out.append("Балл принадлежит месту, а не коммуне: у зоны может быть две-три "
               "коммуны, и это нормально — граница между ними ничего не меняет.\n")
    out.append("| # | балл | площадь | от Макона | высота | над долиной | коммуны | слабое место |")
    out.append("|---|---|---|---|---|---|---|---|")
    for z in clusters[:cfg["output"]["top_n_report"]]:
        lim = (f"{z['limit']} ({z['limit_share']:.0%})" if z["limit"] else "—")
        out.append(f"| {z['rank']} | **{z['score_max']}** (ср. {z['score_mean']}) | "
                   f"{z['area_ha']:.0f} га | {z['dist_macon_km']} км | "
                   f"{z.get('elev') or 0:.0f} м | +{z.get('rel_elev_5km') or 0:.0f} м | "
                   f"{', '.join(z['communes'])} | {lim} |")

    green = [c for c in communes if c["status"] == "green"]
    amber = [c for c in communes if c["status"] == "amber"]
    out.append(f"\n## Коммуны — справочно ({len(green)} зелёных, {len(amber)} жёлтых)\n")
    out.append("Нужны Слою 2: объявления привязаны к коммунам, а не к зонам.\n")
    out.append("| коммуна | от Макона | балл (p90) | хорошей земли | доход €/чел |")
    out.append("|---|---|---|---|---|")
    for c in (green + amber)[:cfg["output"]["top_n_report"]]:
        out.append(f"| {'**' if c['status']=='green' else ''}{c['nom']}"
                   f"{'**' if c['status']=='green' else ''} ({c['cp']}) | "
                   f"{c['dist_macon_km']} км | {c['score_p90']} | "
                   f"{c['area_good_ha']:.0f} га | {c.get('income_1km',0):.0f} |")
    path.write_text("\n".join(out), encoding="utf-8")


MAP_TEMPLATE = """<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Дом под Маконом — карта пригодности</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
 html,body,#map{height:100%;margin:0;font:14px/1.45 system-ui,-apple-system,sans-serif}
 .panel{position:absolute;top:10px;right:10px;z-index:1000;background:#fff;border-radius:10px;
   box-shadow:0 2px 16px rgba(0,0,0,.28);padding:12px 14px;width:290px;max-height:90vh;overflow:auto}
 .panel h3{margin:0 0 4px;font-size:15px}
 .panel h4{margin:12px 0 5px;font-size:12px;color:#666;text-transform:uppercase;letter-spacing:.04em}
 .sub{font-size:12px;color:#555;margin-bottom:2px}
 .bar{height:12px;border-radius:3px;margin:5px 0 3px;
   background:linear-gradient(to right,#c4a864,#e9dc6e,#96cd6e,#3ca56e,#1e7882,#284678)}
 .bl{display:flex;justify-content:space-between;font-size:11px;color:#666}
 table.t{border-collapse:collapse;width:100%;font-size:12px}
 table.t td{padding:3px 4px;border-bottom:1px solid #eee;vertical-align:top}
 table.t td:first-child{color:#666}
 .rank tr{cursor:pointer} .rank tr:hover{background:#eef5ef}
 .num{display:inline-block;min-width:24px;text-align:center;padding:1px 5px;border-radius:9px;
   color:#fff;font-size:11px;font-weight:600}
 .pop b{font-size:14px} .pop .sc{float:right;color:#fff;padding:1px 8px;border-radius:9px;font-weight:600}
 .lim{background:#fff5e0;border-left:3px solid #e0a63a;padding:4px 7px;margin:6px 0;font-size:12px}
 .hint{font-size:11px;color:#888;margin-top:8px;line-height:1.35}
</style></head><body>
<div id="map"></div>
<div class="panel">
  <h3>Где искать дом · Макон</h3>
  <div class="sub">__SUMMARY__</div>
  <div class="bar"></div>
  <div class="bl"><span>хуже</span><span>лучше</span></div>
  <div class="hint">Цвет — насколько место подходит. Переходы плавные:
    резких границ в реальности нет. Кликни в любую точку карты — покажу балл
    и что именно там мешает.</div>
  <h4>Лучшие зоны</h4>
  <table class="t rank">__RANK__</table>
</div>
<script>
const IMG=__IMG__, BOUNDS=__BOUNDS__, CENTER=__CENTER__, ZONES=__ZONES__;
const FIELDS=__FIELDS__, LABELS=__LABELS__;
const GS=__GS__, SCORE_LO=__SLO__, SCORE_HI=__SHI__;
const b64=s=>{const r=atob(s),a=new Uint8Array(r.length);
  for(let i=0;i<r.length;i++)a[i]=r.charCodeAt(i);return a;};
const SCORE=b64("__SCORE_DATA__"), LIMIT=b64("__LIMIT_DATA__");

const map=L.map('map',{preferCanvas:true}).setView(CENTER,11);
const base=L.tileLayer('https://{s}.tile.openstreetmap.fr/osmfr/{z}/{x}/{y}.png',
  {maxZoom:18,attribution:'© OpenStreetMap'}).addTo(map);
const relief=L.tileLayer('https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png',
  {maxZoom:17,attribution:'© OpenTopoMap'});
const sat=L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
  {maxZoom:18,attribution:'© Esri'});
L.control.scale({imperial:false}).addTo(map);

const overlay=L.imageOverlay(IMG,[[BOUNDS[0],BOUNDS[1]],[BOUNDS[2],BOUNDS[3]]],
  {opacity:.72,interactive:false}).addTo(map);

function color(s){
  const st=[[0,'#8c96a0'],[30,'#c4a864'],[45,'#e9dc6e'],[60,'#96cd6e'],
            [72,'#3ca56e'],[85,'#1e7882']];
  let c=st[0][1]; for(const [v,col] of st) if(s>=v) c=col; return c;
}
function fmt(v,f){
  switch(f){
    case 'pct': return (v*100).toFixed(0)+'%';
    case 'pct_raw': return v.toFixed(0)+'%';
    case 'm': return Math.round(v)+' м';
    case 'm+': return (v>=0?'+':'')+Math.round(v)+' м';
    case 'm2': return Math.round(v)+' м²';
    case 'int': return Math.round(v).toLocaleString('ru');
    case 'eur': return Math.round(v).toLocaleString('ru')+' €/чел';
    case 'dist': return v>=2000?(v/1000).toFixed(1)+' км':Math.round(v)+' м';
    case 'sun': return v>0.35?'да':(v<-0.2?'нет, на север':'нейтрально');
    default: return Math.round(v*100)/100;
  }
}
// нормализованные координаты Web Mercator -> индекс в массивах
function cellAt(lat,lon){
  const x=lon/360+0.5, s=Math.sin(lat*Math.PI/180);
  const y=0.5-Math.log((1+s)/(1-s))/(4*Math.PI);
  const [mx0,my0,mx1,my1]=BOUNDS.slice(4);
  const c=Math.floor((x-mx0)/(mx1-mx0)*GS), r=Math.floor((y-my0)/(my1-my0)*GS);
  if(c<0||r<0||c>=GS||r>=GS) return null;
  const i=r*GS+c, q=SCORE[i];
  if(q===0) return null;
  return {score:SCORE_LO+(q-1)/254*(SCORE_HI-SCORE_LO), limit:LIMIT[i]};
}
map.on('click', e=>{
  const d=cellAt(e.latlng.lat,e.latlng.lng);
  if(!d){L.popup().setLatLng(e.latlng).setContent('за пределами зоны расчёта').openOn(map);return;}
  const lim=(d.limit<LABELS.length)?LABELS[d.limit]:null;
  let h=`<div class="pop"><span class="sc" style="background:${color(d.score)}">`
       +`${d.score.toFixed(0)}</span><b>Балл места</b><br>`;
  h+= d.score>=60?'<div style="color:#2a7">подходит</div>'
    : d.score>=45?'<div style="color:#a80">на грани</div>'
    : '<div style="color:#a33">не подходит</div>';
  if(lim) h+=`<div class="lim">Ограничивает: <b>${lim}</b></div>`;
  h+=`<div class="hint">${e.latlng.lat.toFixed(5)}, ${e.latlng.lng.toFixed(5)}</div></div>`;
  L.popup({maxWidth:280}).setLatLng(e.latlng).setContent(h).openOn(map);
});

const markers=L.layerGroup().addTo(map);
ZONES.forEach(z=>{
  const m=L.circleMarker([z.lat,z.lon],{radius:Math.min(16,7+Math.sqrt(z.area_ha)/3),
    color:'#fff',weight:2,fillColor:color(z.score_max),fillOpacity:.95});
  let h=`<div class="pop"><span class="sc" style="background:${color(z.score_max)}">`
       +`${z.score_max}</span><b>Зона №${z.rank}</b><br>`
       +`<span style="color:#666;font-size:12px">${z.communes.join(' / ')} · `
       +`${z.area_ha.toFixed(0)} га · ${z.dist_macon_km} км от Макона</span>`;
  if(z.limit) h+=`<div class="lim">Слабое место: <b>${z.limit}</b>`
    +` — на ${Math.round(z.limit_share*100)}% лучшей части зоны</div>`;
  h+='<table class="t">';
  for(const [k,label,f] of FIELDS){
    if(z[k]===null||z[k]===undefined) continue;
    h+=`<tr><td>${label}</td><td align="right"><b>${fmt(z[k],f)}</b></td></tr>`;
  }
  h+=`</table><div style="margin-top:6px;font-size:12px">`
    +`<a target="_blank" href="https://www.google.com/maps/@${z.lat},${z.lon},15z/data=!3m1!1e3">спутник</a> · `
    +`<a target="_blank" href="https://www.geoportail.gouv.fr/carte?c=${z.lon},${z.lat}&z=16&l0=ORTHOIMAGERY.ORTHOPHOTOS">Géoportail</a></div></div>`;
  m.bindPopup(h,{maxWidth:340}); markers.addLayer(m);
});

L.control.layers({'Карта OSM':base,'Рельеф':relief,'Спутник':sat},
  {'Пригодность (заливка)':overlay,'Лучшие зоны':markers}).addTo(map);
function go(lat,lon){map.setView([lat,lon],14);}
</script></body></html>
"""


def write_map(path, grid, cfg, L, field, feas, limiting, labels, clusters):
    (s, w, n, e), (mx0, my0, mx1, my1) = render.merc_bounds(grid)
    img = render.field_png(field, grid, size=900, vmin=14, vmax=86, fade_below=8)
    lo, hi = 0.0, 100.0
    score_b64 = render.quantized(field, grid, CLICK_GRID, lo, hi)
    limit_b64 = render.quantized_int(limiting, grid, CLICK_GRID)

    summary = (f"{len(clusters)} зон, "
               f"{sum(z['area_ha'] for z in clusters)/100:.0f} км² подходящей земли<br>"
               f"радиус {grid.radius_m/1000:.0f} км от Макона")

    rank = "".join(
        f'<tr onclick="go({z["lat"]},{z["lon"]})">'
        f'<td><span class="num" style="background:{_col(z["score_max"])}">'
        f'{z["score_max"]:.0f}</span></td>'
        f'<td><b>{", ".join(z["communes"][:2])}</b><br>'
        f'<span style="color:#888;font-size:11px">{z["area_ha"]:.0f} га · '
        f'{z["dist_macon_km"]:.0f} км' + (f' · {z["limit"]}' if z["limit"] else '')
        + '</span></td></tr>'
        for z in clusters[:22])

    html = (MAP_TEMPLATE
            .replace("__IMG__", json.dumps(img))
            .replace("__BOUNDS__", json.dumps([s, w, n, e, mx0, my0, mx1, my1]))
            .replace("__CENTER__", json.dumps([grid.center_lat, grid.center_lon]))
            .replace("__ZONES__", json.dumps(clusters, ensure_ascii=False))
            .replace("__FIELDS__", json.dumps(DETAIL, ensure_ascii=False))
            .replace("__LABELS__", json.dumps(labels, ensure_ascii=False))
            .replace("__GS__", str(CLICK_GRID))
            .replace("__SLO__", str(lo)).replace("__SHI__", str(hi))
            .replace("__SCORE_DATA__", score_b64)
            .replace("__LIMIT_DATA__", limit_b64)
            .replace("__SUMMARY__", summary)
            .replace("__RANK__", rank))
    path.write_text(html, encoding="utf-8")


def _col(s):
    for v, c in [(85, "#1e7882"), (72, "#3ca56e"), (60, "#96cd6e"),
                 (45, "#e9dc6e"), (30, "#c4a864")]:
        if s >= v:
            return c
    return "#8c96a0"
