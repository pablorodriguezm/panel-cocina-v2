"""Configuración: config/config.yaml (montado en /config) y secretos por variables de entorno (.env)."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

CONFIG_PATH = Path(os.environ.get("PANEL_CONFIG", "/config/config.yaml"))

DEFAULT_RECOMMENDATIONS = [
    {"id": "coche", "nombre": "Cargar el coche", "emoji": "🚗", "horas": 4},
    {"id": "lavavajillas", "nombre": "Lavavajillas", "emoji": "🍽️", "horas": 2},
    {"id": "lavadora", "nombre": "Lavadora", "emoji": "🧺", "horas": 2},
]


@lru_cache
def load() -> dict:
    with CONFIG_PATH.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg.setdefault("ubicacion", {})
    cfg["ubicacion"].setdefault("zona", "Europe/Madrid")
    cfg.setdefault("usuarios", [])
    cfg.setdefault("energia", {})
    cfg["energia"].setdefault("recomendaciones", DEFAULT_RECOMMENDATIONS)
    cfg.setdefault("home_assistant", {})
    cfg["home_assistant"].setdefault("url", "http://homeassistant.local:8123")
    return cfg


def zone() -> ZoneInfo:
    return ZoneInfo(load()["ubicacion"]["zona"])


def ha_token() -> str | None:
    return os.environ.get("HA_TOKEN") or None


def public_users() -> list[dict]:
    """Lo que la pantalla necesita de cada usuario (sin entidades de Home Assistant)."""
    return [{"id": u["id"], "nombre": u["nombre"], "color": u.get("color", "#6E6358"), "foto": u.get("foto")}
            for u in load()["usuarios"]]


def user(user_id: str) -> dict | None:
    return next((u for u in load()["usuarios"] if u["id"] == user_id), None)


def panel_token() -> str | None:
    return os.environ.get("PANEL_TOKEN") or None


def reminder_lists() -> list[str]:
    """Listas de Recordatorios que enseña el panel; la primera es la de la compra."""
    return [str(n) for n in (load().get("recordatorios") or {}).get("listas", ["Compra"])]
