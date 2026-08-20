"""Обработка собранных объявлений: фото -> хэши, адрес -> балл места,
дубликаты -> группы. Всё, что происходит после адаптера и до показа родителям.
"""
from __future__ import annotations

import json
import time

from housemap import http

from . import communes as communes_mod
from . import db, dedup, geocode, imagehash
from .normalize import slug
from .models import Listing
from .placescore import PlaceMap


def enrich_photos(con, ls: Listing, key: str, limit: int = 6, timeout: int = 20):
    """Качаем первые снимки и считаем перцептивные хэши.

    Больше шести не нужно: для склейки дубликатов хватает нескольких кадров,
    а трафик и терпение сайта не бесконечны.
    """
    done = 0
    for ph in ls.photos[:limit]:
        row = con.execute("SELECT phash FROM photo WHERE listing_key=? AND url=?",
                          (key, ph.url)).fetchone()
        if row and row["phash"]:
            continue
        try:
            r = http.get(ph.url, timeout=timeout)
            r.raise_for_status()
            data = r.content
        except Exception:
            continue
        p, d, w, h = imagehash.hashes(data)
        if p:
            db.update_photo_hashes(con, key, ph.url, p, d, w, h)
            done += 1
        time.sleep(0.25)
    return done


def locate(con, ls: Listing, key: str, pm: PlaceMap):
    """Адрес -> координаты -> балл места из Слоя 1.

    Ловушка, на которую легко попасться: геокодер по строке вроде
    «Route de Solutré, Fuissé» уверенно отдаёт улицу в Solutré-Pouilly —
    соседней коммуне. Координаты выглядят точными, а балл считается для чужой
    деревни. Поэтому результат сверяется с коммуной из объявления, и при
    расхождении мы откатываемся к центру заявленной коммуны: грубо, зато там,
    где дом действительно стоит.
    """
    lat, lon, precision = ls.lat, ls.lon, ls.geo_precision
    commune_code = ls.commune_code

    # Коммуна из ссылки — предположение источника, а не факт. Если в описании
    # прямо названа другая, верим описанию: продавец знает, где стоит его дом,
    # а портал привязывает объявление к ближайшему известному городу.
    found, mismatch = communes_mod.reconcile(
        ls.commune_name, f"{ls.title} {ls.description}")
    if found and mismatch:
        print(f"      коммуна уточнена: {ls.commune_name} -> {found['nom']}")
        ls.commune_name = found["nom"]
        ls.commune_code = commune_code = found["code"]
        lat = lon = None
        precision = ""
        g = geocode.commune(found["nom"])
        ls.postcode = (g or {}).get("postcode", "") or ""

    if not (lat and lon) or not commune_code:
        query = " ".join(x for x in (ls.address, ls.commune_name) if x).strip()
        g = geocode.geocode(query, postcode=ls.postcode) if query else None

        if g and ls.commune_name and g.get("commune_name"):
            if slug(g["commune_name"]) != slug(ls.commune_name):
                g = None            # геокодер ушёл не в ту коммуну

        if not g and ls.commune_name:
            g = geocode.commune(ls.commune_name, ls.postcode)

        if g:
            lat = lat or g["lat"]
            lon = lon or g["lon"]
            precision = precision or g["precision"]
            commune_code = commune_code or g["commune_code"]
            if not ls.commune_name:
                ls.commune_name = g["commune_name"]

    ev = pm.evaluate(lat, lon, precision or "", commune_code or "")
    # Приоритет у уточнённого значения: если коммуна исправлена по тексту
    # объявления, старое (ошибочное) имя из ссылки должно уйти.
    con.execute("""UPDATE listing SET lat=?, lon=?, geo_precision=?, commune_code=?,
                   commune_name=COALESCE(NULLIF(?,''), commune_name),
                   postcode=COALESCE(NULLIF(?,''), postcode) WHERE key=?""",
                (lat, lon, precision, commune_code, ls.commune_name, ls.postcode, key))
    db.set_place(con, key, ev["score"], ev["zone_rank"], ev["communes"], ev["note"])
    return ev


def _listing_rows(con) -> list[dict]:
    rows = [dict(r) for r in con.execute(
        "SELECT * FROM listing WHERE active=1").fetchall()]
    photos = {}
    for p in con.execute("SELECT listing_key,url,ord,phash,dhash FROM photo"):
        photos.setdefault(p["listing_key"], []).append(dict(p))
    for r in rows:
        r["photos"] = sorted(photos.get(r["key"], []), key=lambda x: x["ord"] or 0)
    return rows


def manual_decisions(con) -> dict[tuple[str, str], int]:
    return {(r["a"], r["b"]): r["same"] for r in
            con.execute("SELECT a, b, same FROM dup_decision")}


def rebuild_groups(con) -> dict:
    """Пересобирает группы дубликатов по всем активным объявлениям."""
    items = _listing_rows(con)
    if not items:
        return {"listings": 0, "groups": 0, "links": 0, "duplicates": 0, "candidates": 0}

    groups, links, candidates = dedup.group(items, manual_decisions(con))
    con.execute("DELETE FROM dup_link")
    con.execute("DELETE FROM dup_candidate")
    for c in candidates:
        con.execute("""INSERT OR REPLACE INTO dup_candidate (a,b,reason,score)
                       VALUES (?,?,?,?)""", (c["a"], c["b"], c["reason"], c["score"]))
    by_group: dict[str, list[dict]] = {}
    for i, it in enumerate(items):
        gid = groups[i]
        by_group.setdefault(gid, []).append(it)

    link_by_key = {}
    for lk in links:
        link_by_key.setdefault(lk["a"], lk)
        link_by_key.setdefault(lk["b"], lk)

    for gid, members in by_group.items():
        for m in members:
            lk = link_by_key.get(m["key"], {})
            con.execute("""INSERT OR REPLACE INTO dup_link
                           (listing_key, group_id, method, confidence) VALUES (?,?,?,?)""",
                        (m["key"], gid, lk.get("method", ""), lk.get("confidence")))
    con.commit()
    return {"listings": len(items), "groups": len(by_group), "links": len(links),
            "duplicates": len(items) - len(by_group), "candidates": len(candidates)}


def ingest(con, listings: list[Listing], pm: PlaceMap, with_photos: bool = True) -> dict:
    """Сохранить пачку объявлений и обогатить их."""
    stats = {"seen": 0, "new": 0, "photos": 0}
    for ls in listings:
        key, is_new = db.upsert_listing(con, ls)
        stats["seen"] += 1
        stats["new"] += int(is_new)
        if with_photos:
            stats["photos"] += enrich_photos(con, ls, key)
        locate(con, ls, key, pm)
        con.commit()
    return stats


def group_view(con, group_id: str) -> dict:
    """Группа целиком: канонический вариант + остальные подачи того же дома."""
    keys = [r["listing_key"] for r in
            con.execute("SELECT listing_key FROM dup_link WHERE group_id=?", (group_id,))]
    if not keys:
        keys = [group_id]
    qs = ",".join("?" * len(keys))
    rows = [dict(r) for r in con.execute(
        f"SELECT * FROM listing WHERE key IN ({qs})", keys)]
    for r in rows:
        r["photos"] = [dict(p) for p in con.execute(
            "SELECT * FROM photo WHERE listing_key=? ORDER BY ord", (r["key"],))]
        ev = con.execute("SELECT * FROM ai_eval WHERE listing_key=?", (r["key"],)).fetchone()
        r["ai"] = dict(ev) if ev else None
        r["raw"] = json.loads(r["raw"] or "{}")
    if not rows:
        return {}
    canon = dedup.pick_canonical(rows)
    others = [r for r in rows if r["key"] != canon["key"]]
    return {"group_id": group_id, "canonical": canon, "others": others,
            "review": db.get_review(con, group_id),
            "sources": sorted({r["source"] for r in rows}),
            "price_min": min((r["price"] for r in rows if r["price"]), default=None),
            "price_max": max((r["price"] for r in rows if r["price"]), default=None)}


def decide_duplicate(con, a: str, b: str, same: bool):
    """Ручной вердикт по паре и немедленная пересборка групп."""
    from datetime import datetime, timezone
    a, b = sorted([a, b])
    con.execute("""INSERT OR REPLACE INTO dup_decision (a,b,same,decided_at)
                   VALUES (?,?,?,?)""",
                (a, b, int(same), datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    return rebuild_groups(con)


def duplicate_candidates(con) -> list[dict]:
    """Сомнительные пары для ручной проверки, с данными обоих объявлений."""
    out = []
    for r in con.execute("SELECT * FROM dup_candidate ORDER BY score DESC"):
        pair = []
        for k in (r["a"], r["b"]):
            row = con.execute("SELECT * FROM listing WHERE key=? AND active=1", (k,)).fetchone()
            if not row:
                break
            d = dict(row)
            ph = con.execute("SELECT url FROM photo WHERE listing_key=? ORDER BY ord LIMIT 3",
                             (k,)).fetchall()
            d["photos"] = [p["url"] for p in ph]
            pair.append(d)
        if len(pair) == 2:
            out.append({"a": pair[0], "b": pair[1],
                        "reason": r["reason"], "score": r["score"]})
    return out


def merged_pairs(con) -> list[dict]:
    """Уже склеенные группы — чтобы человек мог не согласиться и разделить."""
    out = []
    rows = con.execute("""SELECT group_id, GROUP_CONCAT(listing_key) ks,
                                 GROUP_CONCAT(method) ms, MAX(confidence) conf
                          FROM dup_link GROUP BY group_id HAVING COUNT(*) > 1""")
    for r in rows:
        keys = r["ks"].split(",")
        members = []
        for k in keys:
            row = con.execute("SELECT * FROM listing WHERE key=?", (k,)).fetchone()
            if not row:
                continue
            d = dict(row)
            ph = con.execute("SELECT url FROM photo WHERE listing_key=? ORDER BY ord LIMIT 3",
                             (k,)).fetchall()
            d["photos"] = [p["url"] for p in ph]
            members.append(d)
        if len(members) > 1:
            method = next((m for m in (r["ms"] or "").split(",") if m), "")
            out.append({"group_id": r["group_id"], "members": members,
                        "method": method, "confidence": r["conf"]})
    return out
