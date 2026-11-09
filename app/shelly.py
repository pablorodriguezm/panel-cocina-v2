"""Envía el precio de la luz de cada hora a la «Tarifa en vivo» de Shelly Cloud, para que la app de Shelly calcule el
coste de lo que miden sus contadores con el PVPC de verdad.

- La URL de Shelly (con su token) va en la variable SHELLY_TARIFA_URL del stack en Portainer: es un secreto.
  Sin ella no se envía nada.
- Al cambiar la hora se manda el PVPC de esa hora en €/kWh, por defecto con impuesto eléctrico e IVA (lo que se
  paga por cada kWh). En config.yaml, «shelly_tarifa: {con_impuestos: false}» lo manda sin impuestos.
- Si falla, se reintenta a los 5 minutos. /api/salud enseña el último envío y el último error.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime

import httpx

from . import calefaccion, config

log = logging.getLogger("panel.shelly")
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
RETRY_S = 5 * 60


def url() -> str | None:
    return os.environ.get("SHELLY_TARIFA_URL") or None


def with_taxes() -> bool:
    c = config.load().get("shelly_tarifa")
    return bool((c if isinstance(c, dict) else {}).get("con_impuestos", True))


def price_for(prices: list, now: datetime) -> tuple[datetime, float] | None:
    """Hora y precio (€/kWh) que hay que mandar ahora: el PVPC de la hora en curso, con impuestos si toca."""
    hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
    p = next((p for p in prices if p.time == hour), None)
    if p is None:
        return None
    return hour, round(calefaccion.electricity_with_taxes(p.eur_kwh) if with_taxes() else p.eur_kwh, 5)


class Sender:
    def __init__(self, client: httpx.AsyncClient, get_prices):
        self.client = client
        self.get_prices = get_prices  # corrutina que devuelve la lista de HourPrice (la caché del panel)
        self.sent_hour: datetime | None = None
        self.last_try = 0.0
        self.status: dict = {"activo": url() is not None, "ultimo_envio": None, "error": None}

    async def tick(self, now: datetime) -> None:
        """Manda el precio si ha cambiado la hora (o reintenta si el último envío falló)."""
        target = url()
        if not target:
            return
        hour = now.replace(minute=0, second=0, microsecond=0, tzinfo=None)
        if self.sent_hour == hour or (self.status["error"] and time.time() - self.last_try < RETRY_S):
            return
        self.last_try = time.time()
        try:
            found = price_for(await self.get_prices(), now)
            if found is None:
                raise ValueError(f"Sin precio de la luz para las {hour:%H:%M}")
            _, price = found
            r = await self.client.post(target, json={"price": f"{price:.5f}"}, timeout=TIMEOUT)
            r.raise_for_status()
        except Exception as e:  # noqa: BLE001 — se reintenta; el detalle queda en /api/salud
            msg = str(e) or e.__class__.__name__
            # No dejar el token en el registro ni en /api/salud
            self.status["error"] = msg.replace(target, "SHELLY_TARIFA_URL")
            log.warning("Tarifa de Shelly: %s", self.status["error"])
            return
        self.sent_hour = hour
        self.status.update(error=None, ultimo_envio={"hora": hour.isoformat(timespec="minutes"), "eur_kwh": price,
                                                     "con_impuestos": with_taxes(),
                                                     "enviado": datetime.now(config.zone()).isoformat(timespec="seconds")})
        log.info("Tarifa de Shelly: %s → %.5f €/kWh", hour.strftime("%H:%M"), price)

    async def run(self) -> None:
        while True:
            try:
                await self.tick(datetime.now(config.zone()))
            except Exception as e:  # noqa: BLE001 — que un fallo raro no pare el bucle
                log.warning("Tarifa de Shelly: %s", e)
            await asyncio.sleep(60)
