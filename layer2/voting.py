"""Лайки, мэтчи и очередь показа.

Правила простые:
  * каждый смотрит свою очередь и жмёт «нравится» / «может быть» / «нет»;
  * дом, который кто-то лайкнул, поднимается в очереди остальных — то есть
    мамин лайк действительно двигает дом к папе;
  * лайкнули все — мэтч, дом уезжает в отдельную вкладку с предложением визита.

Чужой голос до собственного не показывается. Это не про интригу: если написать
«маме понравилось», второй проголосует за мир в семье, а не за дом, и смысл
двойной оценки пропадёт. Отключается через SHOW_OTHERS_BEFORE_VOTE.
"""
from __future__ import annotations

from datetime import datetime, timezone

SHOW_OTHERS_BEFORE_VOTE = False

VOTES = ("like", "maybe", "pass")

def ensure_people(con):
    """Голосующие — те же люди, что заходят в приложение (кроме админа)."""
    from .auth import USERS, VOTERS
    have = {r["id"] for r in con.execute("SELECT id FROM person")}
    for uid in VOTERS:
        if uid not in have:
            con.execute("INSERT INTO person (id,name,emoji) VALUES (?,?,?)",
                        (uid, USERS[uid]["name"], USERS[uid]["emoji"]))
    # старые демо-персонажи из первой версии больше не участвуют
    con.execute("UPDATE person SET active=0 WHERE id NOT IN (%s)"
                % ",".join("?" * len(VOTERS)), VOTERS)
    con.commit()


def people(con) -> list[dict]:
    ensure_people(con)
    return [dict(r) for r in con.execute(
        "SELECT * FROM person WHERE active=1 ORDER BY rowid")]


def cast(con, group_id: str, person: str, vote: str):
    if vote not in VOTES:
        raise ValueError(vote)
    con.execute("""INSERT INTO vote (group_id, person, vote, created_at) VALUES (?,?,?,?)
                   ON CONFLICT(group_id, person) DO UPDATE SET
                     vote=excluded.vote, created_at=excluded.created_at""",
                (group_id, person, vote, datetime.now(timezone.utc).isoformat(timespec="seconds")))
    con.commit()
    return status_of(con, group_id)


def votes_for(con, group_id: str) -> dict[str, str]:
    return {r["person"]: r["vote"] for r in
            con.execute("SELECT person, vote FROM vote WHERE group_id=?", (group_id,))}


def status_of(con, group_id: str) -> dict:
    """-> {votes, matched, liked_by, waiting_for, rejected}"""
    ppl = [p["id"] for p in people(con)]
    v = votes_for(con, group_id)
    liked = [p for p in ppl if v.get(p) == "like"]
    passed = [p for p in ppl if v.get(p) == "pass"]
    waiting = [p for p in ppl if p not in v]
    return {
        "votes": v,
        "matched": len(liked) == len(ppl) and len(ppl) > 0,
        "liked_by": liked,
        "waiting_for": waiting,
        "rejected": bool(passed),
    }


def queue(con, person: str, groups: list[dict]) -> list[dict]:
    """Что показать этому человеку и в каком порядке.

    Сначала — дома, которые уже понравились кому-то другому: по ним ждут
    именно его слова. Дальше — по баллу места.
    """
    v_all = {}
    for r in con.execute("SELECT group_id, person, vote FROM vote"):
        v_all.setdefault(r["group_id"], {})[r["person"]] = r["vote"]

    out = []
    for g in groups:
        v = v_all.get(g["gid"], {})
        if person in v:
            continue                       # уже голосовал
        if any(x == "pass" for p, x in v.items() if p != person):
            continue                       # кто-то уже отказался — не мучаем второго
        g = dict(g)
        g["liked_by_other"] = [p for p, x in v.items() if x == "like"]
        out.append(g)

    out.sort(key=lambda g: (-len(g["liked_by_other"]),
                            -(g["canon"]["place_score"] or 0)))
    return out


def matches(con, groups: list[dict]) -> list[dict]:
    out = []
    for g in groups:
        st = status_of(con, g["gid"])
        if st["matched"]:
            g = dict(g)
            g["status"] = st
            out.append(g)
    out.sort(key=lambda g: -(g["canon"]["place_score"] or 0))
    return out


def counters(con, groups: list[dict]) -> dict:
    ppl = people(con)
    res = {"match": 0, "rejected": 0}
    for p in ppl:
        res[p["id"]] = 0
    for g in groups:
        st = status_of(con, g["gid"])
        if st["matched"]:
            res["match"] += 1
            continue
        if st["rejected"]:
            res["rejected"] += 1
            continue
        for p in ppl:
            if p["id"] in st["waiting_for"]:
                res[p["id"]] += 1
    return res
