from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app import config, consumption, energy

MADRID = ZoneInfo("Europe/Madrid")


def row(state, utc):
    return {"state": str(state), "last_changed": utc}


def test_hourly_from_counter_history():
    start = datetime(2026, 10, 20, 0, 0, tzinfo=MADRID)
    now = datetime(2026, 10, 20, 2, 30, tzinfo=MADRID)
    rows = [row(100.0, "2026-10-19T21:55:00+00:00"),  # antes de medianoche (23:55 en Madrid): valor de partida
            row(100.4, "2026-10-19T22:30:00+00:00"),  # 00:30
            row(100.9, "2026-10-19T23:10:00+00:00"),  # 01:10
            row("unavailable", "2026-10-19T23:20:00+00:00"),
            row(101.0, "2026-10-20T00:15:00+00:00")]  # 02:15
    h = consumption.hourly_from_history(rows, start, now, MADRID)
    assert [x["time"] for x in h] == ["2026-10-20T00:00", "2026-10-20T01:00", "2026-10-20T02:00"]
    assert [x["kwh"] for x in h] == pytest.approx([0.4, 0.5, 0.1])


def test_dst_day_has_25_hours_and_wh_units():
    start = datetime(2026, 10, 25, 0, 0, tzinfo=MADRID)
    now = datetime(2026, 10, 25, 23, 30, tzinfo=MADRID)
    rows = [row(1000, "2026-10-24T21:50:00+00:00"), row(1500, "2026-10-25T01:30:00+00:00")]  # Wh
    h = consumption.hourly_from_history(rows, start, now, MADRID, "Wh")
    assert len(h) == 25
    assert sum(x["kwh"] for x in h) == pytest.approx(0.5)


def test_cost_uses_price_of_each_hour(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    hourly = [{"time": "2026-10-20T00:00", "kwh": 1.0}, {"time": "2026-10-20T01:00", "kwh": 2.0}]
    prices = [energy.HourPrice(datetime(2026, 10, 20, 0), 0.10), energy.HourPrice(datetime(2026, 10, 20, 1), 0.20)]
    out = consumption.build({}, hourly, prices, 0.20)
    assert out["hoy_kwh"] == 3.0 and out["hoy_eur"] == 0.5


def test_hourly_from_power_integrates_watts():
    start = datetime(2026, 10, 20, 0, 0, tzinfo=MADRID)
    now = datetime(2026, 10, 20, 1, 30, tzinfo=MADRID)
    rows = [row(1000, "2026-10-19T22:00:00+00:00"),  # 00:00 → 1 kW
            row(2000, "2026-10-19T22:30:00+00:00"),  # 00:30 → 2 kW, sigue en la 01:00
            row("unavailable", "2026-10-19T23:15:00+00:00"),  # 01:15: hueco
            row(-500, "2026-10-19T23:20:00+00:00")]  # 01:20: vertiendo, no resta
    h = consumption.hourly_from_power(rows, start, now, MADRID)
    assert [x["time"] for x in h] == ["2026-10-20T00:00", "2026-10-20T01:00"]
    assert [x["kwh"] for x in h] == pytest.approx([1.5, 0.5])


def test_power_on_dst_day_counts_the_repeated_hour_once():
    start = datetime(2026, 10, 25, 0, 0, tzinfo=MADRID)
    now = datetime(2026, 10, 25, 23, 59, tzinfo=MADRID)
    rows = [row(1, "2026-10-24T22:00:00+00:00")]  # 1 kW todo el día (unidad kW)
    h = consumption.hourly_from_power(rows, start, now, MADRID, "kW")
    assert len(h) == 25
    assert [x["time"][11:] for x in h[:4]] == ["00:00", "01:00", "02:00", "02:00"]
    assert all(x["kwh"] == pytest.approx(1.0) for x in h[:-1])


def test_counter_on_dst_day_splits_the_two_2am_hours():
    start = datetime(2026, 10, 25, 0, 0, tzinfo=MADRID)
    now = datetime(2026, 10, 25, 4, 0, tzinfo=MADRID)
    rows = [row(10, "2026-10-24T21:50:00+00:00"), row(11, "2026-10-25T00:30:00+00:00"),  # 02:30 CEST
            row(13, "2026-10-25T01:30:00+00:00")]  # 02:30 CET
    h = consumption.hourly_from_history(rows, start, now, MADRID)
    assert [x["kwh"] for x in h[2:4]] == pytest.approx([1.0, 2.0])


def test_power_history_only_asks_for_the_open_hour(tmp_path, monkeypatch):
    import asyncio
    from app import sources
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    asked = []

    class FakeHA:
        async def history(self, entity, start, end):
            asked.append(start)
            return [row(1000, start.astimezone(ZoneInfo("UTC")).isoformat())]

    start = datetime(2026, 10, 20, 0, 0, tzinfo=MADRID)
    run = lambda now: asyncio.run(sources._hourly_from_power(FakeHA(), "sensor.x", "W", start, now))  # noqa: E731
    sources._power_hours.clear()
    assert [h["kwh"] for h in run(datetime(2026, 10, 20, 2, 30, tzinfo=MADRID))] == pytest.approx([1, 1, 0.5])
    h = run(datetime(2026, 10, 20, 2, 45, tzinfo=MADRID))
    assert [x["kwh"] for x in h] == pytest.approx([1, 1, 0.75])
    assert asked[1] == datetime(2026, 10, 20, 2, 0, tzinfo=MADRID)


def test_several_meters_and_powers_are_added(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n"
                 "consumo: {potencia_total: [sensor.shelly_w, sensor.trydan_w, sensor.no_existe]}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    assert consumption.power_entities() == ["sensor.shelly_w", "sensor.trydan_w", "sensor.no_existe"]
    states = {"sensor.shelly_w": {"state": "500", "attributes": {}},
              "sensor.trydan_w": {"state": "7.4", "attributes": {"unit_of_measurement": "kW"}},
              "sensor.no_existe": None}
    hourly = consumption.add_hours([[{"time": "2026-10-20T00:00", "kwh": 0.3}], [],
                                    [{"time": "2026-10-20T00:00", "kwh": 7.0}]])
    out = consumption.build(states, hourly, [], None)
    assert out["ahora_w"] == 7900
    assert out["hoy_kwh"] == pytest.approx(7.3)
