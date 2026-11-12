from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import aire, calefaccion, config, sources
from app.energy import HourPrice

MADRID = ZoneInfo("Europe/Madrid")


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\nconsumo:\n  aparatos:\n"
                 "    - {entidad: sensor.cocina, nombre: Cocina}\n    - {entidad: sensor.clima, nombre: Climatización}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


def test_entity_is_the_appliance_named_climatizacion(cfg):
    assert aire.entity() == "sensor.clima"
    cfg.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    config.load.cache_clear()
    assert aire.entity() is None


def test_day_record_costs_each_hour_at_its_price_and_counts_the_cold():
    hourly = [{"time": "2026-11-11T07:00", "kwh": 2.0}, {"time": "2026-11-11T08:00", "kwh": 1.0}, {"time": "2026-11-11T09:00", "kwh": 0.02}]
    prices = {"2026-11-11T07:00": 0.10, "2026-11-11T08:00": 0.20, "2026-11-11T09:00": 0.30}
    temps = {"2026-11-11T07:00": 4.0, "2026-11-11T08:00": 8.0, "2026-11-11T09:00": 21.0}
    r = aire.day_record(hourly, prices, temps)
    tax = calefaccion.electricity_with_taxes(1.0)
    assert r == {"kwh": 3.02, "eur": round((0.2 + 0.2 + 0.006) * tax, 2), "t_media": 11.0,
                 "grados_dia": round((14 + 10 + 0) / 3, 1), "horas": 2}
    # Sin el precio de alguna hora no se inventa el coste
    assert aire.day_record(hourly, {"2026-11-11T07:00": 0.1}, temps)["eur"] is None


def test_summary_and_kwh_per_degree_day_need_a_week_of_heating(tmp_path):
    s = aire.Store(tmp_path / "aire.json")
    today = date(2026, 11, 12)
    for i in range(1, 7):
        s.add(today - timedelta(days=i), {"kwh": 10.0, "eur": 2.0, "t_media": 8.0, "grados_dia": 10.0, "horas": 6})
    s.add(today - timedelta(days=7), {"kwh": 0.1, "eur": 0.02, "t_media": 17.0, "grados_dia": 1.0, "horas": 0})  # apagado
    out = aire.summary(aire.Store(tmp_path / "aire.json"), today, {"kwh": 1.5, "eur": 0.3})
    assert out["ayer"]["kwh"] == 10.0 and out["hoy"]["kwh"] == 1.5
    assert out["semana"] == {"kwh": 60.0, "eur": 12.0, "dias": 6}
    assert out["kwh_por_grado_dia"] is None and out["dias_calefaccion"] == 6
    s.add(today - timedelta(days=8), {"kwh": 10.0, "eur": 2.0, "t_media": 8.0, "grados_dia": 10.0, "horas": 6})
    assert aire.summary(s, today, None)["kwh_por_grado_dia"] == 1.0
    assert s.missing(today) == []


class FakeHA:
    def __init__(self):
        self.asked = []

    async def states(self, ids):
        return {i: {"state": "1000", "attributes": {"unit_of_measurement": "W"}} for i in ids}

    async def history(self, entity, start, end):
        self.asked.append((start, end))
        return [{"state": "1000", "last_changed": start.astimezone(ZoneInfo("UTC")).isoformat()}]  # 1 kW todo el rato


class FakeClient:
    def __init__(self, fail=False):
        self.fail = fail

    async def get(self, url, params, timeout):
        if self.fail:
            raise sources.httpx.ConnectError("sin red")
        start = datetime.fromisoformat(params["start_date"])
        values = [{"datetime": (start + timedelta(hours=h)).replace(tzinfo=MADRID).isoformat(), "value": 100.0} for h in range(24 * 8)]
        payload = {"included": [{"type": "PVPC", "attributes": {"values": values}}]}
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: payload})()


@pytest.mark.anyio
async def test_air_real_fills_the_closed_days_once_and_adds_today(tmp_path):
    store = aire.Store(tmp_path / "aire.json")
    ha = FakeHA()
    now = datetime.now(MADRID)
    prices = [HourPrice(now.replace(hour=h, minute=0, second=0, microsecond=0, tzinfo=None), 0.1) for h in range(24)]
    out = await sources.air_real(ha, FakeClient(), store, prices, None)
    assert len(store.days) == 7 and len(ha.asked) == 8
    yesterday = out["ayer"]
    assert yesterday["kwh"] == pytest.approx(24.0, abs=1.1)  # 1 kW todo el día (23 o 25 h si cae el cambio de hora)
    assert yesterday["eur"] == pytest.approx(yesterday["kwh"] * calefaccion.electricity_with_taxes(0.1), abs=0.02)
    assert out["hoy"]["kwh"] == pytest.approx(now.hour + now.minute / 60, abs=0.05)
    ha.asked.clear()
    await sources.air_real(ha, FakeClient(), store, prices, None)
    assert len(ha.asked) == 1  # los días cerrados ya están: solo hoy


@pytest.mark.anyio
async def test_air_real_without_ree_keeps_today_and_retries_later(tmp_path):
    store = aire.Store(tmp_path / "aire.json")
    out = await sources.air_real(FakeHA(), FakeClient(fail=True), store, [], None)
    assert store.days == {} and out["ayer"] is None and out["hoy"]["eur"] is None


@pytest.fixture
def anyio_backend():
    return "asyncio"
