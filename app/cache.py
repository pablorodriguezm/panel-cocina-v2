"""Caché en memoria con «stale-if-error», como CachedResource del repositorio original.

Cada dato tiene una vida máxima. Si caduca, se vuelve a pedir; si la petición falla, se sigue sirviendo la última copia
buena (marcada como `stale`) para que la tablet nunca se quede en blanco por un fallo puntual.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Awaitable, Callable

log = logging.getLogger("panel.cache")


class Cached:
    def __init__(self, name: str, max_age_s: int, fetch: Callable[[], Awaitable[Any]]):
        self.name = name
        self.max_age_s = max_age_s
        self._fetch = fetch
        self._value: Any = None
        self._fetched_at: float | None = None
        self._error: str | None = None
        self._lock = asyncio.Lock()

    def _fresh(self) -> bool:
        return self._fetched_at is not None and time.time() - self._fetched_at < self.max_age_s

    async def get(self) -> dict:
        if not self._fresh():
            async with self._lock:  # dos peticiones a la vez no lanzan dos descargas
                if not self._fresh():
                    try:
                        self._value = await self._fetch()
                        self._fetched_at = time.time()
                        self._error = None
                    except Exception as e:  # noqa: BLE001 — cualquier fallo deja la copia anterior
                        log.warning("%s: %s", self.name, e)
                        self._error = str(e) or e.__class__.__name__
        return {
            "data": self._value,
            "updated": self._fetched_at,
            "stale": self._error is not None,
            "error": self._error,
        }

    def invalidate(self) -> None:
        self._fetched_at = None
