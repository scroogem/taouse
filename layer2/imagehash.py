"""Перцептивные хэши фотографий.

Одно и то же объявление у трёх агентств — это, как правило, одни и те же снимки
от собственника, но пережатые, отмасштабированные и с разными водяными знаками.
Побайтовое сравнение тут бесполезно, а перцептивный хэш переживает всё это.

Считаем два независимых:
  dHash — по знаку разности соседних пикселей. Дёшев, устойчив к яркости.
  pHash — по низким частотам DCT. Дороже, но переживает кроп и логотип в углу.

Совпадение по любому из них — сильный сигнал, что дом один и тот же.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image
from scipy.fft import dctn


CROP = 0.86  # доля кадра по центру, по которой считаем хэш


def _gray(data: bytes, size: tuple[int, int]) -> np.ndarray | None:
    """Серый кадр заданного размера, обрезанный по центру.

    Агентства ставят логотип в угол, а порталы добавляют рамку — от этого
    хэш всего кадра уезжает настолько, что одна и та же фотография перестаёт
    узнаваться. Центральная часть от такой правки почти не страдает.
    """
    try:
        img = Image.open(io.BytesIO(data)).convert("L")
        w, h = img.size
        dw, dh = w * (1 - CROP) / 2, h * (1 - CROP) / 2
        img = img.crop((int(dw), int(dh), int(w - dw), int(h - dh)))
        img = img.resize(size, Image.LANCZOS)
    except Exception:
        return None
    return np.asarray(img, dtype=np.float32)


def dhash(data: bytes) -> str | None:
    a = _gray(data, (9, 8))
    if a is None:
        return None
    bits = a[:, 1:] > a[:, :-1]
    return _pack(bits.ravel())


def phash(data: bytes) -> str | None:
    a = _gray(data, (32, 32))
    if a is None:
        return None
    d = dctn(a, norm="ortho")[:8, :8]
    flat = d.ravel()[1:]           # выбрасываем DC — он про общую яркость
    bits = flat > np.median(flat)
    return _pack(bits)


def _pack(bits: np.ndarray) -> str:
    v = 0
    for b in bits.astype(bool):
        v = (v << 1) | int(b)
    return f"{v:016x}"


def distance(a: str | None, b: str | None) -> int:
    """Расстояние Хэмминга; 999 — если сравнивать нечего."""
    if not a or not b:
        return 999
    return bin(int(a, 16) ^ int(b, 16)).count("1")


def image_size(data: bytes) -> tuple[int | None, int | None]:
    try:
        img = Image.open(io.BytesIO(data))
        return img.size
    except Exception:
        return None, None


def hashes(data: bytes) -> tuple[str | None, str | None, int | None, int | None]:
    w, h = image_size(data)
    return phash(data), dhash(data), w, h
