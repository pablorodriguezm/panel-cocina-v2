"""Pestaña «TV»: la tele por internet dentro del panel (docs/TV.md).

Cada canal es de uno de estos tipos:

- hls: emisión abierta en m3u8 (RTVE, TVG…). La dirección sale de la lista pública de TDTChannels
  (github.com/LaQuay/TDTChannels), que se revisa cada 6 h; si falla, se usa la de reserva. Se ve con hls.js a través
  del intermediario de abajo, porque casi ninguna cadena permite reproducir su emisión desde otra web (CORS).
- atres: el reproductor oficial de Atresplayer incrustado (Antena 3, laSexta), con sus anuncios y su aviso de cookies.
- youtube: el directo de un canal de YouTube incrustado.
- web: Mediaset prohíbe incrustar su reproductor; solo un botón para abrir su web.

El intermediario (`/api/tv/hls`) solo pide direcciones de las emisiones de la lista y de lo que esas listas m3u8
enlazan (otras listas, segmentos y claves), y nunca a la red de casa: no sirve para pedir cualquier otra cosa. Cada
dirección que da el panel va firmada (`?u=…&s=…`, HMAC con una clave guardada en /data), así que sigue valiendo tras
un reinicio del contenedor y nadie puede fabricar otra. Las que llevan un secreto (la clave de la lista IPTV,
app/iptv.py) no se mandan a la tablet ni firmadas: van cifradas (`?k=…`) con esa misma clave.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import os
import re
import socket
import time
from pathlib import Path
from urllib.parse import quote, quote_plus, urljoin, urlsplit

import httpx

from . import config

TDTCHANNELS = "https://raw.githubusercontent.com/LaQuay/TDTChannels/master/TELEVISION.md"
TIMEOUT = httpx.Timeout(15.0, connect=5.0)
USER_AGENT = "Mozilla/5.0 (Linux; Android 14) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
LIST_MAX_AGE_S = 6 * 3600
KEY_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "tv-clave.bin"

# Los canales por defecto. «tdt»: nombre exacto en TDTChannels; «reserva»: la dirección si la lista no responde.
CANALES = [
    {"id": "la1", "nombre": "La 1", "tipo": "hls", "tdt": "La 1",
     "reserva": "https://rtvelivestream.rtve.es/rtvesec/la1/la1_main_dvr.m3u8"},
    {"id": "la2", "nombre": "La 2", "tipo": "hls", "tdt": "La 2",
     "reserva": "https://rtvelivestream.rtve.es/rtvesec/la2/la2_main_dvr.m3u8"},
    {"id": "antena3", "nombre": "Antena 3", "tipo": "atres", "slug": "antena3"},
    {"id": "lasexta", "nombre": "laSexta", "tipo": "atres", "slug": "lasexta"},
    {"id": "telecinco", "nombre": "Telecinco", "tipo": "web", "web": "https://www.mediasetinfinity.es/directo/telecinco/"},
    {"id": "cuatro", "nombre": "Cuatro", "tipo": "web", "web": "https://www.mediasetinfinity.es/directo/cuatro/"},
    {"id": "24h", "nombre": "24h", "tipo": "hls", "tdt": "24h", "reserva": "https://ztnr.rtve.es/ztnr/1694255.m3u8"},
    {"id": "tdp", "nombre": "Teledeporte", "tipo": "hls", "tdt": "Teledeporte",
     "reserva": "https://rtvelivestream.rtve.es/rtvesec/tdp/tdp_main.m3u8"},
    {"id": "clan", "nombre": "Clan", "tipo": "hls", "tdt": "Clan", "reserva": "https://ztnr.rtve.es/ztnr/5466990.m3u8"},
    {"id": "laseptima", "nombre": "La Séptima", "tipo": "youtube", "canal_youtube": "UCOCGPFW1UqPP9zdol7vEK1A"},
    {"id": "tvg", "nombre": "TVG", "tipo": "hls", "tdt": "TVG", "reserva": "https://crtvg-europa.flumotion.cloud/playlist_dvr.m3u8"},
]


def channels_config() -> list[dict]:
    c = config.load().get("tv")
    chosen = (c or {}).get("canales") if isinstance(c, dict) else None
    return [x for x in chosen if isinstance(x, dict) and x.get("id") and x.get("tipo")] if chosen else CANALES


# ---------- Lista de TDTChannels ----------

LINK = re.compile(r"\[([^\]]*)\]\((https?://[^)\s]+)\)")


def parse_tdtchannels(markdown: str) -> dict[str, list[str]]:
    """{nombre del canal: [m3u8 que se pueden usar, en orden]} de TELEVISION.md. Se descartan las que llevan huecos
    de plantilla («[IP]», «[UA]»…), que son de publicidad y no funcionan tal cual."""
    out: dict[str, list[str]] = {}
    for line in markdown.splitlines():
        if not line.startswith("| ") or line.startswith("| Canal") or line.startswith("| -"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        urls = [u for label, u in LINK.findall(cells[1]) if "m3u8" in label.lower() and "[" not in u]
        if urls and cells[0] not in out:
            out[cells[0]] = urls
    return out


# ---------- Seguridad del intermediario ----------

def _is_public(host: str) -> bool:
    """Que el nombre no apunte a la red de casa ni a la propia máquina."""
    try:
        infos = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            return False
    return True


def load_key(path: Path | None = None) -> bytes:
    """La clave de las firmas, guardada en /data para que las direcciones sigan valiendo tras un reinicio."""
    path = path or KEY_PATH
    try:
        key = path.read_bytes()
        if len(key) >= 32:
            return key
    except OSError:
        pass
    key = os.urandom(32)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(key)
        path.chmod(0o600)
    except OSError:
        pass  # sin /data (pruebas, desarrollo): vale hasta reiniciar
    return key


class TV:
    def __init__(self, client: httpx.AsyncClient, *, check_public=_is_public, key: bytes | None = None):
        self.client = client
        self.check_public = check_public
        self.key = key or load_key()
        self.streams: dict[str, list[str]] = {}
        self.fetched_at = 0.0
        self.list_error: str | None = None
        self.secrets: list[str] = []

    async def refresh(self) -> None:
        if time.time() - self.fetched_at < LIST_MAX_AGE_S and self.streams:
            return
        try:
            r = await self.client.get(TDTCHANNELS, timeout=TIMEOUT)
            r.raise_for_status()
            parsed = parse_tdtchannels(r.text)
            if not parsed:
                raise ValueError("lista vacía")
            self.streams, self.list_error = parsed, None
        except (httpx.HTTPError, ValueError) as e:
            self.list_error = f"TDTChannels: {e}"
        self.fetched_at = time.time()

    def channels(self) -> list[dict]:
        """Los canales para la interfaz, con lo que hace falta para verlos."""
        out = []
        for c in channels_config():
            item = {"id": c["id"], "nombre": c.get("nombre", c["id"]), "tipo": c["tipo"], "logo": c.get("logo")}
            if c["tipo"] == "hls":
                urls = list(c.get("urls") or []) or self.streams.get(c.get("tdt") or c.get("nombre"), [])
                if c.get("reserva") and c["reserva"] not in urls:
                    urls.append(c["reserva"])
                if not urls:
                    continue
                item["fuentes"] = [self.link(u) for u in urls]
            elif c["tipo"] == "atres":
                item["embed"] = f"https://www.atresplayer.com/embed/live/{quote(c['slug'])}/"
                item["web"] = f"https://www.atresplayer.com/directos/{quote(c['slug'])}/"
            elif c["tipo"] == "youtube":
                item["embed"] = f"https://www.youtube.com/embed/live_stream?channel={quote(c['canal_youtube'])}&autoplay=1"
            elif c["tipo"] == "web":
                item["web"] = c["web"]
            else:
                continue
            out.append(item)
        return out

    def hide(self, secret: str) -> None:
        """Las direcciones que lleven `secret` (tal cual o codificado) no llegan nunca a la tablet."""
        for form in {secret, quote(secret, safe=""), quote_plus(secret)}:
            if form and form not in self.secrets:
                self.secrets.append(form)

    def sign(self, url: str) -> str:
        return hmac.new(self.key, b"u:" + url.encode(), hashlib.sha256).hexdigest()[:32]

    def link(self, url: str) -> str:
        """La dirección del intermediario para `url`: firmada o, si lleva un secreto, cifrada."""
        if any(s in url for s in self.secrets):
            return "/api/tv/hls?k=" + self.seal(url)
        return f"/api/tv/hls?u={quote(url, safe='')}&s={self.sign(url)}"

    # Cifrado determinista y autenticado (como AES-SIV, con HMAC-SHA256): el vector es el HMAC del texto, así que
    # descifrar y recalcularlo comprueba a la vez que la ficha la hizo este panel.
    def _stream(self, iv: bytes, n: int) -> bytes:
        out = b""
        counter = 0
        while len(out) < n:
            out += hmac.new(self.key, b"k:" + iv + counter.to_bytes(4, "big"), hashlib.sha256).digest()
            counter += 1
        return out[:n]

    def seal(self, url: str) -> str:
        data = url.encode()
        iv = hmac.new(self.key, b"iv:" + data, hashlib.sha256).digest()[:16]
        ct = bytes(a ^ b for a, b in zip(data, self._stream(iv, len(data))))
        return base64.urlsafe_b64encode(iv + ct).decode().rstrip("=")

    def unhide(self, token: str) -> str | None:
        try:
            raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
        except (ValueError, TypeError):
            return None
        if len(raw) <= 16:
            return None
        iv, ct = raw[:16], raw[16:]
        data = bytes(a ^ b for a, b in zip(ct, self._stream(iv, len(ct))))
        if not hmac.compare_digest(iv, hmac.new(self.key, b"iv:" + data, hashlib.sha256).digest()[:16]):
            return None
        return data.decode("utf-8", "replace")

    def public(self, url: str) -> bool:
        """http(s) y fuera de la red de casa."""
        parts = urlsplit(url)
        return parts.scheme in ("http", "https") and bool(parts.hostname) and self.check_public(parts.hostname.lower())

    def permitted(self, url: str, sig: str | None) -> bool:
        """Una dirección que dio el propio panel (firma válida) y que no apunta a la red de casa."""
        return bool(sig) and hmac.compare_digest(sig, self.sign(url)) and self.public(url)

    async def fetch(self, url: str):
        """Pide `url` (ya permitida) y devuelve (cuerpo o flujo, tipo de contenido). Las listas m3u8 se reescriben
        para que todo lo que enlazan pase también por aquí."""
        # Las redirecciones se siguen a mano, comprobando cada salto: una cadena no puede mandarnos a la red de casa
        for _ in range(5):
            req = self.client.build_request("GET", url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
            r = await self.client.send(req, stream=True, follow_redirects=False)
            if r.status_code not in (301, 302, 303, 307, 308) or "location" not in r.headers:
                break
            await r.aclose()
            url = urljoin(url, r.headers["location"])
            if not self.public(url):
                raise PermissionError(f"Redirección no permitida a {urlsplit(url).hostname}")
        else:
            raise httpx.TooManyRedirects("Demasiadas redirecciones", request=req)
        if r.status_code >= 400:
            await r.aclose()
            raise httpx.HTTPStatusError(f"{r.status_code}", request=req, response=r)
        ctype = r.headers.get("content-type", "")
        final = str(r.url)
        if is_playlist(final, ctype):
            body = (await r.aread()).decode("utf-8", "replace")
            await r.aclose()
            return rewrite(body, final, self.link), "application/vnd.apple.mpegurl"
        return r, ctype or "application/octet-stream"


def is_playlist(url: str, ctype: str) -> bool:
    return "mpegurl" in ctype.lower() or urlsplit(url).path.lower().endswith(".m3u8")




URI_ATTR = re.compile(r'URI="([^"]+)"')


def rewrite(playlist: str, base: str, link) -> str:
    """Cambia cada dirección de la lista (líneas de segmentos o sublistas, y URI="…" de claves, mapas y pistas) por la
    del intermediario (firmada o cifrada), ya absoluta."""
    out = []
    for line in playlist.splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            absolute = urljoin(base, s)
            out.append(link(absolute))
        elif s.startswith("#") and 'URI="' in s:
            def sub(m):
                absolute = urljoin(base, m.group(1))
                return f'URI="{link(absolute)}"'
            out.append(URI_ATTR.sub(sub, line))
        else:
            out.append(line)
    return "\n".join(out) + "\n"
