"""Переводы интерфейса. Язык привязан к аккаунту: Сильвану — французский.

Словарь плоский и без библиотек: строк немного, а gettext с компиляцией .po
здесь только мешал бы правкам.
"""
from __future__ import annotations

STRINGS: dict[str, dict[str, str]] = {
    # --- общее ---
    "app_name":      {"ru": "Taouse",            "fr": "Taouse"},
    "tagline":       {"ru": "дом под Маконом",   "fr": "une maison près de Mâcon"},
    "login":         {"ru": "Войти",             "fr": "Se connecter"},
    "logout":        {"ru": "выйти",             "fr": "déconnexion"},
    "username":      {"ru": "Имя",               "fr": "Nom"},
    "password":      {"ru": "Пароль",            "fr": "Mot de passe"},
    "wrong_login":   {"ru": "Неверное имя или пароль",
                      "fr": "Nom ou mot de passe incorrect"},

    # --- навигация ---
    "nav_choose":    {"ru": "Выбрать",           "fr": "Choisir"},
    "nav_matches":   {"ru": "Совпадения",        "fr": "Coups de cœur"},
    "nav_all":       {"ru": "Все дома",          "fr": "Toutes les maisons"},
    "nav_map":       {"ru": "Карта",             "fr": "Carte"},
    "nav_dups":      {"ru": "Дубли",             "fr": "Doublons"},
    "nav_stats":     {"ru": "Статистика",        "fr": "Statistiques"},

    # --- выбор ---
    "like":          {"ru": "нравится",          "fr": "j'aime"},
    "maybe":         {"ru": "не знаю",           "fr": "peut-être"},
    "pass":          {"ru": "нет",               "fr": "non"},
    "left":          {"ru": "осталось",          "fr": "restant"},
    "all_seen":      {"ru": "Всё просмотрено",   "fr": "Tout est vu"},
    "all_seen_hint": {"ru": "Новые дома появятся после следующего сбора.",
                      "fr": "De nouvelles annonces arriveront à la prochaine collecte."},
    "match_hint":    {"ru": "Если понравится обоим — дом попадёт в совпадения.",
                      "fr": "Si vous aimez tous les deux, la maison ira dans les coups de cœur."},
    "details":       {"ru": "подробнее",         "fr": "en savoir plus"},

    # --- карточка ---
    "price":         {"ru": "цена",              "fr": "prix"},
    "area":          {"ru": "площадь",           "fr": "surface"},
    "land":          {"ru": "участок",           "fr": "terrain"},
    "rooms":         {"ru": "комнат",            "fr": "pièces"},
    "bedrooms":      {"ru": "спален",            "fr": "chambres"},
    "bedrooms_short": {"ru": "сп.",              "fr": "ch."},
    "terrace":       {"ru": "терраса",           "fr": "terrasse"},
    "pool":          {"ru": "бассейн",           "fr": "piscine"},
    "garage":        {"ru": "гараж",             "fr": "garage"},
    "condition":     {"ru": "состояние",         "fr": "état"},
    "place_score":   {"ru": "место",             "fr": "emplacement"},
    "per_m2":        {"ru": "€/м²",              "fr": "€/m²"},
    "no_photo":      {"ru": "без фото",          "fr": "sans photo"},
    "original":      {"ru": "открыть оригинал",  "fr": "voir l'annonce"},
    "satellite":     {"ru": "посмотреть со спутника", "fr": "vue satellite"},
    "same_house":    {"ru": "Тот же дом у других агентств",
                      "fr": "La même maison chez d'autres agences"},
    "price_range":   {"ru": "у разных агентств", "fr": "selon les agences"},
    "fees_note":     {"ru": "Разница в цене обычно означает, включена ли комиссия агентства.",
                      "fr": "L'écart de prix vient en général des honoraires d'agence."},
    "listings_n":    {"ru": "объявления",        "fr": "annonces"},
    "note":          {"ru": "заметка",           "fr": "note"},
    "save":          {"ru": "сохранить",         "fr": "enregistrer"},

    # --- совпадения ---
    "matches_title": {"ru": "Понравилось обоим", "fr": "Vous avez tous les deux aimé"},
    "matches_hint":  {"ru": "Эти дома стоит посмотреть вживую.",
                      "fr": "Ces maisons méritent une visite."},
    "no_matches":    {"ru": "Пока ни одного совпадения.",
                      "fr": "Aucun coup de cœur pour l'instant."},
    "plan_visit":    {"ru": "назначить визит",   "fr": "prévoir une visite"},
    "waiting_for":   {"ru": "ждём ответа",       "fr": "en attente de"},

    # --- список ---
    "sort_place":    {"ru": "по месту",          "fr": "par emplacement"},
    "sort_price":    {"ru": "по цене",           "fr": "par prix"},
    "sort_area":     {"ru": "по площади",        "fr": "par surface"},
    "sort_new":      {"ru": "сначала новые",     "fr": "les plus récentes"},
    "sort":          {"ru": "сортировка",        "fr": "trier"},
    "filter_price":  {"ru": "цена до",           "fr": "prix max"},
    "filter_score":  {"ru": "место от",          "fr": "emplacement min"},
    "apply":         {"ru": "применить",         "fr": "appliquer"},
    "houses_n":      {"ru": "домов",             "fr": "maisons"},
    "empty_list":    {"ru": "Пока ничего нет.",  "fr": "Rien pour l'instant."},

    # --- скрытие ---
    "hide":          {"ru": "убрать совсем",     "fr": "retirer définitivement"},
    "hide_short":    {"ru": "убрать",            "fr": "retirer"},
    "hidden_title":  {"ru": "Убранные дома",     "fr": "Maisons retirées"},
    "hidden_hint":   {"ru": "Эти дома не показываются нигде и не вернутся при новом сборе.",
                      "fr": "Ces maisons n'apparaissent plus nulle part et ne reviendront pas."},
    "no_hidden":     {"ru": "Ничего не убрано.", "fr": "Rien n'a été retiré."},
    "restore":       {"ru": "вернуть",           "fr": "restaurer"},
    "nav_hidden":    {"ru": "Убранные",          "fr": "Retirées"},

    # --- единицы ---
    "u_m2":          {"ru": "м²",                "fr": "m²"},
    "u_ha":          {"ru": "га",                "fr": "ha"},
    "u_per_m2":      {"ru": "€/м²",              "fr": "€/m²"},

    # --- состояние дома (коды из normalize.py) ---
    "needs_work":    {"ru": "нужен ремонт",      "fr": "travaux à prévoir"},
    "renovated":     {"ru": "отремонтирован",    "fr": "rénovée"},
    "good_state":    {"ru": "в хорошем состоянии", "fr": "bon état"},
    "recent":        {"ru": "недавней постройки", "fr": "récente"},

    # --- вердикт по месту (коды из placescore.py) ---
    "exact_zone":    {"ru": "точный адрес — зона №{n}",
                      "fr": "adresse exacte — zone n°{n}"},
    "exact_ok":      {"ru": "точный адрес — подходящее место",
                      "fr": "adresse exacte — emplacement adapté"},
    "exact_out":     {"ru": "точный адрес — вне найденных зон",
                      "fr": "adresse exacte — hors des zones retenues"},
    "by_commune":    {"ru": "адрес не указан — оценка по коммуне ({st}, {ha} га подходящей земли)",
                      "fr": "adresse non précisée — estimation par commune ({st}, {ha} ha adaptés)"},
    "approx_coords": {"ru": "координаты приблизительные",
                      "fr": "coordonnées approximatives"},
    "outside":       {"ru": "вне зоны поиска",   "fr": "hors zone de recherche"},
    "c_green":       {"ru": "зелёная",           "fr": "verte"},
    "c_amber":       {"ru": "жёлтая",            "fr": "orange"},
    "c_marginal":    {"ru": "почти не подходит", "fr": "peu adaptée"},

    # --- статусы ---
    "st_new":        {"ru": "новые",             "fr": "nouvelles"},
    "st_shortlist":  {"ru": "показать",          "fr": "à montrer"},
    "st_visit":      {"ru": "на визит",          "fr": "à visiter"},
    "st_rejected":   {"ru": "отклонённые",       "fr": "refusées"},

    # --- дубли и статистика (только админ, поэтому по-русски) ---
    "dups_title":    {"ru": "Сомнительные пары", "fr": "Paires douteuses"},
    "dups_hint":     {"ru": "Система склеивает осторожно: лучше показать дом дважды, "
                            "чем потерять его. Спорное — здесь.",
                      "fr": "Le regroupement est prudent : mieux vaut voir deux fois "
                            "que perdre une annonce."},
    "same_one":      {"ru": "это один дом",      "fr": "c'est la même maison"},
    "different":     {"ru": "разные дома",       "fr": "maisons différentes"},
    "merged_title":  {"ru": "Уже склеенные",     "fr": "Déjà regroupées"},
    "split":         {"ru": "разделить",         "fr": "séparer"},
}


def t(key: str, lang: str = "ru") -> str:
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("ru") or key


def make_translator(lang: str):
    def _t(key: str) -> str:
        return t(key, lang)
    return _t


def place_note(code: str, zone_rank: int | None, lang: str = "ru") -> str:
    """Текст вердикта по месту из кода, сохранённого в базе."""
    if not code:
        return ""
    if code.startswith("commune:"):
        _, status, ha = code.split(":")
        return t("by_commune", lang).format(st=t("c_" + status, lang), ha=ha)
    if code == "exact_zone":
        return t("exact_zone", lang).format(n=zone_rank)
    return t(code, lang)


def conditions(codes: str, lang: str = "ru") -> list[str]:
    """Коды состояния дома -> подписи на нужном языке."""
    return [t(c, lang) for c in (codes or "").split(",") if c]
