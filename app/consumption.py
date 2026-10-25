"""Consumo eléctrico de la casa (vista «Consumo»), solo lectura.

- Potencia de ahora de la casa entera y de cada aparato o circuito (sensores en W de Home Assistant).
- Consumo de hoy hora a hora, a partir del historial del contador de energía (kWh, total_increasing), y su coste
  con el PVPC de cada hora. Sin contador (el V2C Trydan solo da la potencia de la casa en W), se calcula integrando
  el historial de la potencia total.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from . import config


def cfg() -> dict:
    return config.load().get("consumo") or {}


def _named(items) -> list[dict]:
    return [{"entidad": it, "nombre": None} if isinstance(it, str) else {"entidad": it["entidad"], "nombre": it.get("nombre")}
            for it in items or []]


def power_entities() -> list[str]:
    c = cfg()
    ids = [c[k] for k in ("potencia_total", "tension", "intensidad") if c.get(k)]
    return ids + [a["entidad"] for a in _named(c.get("aparatos"))]


def _num(st: dict | None) -> float | None:
    try:
        return float(st["state"]) if st else None
    except (TypeError, ValueError, KeyError):
        return None


def _watts(st: dict | None) -> float | None:
    v = _num(st)
    if v is None:
        return None
    unit = (st.get("attributes", {}).get("unit_of_measurement") or "W").lower()
    return v * 1000 if unit == "kw" else v


def _kwh(value: float, unit: str | None) -> float:
    return value / 1000 if (unit or "kWh").lower() == "wh" else value


UTC = ZoneInfo("UTC")


def _hours(start: datetime, now: datetime, zone: ZoneInfo) -> list[tuple[str, datetime, datetime]]:
    """(etiqueta local, comienzo, fin) de cada hora de hoy hasta la de ahora, con comienzo y fin en UTC. Todo se
    compara en UTC: Python compara por hora local dos fechas de la misma zona, y el día del cambio de hora
    mezclaría las dos «02:00»."""
    out, hour, now = [], start.astimezone(UTC), now.astimezone(UTC)
    while hour <= now:
        end = hour + timedelta(hours=1)
        out.append((hour.astimezone(zone).replace(tzinfo=None).isoformat(timespec="minutes"), hour, end))
        hour = end
    return out


def _utc(iso: str) -> datetime:
    return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(UTC)


def hourly_from_history(rows: list[dict], start: datetime, now: datetime, zone: ZoneInfo, unit: str | None = "kWh") -> list[dict]:
    """kWh de cada hora de hoy a partir del historial de un contador que solo sube.
    `rows`: estados de Home Assistant con «state» y «last_changed» (UTC). Un reinicio del contador (baja de valor)
    no cuenta como consumo negativo."""
    points = []
    for r in rows:
        try:
            v = float(r["state"])
        except (TypeError, ValueError, KeyError):
            continue
        points.append((_utc(r["last_changed"]), _kwh(v, unit)))
    points.sort(key=lambda p: p[0])
    if not points:
        return []
    out = []
    i, last = 0, points[0][1]
    for label, _, end in _hours(start, now, zone):
        used = 0.0
        while i < len(points) and points[i][0] < end:
            if points[i][1] >= last:
                used += points[i][1] - last
            last = points[i][1]
            i += 1
        out.append({"time": label, "kwh": round(used, 4)})
    return out


def hourly_from_power(rows: list[dict], start: datetime, now: datetime, zone: ZoneInfo, unit: str | None = "W",
                      first_hour: datetime | None = None) -> list[dict]:
    """kWh de cada hora integrando el historial de un sensor de potencia: cada valor vale hasta el siguiente cambio.
    «unavailable» cuenta como hueco (0) y los valores negativos (vertido de placas) no restan.
    `first_hour`: solo devuelve las horas desde esa (las anteriores ya están calculadas)."""
    factor = 1.0 if (unit or "W").lower() == "kw" else 1 / 1000
    points = []
    for r in rows:
        try:
            v = max(0.0, float(r["state"])) * factor
        except (TypeError, ValueError, KeyError):
            v = None
        points.append((_utc(r["last_changed"]), v))
    points.sort(key=lambda p: p[0])
    now = now.astimezone(UTC)
    # Tramos (desde, hasta, kW) con el valor constante
    spans = [(t, points[i + 1][0] if i + 1 < len(points) else now, kw) for i, (t, kw) in enumerate(points) if kw]
    out = []
    for label, hour, end in _hours(start, now, zone):
        if first_hour is not None and hour < first_hour.astimezone(UTC):
            continue
        end = min(end, now)
        used = sum(kw * (min(b, end) - max(a, hour)).total_seconds() / 3600
                   for a, b, kw in spans if b > hour and a < end)
        out.append({"time": label, "kwh": round(used, 4)})
    return out


def build(states: dict[str, dict | None], hourly: list[dict], prices: list, now_price: float | None) -> dict:
    c = cfg()
    total = _watts(states.get(c.get("potencia_total"))) if c.get("potencia_total") else None
    devices = []
    for a in _named(c.get("aparatos")):
        st = states.get(a["entidad"])
        if st is None:
            continue
        devices.append({"nombre": a["nombre"] or st.get("attributes", {}).get("friendly_name"), "w": _watts(st),
                        "disponible": st.get("state") not in ("unavailable", "unknown")})
    devices.sort(key=lambda d: -(d["w"] or 0))

    # Coste de cada hora con su precio (el día del cambio de hora hay dos «02:00»: se usa el primero)
    price_at = {}
    for p in prices:
        price_at.setdefault(p.time.isoformat(timespec="minutes"), p.eur_kwh)
    cost = 0.0
    for h in hourly:
        price = price_at.get(h["time"])
        h["eur"] = round(h["kwh"] * price, 4) if price is not None else None
        cost += h["eur"] or 0
    return {
        "ahora_w": total,
        "ahora_eur_h": round(total / 1000 * now_price, 4) if total is not None and now_price is not None else None,
        "tension": _num(states.get(c.get("tension"))) if c.get("tension") else None,
        "intensidad": _num(states.get(c.get("intensidad"))) if c.get("intensidad") else None,
        "aparatos": devices,
        "horas": hourly,
        "hoy_kwh": round(sum(h["kwh"] for h in hourly), 3) if hourly else None,
        "hoy_eur": round(cost, 2) if hourly else None,
    }
