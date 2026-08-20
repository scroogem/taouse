"""Файловый кэш. Сеть — самая медленная и ненадёжная часть, поэтому всё,
что скачано, лежит на диске и переиспользуется между запусками."""
from __future__ import annotations

import gzip
import hashlib
import json
import pathlib
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"


def path_for(kind: str, key: str, ext: str = "json.gz") -> pathlib.Path:
    h = hashlib.sha1(key.encode()).hexdigest()[:16]
    d = DATA / kind
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.{ext}"


def load_json(p: pathlib.Path):
    if not p.exists():
        return None
    try:
        with gzip.open(p, "rt", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        p.unlink(missing_ok=True)
        return None


def save_json(p: pathlib.Path, obj):
    tmp = p.with_suffix(p.suffix + ".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as f:
        json.dump(obj, f)
    tmp.replace(p)


def cached_json(kind: str, key: str, producer, label: str = ""):
    """producer() -> json-сериализуемый объект. Вызывается только при промахе."""
    p = path_for(kind, key)
    hit = load_json(p)
    if hit is not None:
        print(f"  [cache] {label or kind}")
        return hit
    t = time.time()
    print(f"  [fetch] {label or kind} ...", end="", flush=True)
    obj = producer()
    save_json(p, obj)
    print(f" готово ({time.time() - t:.1f}s)")
    return obj
