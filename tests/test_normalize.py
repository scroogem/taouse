"""Тесты разбора французских объявлений.

Регулярки тут хрупкие, а ошибка тихая: неверная площадь не падает, а просто
уводит поиск не туда. Поэтому каждый разобранный случай фиксируем.

    ./.venv/bin/python -m pytest tests/ -q
"""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from layer2 import normalize as N  # noqa: E402


CASES = [
    # (текст, площадь, участок, цена, комнат, спален)
    ("Maison 145 m² 349 000 € FAI, 5 pièces, 4 chambres, terrain 1 200 m², terrasse, piscine",
     145, 1200, 349000, 5, 4),
    ("T6 210m2 terrain de 1,5 ha, 320.000 euros hors honoraires, à rénover",
     210, 15000, 320000, 6, None),
    ("Maison 98 m² 285000 €, terrain 2.500 m2, cave 30 m²",
     98, 2500, 285000, None, None),
    ("Villa T4 120 m2 sur 850 m² de terrain, 3 chambres, 275 000 €",
     120, 850, 275000, 4, 3),
    ("Propriété 320 m² habitables, parcelle 12 500 m2, piscine, 690 000 € FAI",
     320, 12500, 690000, None, None),
    ("Maison 160 m² avec grange de 80 m², 1 ha de terrain, 340 000 €",
     160, 10000, 340000, None, None),
    ("Charmante maison de 112 m2, jardin de 600 m², 4 pièces, DPE D, 249 000 €",
     112, 600, 249000, 4, None),
]


def test_parsing():
    for text, area, land, price, rooms, beds in CASES:
        assert N.area_m2(text) == area, f"площадь: {text[:50]}"
        assert N.land_m2(text) == land, f"участок: {text[:50]}"
        assert N.price(text) == price, f"цена: {text[:50]}"
        assert N.rooms(text) == rooms, f"комнаты: {text[:50]}"
        assert N.bedrooms(text) == beds, f"спальни: {text[:50]}"


def test_fees():
    assert N.fees_included("349 000 € FAI") is True
    assert N.fees_included("320 000 € hors honoraires") is False
    assert N.fees_included("honoraires à la charge de l'acquéreur") is False
    assert N.fees_included("285 000 €") is None


def test_features_and_negation():
    assert N.feature("belle terrasse plein sud", "has_terrace") is True
    assert N.feature("maison sans piscine", "has_pool") is False
    assert N.feature("avec piscine chauffée", "has_pool") is True
    assert N.feature("garage double", "has_garage") is True
    assert N.feature("maison lumineuse", "has_pool") is None


def test_condition_and_dpe():
    # состояние хранится кодами: интерфейс двуязычный, текст подставляется при показе
    assert "needs_work" in N.condition_hint("maison à rénover, travaux à prévoir")
    assert "good_state" in N.condition_hint("maison en très bon état")
    assert N.condition_hint("maison rénovée en bon état") == "renovated,good_state"
    assert N.dpe("DPE : C") == "C"
    assert N.dpe("classe énergétique D") == "D"
    assert N.dpe("maison agréable") == ""


def test_price_bounds():
    assert N.price("garage 3 000 €") is None      # слишком дёшево для дома
    assert N.price("1 200 m² de terrain") is None  # это не цена
