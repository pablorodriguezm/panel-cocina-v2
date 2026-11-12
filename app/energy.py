"""Precio de la luz (PVPC) y recomendaciones de «mejores horas».

Portado de marco-familiar-dashboard (EnergyRepository.kt y EnergyScreen.kt):
- El precio sale de la API pública de Red Eléctrica (sin clave). El de mañana se publica sobre las 20:30;
  hasta entonces REE solo devuelve hoy.
- Solo se recomienda un tramo si es barato de verdad: su media por debajo de la media de su día. Por la noche,
  sin el precio de mañana, lo que queda de hoy suele ser caro y se dice que mejor esperar.
- Lo que costaría el tramo, con impuestos: el coche, a la potencia que deja cada periodo de la tarifa 2.0TD
  («potencia_kw»); los electrodomésticos, con su consumo por ciclo («kwh») repartido en sus horas.
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


def period(t: datetime, holidays: frozenset[date] = frozenset()) -> str:
    """Periodo de la tarifa 2.0TD: valle de 0 a 8 h y todo el día en fin de semana y festivo nacional; punta de 10 a 14
    y de 18 a 22 entre semana; el resto, llano."""
    if t.weekday() >= 5 or t.date() in holidays or t.hour < 8:
        return "valle"
    return "punta" if 10 <= t.hour < 14 or 18 <= t.hour < 22 else "llano"


def window_cost(prices: list[HourPrice], window: Window, rec: dict, holidays: frozenset[date] = frozenset(),
                tax_factor: float = 1.0) -> dict | None:
    """kWh y € (con impuestos) del tramo: a la potencia de cada periodo o con el consumo de un ciclo."""
    hours = [p for p in prices if window.start <= p.time < window.end]
    if not hours:
        return None
    if rec.get("kwh"):
        kwh = float(rec["kwh"])
        eur = sum(kwh / len(hours) * p.eur_kwh for p in hours)
    elif rec.get("potencia_kw"):
        pk = rec["potencia_kw"]
        kw = (lambda t: float(pk.get(period(t, holidays), 0))) if isinstance(pk, dict) else (lambda t: float(pk))
        kwh = sum(kw(p.time) for p in hours)
        eur = sum(kw(p.time) * p.eur_kwh for p in hours)
    else:
        return None
    periods = sorted({period(p.time, holidays) for p in hours}, key=["valle", "llano", "punta"].index)
    return {"kwh": round(kwh, 2), "eur": round(eur * tax_factor, 2), "periodos": periods}


def _power(rec: dict, t: datetime, holidays: frozenset[date]) -> float:
    pk = rec.get("potencia_kw") or 0
    return float(pk.get(period(t, holidays), 0)) if isinstance(pk, dict) else float(pk)


def charge_window(prices: list[HourPrice], now: datetime, need_kwh: float, rec: dict,
                  holidays: frozenset[date] = frozenset(), tax_factor: float = 1.0) -> tuple[Window, dict] | None:
    """El tramo seguido más barato que mete `need_kwh` en el coche, a la potencia de cada periodo. Dura lo que haga
    falta (la última hora puede quedar a medias). Como los demás tramos, solo si sale por debajo de la media del día."""
    start_hour = now.replace(minute=0, second=0, microsecond=0)
    hours = sorted((p for p in prices if p.time >= start_hour), key=lambda p: p.time)
    best = None
    for i in range(len(hours)):
        got = cost = 0.0
        end = None
        for j, p in enumerate(hours[i:]):
            if j and p.time != hours[i + j - 1].time + timedelta(hours=1):
                break  # hueco en los precios
            kw = _power(rec, p.time, holidays)
            if kw <= 0:
                break
            part = min(1.0, (need_kwh - got) / kw)
            got += kw * part
            cost += kw * part * p.eur_kwh
            if got >= need_kwh - 1e-9:
                end = p.time + timedelta(minutes=round(part * 60))
                break
        if end is not None and (best is None or cost < best[0] - 1e-9):
            best = (cost, hours[i].time, end)
    if best is None:
        return None
    cost, start, end = best
    avg = cost / need_kwh
    if avg > _day_averages(prices).get(start.date(), float("inf")):
        return None
    used = [p for p in hours if start <= p.time < end]
    periods = sorted({period(p.time, holidays) for p in used}, key=["valle", "llano", "punta"].index)
    return Window(start, end, avg), {"kwh": round(need_kwh, 1), "eur": round(cost * tax_factor, 2), "periodos": periods}


def car_need(car: dict | None, capacity_kwh: float, efficiency: float = 0.9) -> dict | None:
    """kWh de la red que faltan para llevar la batería a su límite de carga, o None si no se sabe."""
    if not car or car.get("bateria") is None or car.get("limite_carga") is None:
        return None
    missing = max(0.0, car["limite_carga"] - car["bateria"]) / 100 * capacity_kwh / efficiency
    return {"falta_kwh": round(missing, 1), "bateria": car["bateria"], "limite": car["limite_carga"]}


def summary(prices: list[HourPrice], now: datetime, recommendations: list[dict], *,
            holidays: frozenset[date] = frozenset(), tax_factor: float = 1.0, car: dict | None = None) -> dict:
    """Todo lo que pinta la tarjeta de la luz: precio actual, día, mañana y recomendaciones."""
    today = now.date()
    tomorrow = today + timedelta(days=1)
    day = [p for p in prices if p.time.date() == today]
    current = next((p for p in reversed(day) if p.time <= now), None)
    tomorrow_known = any(p.time.date() == tomorrow for p in prices)

    recs = []
    for r in recommendations:
        base = {"id": r["id"], "nombre": r["nombre"], "emoji": r.get("emoji", ""), "horas": r["horas"]}
        # El coche, a medida: lo que le falta hasta su límite de carga, si se sabe (`car` viene de car_need)
        if r["id"] == "coche" and car and r.get("potencia_kw"):
            if car["falta_kwh"] < 0.5:
                recs.append({**base, "tramo": None, "coste": None, "carga": {**car, "completa": True}})
                continue
            found = charge_window(prices, now, car["falta_kwh"], r, holidays, tax_factor)
            recs.append({**base, "tramo": found[0].to_json() if found else None, "coste": found[1] if found else None,
                         "carga": {**car, "completa": False}})
            continue
        w = cheapest_window(prices, now, int(r["horas"]))
        recs.append({**base, "tramo": w.to_json() if w else None,
                     "coste": window_cost(prices, w, r, holidays, tax_factor) if w else None})
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
        "wait_for_tomorrow": bool(prices) and not tomorrow_known and any(r["tramo"] is None and not (r.get("carga") or {}).get("completa") for r in recs),
        "recommendations": recs,
        "avoid": avoid.to_json() if avoid else None,
    }
