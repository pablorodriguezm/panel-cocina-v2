"""Vigía de la copia de seguridad de ZimaOS (docs/COPIAS.md).

La copia la hace otro stack («copias»), no el panel. Cuando termina bien, avisa aquí (`POST /api/copias/ok`) y el
panel apunta la hora. Si pasa más de día y medio sin aviso, sale en los avisos de la barra: una copia que deja de
hacerse sin que nadie se entere es como no tenerla. Mientras no llegue el primer aviso, no se vigila nada.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

DATA_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "copias.json"
MAX_AGE_S = 36 * 3600


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or DATA_PATH
        try:
            self.last: float | None = json.loads(self.path.read_text(encoding="utf-8")).get("ultima_ok")
        except (OSError, ValueError, AttributeError):
            self.last = None

    def ok(self) -> None:
        self.last = time.time()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".copias-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"ultima_ok": self.last}, f)
        os.replace(tmp, self.path)

    def status(self) -> dict:
        age = None if self.last is None else time.time() - self.last
        return {"vigilada": self.last is not None, "ultima_ok": self.last,
                "ok": age is None or age <= MAX_AGE_S,
                "error": None if age is None or age <= MAX_AGE_S else
                f"La copia de seguridad de ZimaOS no se hace desde hace {int(age // 86400)} día(s)"}
