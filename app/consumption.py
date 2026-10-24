"""Consumo eléctrico de la casa (vista «Consumo»), solo lectura.

- Potencia de ahora de la casa entera y de cada aparato o circuito (sensores en W de Home Assistant).
- Consumo de hoy hora a hora, a partir del historial del contador de energía (kWh, total_increasing), y su coste
  con el PVPC de cada hora.
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
        t = datetime.fromisoformat(r["last_changed"].replace("Z", "+00:00")).astimezone(zone)
        points.append((t, _kwh(v, unit)))
    points.sort(key=lambda p: p[0])
    if not points:
        return []
    out = []
    hour = start
    i, last = 0, points[0][1]
    while hour <= now:
        end = hour + timedelta(hours=1)
        used = 0.0
        while i < len(points) and points[i][0] < end:
            if points[i][1] >= last:
                used += points[i][1] - last
            last = points[i][1]
            i += 1
        out.append({"time": hour.replace(tzinfo=None).isoformat(timespec="minutes"), "kwh": round(used, 4)})
        hour = (hour.astimezone(ZoneInfo("UTC")) + timedelta(hours=1)).astimezone(zone)  # bien también el día del cambio de hora
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
