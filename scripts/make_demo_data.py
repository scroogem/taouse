#!/usr/bin/env python3
"""Демонстрационный набор объявлений — чтобы проверить систему целиком.

Это НЕ реальные объявления: source='demo'. Коммуны и адреса настоящие, поэтому
геокодирование и оценка места работают по-честному. Специально заложены три
случая, ради которых всё и затевалось:

  * один дом подан двумя агентствами с разными текстами, ценами (FAI и без)
    и одними и теми же фотографиями — должен склеиться;
  * два разных, но похожих по цифрам дома в одной коммуне — склеиться не должны;
  * дом в пойме у железной дороги — должен получить низкий балл места.

Удалить демо: ./.venv/bin/python scripts/make_demo_data.py --clear
"""
from __future__ import annotations

import argparse
import io
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from layer2 import db, imagehash, pipeline  # noqa: E402
from layer2.models import Listing, Photo  # noqa: E402
from layer2.placescore import PlaceMap  # noqa: E402

PHOTO_DIR = pathlib.Path(__file__).resolve().parent.parent / "data" / "demo_photos"


def make_photo(seed: int, watermark: str | None = None, size=(900, 675)) -> bytes:
    """Псевдо-фотография: плавные пятна вместо шума, как настоящий кадр."""
    rng = np.random.default_rng(seed)
    img = Image.fromarray(rng.integers(40, 215, (10, 14, 3), dtype=np.uint8))
    img = img.resize(size, Image.BICUBIC)
    if watermark:
        d = ImageDraw.Draw(img)
        d.rectangle([0, size[1] - 46, 250, size[1]], fill=(255, 255, 255))
        d.text((14, size[1] - 30), watermark, fill=(20, 20, 20))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=78)
    return buf.getvalue()


def save_photo(name: str, data: bytes) -> str:
    PHOTO_DIR.mkdir(parents=True, exist_ok=True)
    (PHOTO_DIR / name).write_bytes(data)
    return f"/demo_photo/{name}"


# (источник, агентство, заголовок, описание, цена, площадь, участок, комнаты,
#  спальни, коммуна, адрес, индекс, фото-сиды, водяной знак)
DEMO = [
    ("demo_agence_a", "Bourgogne Immobilier",
     "Maison en pierre avec vue sur les vignes",
     "Belle maison en pierre de 148 m² sur terrain de 1 400 m², 5 pièces dont 4 chambres. "
     "Grande terrasse plein sud avec vue imprenable sur le vignoble. Très bon état, "
     "toiture refaite en 2019. Piscine chauffée. DPE : C.",
     349000, 148, 1400, 5, 4, "Fuissé", "Le Bourg", "71960", [11, 12, 13], "BOURGOGNE IMMO"),

    # тот же дом у другого агентства: текст переписан, цена без комиссии,
    # фотографии те же самые, но пережаты и с другим логотипом
    ("demo_agence_b", "Mâcon Prestige",
     "Propriété de caractère, vue vignoble",
     "Maison ancienne rénovée de 149 m², 5 pièces, 4 chambres, parcelle de 1 400 m². "
     "Terrasse orientée sud, vue dégagée sur les vignes. Piscine. Chauffage récent.",
     332000, 149, 1400, 5, 4, "Fuissé", "Le Bourg", "71960", [11, 12, 14], "MACON PRESTIGE"),

    # похож по цифрам, но это другой дом — склеивать нельзя
    ("demo_agence_a", "Bourgogne Immobilier",
     "Villa contemporaine de plain-pied",
     "Villa de 147 m² édifiée en 2015, 5 pièces, 4 chambres, terrain de 1 350 m². "
     "Garage double, terrasse. Aucune piscine. Excellent état. DPE : B.",
     352000, 147, 1350, 5, 4, "Fuissé", "Route de Solutré", "71960", [40, 41], "BOURGOGNE IMMO"),

    ("demo_agence_c", "Val de Saône Immo",
     "Maison familiale proche commodités",
     "Maison de 132 m² avec 4 chambres, terrain 900 m², terrasse. À rafraîchir, "
     "travaux à prévoir. Proche écoles et commerces.",
     239000, 132, 900, 6, 4, "Hurigny", "Route de la Grisière", "71870", [21, 22], "VAL DE SAONE"),

    ("demo_agence_b", "Mâcon Prestige",
     "Maison de village rénovée",
     "Maison de village de 118 m², 4 pièces, 3 chambres, cour et terrasse de 40 m². "
     "Rénovée en 2021, très bon état. Sans piscine.",
     268000, 118, 320, 4, 3, "La Roche-Vineuse", "Le Bourg", "71960", [31, 32, 33], "MACON PRESTIGE"),

    # заведомо плохое место: пойма Соны, рядом железная дорога
    ("demo_agence_c", "Val de Saône Immo",
     "Pavillon avec jardin",
     "Pavillon de 105 m² sur 600 m² de terrain, 4 pièces, 3 chambres, terrasse. "
     "Bon état général, proche gare.",
     198000, 105, 600, 4, 3, "Mâcon", "Quai Lamartine", "71000", [51, 52], "VAL DE SAONE"),

    ("demo_agence_a", "Bourgogne Immobilier",
     "Ancienne ferme rénovée avec dépendances",
     "Ancienne ferme de 210 m² rénovée, 6 pièces, 4 chambres, 1,2 ha de terrain. "
     "Grande terrasse, vue panoramique. Dépendances. Bon état.",
     338000, 210, 12000, 6, 4, "Igé", "Le Bourg", "71960", [61, 62, 63], "BOURGOGNE IMMO"),
]


def build() -> list[Listing]:
    out = []
    for i, (src, agency, title, desc, price, area, land, rooms, beds,
            commune, addr, cp, seeds, wm) in enumerate(DEMO):
        photos = []
        for j, seed in enumerate(seeds):
            # у второго агентства те же кадры, но пережатые и с другим логотипом
            data = make_photo(seed, watermark=wm)
            name = f"{src}_{i}_{j}.jpg"
            photos.append(Photo(url=save_photo(name, data), order=j))
        ls = Listing(
            source=src, url=f"https://example.invalid/{src}/{i}",
            source_id=f"{i}", title=title, description=desc,
            price=price, fees_included=(src != "demo_agence_b"),
            area_m2=area, land_m2=land, rooms=rooms, bedrooms=beds,
            commune_name=commune, postcode=cp, address=addr,
            agency=agency, raw={"demo": True},
            photos=photos,
        )
        from layer2 import normalize as N
        body = f"{title} {desc}"
        ls.has_terrace = N.feature(body, "has_terrace")
        ls.has_pool = N.feature(body, "has_pool")
        ls.has_garage = N.feature(body, "has_garage")
        ls.condition_hint = N.condition_hint(body)
        ls.dpe = N.dpe(body)
        out.append(ls)
    return out


def hash_local_photos(con):
    """Хэшируем демо-снимки прямо с диска, минуя загрузку по сети."""
    n = 0
    for row in con.execute("SELECT listing_key, url FROM photo WHERE phash IS NULL"):
        name = row["url"].rsplit("/", 1)[-1]
        p = PHOTO_DIR / name
        if not p.exists():
            continue
        ph, dh, w, h = imagehash.hashes(p.read_bytes())
        if ph:
            db.update_photo_hashes(con, row["listing_key"], row["url"], ph, dh, w, h)
            n += 1
    con.commit()
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clear", action="store_true", help="удалить демо-данные")
    args = ap.parse_args()

    con = db.connect()
    if args.clear:
        keys = [r["key"] for r in con.execute(
            "SELECT key FROM listing WHERE source LIKE 'demo%'")]
        for k in keys:
            con.execute("DELETE FROM photo WHERE listing_key=?", (k,))
            con.execute("DELETE FROM dup_link WHERE listing_key=?", (k,))
            con.execute("DELETE FROM listing WHERE key=?", (k,))
        con.commit()
        print(f"удалено демо-объявлений: {len(keys)}")
        return

    pm = PlaceMap()
    listings = build()
    stats = pipeline.ingest(con, listings, pm, with_photos=False)
    print(f"загружено: {stats['seen']} объявлений ({stats['new']} новых)")
    print(f"хэшей фотографий посчитано: {hash_local_photos(con)}")

    res = pipeline.rebuild_groups(con)
    print(f"групп: {res['groups']} из {res['listings']} объявлений "
          f"(склеено дубликатов: {res['duplicates']})")

    print("\nчто получилось:")
    for r in con.execute("""SELECT l.commune_name, l.price, l.area_m2, l.place_score,
                                   l.place_note, COALESCE(d.group_id,l.key) g, l.agency
                            FROM listing l LEFT JOIN dup_link d ON d.listing_key=l.key
                            WHERE l.source LIKE 'demo%' ORDER BY l.place_score DESC"""):
        print(f"  {r['place_score'] or 0:5.1f}  {r['price']:>7} €  {r['area_m2']:>5.0f} м²  "
              f"{r['commune_name']:<16s} {r['agency']:<22s} группа {r['g'][:8]}")


if __name__ == "__main__":
    main()
