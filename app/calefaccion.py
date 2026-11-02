"""¿Calentar la casa con la caldera de gas o con el aire acondicionado en calor? Hora a hora.

Compara lo que cuesta cada kWh de calor que entra en casa, solo con lo que depende del uso (el término fijo del gas y
la potencia contratada de la luz se pagan igual):

- Gas:  (término variable TUR + impuesto sobre el gas) × (1 + IVA) ÷ rendimiento de la caldera.
- Aire: PVPC de esa hora × (1 + impuesto eléctrico) × (1 + IVA) ÷ COP con la temperatura exterior de esa hora.

El COP sale de la curva del fabricante (Eurovent) entre sus puntos de ensayo, por un factor de uso real (conductos,
desescarches). La caldera, del rendimiento estacional de su etiqueta, algo rebajado porque los radiadores van
calientes. Todo se puede ajustar en config.yaml («calefaccion»).
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


def forecast(prices: list, weather: dict | None, now: datetime) -> dict | None:
    """Desde la hora en curso hasta donde haya precio de la luz (hoy, y mañana a partir de las 20:15)."""
    gas = gas_heat_cost(now.date())
    temps = hourly_temps(weather)
    if gas is None or not prices or not temps:
        return None
    this_hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    hours = []
    for p in prices:
        if p.time < this_hour:
            continue
        key = p.time.isoformat(timespec="minutes")
        if key not in temps:
            continue
        t = temps[key]
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
