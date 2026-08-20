"""SQLite-хранилище. Для двух пользователей этого более чем достаточно,
а файл базы можно просто скопировать или открыть чем угодно.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
from datetime import datetime, timezone

from .models import Listing, Photo

ROOT = pathlib.Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "listings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listing (
  key TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  source_id TEXT,
  url TEXT NOT NULL,
  title TEXT, description TEXT,
  price INTEGER, fees_included INTEGER,
  area_m2 REAL, land_m2 REAL, rooms INTEGER, bedrooms INTEGER,
  commune_name TEXT, commune_code TEXT, postcode TEXT, address TEXT,
  lat REAL, lon REAL, geo_precision TEXT,
  dpe TEXT, year_built INTEGER,
  has_terrace INTEGER, has_pool INTEGER, has_garage INTEGER,
  condition_hint TEXT,
  agency TEXT, agency_ref TEXT,
  place_score REAL, zone_rank INTEGER, zone_communes TEXT,
  place_note TEXT,
  first_seen TEXT, last_seen TEXT, active INTEGER DEFAULT 1,
  price_first INTEGER,
  raw TEXT
);
CREATE INDEX IF NOT EXISTS idx_listing_commune ON listing(commune_code);
CREATE INDEX IF NOT EXISTS idx_listing_active ON listing(active);

CREATE TABLE IF NOT EXISTS photo (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  listing_key TEXT NOT NULL,
  url TEXT NOT NULL,
  ord INTEGER,
  phash TEXT, dhash TEXT,
  width INTEGER, height INTEGER,
  UNIQUE(listing_key, url)
);
CREATE INDEX IF NOT EXISTS idx_photo_listing ON photo(listing_key);

-- группы дубликатов: один физический дом = одна группа
CREATE TABLE IF NOT EXISTS dup_link (
  listing_key TEXT NOT NULL,
  group_id TEXT NOT NULL,
  method TEXT,
  confidence REAL,
  PRIMARY KEY (listing_key)
);
CREATE INDEX IF NOT EXISTS idx_dup_group ON dup_link(group_id);

-- решения родителей
CREATE TABLE IF NOT EXISTS review (
  group_id TEXT PRIMARY KEY,
  status TEXT DEFAULT 'new',       -- new | shortlist | visit | rejected
  note TEXT,
  rating INTEGER,
  updated_at TEXT
);

-- оценка фото и текста моделью
CREATE TABLE IF NOT EXISTS ai_eval (
  listing_key TEXT PRIMARY KEY,
  model TEXT,
  condition_score REAL,
  needs_work TEXT,
  has_terrace INTEGER, has_pool INTEGER,
  price_fairness TEXT,
  summary TEXT,
  raw TEXT,
  created_at TEXT
);

-- история цен: снижение цены — сигнал, что можно торговаться
CREATE TABLE IF NOT EXISTS price_history (
  listing_key TEXT NOT NULL,
  price INTEGER,
  seen_at TEXT
);

-- Кто смотрит дома. Двое, но список не зашит в код: вдруг подключится сестра.
CREATE TABLE IF NOT EXISTS person (
  id TEXT PRIMARY KEY,
  name TEXT,
  emoji TEXT,
  active INTEGER DEFAULT 1
);

-- Голос за дом. Один человек — один голос на дом, можно переголосовать.
CREATE TABLE IF NOT EXISTS vote (
  group_id TEXT NOT NULL,
  person TEXT NOT NULL,
  vote TEXT NOT NULL,               -- like | maybe | pass
  created_at TEXT,
  PRIMARY KEY (group_id, person)
);
CREATE INDEX IF NOT EXISTS idx_vote_group ON vote(group_id);
CREATE INDEX IF NOT EXISTS idx_vote_person ON vote(person, vote);

-- Ручные решения по склейке: человек всегда прав, автоматика уступает.
CREATE TABLE IF NOT EXISTS dup_decision (
  a TEXT NOT NULL, b TEXT NOT NULL,
  same INTEGER NOT NULL,            -- 1 = один дом, 0 = разные
  decided_at TEXT,
  PRIMARY KEY (a, b)
);

-- Пары, которые почти прошли порог склейки. Система намеренно осторожна,
-- поэтому такие сомнения показываем человеку, а не решаем молча.
CREATE TABLE IF NOT EXISTS dup_candidate (
  a TEXT NOT NULL, b TEXT NOT NULL,
  reason TEXT, score REAL,
  PRIMARY KEY (a, b)
);

-- Скрытые дома. Привязка к объявлению, а не к группе: идентификатор группы
-- меняется при пересборке, и решение «убрать навсегда» иначе бы терялось.
-- Запись остаётся в базе, чтобы дом не вернулся при следующем сборе.
CREATE TABLE IF NOT EXISTS hidden (
  listing_key TEXT PRIMARY KEY,
  hidden_by TEXT,
  reason TEXT,
  hidden_at TEXT
);

CREATE TABLE IF NOT EXISTS run_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  source TEXT, started_at TEXT, finished_at TEXT,
  found INTEGER, new INTEGER, errors TEXT
);
"""


def connect(path: pathlib.Path | None = None) -> sqlite3.Connection:
    p = path or DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(p)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript(SCHEMA)
    return con


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def upsert_listing(con: sqlite3.Connection, ls: Listing) -> tuple[str, bool]:
    """-> (key, is_new). Цену пишем в историю, если изменилась."""
    key = ls.key()
    cur = con.execute("SELECT price, first_seen, price_first FROM listing WHERE key=?", (key,))
    row = cur.fetchone()
    now = _now()

    fields = dict(
        key=key, source=ls.source, source_id=ls.source_id, url=ls.url,
        title=ls.title, description=ls.description,
        price=ls.price, fees_included=_b(ls.fees_included),
        area_m2=ls.area_m2, land_m2=ls.land_m2, rooms=ls.rooms, bedrooms=ls.bedrooms,
        commune_name=ls.commune_name, commune_code=ls.commune_code,
        postcode=ls.postcode, address=ls.address,
        lat=ls.lat, lon=ls.lon, geo_precision=ls.geo_precision,
        dpe=ls.dpe, year_built=ls.year_built,
        has_terrace=_b(ls.has_terrace), has_pool=_b(ls.has_pool),
        has_garage=_b(ls.has_garage), condition_hint=ls.condition_hint,
        agency=ls.agency, agency_ref=ls.agency_ref,
        last_seen=now, active=1, raw=json.dumps(ls.raw, ensure_ascii=False),
    )
    if row is None:
        fields["first_seen"] = now
        fields["price_first"] = ls.price
        cols = ",".join(fields)
        con.execute(f"INSERT INTO listing ({cols}) VALUES ({','.join('?'*len(fields))})",
                    tuple(fields.values()))
        is_new = True
    else:
        sets = ",".join(f"{k}=?" for k in fields if k != "key")
        con.execute(f"UPDATE listing SET {sets} WHERE key=?",
                    tuple(v for k, v in fields.items() if k != "key") + (key,))
        is_new = False

    if ls.price is not None and (row is None or row["price"] != ls.price):
        con.execute("INSERT INTO price_history (listing_key, price, seen_at) VALUES (?,?,?)",
                    (key, ls.price, now))

    for ph in ls.photos:
        con.execute("""INSERT OR IGNORE INTO photo (listing_key,url,ord,phash,dhash,width,height)
                       VALUES (?,?,?,?,?,?,?)""",
                    (key, ph.url, ph.order, ph.phash, ph.dhash, ph.width, ph.height))
    return key, is_new


def _b(v):
    return None if v is None else int(bool(v))


def set_place(con, key: str, score: float | None, zone_rank: int | None,
              communes: str, note: str):
    con.execute("""UPDATE listing SET place_score=?, zone_rank=?, zone_communes=?,
                   place_note=? WHERE key=?""", (score, zone_rank, communes, note, key))


def update_photo_hashes(con, listing_key: str, url: str, phash: str, dhash: str,
                        w: int, h: int):
    con.execute("""UPDATE photo SET phash=?, dhash=?, width=?, height=?
                   WHERE listing_key=? AND url=?""", (phash, dhash, w, h, listing_key, url))


def mark_inactive(con, source: str, seen_keys: set[str]):
    """Объявления источника, которых не было в этом обходе, считаем снятыми."""
    rows = con.execute("SELECT key FROM listing WHERE source=? AND active=1", (source,))
    gone = [r["key"] for r in rows if r["key"] not in seen_keys]
    con.executemany("UPDATE listing SET active=0 WHERE key=?", [(k,) for k in gone])
    return len(gone)


def get_review(con, group_id: str) -> dict:
    r = con.execute("SELECT * FROM review WHERE group_id=?", (group_id,)).fetchone()
    return dict(r) if r else {"group_id": group_id, "status": "new", "note": "", "rating": None}


def set_review(con, group_id: str, status: str | None = None, note: str | None = None,
               rating: int | None = None):
    cur = get_review(con, group_id)
    con.execute("""INSERT INTO review (group_id,status,note,rating,updated_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(group_id) DO UPDATE SET
                     status=excluded.status, note=excluded.note,
                     rating=excluded.rating, updated_at=excluded.updated_at""",
                (group_id,
                 status if status is not None else cur["status"],
                 note if note is not None else cur["note"],
                 rating if rating is not None else cur["rating"],
                 _now()))


def hide_group(con, keys: list[str], by: str = "", reason: str = ""):
    """Скрыть дом (все его объявления)."""
    now = _now()
    con.executemany("""INSERT OR REPLACE INTO hidden (listing_key, hidden_by, reason, hidden_at)
                       VALUES (?,?,?,?)""", [(k, by, reason, now) for k in keys])
    con.commit()


def unhide_group(con, keys: list[str]):
    con.executemany("DELETE FROM hidden WHERE listing_key=?", [(k,) for k in keys])
    con.commit()


def hidden_keys(con) -> set[str]:
    return {r["listing_key"] for r in con.execute("SELECT listing_key FROM hidden")}
