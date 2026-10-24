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
    now = _now()
    today = now.date()
    days = [today + timedelta(days=i) for i in range(-7, 14)]
    hours = [datetime.combine(d, datetime.min.time()) + timedelta(hours=h) for d in days for h in range(24)]
    codes = [1, 2, 3, 61, 63, 0, 1]
    temp = lambda t: round(15 + 6 * math.sin((t.hour - 9) / 24 * 2 * math.pi) + (t.toordinal() % 5) - 2, 1)  # noqa: E731
    return {
        "current": {"temperature_2m": temp(now), "apparent_temperature": temp(now) - 1, "relative_humidity_2m": 61,
                    "weather_code": 2, "is_day": int(8 <= now.hour < 19), "wind_speed_10m": 9},
        "hourly": {
            "time": [t.isoformat(timespec="minutes") for t in hours],
            "temperature_2m": [temp(t) for t in hours],
            "precipitation_probability": [max(0, int(40 * math.sin(t.hour / 24 * math.pi)) - 10) for t in hours],
            "weather_code": [codes[t.toordinal() % 7] if 8 <= t.hour < 20 else 0 for t in hours],
            "is_day": [int(8 <= t.hour < 19) for t in hours],
        },
        "daily": {
            "time": [d.isoformat() for d in days],
            "weather_code": [codes[d.toordinal() % 7] for d in days],
            "temperature_2m_max": [21 + (d.toordinal() % 5) - 2 for d in days],
            "temperature_2m_min": [9 + (d.toordinal() % 3) for d in days],
            "precipitation_probability_max": [[5, 10, 30, 75, 60, 0, 5][d.toordinal() % 7] for d in days],
            "sunrise": [f"{d}T08:12" for d in days],
            "sunset": [f"{d}T19:05" for d in days],
        },
    }


async def calendar_events() -> list[dict]:
    t = _now().replace(minute=0, second=0, microsecond=0)
    d = t.date()
    monday = d - timedelta(days=d.weekday())
    at = lambda day, h, m=0: datetime.combine(monday + timedelta(days=day), datetime.min.time()).replace(hour=h, minute=m)  # noqa: E731
    ev = lambda title, when, dur=1, loc=None, desc=None: {  # noqa: E731
        "title": title, "start": when.isoformat(), "end": (when + timedelta(hours=dur)).isoformat(), "all_day": False,
        "location": loc, "description": desc}
    allday = lambda title, day, n=1: {"title": title, "start": (monday + timedelta(days=day)).isoformat(),  # noqa: E731
                                      "end": (monday + timedelta(days=day + n)).isoformat(), "all_day": True,
                                      "location": None, "description": None}
    return [
        ev("Pilates", at(0, 19)), ev("Dentista", at(1, 17, 30), 1, "Clínica Centro"),
        ev("Cena con amigos", t.replace(hour=21) if t.hour < 20 else t + timedelta(hours=1), 2, "Casa de Lucía"),
        ev("Reunión del cole", at(3, 19)), allday("Recoger paquete", 4), ev("Revisión del coche", at(5, 9, 30), 1, "Taller"),
        ev("Comida con los abuelos", at(6, 14), 3), ev("Pilates", at(7, 19)), allday("Vacaciones", 9, 2),
        ev("Cumpleaños de Lucía", at(11, 18), 3), ev("Médico", at(12, 10, 15), 1, "Centro de salud"),
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


_HOUSE = {
    "calefaccion": {"nombre": "Calefacción", "termostato": None, "valvulas": []},
    "temperaturas": [{"nombre": n, "temp": t} for n, t in
                     [("Cocina", 22.8), ("Salón", 23.0), ("Terraza", 12.3), ("Matrimonio", 22.3), ("H. Rim", 22.3), ("Baño", 22.0)]],
    "musica": {"nombre": "Echo Dot Cocina", "estado": "paused", "titulo": "Purple Rain", "artista": "Prince", "album": None, "volumen": 0.34},
}


def _clim(entity, name, mode, action, cur, target, presets=(), preset=None, modes=("auto", "heat")):
    from .house import MODE_NAMES, PRESET_NAMES
    return {"entidad": entity, "nombre": name, "disponible": True, "modo": mode, "accion": action, "actual": cur,
            "consigna": target, "min": 7, "max": 30, "paso": 0.5, "preset": preset,
            "modos": [{"id": m, "nombre": MODE_NAMES[m]} for m in modes],
            "presets": [{"id": p, "nombre": PRESET_NAMES[p]} for p in presets]}


_PRESETS = ("schedule", "away", "boost", "frost_guard")
_HOUSE["calefaccion"]["termostato"] = _clim("climate.sala_de_estar", "Salón", "auto", "heating", 21.4, 22.0, _PRESETS, "schedule")
_HOUSE["calefaccion"]["valvulas"] = [_clim("climate.habitacion_entrada", "Entrada", "auto", "idle", 22.0, 19.0, _PRESETS, "schedule"),
                                     _clim("climate.habitacion_matrimonio", "Matrimonio", "auto", "heating", 20.5, 21.0, _PRESETS, "schedule"),
                                     _clim("climate.dormitorio_secundario", "Dormitorio secundario", "auto", "idle", 22.0, 19.0, _PRESETS, "schedule")]
_HOUSE["aire"] = [{**_clim("climate.daikin", "Daikin", "unavailable", None, None, None, modes=()), "disponible": False}]


async def house() -> dict:
    return _HOUSE


def house_command(action: str, body: dict) -> None:
    """En la demostración las órdenes cambian los datos de ejemplo, para probar la interfaz."""
    if action == "musica":
        m = _HOUSE["musica"]
        if body.get("accion") == "play_pause":
            m["estado"] = "paused" if m["estado"] == "playing" else "playing"
        elif body.get("accion") == "volumen":
            m["volumen"] = round(min(1, max(0, float(body.get("nivel", 0)))), 2)
        return
    every = [_HOUSE["calefaccion"]["termostato"], *_HOUSE["calefaccion"]["valvulas"], *_HOUSE["aire"]]
    c = next((x for x in every if x["entidad"] == body.get("entidad")), None)
    if c is None:
        raise ValueError("Esa entidad no está en la configuración de la casa")
    if action == "consigna":
        c["consigna"] = round(min(c["max"], max(c["min"], float(body["grados"]))) * 2) / 2
    elif action == "preset":
        c["preset"] = body["preset"]
    elif action == "modo":
        c["modo"] = body["modo"]


async def consumption(prices: list) -> dict:
    from . import consumption as cons
    now = _now()
    hours = [{"time": now.replace(hour=h, minute=0, second=0, microsecond=0).isoformat(timespec="minutes"),
              "kwh": round(0.18 + 0.25 * math.exp(-((h - 14) ** 2) / 4) + 0.35 * math.exp(-((h - 21) ** 2) / 3), 3)}
             for h in range(now.hour + 1)]
    current = next((p.eur_kwh for p in reversed(prices) if p.time <= now), None) if prices else None
    states = {}
    out = cons.build(states, hours, prices, current)
    out.update({"ahora_w": 1234.0, "ahora_eur_h": round(1.234 * (current or 0.15), 4), "tension": 236.4, "intensidad": 5.6,
                "aparatos": [{"nombre": n, "w": w, "disponible": True} for n, w in
                             [("Cocina", 640.0), ("Climatización", 0.0), ("Cargador Tesla", 0.0), ("NAS", 84.2), ("Mesa Pablo", 32.4), ("Ventilador salón", 1.0)]]})
    return out
