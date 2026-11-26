"""Cocina: temporizadores y aviso de fogón u horno olvidado (docs/COCINA.md).

- Temporizadores: viven en el servidor, así que se ven igual en la tablet y en el móvil y siguen tras un reinicio.
  Al terminar, la tablet suena y el Echo de la cocina lo anuncia.
- Fogón u horno olvidado: con la potencia del circuito de la cocina (Shelly: placa y horno), cuenta como encendido
  con más de 150 W de media en 10 minutos. Con la media, el horno, que se enciende y se apaga solo para mantener la
  temperatura, no parece que se ha apagado. Aviso a la 1 h y aviso fuerte a las 2 h; de 0:00 a 6:00, aviso fuerte a
  los 15 min. Con un temporizador del panel en marcha no avisa: se da por hecho que alguien está cocinando.
- Anuncios por el Echo: la única orden a Home Assistant fuera de la vista Casa, siempre con el mismo servicio y
  altavoz (config.yaml «cocina.anuncio») y con textos que pone el panel, nunca la tablet.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import tempfile
import time
from collections import deque
from datetime import datetime
from pathlib import Path

from . import config

DATA_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "cocina.json"
LOG = logging.getLogger("panel.cocina")

DEFAULTS = {
    "umbral_w": 150,          # media por encima de la cual la placa o el horno cuentan como encendidos
    "ventana_min": 10,        # minutos de la media
    "aviso_min": 60,          # aviso en el panel
    "fuerte_min": 120,        # aviso fuerte
    "noche": [0, 6],          # de 0:00 a 6:00…
    "noche_min": 15,          # …aviso fuerte a los 15 minutos
    "anuncios": True,         # el Echo anuncia el fogón y el final de los temporizadores
}
MAX_TIMERS = 8
MAX_MINUTES = 12 * 60
KEEP_FINISHED_S = 15 * 60     # un temporizador acabado y sin parar desaparece solo
STEP_S = 30


def cfg() -> dict:
    c = config.load().get("cocina")
    return {**DEFAULTS, **(c if isinstance(c, dict) else {})}


def power_entity() -> str | None:
    """El sensor de potencia de la cocina: «cocina.potencia» o, si no, el aparato «Cocina» de la vista Consumo."""
    if cfg().get("potencia"):
        return str(cfg()["potencia"])
    for a in (config.load().get("consumo") or {}).get("aparatos") or []:
        if isinstance(a, dict) and str(a.get("nombre", "")).strip().lower() == "cocina":
            return a.get("entidad")
    return None


def announce_target() -> dict | None:
    """Servicio de HA y altavoz para los anuncios. Por defecto, Alexa Media Player con el Echo de la vista Casa."""
    a = cfg().get("anuncio")
    a = a if isinstance(a, dict) else {}
    speaker = a.get("objetivo") or ((config.load().get("casa") or {}).get("musica") or {}).get("entidad")
    service = str(a.get("servicio") or "notify.alexa_media")
    if not speaker or "." not in service:
        return None
    return {"servicio": service, "objetivo": speaker, "tipo": a.get("tipo") or "announce"}


def _minutes_text(m: float) -> str:
    if m < 1:
        return f"{round(m * 60)} segundos"
    m = int(round(m))
    if m < 60:
        return f"{m} minuto{'s' if m != 1 else ''}"
    h, r = divmod(m, 60)
    hours = f"{h} hora{'s' if h != 1 else ''}"
    return f"{hours} y {r} minutos" if r else hours


class Kitchen:
    def __init__(self, ha=None, path: Path | None = None, clock=time.time):
        self.ha = ha
        self.path = path or DATA_PATH
        self.clock = clock
        self.timers: list[dict] = []
        self.samples: deque[tuple[float, float]] = deque()
        self.power: float | None = None
        self.on_since: float | None = None
        self.level = ""
        self.seen_level = ""          # el nivel que ya se ha dado por visto en la tablet
        self.announced_level = ""
        self.status: dict = {"sensor": power_entity(), "error_sensor": None, "error_anuncio": None, "ultimo_anuncio": None}
        try:
            self.timers = json.loads(self.path.read_text(encoding="utf-8")).get("temporizadores", [])
        except (OSError, ValueError, AttributeError):
            self.timers = []

    # ---------- Temporizadores ----------

    def _save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".cocina-")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"temporizadores": self.timers}, f, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as e:
            LOG.warning("No se pueden guardar los temporizadores: %s", e)

    def add_timer(self, minutes: float, name: str | None = None) -> dict:
        if not 0 < minutes <= MAX_MINUTES:
            raise ValueError(f"Entre unos segundos y {MAX_MINUTES // 60} horas")
        if len(self.timers) >= MAX_TIMERS:
            raise ValueError(f"Como mucho {MAX_TIMERS} temporizadores a la vez")
        now = self.clock()
        name = (str(name or "").strip() or f"{_minutes_text(minutes)}")[:30]
        t = {"id": secrets.token_hex(4), "nombre": name, "inicio": now, "fin": now + minutes * 60,
             "duracion_s": round(minutes * 60), "acabado": False}
        self.timers.append(t)
        self._save()
        return t

    def _find(self, timer_id: str) -> dict:
        t = next((x for x in self.timers if x["id"] == timer_id), None)
        if t is None:
            raise KeyError(timer_id)
        return t

    def add_time(self, timer_id: str, minutes: float) -> dict:
        """Suma minutos; a uno acabado, los cuenta desde ahora (el «+1 min» del aviso)."""
        if not 0 < minutes <= 60:
            raise ValueError("Entre unos segundos y 60 minutos")
        t = self._find(timer_id)
        now = self.clock()
        t["fin"] = (now if t["acabado"] else t["fin"]) + minutes * 60
        t["acabado"] = False
        t.pop("acabado_t", None)
        self._save()
        return t

    def remove_timer(self, timer_id: str) -> None:
        self.timers.remove(self._find(timer_id))
        self._save()

    def running(self) -> bool:
        return any(not t["acabado"] for t in self.timers)

    def tick_timers(self) -> list[dict]:
        """Marca los que han terminado (devuelve esos, para anunciarlos) y quita los acabados hace rato."""
        now = self.clock()
        done = []
        for t in self.timers:
            if not t["acabado"] and now >= t["fin"]:
                t["acabado"], t["acabado_t"] = True, now
                done.append(t)
        before = len(self.timers)
        self.timers = [t for t in self.timers if not (t["acabado"] and now - t.get("acabado_t", now) > KEEP_FINISHED_S)]
        if done or len(self.timers) != before:
            self._save()
        return done

    # ---------- Fogón u horno olvidado ----------

    def add_sample(self, watts: float) -> None:
        now = self.clock()
        self.power = watts
        self.samples.append((now, watts))
        window = float(cfg()["ventana_min"]) * 60
        while self.samples and now - self.samples[0][0] > window:
            self.samples.popleft()

    def average(self) -> float | None:
        """Media de los últimos «ventana_min» minutos; None hasta tener casi toda la ventana."""
        if len(self.samples) < 2:
            return None
        window = float(cfg()["ventana_min"]) * 60
        if self.samples[-1][0] - self.samples[0][0] < window - STEP_S:
            return None
        return sum(w for _, w in self.samples) / len(self.samples)

    def _night(self) -> bool:
        start, end = (cfg().get("noche") or [0, 6])[:2]
        h = datetime.fromtimestamp(self.clock(), config.zone()).hour
        return start <= h < end if start <= end else (h >= start or h < end)

    def evaluate(self) -> str:
        """Actualiza el estado del fogón y devuelve el nivel de aviso: "", "aviso" o "fuerte"."""
        c = cfg()
        avg = self.average()
        now = self.clock()
        if avg is not None and avg > float(c["umbral_w"]):
            if self.on_since is None:
                self.on_since = now - float(c["ventana_min"]) * 60  # lleva encendido desde el principio de la media
        elif avg is not None:
            self.on_since, self.seen_level, self.announced_level = None, "", ""
        level = ""
        if self.on_since is not None and not self.running():
            minutes = (now - self.on_since) / 60
            if self._night() and minutes >= float(c["noche_min"]):
                level = "fuerte"
            elif minutes >= float(c["fuerte_min"]):
                level = "fuerte"
            elif minutes >= float(c["aviso_min"]):
                level = "aviso"
        self.level = level
        return level

    def mark_seen(self) -> None:
        self.seen_level = self.level

    def fogon_message(self) -> str:
        minutes = (self.clock() - (self.on_since or self.clock())) / 60
        return f"Atención: la placa o el horno lleva encendido {_minutes_text(minutes)}."

    # ---------- Anuncios por el Echo ----------

    async def announce(self, message: str) -> None:
        target = announce_target()
        if not (cfg().get("anuncios") and target and self.ha):
            return
        domain, service = target["servicio"].split(".", 1)
        data = {"message": message, "target": [target["objetivo"]], "data": {"type": target["tipo"], "method": "all"}}
        try:
            await self.ha.call(domain, service, data)
            self.status.update(error_anuncio=None, ultimo_anuncio={"t": self.clock(), "texto": message})
        except Exception as e:  # noqa: BLE001 — un fallo del Echo no puede parar los avisos de la tablet
            self.status["error_anuncio"] = f"{target['servicio']}: {e}"
            LOG.warning("No se pudo anunciar por el Echo: %s", e)

    async def step(self) -> None:
        """Una vuelta: temporizadores, potencia de la cocina y anuncios."""
        for t in self.tick_timers():
            await self.announce(f"El temporizador {t['nombre']} ha terminado.")
        entity = power_entity()
        self.status["sensor"] = entity
        if entity and self.ha:
            try:
                st = await self.ha.state(entity)
                self.add_sample(float(st.get("state")))
                self.status["error_sensor"] = None
            except Exception as e:  # noqa: BLE001
                self.status["error_sensor"] = f"{entity}: {e}"
        level = self.evaluate()
        order = {"": 0, "aviso": 1, "fuerte": 2}
        if level and order[level] > order[self.announced_level]:
            self.announced_level = level
            await self.announce(self.fogon_message())

    async def run(self) -> None:
        while True:
            try:
                await self.step()
            except Exception:  # noqa: BLE001
                LOG.exception("Cocina")
            await asyncio.sleep(STEP_S)

    # ---------- Para la tablet ----------

    def view(self) -> dict:
        now = self.clock()
        self.tick_timers()
        avg = self.average()
        return {
            "ahora": now,
            "temporizadores": [{**t, "restante_s": max(0, round(t["fin"] - now))} for t in sorted(self.timers, key=lambda x: x["fin"])],
            "fogon": {
                "encendido": self.on_since is not None,
                "desde": self.on_since,
                "minutos": round((now - self.on_since) / 60) if self.on_since else 0,
                "nivel": self.level,
                "visto": bool(self.level) and self.seen_level == self.level,
                "potencia_w": self.power,
                "media_w": round(avg) if avg is not None else None,
                "pausado_por_temporizador": self.on_since is not None and self.running(),
            },
        }

    def health(self) -> dict:
        return {**self.status, "anuncio": announce_target(), "anuncios": bool(cfg().get("anuncios")),
                "temporizadores": len(self.timers), "fogon_nivel": self.level}
