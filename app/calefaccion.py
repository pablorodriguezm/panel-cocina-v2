"""¿Calentar la casa con la caldera de gas o con el aire acondicionado en calor? Hora a hora.

Compara lo que cuesta cada kWh de calor que entra en casa, solo con lo que depende del uso (el término fijo del gas y
la potencia contratada de la luz se pagan igual):

- Gas:  (término variable TUR + impuesto sobre el gas) × (1 + IVA) ÷ rendimiento de la caldera.
- Aire: PVPC de esa hora × (1 + impuesto eléctrico) × (1 + IVA) ÷ COP con la temperatura exterior de esa hora.

El COP sale de la curva del fabricante (Eurovent) entre sus puntos de ensayo, por un factor de uso real (conductos,
desescarches). La caldera, del rendimiento estacional de su etiqueta, algo rebajado porque los radiadores van
calientes. Todo se puede ajustar en config.yaml («calefaccion»).

La temperatura exterior de ahora no sale solo de Internet: se combina con los sensores de casa (la estación Netatmo
de la terraza y el sensor exterior del Daikin). Cada uno puede equivocarse (el de la terraza al sol, el del Daikin
cuando la máquina descongela o está sin corriente), así que con tres fuentes se descarta la que se aleje de la
mediana y se hace la media del resto. La diferencia con la previsión se aplica a la hora en curso y se va diluyendo
en las siguientes, que siguen la previsión de Open-Meteo.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

import yaml

from . import config

GAS = Path(__file__).with_name("gas.yaml")

DEFAULTS = {
    "tarifa_gas": "TUR.1",
    # Bosch Condens 2300i W: ηs 94 % (etiqueta ErP); con radiadores a 70-80 °C condensa menos
    "rendimiento_caldera": 0.90,
    # Daikin ADEAS100A (ADEA100A + AZAS100MV), Eurovent: 10,8 kW con 2,33 kW a 7 °C (COP 4,63); 2,42 a −10 °C
    "cop": [[-10, 2.42], [7, 4.63]],
    "cop_maximo": 5.0,
    "factor_real": 0.90,          # pérdidas en conductos y desescarches frente al ensayo
    "impuesto_electrico": 0.0511269632,
    "iva": 0.21,
    # Sensores de temperatura exterior de Home Assistant que se combinan con la de Internet
    "sensores_exterior": [
        {"entidad": "sensor.weather_station_outdoor_module_temperatura", "nombre": "Terraza"},
        {"entidad": "sensor.daikinap69395_outside_temperature", "nombre": "Daikin"},
    ],
    "max_diferencia_exterior": 3.0,   # °C: más lejos de la mediana, la fuente se descarta
    "minutos_sensor_exterior": 120,   # una lectura más vieja no cuenta
    "horas_correccion": 6,            # la corrección se diluye en estas horas
}


def cfg() -> dict:
    c = config.load().get("calefaccion")
    return {**DEFAULTS, **(c if isinstance(c, dict) else {})}


@lru_cache
def gas_file() -> dict:
    with GAS.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def gas_price(day: date) -> tuple[float, date] | None:
    """Término variable vigente ese día (sin impuestos) y desde cuándo, o None si no hay precio."""
    c = cfg()
    if c.get("precio_gas_eur_kwh"):
        return float(c["precio_gas_eur_kwh"]), day
    periods = sorted(gas_file().get(c["tarifa_gas"]) or [], key=lambda p: str(p["desde"]))
    valid = [p for p in periods if date.fromisoformat(str(p["desde"])) <= day]
    if not valid:
        return None
    return float(valid[-1]["eur_kwh"]), date.fromisoformat(str(valid[-1]["desde"]))


def gas_heat_cost(day: date) -> float | None:
    """€ por kWh de calor con la caldera, con impuestos."""
    p = gas_price(day)
    if p is None:
        return None
    g = gas_file()
    with_taxes = (p[0] + float(g.get("impuesto_gas_eur_kwh", 0))) * (1 + float(cfg()["iva"]))
    return with_taxes / float(cfg()["rendimiento_caldera"])


def cop(temp: float) -> float:
    """COP real con esa temperatura exterior: recta entre los puntos del fabricante, con tope, por el factor real."""
    c = cfg()
    pts = sorted((float(t), float(v)) for t, v in c["cop"])
    if len(pts) == 1:
        raw = pts[0][1]
    else:  # el tramo donde cae la temperatura; fuera de los puntos, se prolonga el primero o el último
        (t0, c0), (t1, c1) = next(((a, b) for a, b in zip(pts, pts[1:]) if temp <= b[0]), (pts[-2], pts[-1]))
        raw = c0 + (c1 - c0) * (temp - t0) / (t1 - t0)
    raw = max(1.0, min(float(c["cop_maximo"]), raw))
    return raw * float(c["factor_real"])


def electricity_with_taxes(pvpc: float) -> float:
    return pvpc * (1 + float(cfg()["impuesto_electrico"])) * (1 + float(cfg()["iva"]))


def break_even_pvpc(temp: float, gas_cost: float) -> float:
    """PVPC (sin impuestos) por debajo del cual compensa el aire con esa temperatura."""
    return gas_cost * cop(temp) / electricity_with_taxes(1.0)


def hourly_temps(weather: dict | None) -> dict[str, float]:
    """Temperatura exterior por hora local («AAAA-MM-DDTHH:00») de la previsión de Open-Meteo."""
    h = (weather or {}).get("hourly") or {}
    return {t[:13] + ":00": v for t, v in zip(h.get("time", []), h.get("temperature_2m", [])) if v is not None}


def sensor_readings(states: dict[str, dict | None], now: datetime) -> list[dict]:
    """Las lecturas de los sensores exteriores de config («sensores_exterior») a partir de sus estados de HA."""
    c = cfg()
    out = []
    for s in c.get("sensores_exterior") or []:
        if not isinstance(s, dict) or not s.get("entidad"):
            continue
        st = states.get(s["entidad"])
        item = {"nombre": s.get("nombre") or s["entidad"], "entidad": s["entidad"], "temp": None, "usada": False}
        if st is None:
            item["motivo"] = "no existe en Home Assistant"
        else:
            try:
                t = float(st.get("state"))
                if (st.get("attributes") or {}).get("unit_of_measurement") == "°F":
                    t = (t - 32) * 5 / 9
            except (TypeError, ValueError):
                t = None
            if t is None or not -40 <= t <= 55:
                item["motivo"] = "sin lectura" if t is None else "lectura imposible"
            else:
                item["temp"] = round(t, 1)
                try:
                    updated = datetime.fromisoformat(st.get("last_updated") or st.get("last_changed"))
                    age = (now.astimezone(updated.tzinfo) - updated).total_seconds() / 60
                except (TypeError, ValueError):
                    age = 0
                if age > float(c["minutos_sensor_exterior"]):
                    item["motivo"] = f"lectura de hace {int(age // 60)} h"
        out.append(item)
    return out


def combine_outdoor(internet: float | None, sensors: list[dict]) -> dict | None:
    """La temperatura exterior de ahora: Internet y los sensores válidos. Con tres o más, se descartan los que se
    alejan de la mediana más de «max_diferencia_exterior» y se hace la media del resto; con dos, la media (sin una
    tercera no se sabe cuál falla, y se avisa si discrepan)."""
    limit = float(cfg()["max_diferencia_exterior"])
    sources = ([{"nombre": "Internet", "temp": round(internet, 1), "usada": False}] if internet is not None else [])
    sources += [dict(s) for s in sensors]
    valid = [s for s in sources if s["temp"] is not None and not s.get("motivo")]
    if not valid:
        return None
    vals = sorted(s["temp"] for s in valid)
    mid = len(vals) // 2
    median = vals[mid] if len(vals) % 2 else (vals[mid - 1] + vals[mid]) / 2
    used = [s for s in valid if abs(s["temp"] - median) <= limit] if len(valid) >= 3 else valid
    if not used:  # todas muy separadas entre sí: la mediana es lo más fiable
        used = [min(valid, key=lambda s: abs(s["temp"] - median))]
    for s in valid:
        if s in used:
            s["usada"] = True
        else:
            s["motivo"] = f"se aleja {abs(s['temp'] - median):.1f}° de las demás".replace(".", ",")
    temp = sum(s["temp"] for s in used) / len(used)
    spread = max(vals) - min(vals)
    return {"temp": round(temp, 1), "fuentes": sources,
            "discrepan": len(valid) == 2 and spread > limit}


def forecast(prices: list, weather: dict | None, now: datetime, outdoor: dict | None = None) -> dict | None:
    """Desde la hora en curso hasta donde haya precio de la luz (hoy, y mañana a partir de las 20:15).
    `outdoor`: la temperatura de ahora combinada con los sensores (combine_outdoor); corrige las primeras horas."""
    gas = gas_heat_cost(now.date())
    temps = hourly_temps(weather)
    if gas is None or not prices or not temps:
        return None
    this_hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    base = temps.get(this_hour.isoformat(timespec="minutes"))
    offset = outdoor["temp"] - base if outdoor and base is not None else 0.0
    fade = max(1.0, float(cfg()["horas_correccion"]))
    hours = []
    for p in prices:
        if p.time < this_hour:
            continue
        key = p.time.isoformat(timespec="minutes")
        if key not in temps:
            continue
        ahead = (p.time - this_hour).total_seconds() / 3600
        t = temps[key] + offset * max(0.0, 1 - ahead / fade)
        air = electricity_with_taxes(p.eur_kwh) / cop(t)
        hours.append({"time": key, "temp": round(t, 1), "cop": round(cop(t), 2), "pvpc": round(p.eur_kwh, 5),
                      "aire": round(air, 4), "gas": round(gas, 4), "mejor": "aire" if air <= gas else "gas",
                      "ahorro": round(abs(gas - air) / max(gas, air), 3)})
    if not hours:
        return None
    first = hours[0]
    gas_hours = [h["time"] for h in hours if h["mejor"] == "gas"]
    price, since = gas_price(now.date())
    return {
        "ahora": first,
        "horas": hours,
        "horas_gas": gas_hours,
        "empate_pvpc": round(break_even_pvpc(first["temp"], gas), 4),
        "exterior": outdoor,
        "gas": {"tarifa": cfg()["tarifa_gas"], "eur_kwh": price, "desde": since.isoformat(),
                "eur_kwh_calor": round(gas, 4), "rendimiento": cfg()["rendimiento_caldera"]},
    }


def stale_gas_price(today: date) -> str | None:
    """Aviso para /api/salud si el precio del gas lleva más de un trimestre sin actualizar."""
    p = gas_price(today)
    if p is None:
        return f"No hay precio de {cfg()['tarifa_gas']} en app/gas.yaml"
    if not cfg().get("precio_gas_eur_kwh") and today - p[1] > timedelta(days=95):
        return f"El precio de {cfg()['tarifa_gas']} es del {p[1]:%d/%m/%Y}: falta el del trimestre nuevo en app/gas.yaml"
    return None
