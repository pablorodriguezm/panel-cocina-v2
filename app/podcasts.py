"""Podcasts de Overcast dentro del panel (pestaña TV → Podcasts, docs/PODCASTS.md).

Overcast no tiene API pública ni deja mostrar su web dentro de otra página (X-Frame-Options: DENY), así que el
servidor hace lo mismo que su web, con tu cuenta (OVERCAST_EMAIL y OVERCAST_CLAVE en Portainer):

- Inicia sesión como el formulario de overcast.fm/login y guarda la cookie de sesión en /data (no la contraseña).
- Lee tus podcasts y los capítulos «para seguir» de overcast.fm/podcasts, y los capítulos de cada podcast.
- Al poner un capítulo, lee su página: la dirección del audio, por dónde ibas y su versión de sincronización.
- Guarda el progreso con la misma llamada que su reproductor web (POST /podcasts/set_progress/<id>: p, speed, v), así
  que lo que escuches en la cocina sigue en el iPhone, y al terminar lo marca como escuchado.

Es una vía no oficial: si Overcast cambia su web, deja de funcionar hasta adaptarla; el panel lo dice en Avisos.
La tablet nunca recibe la contraseña ni la cookie, y solo puede pedir páginas de capítulos y podcasts de Overcast.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin

import httpx

BASE = "https://overcast.fm"
DATA_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "overcast.json"
PINS_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "podcasts-fijados.json"  # los podcasts fijados arriba
TIMEOUT = httpx.Timeout(20.0, connect=8.0)
USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
FINISHED = 0x7FFFFFFF          # lo que manda su reproductor al acabar un capítulo
LIST_MAX_AGE_S = 3 * 60
FEED_MAX_AGE_S = 10 * 60
LOG = logging.getLogger("panel.podcasts")

EPISODE_ID = re.compile(r"^[A-Za-z0-9_-]{4,40}$")                 # el código de /+XXXX
FEED_PATH = re.compile(r"^/(itunes\d+|p\d+-[A-Za-z0-9]+)(/[A-Za-z0-9_-]*)?$")


def credentials() -> tuple[str, str] | None:
    email = (os.environ.get("OVERCAST_EMAIL") or "").strip()
    password = os.environ.get("OVERCAST_CLAVE") or ""
    return (email, password) if email and password else None


class NotLoggedIn(Exception):
    pass


# ---------- Lectura de sus páginas ----------

class _Cells(HTMLParser):
    """Las celdas de las listas de Overcast: <a class="feedcell|episodecell|extendedepisodecell" href=…> con su
    imagen (.art) y sus textos (.title y .caption2)."""

    KINDS = ("feedcell", "episodecell", "extendedepisodecell")

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.cells: list[dict] = []
        self.cell: dict | None = None
        self.depth = 0
        self.text_into: str | None = None
        self.text_depth = 0

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = (a.get("class") or "").split()
        if self.cell is None and tag == "a":
            kind = next((k for k in self.KINDS if k in classes), None)
            if kind:
                self.cell = {"tipo": kind, "href": a.get("href") or "", "clases": classes, "titulo": "", "textos": []}
                self.depth = 1
            return
        if self.cell is None:
            return
        if tag not in ("img", "br", "input", "source"):
            self.depth += 1
        if tag == "img" and "art" in classes and not self.cell.get("arte"):
            self.cell["arte"] = a.get("src")
        if self.text_into is None and ("title" in classes or "caption2" in classes):
            self.text_into = "titulo" if "title" in classes else "texto"
            self.text_depth = self.depth
            self.cell["_buf"] = ""

    def handle_endtag(self, tag):
        if self.cell is None:
            return
        if self.text_into and self.depth == self.text_depth:
            text = " ".join(self.cell.pop("_buf", "").split())
            if self.text_into == "titulo" and not self.cell["titulo"]:
                self.cell["titulo"] = text
            elif text:
                self.cell["textos"].append(text)
            self.text_into = None
        self.depth -= 1
        if tag == "a" and self.depth <= 0:
            self.cells.append(self.cell)
            self.cell = None

    def handle_data(self, data):
        if self.cell is not None and self.text_into:
            self.cell["_buf"] = self.cell.get("_buf", "") + data


def parse_cells(html: str) -> list[dict]:
    p = _Cells()
    p.feed(html)
    return p.cells


def _episode_id(href: str) -> str | None:
    m = re.match(r"^/\+([A-Za-z0-9_-]+)", href or "")
    return m.group(1) if m else None


def parse_home(html: str) -> dict:
    """overcast.fm/podcasts: los capítulos «para seguir» y tus podcasts."""
    episodes, feeds = [], []
    for c in parse_cells(html):
        if c["tipo"] == "episodecell" and _episode_id(c["href"]):
            texts = c["textos"]
            episodes.append({"id": _episode_id(c["href"]), "titulo": c["titulo"],
                             "podcast": texts[0] if texts else "", "info": " · ".join(texts[1:]), "arte": c.get("arte")})
        elif c["tipo"] == "feedcell" and FEED_PATH.match(c["href"].split("?")[0]):
            feeds.append({"ruta": c["href"].split("?")[0], "titulo": c["titulo"], "arte": c.get("arte")})
    return {"en_curso": episodes, "podcasts": feeds}


def parse_feed(html: str) -> list[dict]:
    """La página de un podcast: sus capítulos, con los nuevos marcados."""
    out = []
    for c in parse_cells(html):
        if c["tipo"] == "extendedepisodecell" and _episode_id(c["href"]):
            out.append({"id": _episode_id(c["href"]), "titulo": c["titulo"], "info": " · ".join(c["textos"]),
                        "nuevo": "usernewepisode" in c["clases"]})
    return out


class _Episode(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.player: dict | None = None
        self.source: str | None = None
        self.in_player = False
        self.art: str | None = None
        self.h: dict[str, str] = {}
        self._h: str | None = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "audio" and a.get("id") == "audioplayer":
            self.player, self.in_player = a, True
            if a.get("src"):
                self.source = a["src"]
        elif tag == "source" and self.in_player and not self.source:
            self.source = a.get("src")
        elif tag == "img" and "art" in (a.get("class") or "").split() and not self.art:
            self.art = a.get("src")
        elif tag in ("h2", "h3") and tag not in self.h:
            self._h, self.h[tag] = tag, ""

    def handle_endtag(self, tag):
        if tag == "audio":
            self.in_player = False
        if tag == self._h:
            self._h = None

    def handle_data(self, data):
        if self._h:
            self.h[self._h] += data


def parse_episode(html: str) -> dict:
    p = _Episode()
    p.feed(html)
    if not p.player or not p.source:
        raise ValueError("la página del capítulo no trae el reproductor")
    a = p.player
    def num(k):
        try:
            return int(a.get(k) or 0)
        except ValueError:
            return 0
    return {
        "item_id": a.get("data-item-id"),
        "audio": p.source.split("#")[0],
        "inicio": num("data-start-time"),
        "version": num("data-sync-version"),
        "velocidad_id": num("data-speed-id"),
        "guardado": a.get("data-saved-for-user") == "1",
        "sesion": a.get("data-logged-in") == "1",
        "titulo": " ".join(p.h.get("h2", "").split()),
        "podcast": " ".join(p.h.get("h3", "").split()),
        "arte": p.art,
    }


# ---------- La cuenta ----------

class Overcast:
    def __init__(self, path: Path | None = None, transport=None):
        self.path = path or DATA_PATH
        self.creds = credentials()
        self.client = httpx.AsyncClient(base_url=BASE, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT,
                                        follow_redirects=True, transport=transport)
        self.home: dict | None = None
        self.home_at = 0.0
        self.feeds: dict[str, tuple[float, list]] = {}
        self.episodes: dict[str, dict] = {}       # id → datos de su página (para guardar el progreso)
        self.error: str | None = None
        self.pins_path = self.path.with_name(PINS_PATH.name) if path else PINS_PATH
        try:
            self.pins: list[str] = [p for p in json.loads(self.pins_path.read_text(encoding="utf-8")) if FEED_PATH.match(p)]
        except (OSError, ValueError, TypeError):
            self.pins = []
        self.last_ok: float | None = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            for name, value in (saved.get("cookies") or {}).items():
                self.client.cookies.set(name, value, domain="overcast.fm")
        except (OSError, ValueError, AttributeError):
            pass

    @property
    def configured(self) -> bool:
        return self.creds is not None

    def _save_cookies(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"cookies": {c.name: c.value for c in self.client.cookies.jar}}), encoding="utf-8")
            self.path.chmod(0o600)
        except OSError as e:
            LOG.warning("No se puede guardar la sesión de Overcast: %s", e)

    async def login(self) -> None:
        email, password = self.creds
        self.client.cookies.clear()
        r = await self.client.post("/login", data={"then": "podcasts", "email": email, "password": password})
        if r.url.path.startswith("/login") or 'name="password"' in r.text:
            raise NotLoggedIn("Overcast no acepta el correo o la contraseña")
        self._save_cookies()

    async def _get(self, path: str) -> str:
        """Una página con la sesión; si ha caducado, vuelve a iniciar sesión una vez."""
        for attempt in (1, 2):
            r = await self.client.get(path)
            r.raise_for_status()
            if not r.url.path.startswith("/login"):
                return r.text
            if attempt == 1:
                await self.login()
        raise NotLoggedIn("Overcast pide iniciar sesión otra vez")

    def _ok(self) -> None:
        self.error, self.last_ok = None, time.time()

    def _fail(self, e: Exception) -> None:
        msg = str(e) or e.__class__.__name__
        if self.creds:
            msg = msg.replace(self.creds[1], "***")
        self.error = f"Overcast: {msg}"
        LOG.warning(self.error)

    async def library(self) -> dict:
        if self.home is None or time.time() - self.home_at > LIST_MAX_AGE_S:
            try:
                self.home = parse_home(await self._get("/podcasts"))
                self.home_at = time.time()
                if not self.home["podcasts"] and not self.home["en_curso"]:
                    raise ValueError("la página de tus podcasts ha cambiado: no se encuentra ninguno")
                self._ok()
            except (httpx.HTTPError, NotLoggedIn, ValueError) as e:
                self._fail(e)
        return {**(self.home or {"en_curso": [], "podcasts": []}), "fijados": self.pins, "error": self.error}

    def pin(self, path: str, pinned: bool) -> list[str]:
        """Fija un podcast arriba de la lista (al final de los fijados) o lo quita. Se ve igual en todos los aparatos."""
        if not FEED_PATH.match(path):
            raise ValueError("podcast desconocido")
        self.pins = [p for p in self.pins if p != path] + ([path] if pinned else [])
        try:
            self.pins_path.parent.mkdir(parents=True, exist_ok=True)
            self.pins_path.write_text(json.dumps(self.pins), encoding="utf-8")
        except OSError as e:
            LOG.warning("No se pueden guardar los podcasts fijados: %s", e)
        return self.pins

    async def feed(self, path: str) -> list[dict]:
        if not FEED_PATH.match(path):
            raise ValueError("podcast desconocido")
        at, cached = self.feeds.get(path, (0.0, []))
        if time.time() - at > FEED_MAX_AGE_S:
            cached = parse_feed(await self._get(path))
            self.feeds[path] = (time.time(), cached)
            self._ok()
        return cached

    async def episode(self, episode_id: str) -> dict:
        if not EPISODE_ID.match(episode_id):
            raise ValueError("capítulo desconocido")
        e = parse_episode(await self._get(f"/+{episode_id}"))
        if not e["item_id"]:
            raise ValueError("la página del capítulo no trae su identificador")
        self.episodes[episode_id] = e
        self._ok()
        return {"id": episode_id, **{k: e[k] for k in ("titulo", "podcast", "arte", "audio", "inicio", "velocidad_id")}}

    async def progress(self, episode_id: str, seconds: float, finished: bool = False) -> int:
        """Guarda por dónde vas (o que lo has terminado) como su reproductor web. Devuelve la versión nueva."""
        e = self.episodes.get(episode_id)
        if not e:
            raise KeyError(episode_id)
        p = FINISHED if finished else max(0, int(seconds))
        r = await self.client.post(f"/podcasts/set_progress/{e['item_id']}",
                                   data={"p": p, "speed": e["velocidad_id"], "v": e["version"]})
        if r.url.path.startswith("/login"):
            await self.login()
            r = await self.client.post(f"/podcasts/set_progress/{e['item_id']}",
                                       data={"p": p, "speed": e["velocidad_id"], "v": e["version"]})
        r.raise_for_status()
        try:
            v = int(r.text.strip())
            if v:
                e["version"] = v
        except ValueError:
            pass
        e["inicio"] = p if not finished else e["inicio"]
        self.home_at = 0.0  # «para seguir» cambia
        self._ok()
        return e["version"]

    def status(self) -> dict:
        return {"configurado": self.configured, "error": self.error, "ultimo_ok": self.last_ok}
