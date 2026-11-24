from datetime import date, datetime

import pytest

from app import calefaccion, config
from app.energy import HourPrice


@pytest.fixture(autouse=True)
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "config.yaml"
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", p)
    config.load.cache_clear()
    yield p
    config.load.cache_clear()


def set_cfg(p, text):
    p.write_text("ubicacion: {latitud: 0, longitud: 0}\n" + text, encoding="utf-8")
    config.load.cache_clear()


def test_gas_cost_matches_the_bill():
    # Factura TUR.1 desde el 1/10/2026: 0,0525259 €/kWh + impuesto 0,00234 €/kWh, IVA 21 %, caldera al 90 %
    assert calefaccion.gas_price(date(2026, 11, 2)) == (0.0525259, date(2026, 10, 1))
    assert calefaccion.gas_price(date(2026, 9, 15))[0] == 0.04329798
    assert calefaccion.gas_price(date(2026, 6, 30)) is None
    assert calefaccion.gas_heat_cost(date(2026, 11, 2)) == pytest.approx((0.0525259 + 0.00234) * 1.21 / 0.90)


def test_cop_follows_the_manufacturer_curve_with_real_use_factor():
    assert calefaccion.cop(7) == pytest.approx(4.63 * 0.9)
    assert calefaccion.cop(-10) == pytest.approx(2.42 * 0.9)
    assert calefaccion.cop(-1.5) == pytest.approx((2.42 + (4.63 - 2.42) * 8.5 / 17) * 0.9)
    assert calefaccion.cop(25) == pytest.approx(5.0 * 0.9)   # con tope
    assert calefaccion.cop(-40) == pytest.approx(1.0 * 0.9)  # nunca por debajo de 1


def test_electricity_taxes():
    assert calefaccion.electricity_with_taxes(0.1) == pytest.approx(0.1 * 1.0511269632 * 1.21)


def weather(temps: dict[str, float]) -> dict:
    return {"hourly": {"time": list(temps), "temperature_2m": list(temps.values())}}


def test_forecast_picks_gas_only_in_an_expensive_frosty_hour():
    prices = [HourPrice(datetime(2026, 12, 15, h), v) for h, v in [(6, 0.09), (7, 0.25), (8, 0.26), (9, 0.12)]]
    temps = weather({"2026-12-15T06:00": -1, "2026-12-15T07:00": -3, "2026-12-15T08:00": 2, "2026-12-15T09:00": 4})
    out = calefaccion.forecast(prices, temps, datetime(2026, 12, 15, 6, 40))
    assert [h["mejor"] for h in out["horas"]] == ["aire", "gas", "gas", "aire"]
    assert out["horas_gas"] == ["2026-12-15T07:00", "2026-12-15T08:00"]
    assert out["ahora"]["time"] == "2026-12-15T06:00" and out["ahora"]["temp"] == -1
    # Precio de empate con -1 °C: con la luz justo ahí, aire y gas cuestan lo mismo
    p = out["empate_pvpc"]
    assert calefaccion.electricity_with_taxes(p) / calefaccion.cop(-1) == pytest.approx(out["gas"]["eur_kwh_calor"], rel=1e-3)
    assert out["gas"] == {"tarifa": "TUR.1", "eur_kwh": 0.0525259, "desde": "2026-10-01",
                          "eur_kwh_calor": round(calefaccion.gas_heat_cost(date(2026, 12, 15)), 4), "rendimiento": 0.9}


def test_forecast_skips_past_hours_and_hours_without_temperature():
    prices = [HourPrice(datetime(2026, 12, 15, h), 0.1) for h in range(5, 9)]
    temps = weather({"2026-12-15T05:00": 3, "2026-12-15T06:00": 3, "2026-12-15T08:00": 3})
    out = calefaccion.forecast(prices, temps, datetime(2026, 12, 15, 6, 5))
    assert [h["time"] for h in out["horas"]] == ["2026-12-15T06:00", "2026-12-15T08:00"]
    assert calefaccion.forecast([], temps, datetime(2026, 12, 15, 6)) is None
    assert calefaccion.forecast(prices, None, datetime(2026, 12, 15, 6)) is None


def test_config_overrides(cfg):
    set_cfg(cfg, "calefaccion: {precio_gas_eur_kwh: 0.08, rendimiento_caldera: 0.8, cop: [[7, 4.0]], factor_real: 1}\n")
    assert calefaccion.gas_heat_cost(date(2026, 1, 1)) == pytest.approx((0.08 + 0.00234) * 1.21 / 0.8)
    assert calefaccion.cop(-5) == calefaccion.cop(10) == 4.0
    assert calefaccion.stale_gas_price(date(2030, 1, 1)) is None  # precio a mano: no caduca


def test_stale_gas_price_warning():
    assert calefaccion.stale_gas_price(date(2026, 11, 2)) is None
    assert "trimestre nuevo" in calefaccion.stale_gas_price(date(2027, 1, 10))
    assert "No hay precio" in calefaccion.stale_gas_price(date(2026, 1, 1))


# ---------- Temperatura exterior: Internet + sensores de casa ----------

NOW = datetime.fromisoformat("2026-12-15T06:40:00+01:00")


def ha_state(value, minutes_ago=5, unit="°C"):
    when = NOW.timestamp() - minutes_ago * 60
    return {"state": str(value), "attributes": {"unit_of_measurement": unit},
            "last_updated": datetime.fromtimestamp(when, NOW.tzinfo).isoformat()}


def readings(terraza, daikin):
    states = {"sensor.weather_station_outdoor_module_temperatura": terraza, "sensor.daikinap69395_climatecontrol_outdoor_temperature": daikin}
    return calefaccion.sensor_readings(states, NOW)


def by_name(out):
    return {f["nombre"]: f for f in out["fuentes"]}


def test_three_sources_agreeing_are_averaged():
    out = calefaccion.combine_outdoor(4.0, readings(ha_state(3.4), ha_state(3)))
    assert out["temp"] == pytest.approx((4.0 + 3.4 + 3) / 3, abs=0.05)
    assert all(f["usada"] for f in out["fuentes"]) and not out["discrepan"]


def test_a_source_far_from_the_others_is_discarded():
    # La terraza al sol marca 15 °C con 5 fuera: no cuenta
    out = calefaccion.combine_outdoor(5.0, readings(ha_state(15.2), ha_state(4)))
    assert out["temp"] == 4.5
    terraza = by_name(out)["Terraza"]
    assert not terraza["usada"] and "se aleja" in terraza["motivo"]
    # Internet también se descarta si es la que falla
    out = calefaccion.combine_outdoor(12.0, readings(ha_state(4.2), ha_state(4)))
    assert out["temp"] == 4.1 and not by_name(out)["Internet"]["usada"]


def test_two_sources_are_averaged_and_flagged_when_they_disagree():
    out = calefaccion.combine_outdoor(4.0, readings(ha_state(5), None))
    assert out["temp"] == 4.5 and not out["discrepan"]
    assert by_name(out)["Daikin"]["motivo"] == "no existe en Home Assistant"
    out = calefaccion.combine_outdoor(4.0, readings(ha_state(10), ha_state("unavailable")))
    assert out["temp"] == 7.0 and out["discrepan"]
    assert by_name(out)["Daikin"]["motivo"] == "sin lectura"   # el Daikin sin corriente


def test_stale_impossible_and_fahrenheit_readings():
    r = readings(ha_state(3, minutes_ago=300), ha_state(99))
    assert r[0]["motivo"] == "lectura de hace 5 h" and r[1]["motivo"] == "lectura imposible"
    assert calefaccion.combine_outdoor(4.0, r)["temp"] == 4.0   # solo Internet
    assert readings(ha_state(41, unit="°F"), None)[0]["temp"] == 5.0
    assert calefaccion.combine_outdoor(None, readings(None, None)) is None


def test_the_correction_fades_over_the_next_hours():
    prices = [HourPrice(datetime(2026, 12, 15, h), 0.1) for h in range(6, 14)]
    temps = weather({f"2026-12-15T{h:02d}:00": 4 for h in range(6, 14)})
    outdoor = calefaccion.combine_outdoor(4.0, readings(ha_state(-2), ha_state(-2)))  # en casa hace -2 °C, no 4
    out = calefaccion.forecast(prices, temps, datetime(2026, 12, 15, 6, 40), outdoor)
    assert [h["temp"] for h in out["horas"]] == [-2.0, -1.0, 0.0, 1.0, 2.0, 3.0, 4.0, 4.0]
    assert out["exterior"]["temp"] == -2.0 and out["ahora"]["cop"] == round(calefaccion.cop(-2.0), 2)
    # Sin sensores, la previsión tal cual
    assert calefaccion.forecast(prices, temps, datetime(2026, 12, 15, 6, 40))["ahora"]["temp"] == 4


def test_sensors_can_be_configured(cfg):
    set_cfg(cfg, "calefaccion:\n  sensores_exterior:\n    - {entidad: sensor.otro, nombre: Patio}\n")
    r = calefaccion.sensor_readings({"sensor.otro": ha_state(2)}, NOW)
    assert [x["nombre"] for x in r] == ["Patio"] and r[0]["temp"] == 2.0
