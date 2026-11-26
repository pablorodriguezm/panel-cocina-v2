from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import config, menu, reminders

UNIDADES = {"g", "ml", "ud", "diente", "lata", "manojo", "barra"}


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    # Las pruebas del sorteo, en modo recetario; las de los planes lo cambian (plan_mode)
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\nrecordatorios: {listas: [Compra, Casa]}\nmenu: {modo: recetario}\n",
                 encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


def test_recipes_are_well_formed():
    basics = {menu.norm(b) for b in menu.recetario()["basicos"]}
    ids = [r["id"] for r in menu.recetario()["recetas"]]
    assert len(ids) == len(set(ids))
    for r in menu.recetario()["recetas"]:
        assert any(r.get(t) for t in menu.TOMAS), r["id"]
        assert r["grupo"] in set(menu.COMIDAS) | set(menu.CENAS) | menu.GRUPOS_TOMAS, r["id"]
        assert (r["grupo"] in menu.GRUPOS_TOMAS) == (not (r.get("comida") or r.get("cena"))), r["id"]
        for ing in r["ingredientes"]:
            if menu.norm(ing["nombre"]) in basics:
                continue
            assert ing["unidad"] in UNIDADES and ing["seccion"] in menu.SECCIONES and ing["cantidad"] > 0, (r["id"], ing)
        assert set(r.get("temporada") or []) <= {"primavera", "verano", "otoño", "invierno"}, r["id"]
    # En cada estación, cada grupo tiene recetas para no repetir en la semana y una más para poder cambiar
    for when in ("primavera", "verano", "otoño", "invierno"):
        for meal, template in (("comida", menu.COMIDAS), ("cena", menu.CENAS)):
            for group, n in Counter(template).items():
                assert len(menu.pool(meal, group, when)) >= n + 1, (when, meal, group)


def test_week_plan_is_balanced_stable_and_without_repeats():
    week = date(2026, 10, 26)
    days = menu.plan(date(2026, 10, 29))  # cualquier día de la semana da la misma semana
    assert days == menu.plan(week)
    assert [d["fecha"] for d in days][0] == "2026-10-26" and len(days) == 7
    ids = [d[m]["id"] for d in days for m in ("comida", "cena")]
    assert len(ids) == len(set(ids)) == 14
    for monday in (date(2026, 10, 26), date(2026, 11, 2), date(2026, 11, 9), date(2027, 3, 1)):
        mains = [menu._main(r) for d in menu.plan(monday) for r in (d["comida"], d["cena"])
                 if r["grupo"] in ("pescado", "carne_blanca", "carne_roja")]
        assert len(mains) == len(set(mains)), monday  # nada de pavo o merluza dos veces en la semana
    groups = Counter(d["comida"]["grupo"] for d in days)
    assert groups["legumbre"] == 3 and groups["carne_roja"] == 1
    assert menu.plan(date(2026, 11, 2)) != days  # otra semana, otro menú


def test_shopping_list_adds_up_the_week_and_leaves_out_basics():
    days = menu.plan(date(2026, 10, 26))
    sections = menu.shopping(days)
    assert [s["seccion"] for s in sections] == [s for s in menu.SECCIONES if s in {x["seccion"] for x in sections}]
    items = {i["clave"]: i for s in sections for i in s["items"]}
    expected = Counter()
    for d in days:
        for m in ("comida", "cena"):
            for ing in d[m]["ingredientes"]:
                expected[menu.key(ing["nombre"], ing["unidad"])] += ing["cantidad"]
    assert {k: i["cantidad"] for k, i in items.items()} == dict(expected)
    names = {menu.norm(i["nombre"]) for i in items.values()}
    assert not names & {"sal", "aceite de oliva virgen extra", "pimenton dulce"}


def test_amounts_read_like_a_shopping_list():
    assert menu.amount(320, "g") == "320 g"
    assert menu.amount(1200, "g") == "1,2 kg"
    assert menu.amount(1000, "ml") == "1 l"
    assert menu.amount(6, "ud") == "6"
    assert menu.amount(1, "diente") == "1 diente" and menu.amount(5, "diente") == "5 dientes"


def test_more_people_scale_the_quantities(cfg):
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\nmenu: {personas: 3, modo: recetario}\n", encoding="utf-8")
    config.load.cache_clear()
    dish = next(d["comida"] for d in menu.plan(date(2026, 10, 26)) if d["comida"]["id"])
    recipe = next(r for r in menu.recetario()["recetas"] if r["id"] == dish["id"])
    grams = next(i for i in recipe["ingredientes"] if i.get("unidad") == "g")
    scaled = next(i for i in dish["ingredientes"] if i["nombre"] == grams["nombre"])
    assert scaled["cantidad"] == round(grams["cantidad"] * 1.5 / 10) * 10


def test_in_list_matches_the_start_of_the_name():
    assert menu.in_list("Huevos", ["Huevos camperos"])
    assert menu.in_list("Limón", ["limon"])
    assert not menu.in_list("Leche de coco ligera", ["Leche"])


def test_store_flow_from_tablet_to_reminders(tmp_path):
    path = tmp_path / "menu.json"
    s = menu.Store(path)
    item = {"clave": "lentejas pardinas|g", "recordatorio": "Lentejas pardinas (300 g)"}
    assert s.toggle("2026-10-26", item) is True
    assert s.toggle("2026-10-26", item) is False  # tocar otra vez lo quita
    s.toggle("2026-10-26", item)
    lists = [{"nombre": "Compra", "items": [{"titulo": "Pan", "notas": None, "vence": None}], "updated": 1}]
    merged = menu.Store(path).merge_into(lists)  # sobrevive a un reinicio
    assert [i["titulo"] for i in merged[0]["items"]] == ["Pan", "Lentejas pardinas (300 g)"]
    assert merged[0]["items"][1]["panel"] is True

    assert s.collect() == ["Lentejas pardinas (300 g)"]
    assert s.collect() == []  # no se añade dos veces a Recordatorios
    assert s.toggle("2026-10-26", item) is True  # ya entregado: no se puede quitar desde el panel
    # El Atajo no llegó a añadirlo: la lista llega sin él y se vuelve a ofrecer, no se pierde
    s.shopping_list_arrived(["Pan"])
    assert s.merge_into(lists)[0]["items"][-1]["titulo"] == "Lentejas pardinas (300 g)"
    assert s.status()["sin_llegar"] == {"Lentejas pardinas (300 g)": 1}
    assert s.collect() == ["Lentejas pardinas (300 g)"]
    s.shopping_list_arrived(["Pan", "lentejas pardinas (300 g)"])  # esta vez sí ha llegado
    assert s.pending == [] and s.merge_into(lists) == lists


@pytest.fixture
def client(tmp_path, monkeypatch, cfg):
    monkeypatch.setattr(reminders, "DATA_PATH", tmp_path / "data" / "r.json")
    monkeypatch.setattr(menu, "DATA_PATH", tmp_path / "data" / "menu.json")
    monkeypatch.setenv("PANEL_TOKEN", "abc")
    from app import main
    with TestClient(main.app) as c:
        yield c


def test_endpoints_move_an_ingredient_and_the_shortcut_collects_it(client):
    week = client.get("/api/menu").json()
    assert len(week["dias"]) == 7 and week["lista"] == "Compra"
    item = week["compra"][0]["items"][0]
    r = client.post("/api/menu/compra", json={"semana": 0, "clave": item["clave"]})
    moved = next(i for s in r.json()["compra"] for i in s["items"] if i["clave"] == item["clave"])
    assert moved["pasado"] and moved["en_lista"]
    compra = client.get("/api/hogar").json()["recordatorios"]["data"][0]
    assert compra["items"][-1]["titulo"] == item["recordatorio"]

    assert client.post("/api/recordatorios/recoger").status_code == 401
    got = client.post("/api/recordatorios/recoger", headers={"X-Panel-Token": "abc"}).json()
    assert got == {"lista": "Compra", "items": [item["recordatorio"]], "texto": item["recordatorio"]}
    client.post("/api/recordatorios", headers={"X-Panel-Token": "abc"},
                json={"lista": "Compra", "items": item["recordatorio"]})
    compra = client.get("/api/hogar").json()["recordatorios"]["data"][0]
    assert [i["titulo"] for i in compra["items"]] == [item["recordatorio"]]  # sin duplicar
    assert "panel" not in compra["items"][0]


def test_bad_requests(client):
    assert client.get("/api/menu?semana=x").status_code == 422
    assert client.post("/api/menu/compra", json={"semana": 0}).status_code == 400
    assert client.post("/api/menu/compra", json={"semana": 0, "clave": "nada|g"}).status_code == 404


def test_seasons_follow_the_calendar_and_filter_the_recipes():
    assert [menu.season(date(2026, m, 15)) for m in (1, 4, 7, 10, 12)] == ["invierno", "primavera", "verano", "otoño", "invierno"]
    summer = {d[m]["id"] for wk in (date(2026, 7, 6), date(2026, 7, 13), date(2026, 8, 3)) for d in menu.plan(wk) for m in ("comida", "cena")}
    winter = {d[m]["id"] for wk in (date(2027, 1, 4), date(2027, 1, 11), date(2027, 2, 1)) for d in menu.plan(wk) for m in ("comida", "cena")}
    by_id = {r["id"]: r for r in menu.recetario()["recetas"]}
    assert all("verano" in (by_id[i].get("temporada") or ["verano"]) for i in summer)
    assert all("invierno" in (by_id[i].get("temporada") or ["invierno"]) for i in winter)
    assert "gazpacho-huevo" not in winter and "ternera-guisada" not in summer


def test_swapping_a_dish_keeps_its_group_avoids_repeats_and_survives_restart(tmp_path):
    path = tmp_path / "menu.json"
    s = menu.Store(path)
    day = date(2026, 11, 18)  # miércoles: comida de carne blanca
    before = next(d for d in s.plan(day) if d["fecha"] == "2026-11-18")["comida"]
    assert s.swap(day, "comida") is True
    days = menu.Store(path).plan(day)
    after = next(d for d in days if d["fecha"] == "2026-11-18")["comida"]
    assert after["id"] != before["id"] and after["grupo"] == before["grupo"] and after["cambiado"] is True
    ids = [d[m]["id"] for d in days for m in ("comida", "cena")]
    assert len(ids) == len(set(ids))
    # La lista de ingredientes sale del menú cambiado
    names = {i["nombre"] for sec in menu.week_view(day, s, [])["compra"] for i in sec["items"]}
    assert {i["nombre"] for i in after["ingredientes"]} <= names
    # Dando vueltas se vuelve al plato original y el cambio se borra
    for _ in range(10):
        s.swap(day, "comida")
        if next(d for d in s.plan(day) if d["fecha"] == "2026-11-18")["comida"]["id"] == before["id"]:
            break
    assert "cambiado" not in next(d for d in s.plan(day) if d["fecha"] == "2026-11-18")["comida"]
    assert s.changes.get("2026-11-16", {}) == {}


def test_swap_endpoint(client):
    week = client.get("/api/menu").json()
    fecha = week["dias"][-1]["fecha"]  # el domingo de esta semana: nunca es pasado para el servidor
    before = week["dias"][-1]["cena"]["id"]
    r = client.post("/api/menu/cambiar", json={"fecha": fecha, "momento": "cena"})
    assert r.status_code == 200 and r.json()["dias"][-1]["cena"]["id"] != before
    assert client.get("/api/menu").json()["dias"][-1]["cena"]["cambiado"] is True
    assert client.post("/api/menu/cambiar", json={"fecha": fecha, "momento": "postre"}).status_code == 400
    assert client.post("/api/menu/cambiar", json={"fecha": "2020-01-01", "momento": "cena"}).status_code == 400
    assert client.post("/api/menu/cambiar", json={"fecha": "ayer"}).status_code == 400


# ---------- Planes nutricionales por turnos (modo por defecto) ----------

@pytest.fixture
def plan_mode(cfg):
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\nrecordatorios: {listas: [Compra, Casa]}\n", encoding="utf-8")
    config.load.cache_clear()
    assert menu.mode() == "planes"
    return cfg


def test_every_plan_cell_is_a_recipe_of_its_meal():
    by_id = {r["id"]: r for r in menu.recetario()["recetas"]}
    plans = menu.planes()["planes"]
    assert [p["nombre"] for p in plans] == ["Plan del 23 de enero", "Plan del 27 de febrero"]
    for p in plans:
        assert len(p["dias"]) == 7
        for day in p["dias"]:
            assert set(day) == set(menu.TOMAS), (p["nombre"], day)
            for toma, rid in day.items():
                if rid != menu.LIBRE:
                    assert by_id[rid].get(toma), (p["nombre"], toma, rid)  # p. ej. un desayuno en el desayuno


def test_plans_alternate_week_by_week(plan_mode):
    names = [menu.week_plan(date(2026, 11, 23) + timedelta(weeks=i))["nombre"] for i in range(4)]
    assert names == ["Plan del 23 de enero", "Plan del 27 de febrero"] * 2
    assert menu.week_plan(date(2026, 11, 26))["nombre"] == "Plan del 23 de enero"  # cualquier día de la semana
    days = menu.plan(date(2026, 11, 23))
    assert days[0]["comida"]["nombre"] == "Brócoli con huevo cocido y taquitos de pavo"
    assert days[0]["desayuno"]["id"] == "plan-desayuno-pavo" and days[6]["cena"]["id"] == "plan-revuelto-gambas-champinones"
    feb = menu.plan(date(2026, 11, 30))
    assert feb[5]["cena"]["libre"] and feb[5]["cena"]["ingredientes"] == []   # sábado: cena libre
    assert feb[1]["comida"]["nombre"] == "Lacón con pimentón, patatas y espárragos blancos"


def test_plan_start_can_be_moved_in_config(plan_mode):
    plan_mode.write_text("ubicacion: {latitud: 0, longitud: 0}\nmenu: {planes_desde: '2026-11-30'}\n", encoding="utf-8")
    config.load.cache_clear()
    assert menu.week_plan(date(2026, 11, 23))["nombre"] == "Plan del 27 de febrero"


def test_plan_shopping_includes_every_meal_but_not_basics(plan_mode):
    days = menu.plan(date(2026, 11, 23))
    items = {i["nombre"]: i for s in menu.shopping(days) for i in s["items"]}
    assert items["Leche semidesnatada"]["cantidad"] == 400 * 7                     # desayuno de cada día
    assert items["Yogur de proteínas stracciatella"]["cantidad"] == 2 * 4          # media mañana, 4 días
    assert items["Lomo embuchado"]["cantidad"] == 40 * 4                            # merienda, 4 días
    assert "Café" not in items                                                      # de la despensa
    view = menu.week_view(date(2026, 11, 23), menu.Store(Path("/nonexistent/menu.json")), [])
    assert view["plan"] == "Plan del 23 de enero" and view["modo"] == "planes"
    assert view["tomas"] == menu.TOMAS


def test_swapping_in_a_plan_week(plan_mode, tmp_path):
    s = menu.Store(tmp_path / "menu.json")
    sat = date(2026, 12, 5)  # sábado de la semana del plan de febrero
    assert s.swap(sat, "cena") is False                         # la cena libre no se cambia
    assert s.swap(sat, "merienda") is True                      # un tentempié por otro
    day = next(d for d in s.plan(sat) if d["fecha"] == "2026-12-05")
    assert day["merienda"]["grupo"] == "tentempie" and day["merienda"]["id"] != "plan-griego-o-cafe"
    assert day["merienda"]["cambiado"] is True
    assert s.swap(sat, "comida") is True                        # la comida, por otra de su grupo (pescado)
    assert next(d for d in s.plan(sat) if d["fecha"] == "2026-12-05")["comida"]["grupo"] == "pescado"
