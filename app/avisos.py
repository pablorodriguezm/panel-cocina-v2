"""Avisos de mantenimiento: lo que necesita atención y que, si no, solo se vería abriendo /api/salud.

Cada aviso es {"id", "texto"}. Salen en un botón de la barra que solo aparece cuando hay alguno.
"""
from __future__ import annotations

import time
from datetime import datetime

from . import calefaccion, calendarios, config

NOMBRES = {"weather": "el tiempo", "prices": "el precio de la luz", "calendar": "el calendario"}
LISTA_SIN_LLEGAR_S = 24 * 3600
IPTV_CADUCA_DIAS = 10


def build(now: datetime, *, sources: dict[str, dict], extra: dict[str, dict], lists: list[dict], shelly: dict,
          backups: dict | None = None, iptv: dict | None = None, kitchen: dict | None = None,
          podcasts: dict | None = None) -> list[dict]:
    """`sources`: bloques de caché por clave; `extra`: fuentes de los calendarios extra; `lists`: las de
    Recordatorios; `shelly`: el estado del envío de la tarifa; `iptv`: el de «Mi lista» de la pestaña TV."""
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
    if backups and not backups["ok"]:
        out.append({"id": "copias", "texto": f"{backups['error']}. Mira el stack «copias» en Portainer."})
    if kitchen:
        if kitchen.get("error_sensor"):
            out.append({"id": "cocina:sensor", "texto": f"Sin el sensor de la cocina, no hay aviso de fogón olvidado: "
                                                         f"{kitchen['error_sensor'].splitlines()[0]}"})
        elif not kitchen.get("sensor"):
            out.append({"id": "cocina:sensor", "texto": "No hay sensor de potencia de la cocina (cocina.potencia o el aparato "
                                                         "«Cocina» de consumo): no hay aviso de fogón olvidado."})
        if kitchen.get("error_anuncio"):
            out.append({"id": "cocina:echo", "texto": f"El Echo no anuncia los avisos de la cocina: {kitchen['error_anuncio'].splitlines()[0]}"})
    if podcasts and podcasts.get("configurado") and podcasts.get("error"):
        out.append({"id": "podcasts", "texto": f"Podcasts: {podcasts['error']}"})
    if iptv and iptv.get("configurada"):
        if iptv.get("error"):
            out.append({"id": "iptv", "texto": f"TV: {iptv['error']}"})
        elif iptv.get("caduca"):
            dias = (datetime.fromisoformat(iptv["caduca"]).date() - now.date()).days
            if dias <= IPTV_CADUCA_DIAS:
                cuando = "ha caducado" if dias < 0 else "caduca hoy" if dias == 0 else f"caduca en {dias} día{'s' if dias != 1 else ''}"
                out.append({"id": "iptv", "texto": f"TV: la suscripción de «Mi lista» {cuando} ({iptv['caduca']})."})
    return out
