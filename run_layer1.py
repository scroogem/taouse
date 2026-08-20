#!/usr/bin/env python3
"""Слой 1 — «ГДЕ»: карта пригодности вокруг Макона.

    ./.venv/bin/python run_layer1.py [--radius 25] [--cell 200]

Первый запуск качает данные (2–4 мин), дальше всё из кэша (~15 с).
Результат — в out/: map.html, whitelist.json, zones.csv, communes.csv, report.md

Разбор конкретного места:  ./.venv/bin/python explain.py Hurigny
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time

import numpy as np
import yaml

from housemap import export, layers, score, zones
from housemap.grid import Grid

ROOT = pathlib.Path(__file__).resolve().parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--radius", type=float, help="переопределить радиус, км")
    ap.add_argument("--cell", type=int, help="переопределить размер ячейки, м")
    args = ap.parse_args()

    cfg = yaml.safe_load((ROOT / args.config).read_text(encoding="utf-8"))
    a = cfg["area"]
    if args.radius:
        a["radius_km"] = args.radius
    if args.cell:
        a["cell_m"] = args.cell

    t0 = time.time()
    grid = Grid(a["center_lat"], a["center_lon"], a["radius_km"], a["cell_m"])
    print(f"Зона поиска: {a['radius_km']} км вокруг {a['center_lat']}, {a['center_lon']}")
    print(f"Сетка {grid.ny}×{grid.nx}, ячейка {grid.cell:.0f} м "
          f"({int(grid.inside.sum())} в круге)\n")

    L = layers.build(grid, cfg)
    inside_n = int(grid.inside.sum())

    print("\n• Пригодность (пороги с зоной допуска)")
    feas, limiting, labels, stats = score.feasibility(L, cfg, grid.inside)
    for label, key, thr, margin, kind, killed, touched in sorted(
            stats, key=lambda s: (s[4] != "veto", -s[5])):
        tag = "ЗАПРЕТ " if kind == "veto" else "предпоч"
        print(f"  [{tag}] {label:28s} режет {killed/inside_n*100:5.1f}%   "
              f"задевает {touched/inside_n*100:5.1f}%   (порог {thr}, допуск ±{margin})")

    attract = score.attractiveness(L, cfg["soft"])
    field, mask, parts, cinfo = zones.build(L, grid, cfg, feas, attract)
    n_before, n_after = cinfo

    f_in = field[grid.inside]
    print(f"\n• Поле баллов: медиана {np.median(f_in):.0f}, "
          f"лучшие 5% ≥ {np.percentile(f_in, 95):.0f}, максимум {f_in.max():.0f}")
    print(f"• Массивы (балл ≥ {cfg['zones']['min_score']}, "
          f"кластер ≥ {cfg['zones']['min_cluster_cells']} яч.): "
          f"{n_after}, мелких отброшено {n_before - n_after}")
    print(f"  после дробления по вершинам (шаг {cfg['zones']['peak_min_distance_m']} м): "
          f"{int(parts.max())} зон")
    print(f"  площадь: {int(mask.sum())*grid.cell**2/1e6:.0f} км² "
          f"({int(mask.sum())/inside_n*100:.1f}% территории)")

    if not mask.any():
        print("\n! Ни одной зоны. Смягчи пороги или zones.min_score в config.yaml.")
        return 1

    clusters = export.find_clusters(grid, L, field, mask, feas, limiting,
                                    labels, parts)
    communes = export.commune_table(grid, L, field, mask, cfg)
    outdir = ROOT / cfg["output"]["dir"]
    export.write_all(outdir, grid, cfg, L, field, mask, feas, limiting, labels,
                     stats, clusters, communes, cinfo, parts)

    print("\n  ТОП-15 ЗОН:")
    for z in clusters[:15]:
        lim = (f"  слабое место: {z['limit']} ({z['limit_share']:.0%})"
               if z["limit"] else "")
        print(f"   {z['rank']:2d}. {z['score_max']:5.1f}  {z['area_ha']:6.0f} га  "
              f"{z['dist_macon_km']:4.1f} км  {z.get('elev') or 0:4.0f} м  "
              f"{', '.join(z['communes'][:2]):<34s}{lim}")

    green = [c for c in communes if c["status"] == "green"]
    amber = [c for c in communes if c["status"] == "amber"]
    print(f"\n• Коммуны (справочно для Слоя 2): {len(green)} зелёных, {len(amber)} жёлтых")
    print(f"\nГотово за {time.time()-t0:.0f} с. Открой: {outdir/'map.html'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
