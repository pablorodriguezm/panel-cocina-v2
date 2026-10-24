"""Lectura de Home Assistant con un HA de mentira (httpx.MockTransport)."""
import asyncio
import httpx
import pytest

from app import config, sources

CFG = """
home_assistant: {url: "http://ha.test:8123"}
ubicacion: {latitud: 0, longitud: 0, zona: Europe/Madrid}
usuarios:
  - {id: pablo, nombre: Pablo, trayecto: sensor.trayecto_pablo}
calendario: {entidad: calendar.rim_y_pablo, dias: 7}
coche:
  nombre: Tesla
  entidades:
    bateria: sensor.tesla_battery_level
    cargando: sensor.tesla_charging
    potencia_carga: sensor.tesla_charger_power
    ruedas: {del_izq: sensor.tesla_tire_fl, del_der: sensor.tesla_tire_missing}
"""

STATES = {
    "sensor.tesla_battery_level": {"state": "64", "attributes": {"unit_of_measurement": "%"}, "last_changed": "x"},
    "sensor.tesla_charging": {"state": "charging", "attributes": {}},
    "sensor.tesla_charger_power": {"state": "7400", "attributes": {"unit_of_measurement": "W"}},
    "sensor.tesla_tire_fl": {"state": "41.3357570107257", "attributes": {"unit_of_measurement": "psi"}},
    "sensor.trayecto_pablo": {"state": "24", "attributes": {"route": "A-49", "distance": 21.5}, "last_updated": "y"},
}


def handler(request: httpx.Request) -> httpx.Response:
    assert request.headers["Authorization"] == "Bearer secreto"
    path = request.url.path
    if path.startswith("/api/states/"):
        e = path.rsplit("/", 1)[1]
        return httpx.Response(200, json=STATES[e]) if e in STATES else httpx.Response(404)
    if path == "/api/calendars/calendar.rim_y_pablo":
        return httpx.Response(200, json=[
            {"summary": "Cena", "start": {"dateTime": "2026-10-24T21:00:00+02:00"}, "end": {"dateTime": "2026-10-24T23:00:00+02:00"}},
            {"summary": "Puente", "start": {"date": "2026-10-23"}, "end": {"date": "2026-10-25"}},
        ])
    return httpx.Response(500)


@pytest.fixture
def ha(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text(CFG, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    monkeypatch.setenv("HA_TOKEN", "secreto")
    config.load.cache_clear()
    yield sources.HomeAssistant(httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    config.load.cache_clear()


def test_car(ha):
    car = asyncio.run(sources.car(ha))
    assert car["bateria"] == 64 and car["cargando"] is True
    assert car["potencia_kw"] == pytest.approx(7.4)
    # 41,3 psi → 2,85 bar; una entidad que no existe no tumba el resto
    assert car["ruedas"] == {"del_izq": 2.85, "del_der": None}
    assert car["ruedas_unidad"] == "bar"


def test_calendar_sorted_with_all_day_first(ha):
    events = asyncio.run(sources.calendar_events(ha))
    assert [e["title"] for e in events] == ["Puente", "Cena"]
    assert events[0]["all_day"] is True


def test_commute(ha):
    c = asyncio.run(sources.commute(ha, "pablo"))
    assert c["minutos"] == 24 and c["ruta"] == "A-49"


def test_missing_token_is_clear_error(ha, monkeypatch):
    monkeypatch.delenv("HA_TOKEN")
    with pytest.raises(RuntimeError, match="HA_TOKEN"):
        asyncio.run(sources.car(ha))
