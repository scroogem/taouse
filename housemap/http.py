"""Общая HTTP-сессия.

Overpass отдаёт 406 на дефолтный User-Agent python-requests, да и в целом
вежливо представляться при работе с бесплатными публичными API.
"""
from __future__ import annotations

import requests

UA = "housemap/1.0 (private house search around Macon; python)"

session = requests.Session()
session.headers.update({"User-Agent": UA, "Accept": "*/*"})


def get(url, **kw):
    return session.get(url, **kw)


def post(url, **kw):
    return session.post(url, **kw)
