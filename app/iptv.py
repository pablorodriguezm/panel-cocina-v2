"""«Mi lista»: la lista IPTV privada (Xtream Codes) en la pestaña TV (docs/TV.md).

Servidor, usuario y clave van en variables del stack en Portainer (IPTV_SERVIDOR, IPTV_USUARIO, IPTV_CLAVE): son
secretos. Nunca salen del servidor: la tablet recibe identificadores de canal y el intermediario de app/tv.py cambia
por fichas opacas cualquier dirección que lleve la clave.

Solo los canales en directo (`get_live_streams`), sin películas ni series. Se ven en HLS (`/live/u/c/<id>.m3u8`).
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone

import httpx
from urllib.parse import quote, quote_plus

TIMEOUT = httpx.Timeout(30.0, connect=8.0)
MAX_AGE_S = 6 * 3600
RETRY_S = 10 * 60


def credentials() -> tuple[str, str, str] | None:
    server = (os.environ.get("IPTV_SERVIDOR") or "").strip().rstrip("/")
    user = (os.environ.get("IPTV_USUARIO") or "").strip()
    password = (os.environ.get("IPTV_CLAVE") or "").strip()
    if not (server and user and password):
        return None
    if not server.startswith(("http://", "https://")):
        server = "http://" + server
    return server, user, password


class IPTV:
    def __init__(self, client: httpx.AsyncClient, tv):
        self.client = client
        self.tv = tv
        self.creds = credentials()
        if self.creds:
            tv.hide(self.creds[2])
        self.groups: list[dict] = []
        self.streams: list[dict] = []
        self.ids: set[int] = set()
        self.account: dict = {}
        self.error: str | None = None
        self.fetched_at = 0.0

    @property
    def configured(self) -> bool:
        return self.creds is not None

    def _clean(self, msg: str) -> str:
        """Un mensaje de error sin el usuario ni la clave."""
        if self.creds:
            for secret in self.creds[1:]:
                for form in {secret, quote(secret, safe=""), quote_plus(secret)}:
                    msg = msg.replace(form, "***")
        return msg

    async def _api(self, action: str | None = None):
        server, user, password = self.creds
        params = {"username": user, "password": password}
        if action:
            params["action"] = action
        r = await self.client.get(f"{server}/player_api.php", params=params, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()

    async def refresh(self) -> None:
        if not self.configured:
            return
        age = time.time() - self.fetched_at
        if age < (MAX_AGE_S if self.streams and not self.error else RETRY_S):
            return
        self.fetched_at = time.time()
        try:
            info = await self._api()
            user_info = (info or {}).get("user_info") or {}
            if str(user_info.get("auth", "1")) == "0":
                raise ValueError("el servidor no acepta el usuario o la clave")
            exp = user_info.get("exp_date")
            self.account = {
                "estado": user_info.get("status"),
                "caduca": datetime.fromtimestamp(int(exp), timezone.utc).date().isoformat() if str(exp or "").isdigit() else None,
                "conexiones": user_info.get("max_connections"),
                "formatos": user_info.get("allowed_output_formats"),
            }
            cats = await self._api("get_live_categories") or []
            streams = await self._api("get_live_streams") or []
            if not isinstance(streams, list) or not streams:
                raise ValueError("la lista no trae canales en directo")
            self.groups = [{"id": str(c.get("category_id")), "nombre": str(c.get("category_name") or "").strip()}
                           for c in cats if isinstance(c, dict) and c.get("category_id") is not None]
            out = []
            for s in streams:
                if not isinstance(s, dict) or not str(s.get("stream_id", "")).isdigit():
                    continue
                item = {"id": int(s["stream_id"]), "n": str(s.get("name") or "").strip(), "g": str(s.get("category_id") or "")}
                logo = str(s.get("stream_icon") or "")
                if logo.startswith("https://") and len(logo) < 400:  # http no se puede enseñar en una página https
                    item["logo"] = logo
                if item["n"]:
                    out.append(item)
            self.streams = out
            self.ids = {s["id"] for s in out}
            self.error = None
        except (httpx.HTTPError, ValueError, TypeError) as e:
            self.error = "Mi lista: " + self._clean(str(e) or e.__class__.__name__)

    def listing(self) -> dict:
        return {"grupos": self.groups, "canales": self.streams, "error": self.error, "cuenta": self.account}

    def stream_url(self, stream_id: int) -> str | None:
        """La dirección de la emisión (con la clave dentro: nunca se manda a la tablet)."""
        if not self.configured or stream_id not in self.ids:
            return None
        server, user, password = self.creds
        return f"{server}/live/{quote(user, safe='')}/{quote(password, safe='')}/{stream_id}.m3u8"

    def status(self) -> dict:
        return {"configurada": self.configured, "canales": len(self.streams), "error": self.error, **self.account}
