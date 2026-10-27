from collections import Counter
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app import config, menu, reminders

UNIDADES = {"g", "ml", "ud", "diente", "lata", "manojo", "barra"}


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\nrecordatorios: {listas: [Compra, Casa]}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


def test_recipes_are_well_formed():
    basics = {menu.norm(b) for b in menu.recetario()["basicos"]}
    ids = [r["id"] for r in menu.recetario()["recetas"]]
    assert len(ids) == len(set(ids))
    for r in menu.recetario()["recetas"]:
        assert r.get("comida") or r.get("cena"), r["id"]
        assert r["grupo"] in set(menu.COMIDAS) | set(menu.CENAS), r["id"]
        for ing in r["ingredientes"]:
            if menu.norm(ing["nombre"]) in basics:
                continue
            assert ing["unidad"] in UNIDADES and ing["seccion"] in menu.SECCIONES and ing["cantidad"] > 0, (r["id"], ing)
    # Cada grupo del plan tiene recetas suficientes para no repetir en la semana
    recipes = menu.recetario()["recetas"]
    for meal, template in (("comida", menu.COMIDAS), ("cena", menu.CENAS)):
        for group, n in Counter(template).items():
            assert sum(1 for r in recipes if r.get(meal) and r["grupo"] == group) >= n, (meal, group)


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
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\nmenu: {personas: 3}\n", encoding="utf-8")
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
