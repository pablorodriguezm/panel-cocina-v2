import pytest
from fastapi.testclient import TestClient

from app import config, reminders


def test_accepts_the_shapes_shortcuts_can_send():
    assert reminders.parse({"lista": "Compra", "items": ["Leche", " ", "Pan"]}) == [
        ("Compra", [{"titulo": "Leche", "notas": None, "vence": None}, {"titulo": "Pan", "notas": None, "vence": None}])]
    assert reminders.parse({"lista": "Compra", "items": "Leche\nPan\n"})[0][1][1]["titulo"] == "Pan"
    [(name, items)] = reminders.parse({"lista": "Casa", "items": [{"titulo": "Fontanero", "notas": "", "vence": "2026-10-25"}]})
    assert items == [{"titulo": "Fontanero", "notas": None, "vence": "2026-10-25"}]
    assert [n for n, _ in reminders.parse({"listas": [{"lista": "A", "items": []}, {"lista": "B", "items": []}]})] == ["A", "B"]



@pytest.mark.parametrize("empty", ["", None])
def test_everything_bought_empties_the_list(empty):
    assert reminders.parse({"lista": "Compra", "items": empty}) == [("Compra", [])]


@pytest.mark.parametrize("bad", [[], {"items": ["x"]}, {"lista": "Compra", "items": 3}])
def test_rejects_malformed(bad):
    with pytest.raises(ValueError):
        reminders.parse(bad)


def test_store_replaces_list_and_survives_restart(tmp_path):
    path = tmp_path / "r.json"
    s = reminders.Store(path)
    s.update({"lista": "Compra", "items": ["Leche", "Pan"]})
    s.update({"lista": "Compra", "items": ["Pan"]})  # la leche ya se compró
    again = reminders.Store(path)
    [compra, casa] = again.view(["Compra", "Casa"])
    assert [i["titulo"] for i in compra["items"]] == ["Pan"]
    assert casa == {"nombre": "Casa", "items": [], "updated": None}


@pytest.fixture
def client(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\nrecordatorios: {listas: [Compra]}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    monkeypatch.setattr(reminders, "DATA_PATH", tmp_path / "data" / "r.json")
    monkeypatch.setenv("PANEL_TOKEN", "abc")
    config.load.cache_clear()
    from app import main
    with TestClient(main.app) as c:
        yield c
    config.load.cache_clear()


def test_endpoint_needs_token(client):
    assert client.post("/api/recordatorios", json={"lista": "Compra", "items": []}).status_code == 401
    assert client.post("/api/recordatorios", json={"lista": "Compra", "items": []}, headers={"X-Panel-Token": "no"}).status_code == 401


def test_endpoint_stores_and_warns_unknown_list(client):
    r = client.post("/api/recordatorios", headers={"X-Panel-Token": "abc"},
                    json={"listas": [{"lista": "Compra", "items": ["Leche"]}, {"lista": "Farmacia", "items": ["Tiritas"]}]})
    assert r.status_code == 200
    assert "Farmacia" in r.json()["aviso"]
    from app import main
    [compra] = main.state["reminders"].view(["Compra"])
    assert compra["items"][0]["titulo"] == "Leche"
