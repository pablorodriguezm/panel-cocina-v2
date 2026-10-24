"""Modo demostración (PANEL_DEMO=1): datos ficticios para probar la interfaz sin Home Assistant ni Internet,
igual que el entorno de demo del repositorio original. Las fechas son relativas a hoy."""
from __future__ import annotations

import math
from datetime import datetime, timedelta

from . import config, energy


def _now() -> datetime:
    return datetime.now(config.zone()).replace(tzinfo=None)


async def prices() -> list[energy.HourPrice]:
    base = _now().replace(hour=0, minute=0, second=0, microsecond=0)
    out = []
    # Hoy siempre; mañana solo a partir de las 20:30, como REE
    days = 2 if _now().hour * 60 + _now().minute >= 20 * 60 + 30 else 1
    for d in range(days):
        for h in range(24):
            # Valle de madrugada y a mediodía (solar), picos por la mañana y por la tarde
            v = 0.13 + 0.06 * math.sin((h - 5) / 24 * 2 * math.pi) - 0.05 * math.exp(-((h - 14) ** 2) / 6)
            v += 0.08 * math.exp(-((h - 20.5) ** 2) / 3) + 0.01 * d
            out.append(energy.HourPrice(base + timedelta(days=d, hours=h), max(0.02, v)))
    return out


async def weather() -> dict:
    today = _now().date()
    days = [today + timedelta(days=i) for i in range(7)]
    return {
        "current": {"temperature_2m": 22.4, "apparent_temperature": 22.0, "weather_code": 1, "is_day": 1, "wind_speed_10m": 9},
        "daily": {
            "time": [d.isoformat() for d in days],
            "weather_code": [1, 2, 3, 61, 63, 0, 1],
            "temperature_2m_max": [26, 25, 23, 20, 19, 24, 26],
            "temperature_2m_min": [14, 14, 15, 13, 12, 13, 15],
            "precipitation_probability_max": [5, 10, 30, 75, 60, 0, 5],
            "sunrise": [f"{d}T08:12" for d in days],
            "sunset": [f"{d}T19:05" for d in days],
        },
    }


async def calendar_events() -> list[dict]:
    t = _now().replace(minute=0, second=0, microsecond=0)
    d = t.date()
    ev = lambda title, when, dur=1, loc=None: {  # noqa: E731
        "title": title, "start": when.isoformat(), "end": (when + timedelta(hours=dur)).isoformat(), "all_day": False, "location": loc}
    return [
        ev("Dentista", t + timedelta(hours=2), 1, "Clínica Centro"),
        ev("Cena con amigos", t.replace(hour=21) if t.hour < 20 else t + timedelta(hours=1), 2),
        {"title": "Recoger paquete", "start": (d + timedelta(days=1)).isoformat(), "end": (d + timedelta(days=2)).isoformat(), "all_day": True, "location": None},
        ev("Revisión del coche", datetime.combine(d + timedelta(days=2), datetime.min.time()).replace(hour=9, minute=30), 1, "Taller"),
        ev("Cumpleaños de Lucía", datetime.combine(d + timedelta(days=4), datetime.min.time()).replace(hour=18), 3),
    ]


def reminders() -> dict:
    import time
    item = lambda t, n=None, v=None: {"titulo": t, "notas": n, "vence": v}  # noqa: E731
    tomorrow = (_now().date() + timedelta(days=1)).isoformat()
    return {
        "Compra": {"updated": time.time(), "items": [item("Leche", "sin lactosa"), item("Pan"), item("Tomates"),
                                                     item("Café", "en grano"), item("Plátanos"), item("Detergente")]},
        "Casa": {"updated": time.time(), "items": [item("Llamar al fontanero", v=tomorrow), item("Cambiar filtro de la campana")]},
    }


async def car() -> dict:
    return {"nombre": "Tesla", "bateria": 64, "autonomia": 298, "autonomia_unidad": "km", "cargando": False, "enchufado": True,
            "potencia_kw": None, "limite_carga": 80, "km": 23_418,
            "ruedas": {"del_izq": 2.9, "del_der": 2.9, "tras_izq": 2.8, "tras_der": 2.9}, "ruedas_unidad": "bar",
            "actualizado": None}


async def commute(user_id: str) -> dict | None:
    u = config.user(user_id)
    if not u:
        return None
    minutes = {"pablo": 24, "rim": 38}.get(user_id, 30)
    return {"destino": u.get("destino", "Trabajo"), "minutos": minutes, "ruta": "A-49" if user_id == "pablo" else "SE-30",
            "distancia": None, "actualizado": None}
