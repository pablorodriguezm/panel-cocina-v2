"""Precio de la luz (PVPC) y recomendaciones de «mejores horas».

Portado de marco-familiar-dashboard (EnergyRepository.kt y EnergyScreen.kt):
- El precio sale de la API pública de Red Eléctrica (sin clave). El de mañana se publica sobre las 20:30;
  hasta entonces REE solo devuelve hoy.
- Solo se recomienda un tramo si es barato de verdad: su media por debajo de la media de su día. Por la noche,
  sin el precio de mañana, lo que queda de hoy suele ser caro y se dice que mejor esperar.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

REE_URL = "https://apidatos.ree.es/es/datos/mercados/precios-mercados-tiempo-real"


def ree_params(start: date, end: date) -> dict:
    return {"start_date": f"{start}T00:00", "end_date": f"{end}T23:59", "time_trunc": "hour"}


@dataclass(frozen=True)
class HourPrice:
    time: datetime  # hora local, sin zona
    eur_kwh: float

    def to_json(self) -> dict:
        return {"time": self.time.isoformat(timespec="minutes"), "eur_kwh": round(self.eur_kwh, 5)}


def parse_ree(payload: dict, zone: ZoneInfo) -> list[HourPrice]:
    """La serie PVPC en €/kWh y hora local. Sin ella (REE sin datos) es un error: se queda la copia anterior."""
    series = next((s for s in payload.get("included") or [] if "pvpc" in str(s.get("type", "")).lower()), None)
    if series is None:
        raise ValueError("REE sin PVPC")
    prices = []
    for v in series["attributes"]["values"]:
        at = datetime.fromisoformat(v["datetime"]).astimezone(zone).replace(tzinfo=None)
        prices.append(HourPrice(at, v["value"] / 1000.0))
    return sorted(prices, key=lambda p: p.time)


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime
    avg: float

    def to_json(self) -> dict:
        return {"start": self.start.isoformat(timespec="minutes"), "end": self.end.isoformat(timespec="minutes"),
                "avg_eur_kwh": round(self.avg, 5)}


def _consecutive(w: list[HourPrice]) -> bool:
    return all(a.time + timedelta(hours=1) == b.time for a, b in zip(w, w[1:]))


def _day_averages(prices: list[HourPrice]) -> dict[date, float]:
    by_day: dict[date, list[float]] = {}
    for p in prices:
        by_day.setdefault(p.time.date(), []).append(p.eur_kwh)
    return {d: sum(v) / len(v) for d, v in by_day.items()}


def cheapest_window(prices: list[HourPrice], now: datetime, hours: int) -> Window | None:
    """El tramo de `hours` horas seguidas más barato desde esta hora (hoy o mañana), si está por debajo de la media de su día."""
    start_hour = now.replace(minute=0, second=0, microsecond=0)
    until = datetime.combine(now.date() + timedelta(days=2), datetime.min.time())
    candidates = sorted((p for p in prices if start_hour <= p.time < until), key=lambda p: p.time)
    windows = [candidates[i:i + hours] for i in range(len(candidates) - hours + 1)]
    windows = [w for w in windows if _consecutive(w)]
    if not windows:
        return None
    best = min(windows, key=lambda w: sum(p.eur_kwh for p in w))
    avg = sum(p.eur_kwh for p in best) / hours
    if avg > _day_averages(prices).get(best[0].time.date(), float("inf")):
        return None
    return Window(best[0].time, best[-1].time + timedelta(hours=1), avg)


def most_expensive_today(prices: list[HourPrice], now: datetime, hours: int = 3) -> Window | None:
    start_hour = now.replace(minute=0, second=0, microsecond=0)
    end_today = datetime.combine(now.date() + timedelta(days=1), datetime.min.time())
    rest = sorted((p for p in prices if start_hour <= p.time < end_today), key=lambda p: p.time)
    windows = [rest[i:i + hours] for i in range(len(rest) - hours + 1)]
    if not windows:
        return None
    worst = max(windows, key=lambda w: sum(p.eur_kwh for p in w))
    return Window(worst[0].time, worst[-1].time + timedelta(hours=1), sum(p.eur_kwh for p in worst) / hours)


def summary(prices: list[HourPrice], now: datetime, recommendations: list[dict]) -> dict:
    """Todo lo que pinta la tarjeta de la luz: precio actual, día, mañana y recomendaciones."""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    day = [p for p in prices if p.time.date() == today]
    current = next((p for p in reversed(day) if p.time <= now), None)
    tomorrow_known = any(p.time.date() == tomorrow for p in prices)

    recs = []
    for r in recommendations:
        w = cheapest_window(prices, now, int(r["horas"]))
        recs.append({"id": r["id"], "nombre": r["nombre"], "emoji": r.get("emoji", ""), "horas": r["horas"],
                     "tramo": w.to_json() if w else None})
    avoid = most_expensive_today(prices, now)

    return {
        "now": current.to_json() if current else None,
        "today": [p.to_json() for p in day],
        "tomorrow": [p.to_json() for p in prices if p.time.date() == tomorrow],
        "min": min((p.eur_kwh for p in day), default=None),
        "max": max((p.eur_kwh for p in day), default=None),
        "avg": (sum(p.eur_kwh for p in day) / len(day)) if day else None,
        "tomorrow_known": tomorrow_known,
        # Sin tramo barato y sin el precio de mañana: mejor esperar a que REE lo publique (≈20:30)
        "wait_for_tomorrow": bool(prices) and not tomorrow_known and any(r["tramo"] is None for r in recs),
        "recommendations": recs,
        "avoid": avoid.to_json() if avoid else None,
    }
