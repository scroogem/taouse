"""Тесты склейки одинаковых объявлений.

Проверяем ровно то, что происходит в жизни: один дом у двух агентств с
переписанным текстом, ценой с комиссией и без, и теми же фотографиями —
но пережатыми, отмасштабированными и с водяным знаком.
"""
import io
import pathlib
import sys

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from layer2 import dedup, imagehash  # noqa: E402


def _photo(seed: int, size=(800, 600)) -> Image.Image:
    """Псевдо-фотография: плавные пятна, как реальный кадр, а не белый шум."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 255, (12, 16, 3), dtype=np.uint8)
    return Image.fromarray(small).resize(size, Image.BICUBIC)


def _jpeg(img: Image.Image, quality=70) -> bytes:
    buf = io.BytesIO()
    img.convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _watermarked(img: Image.Image) -> Image.Image:
    out = img.copy()
    d = ImageDraw.Draw(out)
    d.rectangle([0, out.height - 60, 260, out.height], fill=(255, 255, 255))
    d.text((12, out.height - 40), "AGENCE IMMO 71", fill=(0, 0, 0))
    return out


def test_phash_survives_recompression():
    src = _photo(1)
    a = imagehash.hashes(_jpeg(src, 92))
    # то же фото: уменьшено, сильнее сжато, с логотипом агентства
    variant = _watermarked(src.resize((520, 390), Image.LANCZOS))
    b = imagehash.hashes(_jpeg(variant, 55))
    assert imagehash.distance(a[0], b[0]) <= dedup.PHOTO_MAX_DIST
    assert a[2] == 800 and b[2] == 520


def test_phash_separates_different_photos():
    a = imagehash.hashes(_jpeg(_photo(1)))
    b = imagehash.hashes(_jpeg(_photo(999)))
    assert imagehash.distance(a[0], b[0]) > dedup.PHOTO_MAX_DIST


def _listing(key, source, price, area, desc, photo_seeds, rooms=5, commune="71235"):
    photos = []
    for i, s in enumerate(photo_seeds):
        ph, dh, w, h = imagehash.hashes(_jpeg(_photo(s)))
        photos.append({"phash": ph, "dhash": dh, "order": i})
    return {"key": key, "source": source, "price": price, "area_m2": area,
            "rooms": rooms, "commune_code": commune, "commune_name": "Hurigny",
            "title": "", "description": desc, "photos": photos}


def test_same_house_two_agencies():
    a = _listing("a", "agence1", 349000, 145,
                 "Belle maison avec vue sur les vignes, terrasse plein sud", [1, 2, 3])
    b = _listing("b", "agence2", 330000, 146,        # цена без комиссии
                 "Maison lumineuse, terrasse exposée sud, vue sur le vignoble", [1, 2, 9])
    res = dedup.compare(a, b)
    assert res is not None and "фото" in res["method"]
    assert res["confidence"] >= 0.8


def test_similar_but_different_houses_stay_apart():
    a = _listing("a", "agence1", 349000, 145, "Maison de plain-pied avec garage", [1, 2])
    b = _listing("b", "agence2", 352000, 144, "Villa contemporaine sur sous-sol", [50, 51])
    # похожие цифры, но другие фото и другой текст — склеивать нельзя
    assert dedup.compare(a, b) is None


def test_grouping_builds_one_group():
    items = [
        _listing("a", "s1", 349000, 145, "Maison avec vue sur les vignes", [1, 2]),
        _listing("b", "s2", 330000, 146, "Maison, vue sur le vignoble", [1, 7]),
        _listing("c", "s3", 275000, 98, "Autre maison au centre du village", [30, 31]),
    ]
    groups, links, candidates = dedup.group(items)
    assert groups[0] == groups[1], "две подачи одного дома должны слиться"
    assert groups[2] != groups[0], "чужой дом должен остаться отдельным"
    assert len(links) == 1


def test_manual_decision_overrides_automatic():
    """Человек всегда прав: и склеить, и разделить."""
    items = [
        _listing("a", "s1", 349000, 145, "Maison avec vue sur les vignes", [1, 2]),
        _listing("b", "s2", 330000, 146, "Maison, vue sur le vignoble", [1, 7]),
    ]
    auto, _, _ = dedup.group(items)
    assert auto[0] == auto[1], "по фото должны склеиться сами"

    split, _, _ = dedup.group(items, decisions={("a", "b"): 0})
    assert split[0] != split[1], "ручное «разные дома» должно разъединить"

    far = [
        _listing("x", "s1", 349000, 145, "Maison de plain-pied", [1, 2]),
        _listing("y", "s2", 210000, 88, "Studio en centre-ville", [60, 61], rooms=2),
    ]
    joined, _, _ = dedup.group(far, decisions={("x", "y"): 1})
    assert joined[0] == joined[1], "ручное «один дом» должно склеить"


def test_near_miss_flags_uncertain_pair():
    """Похожие цифры при разных фото — не склейка, но и не молчание."""
    a = _listing("a", "s1", 349000, 145, "Maison de plain-pied avec garage", [1, 2])
    b = _listing("b", "s2", 352000, 144, "Villa contemporaine sur sous-sol", [50, 51])
    assert dedup.compare(a, b) is None
    nm = dedup.near_miss(a, b)
    assert nm is not None and "цена" in nm["reason"]


def test_canonical_prefers_richer_listing():
    poor = {"key": "p", "photos": [{}], "description": "court", "price": 349000}
    rich = {"key": "r", "photos": [{}, {}, {}], "description": "x" * 400, "price": 355000}
    assert dedup.pick_canonical([poor, rich])["key"] == "r"
