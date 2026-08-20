#!/usr/bin/env python3
"""Разбор: почему конкретное место проходит или не проходит.

    ./.venv/bin/python explain.py Hurigny
    ./.venv/bin/python explain.py 46.3400,4.7800

Показывает по каждому критерию не только «да/нет», а насколько место близко к
порогу — с зоной допуска граница перестала быть обрывом, и важно видеть, идёт
речь о промахе на волос или о безнадёжном месте.
"""
from __future__ import annotations

import pathlib
import sys

import numpy as np
import yaml

from housemap import layers, score, zones
from housemap.grid import Grid, to_l93

ROOT = pathlib.Path(__file__).resolve().parent


def bar(p: float, width: int = 12) -> str:
    n = int(round(p * width))
    return "█" * n + "·" * (width - n)


def verdict(p: float) -> str:
    return "ок" if p >= 0.999 else ("почти" if p >= 0.5 else
                                    ("слабо" if p > 0 else "НЕТ"))


def load():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    a = cfg["area"]
    grid = Grid(a["center_lat"], a["center_lon"], a["radius_km"], a["cell_m"])
    L = layers.build(grid, cfg)
    feas, limiting, labels, _ = score.feasibility(L, cfg, grid.inside)
    attract = score.attractiveness(L, cfg["soft"])
    field, mask, _, _ = zones.build(L, grid, cfg, feas, attract)
    return cfg, grid, L, feas, limiting, labels, attract, field, mask


def rules(cfg):
    for key, layer, direction, label, dm, kind, w in score.HARD_RULES:
        thr = cfg["hard"].get(key)
        if thr is None:
            continue
        margin = (cfg.get("margins") or {}).get(key, dm)
        if margin is None:
            margin = abs(thr) * float(cfg.get("tolerance", 0))
        yield key, layer, direction, label, thr, margin, kind


def cell_report(L, cfg, r, c, title, field, attract):
    print(f"\n{'='*78}\n{title}\n{'='*78}")
    print("(! = запрет, остальное — предпочтения)")
    print(f"{'критерий':30s} {'значение':>11s} {'нужно':>12s}  {'оценка':<14s} вердикт")
    print("-" * 78)
    worst = []
    for key, layer, direction, label, thr, margin, kind in rules(cfg):
        if layer not in L:
            continue
        v = float(L[layer][r, c])
        p = float(score._membership(np.array([v]), thr, direction, margin)[0])
        sign = "≥" if direction == "min" else "≤"
        tag = "!" if kind == "veto" else " "
        print(f"{tag}{label:29s} {v:11.1f} {sign}{thr:>9}  {bar(p)}  {verdict(p)}")
        worst.append((p, label))
    worst.sort()
    print("-" * 78)
    print(f"привлекательность места: {attract[r,c]:.0f}/100")
    lim = ("ничего — все критерии выполнены" if worst[0][0] >= 0.995
           else f"{worst[0][1]} (оценка {worst[0][0]:.2f})")
    print(f"ограничивающий фактор:   {lim}")
    print(f"ИТОГОВЫЙ БАЛЛ (сглаженный): {field[r,c]:.1f}")


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    target = sys.argv[1]
    cfg, grid, L, feas, limiting, labels, attract, field, mask = load()

    if "," in target:
        lat, lon = [float(x) for x in target.split(",")]
        x, y = to_l93(lon, lat)
        c = int((x - grid.x0) / grid.cell)
        r = int((y - grid.y0) / grid.cell)
        if not (0 <= r < grid.ny and 0 <= c < grid.nx):
            print("Точка вне области расчёта.")
            return 1
        cell_report(L, cfg, r, c, f"Точка {lat}, {lon}", field, attract)
        print(f"попадает в найденную зону: {'ДА' if mask[r,c] else 'нет'}")
        return 0

    coms = L["_communes"]
    idx = [i for i, c in enumerate(coms) if c["nom"].lower() == target.lower()]
    if not idx:
        idx = [i for i, c in enumerate(coms) if target.lower() in c["nom"].lower()]
    if not idx:
        print(f"Коммуна '{target}' не найдена в радиусе поиска.")
        near = sorted(coms, key=lambda c: np.hypot(c["_xy"][0] - grid.cx,
                                                   c["_xy"][1] - grid.cy))
        print("Ближайшие:", ", ".join(c["nom"] for c in near[:15]))
        return 1

    i = idx[0]
    com = coms[i]
    sel = (L["commune_idx"] == i) & grid.inside
    n = int(sel.sum())
    print(f"\n{'='*78}")
    print(f"{com['nom']} ({com['code']}), население {com.get('population')}, "
          f"{n} ячеек по {grid.cell:.0f} м")
    print(f"{'='*78}")
    f = field[sel]
    print(f"балл: лучший {f.max():.1f}, p90 {np.percentile(f,90):.1f}, "
          f"медиана {np.median(f):.1f}")
    print(f"попало в зоны: {int((sel & mask).sum())} ячеек "
          f"({int((sel & mask).sum())*grid.cell**2/1e4:.0f} га)\n")

    print(f"{'критерий':30s} {'медиана':>10s} {'лучшее':>10s} {'нужно':>11s}  "
          f"{'ср.оценка':<13s}")
    print("-" * 78)
    rows = []
    for key, layer, direction, label, thr, margin, kind in rules(cfg):
        if layer not in L:
            continue
        v = L[layer][sel]
        v = v[~np.isnan(v)]
        if not len(v):
            continue
        p = score._membership(v, thr, direction, margin)
        best = float(v.max() if direction == "min" else v.min())
        rows.append((float(p.mean()), label, float(np.median(v)), best, thr,
                     direction, kind))
    for pm, label, med, best, thr, d, kind in sorted(rows):
        sign = "≥" if d == "min" else "≤"
        tag = "!" if kind == "veto" else " "
        flag = "  <<< главное ограничение" if pm < 0.35 else ""
        print(f"{tag}{label:29s} {med:10.1f} {best:10.1f} {sign}{thr:>10}  {bar(pm)}{flag}")

    if sel.any():
        masked = np.where(sel, field, -1)
        r, c = np.unravel_index(np.argmax(masked), masked.shape)
        cell_report(L, cfg, r, c, f"Лучшая точка в {com['nom']}", field, attract)
        lon, lat = __import__("housemap.grid", fromlist=["to_wgs"]).to_wgs(
            grid.X[r, c], grid.Y[r, c])
        print(f"координаты: {lat:.5f}, {lon:.5f}")
        print(f"спутник: https://www.google.com/maps/@{lat:.5f},{lon:.5f},15z/data=!3m1!1e3")
    return 0


if __name__ == "__main__":
    sys.exit(main())
