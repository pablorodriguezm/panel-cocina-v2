from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from app import energy

MADRID = ZoneInfo("Europe/Madrid")


def day(start: datetime, values: list[float]) -> list[energy.HourPrice]:
    return [energy.HourPrice(start + timedelta(hours=i), v) for i, v in enumerate(values)]


def test_parse_ree_to_eur_kwh_local_time():
    payload = {"included": [
        {"type": "Precio mercado spot (€/MWh)", "attributes": {"values": [{"value": 235.0, "datetime": "2026-10-20T00:00:00.000+02:00"}]}},
        {"type": "PVPC", "attributes": {"values": [
            {"value": 200.97, "datetime": "2026-10-20T01:00:00.000+02:00"},
            {"value": 208.94, "datetime": "2026-10-20T00:00:00.000+02:00"},
            # El día del cambio de hora llega con otra zona: se pasa a la local
            {"value": 150.0, "datetime": "2026-10-25T02:00:00.000+01:00"},
        ]}},
    ]}
    prices = energy.parse_ree(payload, MADRID)
    assert [p.time for p in prices] == [datetime(2026, 10, 20, 0), datetime(2026, 10, 20, 1), datetime(2026, 10, 25, 2)]
    assert prices[0].eur_kwh == pytest.approx(0.20894)


def test_without_pvpc_is_an_error():
    with pytest.raises(ValueError):
        energy.parse_ree({"included": []}, MADRID)


def test_cheapest_window_finds_night_valley():
    today = datetime(2026, 10, 24)
    values = [0.10] * 24
    values[2:6] = [0.03, 0.02, 0.02, 0.03]  # valle de 2 a 6
    values[19:22] = [0.30, 0.32, 0.31]  # pico
    prices = day(today, values)
    w = energy.cheapest_window(prices, today, 4)
    assert (w.start, w.end) == (datetime(2026, 10, 24, 2), datetime(2026, 10, 24, 6))
    avoid = energy.most_expensive_today(prices, today)
    assert (avoid.start, avoid.end) == (datetime(2026, 10, 24, 19), datetime(2026, 10, 24, 22))


def test_no_recommendation_when_rest_of_day_is_expensive():
    # A las 21:00, sin precio de mañana y con lo que queda por encima de la media: mejor esperar
    today = datetime(2026, 10, 24)
    values = [0.05] * 20 + [0.30, 0.31, 0.29, 0.28]
    prices = day(today, values)
    now = datetime(2026, 10, 24, 21, 10)
    assert energy.cheapest_window(prices, now, 2) is None
    s = energy.summary(prices, now, [{"id": "x", "nombre": "X", "horas": 2}])
    assert s["wait_for_tomorrow"] is True
    assert s["now"]["eur_kwh"] == pytest.approx(0.31)


def test_window_can_cross_midnight_into_tomorrow():
    today = datetime(2026, 10, 24)
    values_today = [0.20] * 24
    values_tomorrow = [0.04, 0.03, 0.03, 0.04] + [0.20] * 20
    prices = day(today, values_today) + day(today + timedelta(days=1), values_tomorrow)
    w = energy.cheapest_window(prices, datetime(2026, 10, 24, 22), 4)
    assert w.start == datetime(2026, 10, 25, 0)


def test_gaps_are_not_windows():
    today = datetime(2026, 10, 24)
    prices = [p for p in day(today, [0.01] * 24) if p.time.hour != 3]
    w = energy.cheapest_window(prices, today, 4)
    assert w.start.hour >= 4


def test_periods_of_the_2_0td_tariff():
    wed = datetime(2026, 11, 4)
    assert [energy.period(wed.replace(hour=h)) for h in (0, 7, 8, 10, 14, 18, 22, 23)] == \
        ["valle", "valle", "llano", "punta", "llano", "punta", "llano", "llano"]
    assert energy.period(datetime(2026, 11, 7, 19)) == "valle"  # sábado
    holiday = datetime(2026, 12, 8, 19)
    assert energy.period(holiday) == "punta" and energy.period(holiday, frozenset({holiday.date()})) == "valle"


def test_car_cost_uses_the_power_of_each_period():
    # Miércoles de 6 a 10: dos horas de valle a 7 kW y dos de llano a 4,5 kW
    prices = day(datetime(2026, 11, 4, 6), [0.08, 0.09, 0.12, 0.13])
    w = energy.Window(datetime(2026, 11, 4, 6), datetime(2026, 11, 4, 10), 0.105)
    car = {"potencia_kw": {"valle": 7.0, "llano": 4.5, "punta": 4.5}}
    c = energy.window_cost(prices, w, car, tax_factor=1.272)
    assert c["kwh"] == 23.0 and c["periodos"] == ["valle", "llano"]
    assert c["eur"] == pytest.approx(round((7.0 * 0.08 + 7.0 * 0.09 + 4.5 * 0.12 + 4.5 * 0.13) * 1.272, 2))


def test_appliance_cost_is_one_cycle_spread_over_its_hours():
    prices = day(datetime(2026, 11, 5, 2), [0.07, 0.09])
    w = energy.Window(datetime(2026, 11, 5, 2), datetime(2026, 11, 5, 4), 0.08)
    c = energy.window_cost(prices, w, {"kwh": 0.65}, tax_factor=1.272)
    assert c["kwh"] == 0.65 and c["eur"] == pytest.approx(round(0.65 * 0.08 * 1.272, 2))
    assert energy.window_cost(prices, w, {}) is None


def test_summary_adds_the_cost_to_each_recommendation():
    prices = day(datetime(2026, 11, 5), [0.08] * 8 + [0.2] * 16)
    s = energy.summary(prices, datetime(2026, 11, 5, 0, 30), [{"id": "lavadora", "nombre": "Lavadora", "horas": 2, "kwh": 0.65}],
                       tax_factor=1.0)
    assert s["recommendations"][0]["coste"] == {"kwh": 0.65, "eur": 0.05, "periodos": ["valle"]}


def test_recommendations_in_config_take_the_default_power_and_consumption(tmp_path, monkeypatch):
    from app import config
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\nenergia:\n  recomendaciones:\n"
                 "    - {id: coche, nombre: Cargar el Tesla, horas: 4}\n"
                 "    - {id: lavadora, nombre: Lavadora, horas: 2, kwh: 0.9}\n"
                 "    - {id: horno, nombre: Horno, horas: 1}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    try:
        coche, lavadora, horno = config.load()["energia"]["recomendaciones"]
        assert coche["potencia_kw"]["valle"] == 7.0 and coche["nombre"] == "Cargar el Tesla"
        assert lavadora["kwh"] == 0.9  # lo de config.yaml manda
        assert "kwh" not in horno and "potencia_kw" not in horno
    finally:
        config.load.cache_clear()


CAR = {"id": "coche", "nombre": "Coche", "horas": 4, "potencia_kw": {"valle": 7.0, "llano": 4.5, "punta": 4.5}}


def test_car_need_from_battery_and_limit():
    assert energy.car_need({"bateria": 64, "limite_carga": 80}, 75, 0.9) == {"falta_kwh": 13.3, "bateria": 64, "limite": 80}
    assert energy.car_need({"bateria": 82, "limite_carga": 80}, 75)["falta_kwh"] == 0
    assert energy.car_need({"bateria": None, "limite_carga": 80}, 75) is None and energy.car_need(None, 75) is None


def test_charge_window_lasts_what_the_battery_needs():
    # Jueves: madrugada barata (valle, 7 kW) y día caro. 10,5 kWh son hora y media de valle
    prices = day(datetime(2026, 11, 12), [0.10, 0.08, 0.06, 0.07, 0.09] + [0.2] * 19)
    w, cost = energy.charge_window(prices, datetime(2026, 11, 12, 0, 10), 10.5, CAR, tax_factor=1.0)
    assert (w.start, w.end) == (datetime(2026, 11, 12, 2), datetime(2026, 11, 12, 3, 30))
    assert cost == {"kwh": 10.5, "eur": round(7 * 0.06 + 3.5 * 0.07, 2), "periodos": ["valle"]}
    # De día va a 4,5 kW: los mismos kWh tardan más
    w2, _ = energy.charge_window(day(datetime(2026, 11, 12, 8), [0.05] * 4 + [0.3] * 12), datetime(2026, 11, 12, 8), 9.0, CAR)
    assert w2.end - w2.start == timedelta(hours=2)


def test_charge_window_none_when_expensive_or_not_enough_hours():
    prices = day(datetime(2026, 11, 12), [0.1] * 20 + [0.3] * 4)
    assert energy.charge_window(prices, datetime(2026, 11, 12, 21), 5, CAR) is None      # lo que queda es caro
    assert energy.charge_window(prices, datetime(2026, 11, 12, 23), 20, CAR) is None     # no caben 20 kWh


def test_summary_sizes_the_car_charge_and_says_when_it_is_full():
    prices = day(datetime(2026, 11, 12), [0.08] * 8 + [0.2] * 16)
    s = energy.summary(prices, datetime(2026, 11, 12, 0, 5), [CAR], car={"falta_kwh": 14.0, "bateria": 63, "limite": 80})
    r = s["recommendations"][0]
    assert r["tramo"]["end"] == "2026-11-12T02:00" and r["coste"]["kwh"] == 14.0 and r["carga"]["completa"] is False
    full = energy.summary(prices, datetime(2026, 11, 12, 21), [CAR], car={"falta_kwh": 0.0, "bateria": 80, "limite": 80})
    assert full["recommendations"][0]["carga"]["completa"] and full["recommendations"][0]["tramo"] is None
    assert full["wait_for_tomorrow"] is False  # coche lleno: no hay nada que esperar
    # Sin datos del coche, como siempre: 4 horas fijas
    assert "carga" not in energy.summary(prices, datetime(2026, 11, 12, 0, 5), [CAR])["recommendations"][0]
