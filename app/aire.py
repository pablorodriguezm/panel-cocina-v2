"""Consumo real del aire acondicionado: lo que mide el Shelly en el circuito de climatización, día a día.

La tarjeta «¿gas o aire?» estima con el COP de catálogo; esto apunta lo que de verdad gasta el aire para poder
comparar: kWh y € de cada día (con el PVPC de cada hora e impuestos), la temperatura media de fuera y los
«grados-día» de frío (lo que la temperatura media queda por debajo de 18 °C). Con unas semanas de datos, los kWh por
grado-día dicen cuánta luz pide la casa por cada grado de frío; comparado con el gas de las facturas en periodos de
solo caldera, da el rendimiento real aproximado del aire (docs/CALEFACCION.md).

El Shelly mide la luz que entra al aire, no el calor que da: el COP no se puede medir directamente.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path

from . import calefaccion, config

DATA_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "aire.json"
BASE_C = 18.0     # por debajo de esta temperatura media se considera que hace falta calefacción
MIN_KWH = 0.3     # menos que esto en un día es que el aire estuvo apagado (consumo en espera)
KEEP_DAYS = 400


def appliance_name() -> str:
    return str(calefaccion.cfg().get("aparato_aire", "Climatización"))


def entity() -> str | None:
    """El sensor de potencia del aire: el aparato de «consumo.aparatos» con ese nombre."""
    for a in (config.load().get("consumo") or {}).get("aparatos") or []:
        if isinstance(a, dict) and a.get("nombre") == appliance_name():
            return a.get("entidad")
    return None


def day_record(hourly: list[dict], prices: dict[str, float], temps: dict[str, float]) -> dict:
    """Resumen de un día a partir de sus horas ({"time", "kwh"}), el PVPC por hora y la temperatura por hora."""
    kwh = sum(h["kwh"] for h in hourly)
    priced = [h for h in hourly if h["time"] in prices]
    eur = sum(calefaccion.electricity_with_taxes(prices[h["time"]]) * h["kwh"] for h in priced)
    ts = [temps[h["time"]] for h in hourly if h["time"] in temps]
    return {"kwh": round(kwh, 2),
            "eur": round(eur, 2) if len(priced) == len(hourly) and hourly else None,
            "t_media": round(sum(ts) / len(ts), 1) if ts else None,
            "grados_dia": round(sum(max(0.0, BASE_C - t) for t in ts) / len(ts), 1) if ts else None,
            "horas": sum(1 for h in hourly if h["kwh"] >= 0.1)}


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_PATH
        try:
            self.days: dict[str, dict] = json.loads(self.path.read_text(encoding="utf-8")).get("dias", {})
        except (OSError, ValueError, AttributeError):
            self.days = {}

    def add(self, day: date, record: dict) -> None:
        self.days[day.isoformat()] = record
        limit = (day - timedelta(days=KEEP_DAYS)).isoformat()
        self.days = {d: r for d, r in sorted(self.days.items()) if d >= limit}
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".aire-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"dias": self.days}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def missing(self, today: date, back: int = 7) -> list[date]:
        """Días ya cerrados de la última semana que aún no están apuntados."""
        days = [today - timedelta(days=i) for i in range(back, 0, -1)]
        return [d for d in days if d.isoformat() not in self.days]


def summary(store: Store, today: date, today_record: dict | None) -> dict:
    """Lo que enseña la tarjeta: hoy, ayer, la última semana y los kWh por grado-día de los días con calefacción."""
    last = [(d, r) for d, r in store.days.items() if (today - timedelta(days=7)).isoformat() <= d < today.isoformat()]
    used = [r for _, r in last if r["kwh"] >= MIN_KWH]
    heating = [r for r in store.days.values() if r["kwh"] >= MIN_KWH and (r.get("grados_dia") or 0) >= 2]
    degree_days = sum(r["grados_dia"] for r in heating)
    return {
        "aparato": appliance_name(),
        "hoy": today_record,
        "ayer": store.days.get((today - timedelta(days=1)).isoformat()),
        "semana": {"kwh": round(sum(r["kwh"] for r in used), 1), "eur": round(sum(r["eur"] or 0 for r in used), 2),
                   "dias": len(used)} if used else None,
        # Con pocos días no dice nada: a partir de una semana de calefacción
        "kwh_por_grado_dia": round(sum(r["kwh"] for r in heating) / degree_days, 2) if len(heating) >= 7 else None,
        "dias_calefaccion": len(heating),
    }
