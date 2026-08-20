"""Taouse — веб-приложение для выбора дома.

Три аккаунта: Tanya и Sylvain смотрят дома и голосуют, Maks видит ещё и
техническую часть — статистику, дубли, источники. Язык интерфейса привязан к
аккаунту: Сильвану французский, остальным русский.
"""
from __future__ import annotations

import datetime
import json
import os
import pathlib
import re

from flask import (Flask, g, redirect, render_template, request,
                   send_from_directory, url_for)

from .. import auth, db, pipeline, voting
from ..i18n import conditions, make_translator, place_note

ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
app = Flask(__name__)
app.secret_key = os.environ.get("TAOUSE_SECRET", "taouse-local-dev-key")
app.permanent_session_lifetime = datetime.timedelta(days=90)

STATUSES = {"new": "st_new", "shortlist": "st_shortlist",
            "visit": "st_visit", "rejected": "st_rejected"}


def _con():
    return db.connect()


@app.context_processor
def _shared():
    user = auth.current()
    lang = user["lang"] if user else "ru"
    ctx = {"t": make_translator(lang), "lang": lang, "user": user,
           "statuses": STATUSES, "nav": None, "people": [],
           "place_note": lambda code, rank=None: place_note(code, rank, lang),
           "conditions": lambda codes: conditions(codes, lang),
           "m2": ("m²" if lang == "fr" else "м²")}
    if user:
        con = _con()
        ctx["people"] = voting.people(con)
        ctx["nav"] = _nav_counts(con, user)
    return ctx


def _nav_counts(con, user) -> dict:
    groups = _groups(con, None, "score", 0, 0)
    c = voting.counters(con, groups)
    c["dups"] = len(pipeline.duplicate_candidates(con))
    c["mine"] = c.get(user["id"], 0)
    c["liked"] = len(voting.liked_houses(con, user["id"], groups))
    return c


@app.template_filter("eur")
def eur(v):
    return f"{int(v):,} €".replace(",", " ") if v else "—"


@app.template_filter("num")
def num(v, unit=""):
    if v is None:
        return "—"
    s = f"{v:.0f}" if float(v).is_integer() else f"{v:.1f}"
    return f"{s} {unit}".strip()


# ---------------------------------------------------------------------------
# вход
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login_view():
    error = None
    if request.method == "POST":
        if auth.check(request.form.get("username"), request.form.get("password")):
            auth.login(request.form["username"])
            return redirect(request.args.get("next") or url_for("index"))
        error = True
    return render_template("login.html", error=error)


@app.route("/logout")
def logout_view():
    auth.logout()
    return redirect(url_for("login_view"))


# ---------------------------------------------------------------------------
# дома
# ---------------------------------------------------------------------------

def _groups(con, status: str | None, sort: str, min_score: float, max_price: int,
            include_hidden: bool = False, min_price: int = 0, min_area: float = 0,
            min_bedrooms: int = 0, terrace: bool = False, pool: bool = False,
            garage: bool = False):
    rows = con.execute("""
        SELECT l.*, COALESCE(d.group_id, l.key) AS gid
        FROM listing l LEFT JOIN dup_link d ON d.listing_key = l.key
        WHERE l.active = 1
    """).fetchall()

    hidden = db.hidden_keys(con)
    groups: dict[str, list[dict]] = {}
    for r in rows:
        groups.setdefault(r["gid"], []).append(dict(r))
    if not include_hidden:
        # дом скрыт, если убрано хоть одно его объявление: это один и тот же дом
        groups = {g: m for g, m in groups.items()
                  if not any(x["key"] in hidden for x in m)}
    elif include_hidden == "only":
        groups = {g: m for g, m in groups.items()
                  if any(x["key"] in hidden for x in m)}

    out = []
    for gid, members in groups.items():
        canon = max(members, key=lambda m: (m["price"] is not None,
                                             len(m["description"] or "")))
        review = db.get_review(con, gid)
        if status and review["status"] != status:
            continue
        if (canon["place_score"] or 0) < min_score:
            continue
        if max_price and canon["price"] and canon["price"] > max_price:
            continue
        if min_price and (canon["price"] or 0) < min_price:
            continue
        if min_area and (canon["area_m2"] or 0) < min_area:
            continue
        if min_bedrooms and (canon["bedrooms"] or 0) < min_bedrooms:
            continue
        if terrace and not canon["has_terrace"]:
            continue
        if pool and not canon["has_pool"]:
            continue
        if garage and not canon["has_garage"]:
            continue
        photo = con.execute(
            "SELECT url FROM photo WHERE listing_key=? ORDER BY ord LIMIT 1",
            (canon["key"],)).fetchone()
        out.append({
            "gid": gid, "canon": canon, "n_listings": len(members), "review": review,
            "photo": photo["url"] if photo else None,
            "price_min": min((m["price"] for m in members if m["price"]), default=None),
            "price_max": max((m["price"] for m in members if m["price"]), default=None),
        })

    keys = {"score": lambda x: -(x["canon"]["place_score"] or 0),
            "price": lambda x: (x["canon"]["price"] or 10**9),
            "new": lambda x: (x["canon"]["first_seen"] or ""),
            "area": lambda x: -(x["canon"]["area_m2"] or 0)}
    out.sort(key=keys.get(sort, keys["score"]), reverse=(sort == "new"))
    return out


@app.route("/")
@auth.required
def index():
    """Голосующих ведём сразу к выбору — список нужен скорее админу."""
    if g.user["role"] == "voter" and not request.args:
        return redirect(url_for("swipe", person=g.user["id"]))
    con = _con()
    sort = request.args.get("sort", "score")
    status = request.args.get("status") or None
    min_score = float(request.args.get("min_score") or 0)
    max_price = int(request.args.get("max_price") or 0)
    min_price = int(request.args.get("min_price") or 0)
    min_area = float(request.args.get("min_area") or 0)
    min_bedrooms = int(request.args.get("min_bedrooms") or 0)
    terrace = request.args.get("terrace") == "1"
    pool = request.args.get("pool") == "1"
    garage = request.args.get("garage") == "1"
    groups = _groups(con, status, sort, min_score, max_price,
                     min_price=min_price, min_area=min_area,
                     min_bedrooms=min_bedrooms, terrace=terrace,
                     pool=pool, garage=garage)
    return render_template("index.html", groups=groups, cur_status=status,
                           sort=sort, min_score=min_score, max_price=max_price,
                           min_price=min_price, min_area=min_area,
                           min_bedrooms=min_bedrooms, terrace=terrace,
                           pool=pool, garage=garage)


@app.route("/g/<gid>")
@auth.required
def group(gid):
    con = _con()
    data = pipeline.group_view(con, gid)
    if not data:
        return redirect(url_for("index"))
    data["vote_status"] = voting.status_of(con, gid)
    return render_template("group.html", g=data)


@app.post("/g/<gid>/status")
@auth.required
def set_status(gid):
    con = _con()
    db.set_review(con, gid, status=request.form.get("status") or None,
                  note=request.form.get("note"))
    con.commit()
    return redirect(request.form.get("back") or url_for("index"))


# ---------------------------------------------------------------------------
# выбор
# ---------------------------------------------------------------------------

@app.route("/swipe/<person>")
@auth.required
def swipe(person):
    con = _con()
    ppl = {p["id"]: p for p in voting.people(con)}
    if person not in ppl:
        return redirect(url_for("index"))
    if g.user["role"] != "admin" and person != g.user["id"]:
        return redirect(url_for("swipe", person=g.user["id"]))

    q = voting.queue(con, person, _groups(con, None, "score", 0, 0))
    card = q[0] if q else None
    detail = pipeline.group_view(con, card["gid"]) if card else None
    return render_template("swipe.html", person=ppl[person], card=card,
                           detail=detail, left=len(q),
                           show_others=voting.SHOW_OTHERS_BEFORE_VOTE)


@app.post("/vote/<person>/<gid>")
@auth.required
def vote(person, gid):
    if g.user["role"] != "admin" and person != g.user["id"]:
        return redirect(url_for("swipe", person=g.user["id"]))
    con = _con()
    st = voting.cast(con, gid, person, request.form.get("vote", "pass"))
    if st["matched"]:
        db.set_review(con, gid, status="visit")
        con.commit()
    return redirect(url_for("swipe", person=person))


@app.post("/g/<gid>/hide")
@auth.required
def hide(gid):
    """Убрать дом из выдачи навсегда — «маме не нравится, и хватит о нём»."""
    con = _con()
    keys = [r["listing_key"] for r in
            con.execute("SELECT listing_key FROM dup_link WHERE group_id=?", (gid,))] or [gid]
    db.hide_group(con, keys, by=g.user["id"], reason=request.form.get("reason", ""))
    return redirect(request.form.get("back") or url_for("index"))


@app.post("/g/<gid>/unhide")
@auth.required
def unhide(gid):
    con = _con()
    keys = [r["listing_key"] for r in
            con.execute("SELECT listing_key FROM dup_link WHERE group_id=?", (gid,))] or [gid]
    db.unhide_group(con, keys)
    return redirect(url_for("hidden_view"))


@app.route("/hidden")
@auth.required
def hidden_view():
    con = _con()
    groups = _groups(con, None, "score", 0, 0, include_hidden="only")
    return render_template("hidden.html", groups=groups)


@app.route("/matches")
@auth.required
def matches():
    con = _con()
    ms = voting.matches(con, _groups(con, None, "score", 0, 0))
    return render_template("matches.html", matches=ms)


@app.route("/liked")
@auth.required
def liked_view():
    con = _con()
    groups = _groups(con, None, "score", 0, 0)
    liked = voting.liked_houses(con, g.user["id"], groups)
    return render_template("liked.html", liked=liked)


# ---------------------------------------------------------------------------
# карта
# ---------------------------------------------------------------------------

@app.route("/map")
@auth.required
def map_view():
    con = _con()
    pts = []
    for r in con.execute("""SELECT l.*, COALESCE(d.group_id,l.key) gid
                            FROM listing l LEFT JOIN dup_link d ON d.listing_key=l.key
                            WHERE l.active=1 AND l.lat IS NOT NULL"""):
        rv = db.get_review(con, r["gid"])
        pts.append({"gid": r["gid"], "lat": r["lat"], "lon": r["lon"],
                    "price": r["price"], "area": r["area_m2"],
                    "score": r["place_score"], "commune": r["commune_name"],
                    "status": rv["status"],
                    "approx": (r["geo_precision"] or "") not in ("housenumber", "street")})
    field, bounds = "", "null"
    p = ROOT / "out" / "map.html"
    if p.exists():
        html = p.read_text(encoding="utf-8")
        m = re.search(r'const IMG="(data:image/png;base64,[^"]+)"', html)
        b = re.search(r"const BOUNDS=(\[[^\]]+\])", html)
        if m and b:
            field, bounds = m.group(1), b.group(1)
    return render_template("map.html", points=json.dumps(pts, ensure_ascii=False),
                           field=field, bounds=bounds)


# ---------------------------------------------------------------------------
# админ
# ---------------------------------------------------------------------------

@app.route("/duplicates")
@auth.admin_required
def duplicates():
    con = _con()
    return render_template("duplicates.html",
                           candidates=pipeline.duplicate_candidates(con),
                           merged=pipeline.merged_pairs(con))


@app.post("/duplicates/decide")
@auth.admin_required
def decide():
    con = _con()
    pipeline.decide_duplicate(con, request.form["a"], request.form["b"],
                              request.form["same"] == "1")
    return redirect(url_for("duplicates"))


@app.route("/stats")
@auth.admin_required
def stats():
    con = _con()
    groups = _groups(con, None, "score", 0, 0)

    by_person = {}
    for p in voting.people(con):
        rows = con.execute("SELECT vote, COUNT(*) c FROM vote WHERE person=? GROUP BY vote",
                           (p["id"],)).fetchall()
        d = {r["vote"]: r["c"] for r in rows}
        d["total"] = sum(d.values())
        d["pending"] = len(voting.queue(con, p["id"], groups))
        by_person[p["id"]] = {**p, **d}

    sources = con.execute("""SELECT source, COUNT(*) n, SUM(active) act,
                                    AVG(place_score) avg_score
                             FROM listing GROUP BY source ORDER BY n DESC""").fetchall()
    price_drops = con.execute("""
        SELECT l.title, l.commune_name, l.price_first, l.price,
               COALESCE(d.group_id, l.key) gid
        FROM listing l LEFT JOIN dup_link d ON d.listing_key=l.key
        WHERE l.active=1 AND l.price_first IS NOT NULL AND l.price < l.price_first
        ORDER BY (l.price_first - l.price) DESC LIMIT 10""").fetchall()

    dist = {"green": 0, "amber": 0, "weak": 0, "none": 0}
    for x in groups:
        s = x["canon"]["place_score"]
        if s is None:
            dist["none"] += 1
        elif s >= 60:
            dist["green"] += 1
        elif s >= 45:
            dist["amber"] += 1
        else:
            dist["weak"] += 1

    n_links = con.execute("SELECT COUNT(*) c FROM dup_link").fetchone()["c"]
    n_groups = con.execute("SELECT COUNT(DISTINCT group_id) c FROM dup_link").fetchone()["c"]
    return render_template(
        "stats.html", by_person=by_person, sources=[dict(r) for r in sources],
        price_drops=[dict(r) for r in price_drops], dist=dist,
        totals={"groups": len(groups),
                "listings": con.execute(
                    "SELECT COUNT(*) c FROM listing WHERE active=1").fetchone()["c"],
                "duplicates": max(0, n_links - n_groups),
                "candidates": len(pipeline.duplicate_candidates(con)),
                "matches": len(voting.matches(con, groups))})


@app.route("/demo_photo/<path:name>")
def demo_photo(name):
    return send_from_directory(ROOT / "data" / "demo_photos", name)


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=5055)
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    print(f"Taouse → http://{a.host}:{a.port}")
    app.run(host=a.host, port=a.port, debug=False)


if __name__ == "__main__":
    main()
