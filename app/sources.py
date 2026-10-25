"""Fuentes de datos. Home Assistant hace de pegamento: la tablet nunca habla con él, solo con este servicio.

- Calendario: entidad calendar.* (iCloud vía la integración CalDAV de HA).
- Recordatorios (compra y tareas): no pasan por aquí; los envía un Atajo (ver reminders.py).
- Coche: sensores del Tesla en HA.
- Casa: calefacción, aire, temperaturas y música (house.py; la única parte que también da órdenes).
- Trayectos: un sensor de tiempo de viaje (Waze Travel Time o similar) por usuario.
- Tiempo: Open-Meteo, sin clave.
- Luz: Red Eléctrica (PVPC), sin clave.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import httpx

from . import config, energy

TIMEOUT = httpx.Timeout(15.0, connect=5.0)


class HomeAssistant:
    def __init__(self, client: httpx.AsyncClient):
        self.client = client

    @property
    def _base(self) -> str:
        return config.load()["home_assistant"]["url"].rstrip("/")

    def _headers(self) -> dict:
        token = config.ha_token()
        if not token:
            raise RuntimeError("Falta HA_TOKEN en .env")
        return {"Authorization": f"Bearer {token}"}

    async def state(self, entity_id: str) -> dict:
        r = await self.client.get(f"{self._base}/api/states/{entity_id}", headers=self._headers(), timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    async def states(self, entity_ids: list[str]) -> dict[str, dict | None]:
        out: dict[str, dict | None] = {}
        for e in entity_ids:
            try:
                out[e] = await self.state(e)
            except httpx.HTTPStatusError as err:
                if err.response.status_code == 404:
                    out[e] = None  # entidad mal escrita o que ya no existe: no tumba el resto
                else:
                    raise
        return out

    async def call(self, domain: str, service: str, data: dict) -> None:
        r = await self.client.post(f"{self._base}/api/services/{domain}/{service}", headers=self._headers(),
                                   timeout=TIMEOUT, json=data)
        r.raise_for_status()

    async def history(self, entity_id: str, start: datetime, end: datetime) -> list[dict]:
        r = await self.client.get(f"{self._base}/api/history/period/{start.isoformat()}", headers=self._headers(),
                                  timeout=TIMEOUT, params={"filter_entity_id": entity_id, "end_time": end.isoformat(),
                                                           "minimal_response": "", "no_attributes": ""})
        r.raise_for_status()
        rows = r.json()
        return rows[0] if rows else []

    async def calendar(self, entity_id: str, start: datetime, end: datetime) -> list[dict]:
        r = await self.client.get(f"{self._base}/api/calendars/{entity_id}", headers=self._headers(), timeout=TIMEOUT,
                                  params={"start": start.isoformat(), "end": end.isoformat()})
        r.raise_for_status()
        return r.json()


def _num(state: dict | None) -> float | None:
    if not state:
        return None
    try:
        return float(state["state"])
    except (TypeError, ValueError):
        return None


def _unit(state: dict | None) -> str | None:
    return (state or {}).get("attributes", {}).get("unit_of_measurement")


# Presión de las ruedas: el panel siempre la enseña en bar
TO_BAR = {"bar": 1.0, "psi": 0.0689476, "kpa": 0.01}


def _pressure_bar(state: dict | None) -> float | None:
    value = _num(state)
    if value is None:
        return None
    factor = TO_BAR.get((_unit(state) or "bar").lower())
    return round(value * factor, 2) if factor else None


def _on(state: dict | None, *values: str) -> bool:
    return bool(state) and str(state["state"]).lower() in {"on", "true", *values}


async def calendar_events(ha: HomeAssistant) -> list[dict]:
    cfg = config.load().get("calendario") or {}
    if not cfg.get("entidad"):
        return []
    zone = config.zone()
    # Desde el lunes de esta semana: la vista de calendario enseña la semana actual y la siguiente
    today = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    start = today - timedelta(days=today.weekday())
    end = start + timedelta(days=max(14, int(cfg.get("dias", 14))))
    events = []
    for ev in await ha.calendar(cfg["entidad"], start, end):
        s, e = ev.get("start", {}), ev.get("end", {})
        all_day = "date" in s
        events.append({
            "title": ev.get("summary") or "(sin título)",
            "start": s.get("date") or s.get("dateTime"),
            "end": e.get("date") or e.get("dateTime"),
            "all_day": all_day,
            "location": ev.get("location"),
            "description": ev.get("description"),
        })
    return sorted(events, key=lambda x: x["start"] or "")


async def car(ha: HomeAssistant) -> dict | None:
    cfg = config.load().get("coche")
    if not cfg:
        return None
    ent = cfg.get("entidades", {})
    wanted = [v for k, v in ent.items() if v and k != "ruedas"] + [v for v in (ent.get("ruedas") or {}).values() if v]
    st = await ha.states(wanted)
    get = lambda key: st.get(ent.get(key)) if ent.get(key) else None  # noqa: E731
    ruedas = {pos: _pressure_bar(st.get(e)) for pos, e in (ent.get("ruedas") or {}).items() if e}
    potencia = _num(get("potencia_carga"))
    return {
        "nombre": cfg.get("nombre", "Coche"),
        "bateria": _num(get("bateria")),
        "autonomia": _num(get("autonomia")),
        "autonomia_unidad": _unit(get("autonomia")) or "km",
        "cargando": _on(get("cargando"), "charging"),
        "enchufado": _on(get("enchufado"), "connected", "plugged_in"),
        "potencia_kw": potencia if (_unit(get("potencia_carga")) or "kW").lower() == "kw" else (potencia / 1000 if potencia else None),
        "limite_carga": _num(get("limite_carga")),
        "km": _num(get("cuentakilometros")),
        "ruedas": ruedas or None,
        "ruedas_unidad": "bar",
        "actualizado": (get("bateria") or {}).get("last_changed"),
    }


async def house(ha: HomeAssistant) -> dict | None:
    from . import house as house_mod
    ids = house_mod.entities()
    if not ids:
        return None
    return house_mod.build(await ha.states(ids))


# Horas ya cerradas del consumo calculado con la potencia: así cada 30 s solo se pide el historial de la hora en curso
_power_hours: dict = {"clave": None, "horas": []}


async def _hourly_from_power(ha: HomeAssistant, entity: str, unit: str | None, start: datetime, now: datetime) -> list[dict]:
    from . import consumption as cons
    zone = config.zone()
    key = (entity, start.isoformat())
    closed = _power_hours["horas"] if _power_hours["clave"] == key else []
    hours = cons._hours(start, now, zone)
    first = hours[len(closed)][1] if len(closed) < len(hours) else now
    rows = await ha.history(entity, first, now)
    fresh = cons.hourly_from_power(rows, start, now, zone, unit, first_hour=first)
    out = closed + fresh
    _power_hours.update(clave=key, horas=[h for h, (_, _, end) in zip(out, hours) if end <= now])
    return out


async def consumption(ha: HomeAssistant, prices: list) -> dict | None:
    from . import consumption as cons
    c = cons.cfg()
    if not c:
        return None
    zone = config.zone()
    now = datetime.now(zone)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    states = await ha.states(cons.power_entities())
    hourly, source = [], None
    if c.get("energia_total"):
        meter = (await ha.states([c["energia_total"]]))[c["energia_total"]]
        if meter:  # si la entidad no existe, se calcula con la potencia
            unit = meter.get("attributes", {}).get("unit_of_measurement")
            # Desde un poco antes de medianoche, para tener el valor de partida
            rows = await ha.history(c["energia_total"], start - timedelta(minutes=10), now)
            hourly = cons.hourly_from_history(rows, start, now, zone, unit)
            source = "contador" if hourly else None
    if not hourly and c.get("potencia_total") and states.get(c["potencia_total"]):
        unit = states[c["potencia_total"]].get("attributes", {}).get("unit_of_measurement")
        hourly = await _hourly_from_power(ha, c["potencia_total"], unit, start, now)
        source = "potencia" if hourly else None
    current = next((p.eur_kwh for p in reversed(prices) if p.time <= now.replace(tzinfo=None)), None) if prices else None
    out = cons.build(states, hourly, prices or [], current)
    out["horas_fuente"] = source
    return out


async def commute(ha: HomeAssistant, user_id: str) -> dict | None:
    u = config.user(user_id)
    if not u or not u.get("trayecto"):
        return None
    st = await ha.state(u["trayecto"])
    attrs = st.get("attributes", {})
    return {
        "destino": u.get("destino", "Trabajo"),
        "minutos": _num(st),
        "ruta": attrs.get("route"),
        "distancia": attrs.get("distance"),
        "actualizado": st.get("last_updated"),
    }


async def weather(client: httpx.AsyncClient) -> dict:
    loc = config.load()["ubicacion"]
    r = await client.get("https://api.open-meteo.com/v1/forecast", timeout=TIMEOUT, params={
        "latitude": loc["latitud"], "longitude": loc["longitud"], "timezone": loc["zona"],
        # Días pasados de esta semana y las dos siguientes, para la vista de calendario
        "past_days": 7, "forecast_days": 14,
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,is_day,wind_speed_10m",
        "hourly": "temperature_2m,precipitation_probability,weather_code,is_day",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
    })
    r.raise_for_status()
    return r.json()


async def prices(client: httpx.AsyncClient) -> list[energy.HourPrice]:
    today = datetime.now(config.zone()).date()
    r = await client.get(energy.REE_URL, params=energy.ree_params(today, today + timedelta(days=1)), timeout=TIMEOUT)
    r.raise_for_status()
    return energy.parse_ree(r.json(), config.zone())
