#!/usr/bin/env python3
"""Слой 2 — сбор объявлений.

    ./.venv/bin/python run_layer2.py                 # все источники
    ./.venv/bin/python run_layer2.py --source orpi   # один
    ./.venv/bin/python run_layer2.py --limit 5       # не больше 5 объявлений
    ./.venv/bin/python run_layer2.py --fresh         # игнорировать кэш страниц

Область поиска берётся из whitelist Слоя 1: обходим только те коммуны, которые
прошли критерии места. Это и экономит запросы, и держит выдачу осмысленной.
"""
from __future__ import annotations

import argparse
import pathlib
import sys
import time
import traceback

import yaml

from layer2 import db, fetcher, pipeline
from layer2.placescore import PlaceMap
from layer2.sources import (century21, laforet, orpi,  # noqa: F401
                            safti)  # регистрируют адаптеры
from layer2.sources.base import REGISTRY, SearchArea

ROOT = pathlib.Path(__file__).resolve().parent


def build_area(cfg_path="config.yaml") -> SearchArea:
    import json
    wl = json.loads((ROOT / "out" / "whitelist.json").read_text(encoding="utf-8"))
    good = {code: c for code, c in wl["communes"].items()
            if c["status"] in ("green", "amber")}
    house = yaml.safe_load((ROOT / cfg_path).read_text(encoding="utf-8")).get("house", {})
    return SearchArea(
        commune_codes=sorted(good),
        commune_names=[c["nom"] for c in good.values()],
        postcodes=sorted({c["cp"] for c in good.values() if c.get("cp")}),
        max_price=house.get("max_price", 350_000),
        min_area=house.get("min_area_m2", 100),
        min_bedrooms=house.get("min_bedrooms", 3),
        min_place_score=house.get("min_place_score", 0),
    )


def wanted(ls, area: SearchArea) -> tuple[bool, str]:
    """Грубый фильтр по критериям дома — до дорогой обработки."""
    if ls.price and ls.price > area.max_price * 1.15:
        return False, f"дорого ({ls.price} €)"
    if ls.area_m2 and ls.area_m2 < area.min_area * 0.85:
        return False, f"мало площади ({ls.area_m2} м²)"
    if ls.bedrooms and ls.bedrooms < area.min_bedrooms:
        return False, f"спален {ls.bedrooms}"
    return True, ""


def run_source(name: str, area: SearchArea, pm: PlaceMap, con, limit: int,
               fresh: bool) -> dict:
    cls = REGISTRY[name]
    fetch = fetcher.make(cls.transport)
    src = cls(area, fetch)
    stats = {"pages": 0, "found": 0, "kept": 0, "new": 0, "skipped": []}
    try:
        urls: list[str] = []
        for su in src.search_urls():
            print(f"  обход: {su}")
            page = fetch.get(su, use_cache=not fresh)
            stats["pages"] += 1
            got = src.parse_list(page, su)
            print(f"    подходящих ссылок: {len(got)}")
            urls.extend(got)

        urls = sorted(set(urls))[:limit] if limit else sorted(set(urls))
        stats["found"] = len(urls)

        for u in urls:
            try:
                page = fetch.get(u, use_cache=not fresh, prepare=src.prepare_page)
                ls = src.parse_listing(page, u)
            except Exception as e:
                print(f"    ! {u[:70]}: {str(e)[:60]}")
                continue
            if not ls:
                stats["skipped"].append((u, "не разобралось"))
                continue
            ok, why = wanted(ls, area)
            if not ok:
                stats["skipped"].append((ls.commune_name or u[:40], why))
                continue
            key, is_new = db.upsert_listing(con, ls)
            ev = pipeline.locate(con, ls, key, pm)
            # Дом мог «переехать» при сверке коммуны по тексту: в ссылке Cluny,
            # а на деле хутор в 20 минутах оттуда, вне радиуса поиска. Такие
            # в выдаче не нужны — карта Слоя 1 про них ничего не знает.
            if ev["score"] is not None and ev["score"] < area.min_place_score:
                con.execute("DELETE FROM listing WHERE key=?", (key,))
                con.commit()
                stats["skipped"].append(
                    (ls.commune_name, f"плохое место ({ev['score']:.0f})"))
                continue
            if ev["score"] is None:
                con.execute("DELETE FROM listing WHERE key=?", (key,))
                con.commit()
                stats["skipped"].append((ls.commune_name, "вне зоны поиска"))
                continue
            pipeline.enrich_photos(con, ls, key, limit=5)
            con.commit()
            stats["kept"] += 1
            stats["new"] += int(is_new)
            print(f"    + {ls.price:>7} € · {ls.area_m2 or '?':>5} м² · "
                  f"{ls.commune_name:<20s} место {ev['score']}")
    finally:
        fetch.close()
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", action="append", help="только этот источник")
    ap.add_argument("--limit", type=int, default=0, help="максимум объявлений на источник")
    ap.add_argument("--fresh", action="store_true", help="не использовать кэш страниц")
    args = ap.parse_args()

    t0 = time.time()
    area = build_area()
    print(f"Зона поиска: {len(area.commune_codes)} коммун, "
          f"{len(area.postcodes)} почтовых индексов")
    print(f"Критерии дома: до {area.max_price} €, от {area.min_area} м², "
          f"от {area.min_bedrooms} спален\n")

    pm = PlaceMap()
    con = db.connect()
    names = args.source or list(REGISTRY)
    names = [n for n in names if n in REGISTRY and n != "jsonld"]

    total = {"kept": 0, "new": 0}
    for name in names:
        print(f"• {name}")
        try:
            st = run_source(name, area, pm, con, args.limit, args.fresh)
        except Exception:
            traceback.print_exc()
            continue
        total["kept"] += st["kept"]
        total["new"] += st["new"]
        print(f"  итого: страниц {st['pages']}, объявлений {st['found']}, "
              f"взято {st['kept']} (новых {st['new']})")
        if st["skipped"]:
            print("  отсеяно:")
            for what, why in st["skipped"][:8]:
                print(f"    − {what}: {why}")

    res = pipeline.rebuild_groups(con)
    print(f"\nГруппы: {res['groups']} из {res['listings']} объявлений "
          f"(дублей {res['duplicates']}, на проверку {res['candidates']})")
    print(f"Готово за {time.time()-t0:.0f} с. Открой Taouse: "
          f"./.venv/bin/python -m layer2.web.app")
    return 0


if __name__ == "__main__":
    sys.exit(main())
