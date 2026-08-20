"""Оценка пригодности места — непрерывная, без обрывов на порогах.

Раньше каждый критерий был ступенькой: 900 м до автострады — годится, 899 —
выброшено. На карте это давало рваные пятна, а на границе двух почти одинаковых
мест — разный вердикт.

Теперь у каждого порога есть зона допуска (margin). Внутри неё оценка плавно
падает от 1 до 0:

    порог ────────────── 1.0   (точно нормально)
      │        margin
    порог-margin ─────── 0.0   (точно нет)

Критерии при этом двух разных сортов (см. HARD_RULES): запреты берутся по
минимуму — хороший вид не компенсирует железную дорогу под окном; предпочтения
сворачиваются взвешенным геометрическим средним. Итог — произведение того и
другого. Заодно всегда известно, ЧТО именно ограничивает место, — это и
показываем в попапе карты.
"""
from __future__ import annotations

import numpy as np

# Критерии двух разных природ, и мешать их в одну кучу нельзя:
#
#   veto — настоящий запрет. Железная дорога в 300 м не компенсируется ничем,
#          поэтому такие критерии берутся по минимуму: провалил один — всё.
#   pref — сильное предпочтение. «Многовато полей вокруг» или «доход ниже
#          среднего» — это минус, а не приговор. Они усредняются с весами,
#          давая плавный градиент вместо обрыва.
#
# Именно смешение этих двух типов в одном минимуме делало карту похожей на
# биомы: 76% территории получали ровно ноль из-за одного придирчивого критерия.
#
# (ключ в config.hard, слой, направление, подпись, margin, тип, вес для pref)
HARD_RULES = [
    ("dist_motorway_min_m",        "dist_motorway",            "min", "шум автомагистрали", 350, "veto", 0),
    ("dist_trunk_primary_min_m",   "dist_trunk_primary",       "min", "шум нац/деп дороги", 150, "veto", 0),
    ("dist_rail_min_m",            "dist_rail",                "min", "рядом ж/д", 350, "veto", 0),
    ("dist_rail_highspeed_min_m",  "dist_rail_highspeed",      "min", "рядом LGV", 600, "veto", 0),
    ("dist_nuisance_min_m",        "dist_nuisance",            "min", "карьер/свалка/завод", 300, "veto", 0),
    ("dist_farmyard_min_m",        "dist_farmyard",            "min", "рядом скотный двор", 150, "veto", 0),
    ("dist_light_industry_min_m",  "dist_light_industry",      "min", "ремесленная зона рядом", 150, "veto", 0),
    ("slope_max_pct",              "slope_pct",                "max", "слишком крутой склон", 8, "veto", 0),
    ("elev_min_m",                 "elev",                     "min", "низко: пойма Соны", 25, "veto", 0),

    ("farm_share_800m_max",        "farm_share_800m",          "max", "вокруг поля/луга", 0.18, "pref", 3.0),
    # Два разных вопроса про рельеф, и путать их нельзя:
    #   rel_elev_2km — «высоко ли над дном долины» (не затопит, сухо, вид);
    #   tpi_1km      — «выпуклое ли место локально» (не в ямке, дренаж).
    # Седловина между двумя холмами на 400 м — это низкий TPI, но никакая не
    # низина. Поэтому TPI мягче и весит меньше, а решает высота над долиной.
    ("rel_elev_2km_min_m",         "rel_elev_2km",             "min", "низко над долиной", 12, "pref", 3.0),
    ("tpi_1km_min_m",              "tpi_1km",                  "min", "ложбина между холмами", 12, "pref", 1.5),
    ("pop_2km_min",                "pop_2km",                  "min", "глухомань (мало жителей)", 250, "pref", 2.0),
    ("dist_bakery_max_m",          "dist_bakery",              "max", "булочная далеко", 2500, "pref", 1.5),
    ("dist_school_max_m",          "dist_school",              "max", "школа далеко", 2500, "pref", 1.5),
    ("income_1km_min_eur",         "income_1km",               "min", "низкие доходы в округе", 2500, "pref", 1.5),
    ("social_housing_share_1km_max", "social_housing_share_1km", "max", "много соцжилья", 0.15, "pref", 1.0),
    ("dist_motorway_junction_max_m", "dist_junction",          "max", "далеко до съезда", 5000, "pref", 1.0),
]

# Даже полностью провалив все предпочтения, место сохраняет этот множитель —
# чтобы на карте была видна разница между «так себе» и «совсем никак».
PREF_FLOOR = 0.20

NO_LIMIT = 250  # «ограничений нет» — для карты и отчётов


def _membership(v, thr, direction, margin):
    """1.0 — критерий выполнен с запасом, 0.0 — провален, между — плавно."""
    margin = max(float(margin), 1e-9)
    with np.errstate(invalid="ignore"):
        t = ((v - (thr - margin)) / margin) if direction == "min" \
            else (((thr + margin) - v) / margin)
    t = np.clip(t, 0.0, 1.0)
    return np.where(np.isnan(t), 0.6, t)  # нет данных — не хвалим и не казним


def feasibility(L: dict, cfg: dict, inside: np.ndarray):
    """-> (пригодность 0..1, индекс ограничивающего критерия, подписи, статистика)

    Запреты берутся по минимуму, предпочтения — взвешенным средним. Итог —
    их произведение, так что железная дорога по-прежнему убивает место, а
    десяток мелких «не идеально» лишь плавно снижают балл.
    """
    hard = cfg["hard"]
    tol = float(cfg.get("tolerance", 0.0))
    overrides = cfg.get("margins") or {}

    parts, labels, stats, kinds, weights = [], [], [], [], []
    for key, layer, direction, label, default_margin, kind, weight in HARD_RULES:
        thr = hard.get(key)
        if thr is None or layer not in L:
            continue
        margin = overrides.get(key, default_margin)
        if margin is None:
            margin = abs(thr) * tol
        margin = margin * (1.0 + tol) if tol else margin

        p = _membership(L[layer], thr, direction, margin)
        parts.append(p)
        labels.append(label)
        kinds.append(kind)
        weights.append(weight)
        stats.append((label, key, thr, round(float(margin), 3), kind,
                      int((inside & (p <= 0.001)).sum()),
                      int((inside & (p < 1.0)).sum())))

    P = np.stack(parts)
    kinds = np.array(kinds)
    is_veto = kinds == "veto"

    veto = P[is_veto].min(axis=0) if is_veto.any() else np.ones_like(P[0])

    if (~is_veto).any():
        w = np.array(weights, dtype=np.float32)[~is_veto]
        # Взвешенное ГЕОМЕТРИЧЕСКОЕ среднее, а не арифметическое: иначе хорошая
        # школа и высокий доход вытягивают место, где нет ни холма, ни
        # виноградника — так в рейтинг лезли равнины Бресса. Геометрическое
        # среднее не даёт второстепенному компенсировать главное.
        q = PREF_FLOOR * 0.4 + (1.0 - PREF_FLOOR * 0.4) * P[~is_veto]
        pref = np.exp((np.log(q) * w[:, None, None]).sum(axis=0) / w.sum())
    else:
        pref = np.ones_like(P[0])

    feas = veto * pref
    # ограничивающий фактор: сначала смотрим на запреты, они решают
    lim_all = P.argmin(axis=0).astype(np.int16)
    if is_veto.any():
        veto_idx = np.nonzero(is_veto)[0]
        lim_veto = veto_idx[P[is_veto].argmin(axis=0)].astype(np.int16)
        limiting = np.where(veto < 0.75, lim_veto, lim_all)
    else:
        limiting = lim_all
    # там, где выполнено вообще всё, ограничивать нечему: иначе argmin вернёт
    # просто первый критерий по списку и соврёт («мешает автострада» в 2,5 км)
    limiting = np.where(P.min(axis=0) >= 0.995, NO_LIMIT, limiting).astype(np.int16)
    return feas.astype(np.float32), limiting, labels, stats


def _norm(v, bad, good):
    with np.errstate(invalid="ignore"):
        t = (v - bad) / (good - bad)
    t = np.clip(t, 0.0, 1.0)
    return np.where(np.isnan(t), 0.35, t)


def attractiveness(L: dict, cfg_soft: dict) -> np.ndarray:
    """Балл 0..100 «насколько тут хорошо», без учёта запретов."""
    total_w = sum(c["weight"] for c in cfg_soft.values())
    score = np.zeros_like(L["elev"], dtype=np.float32)
    for name, c in cfg_soft.items():
        if c["metric"] not in L:
            print(f"  ! мягкий критерий '{name}': нет слоя {c['metric']}, пропущен")
            continue
        score += _norm(L[c["metric"]], c["bad"], c["good"]) * c["weight"]
    return (score / total_w * 100.0).astype(np.float32)
