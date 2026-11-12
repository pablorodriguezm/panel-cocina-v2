"""Avisos de mantenimiento: lo que necesita atención y que, si no, solo se vería abriendo /api/salud.

Cada aviso es {"id", "texto"}. Salen en un botón de la barra que solo aparece cuando hay alguno.
"""
from __future__ import annotations

import time
from datetime import datetime

from . import calefaccion, calendarios, config

NOMBRES = {"weather": "el tiempo", "prices": "el precio de la luz", "calendar": "el calendario"}
LISTA_SIN_LLEGAR_S = 24 * 3600


def build(now: datetime, *, sources: dict[str, dict], extra: dict[str, dict], lists: list[dict], shelly: dict) -> list[dict]:
    """`sources`: bloques de caché por clave; `extra`: fuentes de los calendarios extra; `lists`: las de
    Recordatorios; `shelly`: el estado del envío de la tarifa."""
    out = []
    gas = calefaccion.stale_gas_price(now.date())
    if gas:
        out.append({"id": "gas", "texto": f"{gas}. La tarjeta «¿gas o aire?» usa el último precio."})
    for name, f in extra.items():
        if not f.get("ok"):
            out.append({"id": f"calendario:{name}", "texto": f"Calendario «{name}»: {f.get('error') or 'sin datos'}"})
    for key, label in NOMBRES.items():
        c = sources.get(key)
        if c and (c["stale"] or c["data"] is None):
            out.append({"id": key, "texto": f"No se actualiza {label}: {c['error'] or 'sin datos'}"})
    for l in lists:
        if l["updated"] and time.time() - l["updated"] > LISTA_SIN_LLEGAR_S:
            dias = int((time.time() - l["updated"]) // 86400)
            out.append({"id": f"lista:{l['nombre']}", "texto": f"La lista «{l['nombre']}» no llega desde el iPhone desde hace "
                                                               f"{dias} día{'s' if dias != 1 else ''}. Revisa el Atajo."})
    if shelly.get("activo") and shelly.get("error"):
        out.append({"id": "shelly", "texto": f"No se envía el precio a Shelly: {shelly['error'].splitlines()[0]}"})
    return out
