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
