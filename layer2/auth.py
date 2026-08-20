"""Три аккаунта: двое выбирают дом, третий следит за системой.

Пароли лежат хэшами, а не текстом. Пароль тут простой и общий, но хранить
его в открытом виде всё равно незачем: файл базы легко утекает вместе с
резервной копией.
"""
from __future__ import annotations

import functools

from flask import g, redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

DEFAULT_PASSWORD = "12345"

# id, имя, роль, язык интерфейса, эмодзи
USERS = {
    "maks":    {"name": "Maks",    "role": "admin", "lang": "ru", "emoji": "🛠"},
    "tanya":   {"name": "Tanya",   "role": "voter", "lang": "ru", "emoji": "🌷"},
    "sylvain": {"name": "Sylvain", "role": "voter", "lang": "fr", "emoji": "🍇"},
}

VOTERS = [u for u, v in USERS.items() if v["role"] == "voter"]


def password_hash(pw: str = DEFAULT_PASSWORD) -> str:
    return generate_password_hash(pw)


_HASHES = {u: password_hash() for u in USERS}


def check(username: str, password: str) -> bool:
    username = (username or "").strip().lower()
    if username not in USERS:
        return False
    return check_password_hash(_HASHES[username], password or "")


def login(username: str):
    session["user"] = username.strip().lower()
    session.permanent = True


def logout():
    session.pop("user", None)


def current() -> dict | None:
    uid = session.get("user")
    if uid not in USERS:
        return None
    return {"id": uid, **USERS[uid]}


def required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        u = current()
        if not u:
            return redirect(url_for("login_view", next=request.path))
        g.user = u
        return view(*a, **kw)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    def wrapped(*a, **kw):
        u = current()
        if not u:
            return redirect(url_for("login_view", next=request.path))
        if u["role"] != "admin":
            return redirect(url_for("index"))
        g.user = u
        return view(*a, **kw)
    return wrapped
