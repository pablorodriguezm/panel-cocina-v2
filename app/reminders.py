"""Recordatorios de Apple (lista de la compra y tareas).

Desde iOS 13 los Recordatorios «actualizados» ya no están en el CalDAV de iCloud: solo los ve un dispositivo Apple.
Así que no se leen desde el servidor: un **Atajo** en el iPhone (o en un Mac) los envía a este servicio con
`POST /api/recordatorios`, y aquí se guardan en disco para que sobrevivan a un reinicio del contenedor.

Formato que acepta (lo más fácil de montar en Atajos):

    {"lista": "Compra", "items": ["Leche", "Pan"]}
    {"lista": "Compra", "items": [{"titulo": "Leche", "notas": "sin lactosa", "vence": "2026-10-25"}]}
    {"lista": "Compra", "items": "Leche\\nPan"}          ← texto, un elemento por línea
    {"listas": [{"lista": "Compra", "items": [...]}, {"lista": "Casa", "items": [...]}]}

Cada envío sustituye la lista entera: lo que no viene es que ya está hecho o se ha borrado.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any

DATA_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "recordatorios.json"
MAX_ITEMS = 300
MAX_TEXT = 300


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s[:MAX_TEXT] or None


def _item(raw: Any) -> dict | None:
    if isinstance(raw, dict):
        title = _text(raw.get("titulo") or raw.get("title") or raw.get("nombre"))
        if not title:
            return None
        return {"titulo": title, "notas": _text(raw.get("notas") or raw.get("notes")),
                "vence": _text(raw.get("vence") or raw.get("due"))}
    title = _text(raw)
    return {"titulo": title, "notas": None, "vence": None} if title else None


def parse_list(raw: dict) -> tuple[str, list[dict]]:
    name = _text(raw.get("lista") or raw.get("nombre"))
    if not name:
        raise ValueError("Falta «lista» con el nombre de la lista de Recordatorios")
    items = raw.get("items", [])
    if isinstance(items, str):
        items = items.splitlines()
    if not isinstance(items, list):
        raise ValueError("«items» tiene que ser una lista o un texto con un elemento por línea")
    parsed = [i for i in (_item(x) for x in items[:MAX_ITEMS]) if i]
    return name, parsed


def parse(payload: Any) -> list[tuple[str, list[dict]]]:
    if not isinstance(payload, dict):
        raise ValueError("Se esperaba un objeto JSON")
    raws = payload["listas"] if isinstance(payload.get("listas"), list) else [payload]
    return [parse_list(r) for r in raws if isinstance(r, dict)]


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_PATH
        self.lists: dict[str, dict] = {}
        try:
            self.lists = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.lists = {}

    def update(self, payload: Any) -> list[str]:
        updated = []
        for name, items in parse(payload):
            self.lists[name] = {"items": items, "updated": time.time()}
            updated.append(name)
        self._save()
        return updated

    def _save(self) -> None:
        # Escritura atómica: un corte deja el fichero viejo o el nuevo, nunca uno a medias
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".recordatorios-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(self.lists, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def view(self, names: list[str]) -> list[dict]:
        """Las listas configuradas, en su orden; las que aún no han llegado salen vacías y sin fecha."""
        out = []
        for n in names:
            entry = self.lists.get(n)
            out.append({"nombre": n, "items": entry["items"] if entry else [], "updated": entry["updated"] if entry else None})
        return out
