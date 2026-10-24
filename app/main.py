"""Panel de cocina: API de solo lectura para la tablet y la propia web.

GET  /api/hogar           → lo común: tiempo, luz, calendario, recordatorios y coche
POST /api/recordatorios   → el Atajo del iPhone envía las listas de Recordatorios (cabecera X-Panel-Token)
GET /api/usuario/{id}     → lo de cada uno: su trayecto
GET /api/usuarios         → avatares de la pantalla de bloqueo y ajustes de pantalla
GET /api/salud            → estado de cada fuente (para depurar)
"""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config, demo, energy, reminders, sources
from .cache import Cached

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
WEB = Path(__file__).resolve().parent.parent / "web"

DEMO = os.environ.get("PANEL_DEMO", "").lower() in {"1", "true", "si", "sí"}

state: dict = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    client = httpx.AsyncClient(follow_redirects=True)
    ha = sources.HomeAssistant(client)
    state["ha"] = ha
    if DEMO:
        logging.getLogger("panel").info("Modo demostración: datos ficticios")
    src = demo if DEMO else None
    state["weather"] = Cached("tiempo", 30 * 60, src.weather if src else lambda: sources.weather(client))
    state["prices"] = Cached("luz", 30 * 60, src.prices if src else lambda: sources.prices(client))
    state["calendar"] = Cached("calendario", 5 * 60, src.calendar_events if src else lambda: sources.calendar_events(ha))
    state["reminders"] = reminders.Store()
    if DEMO and not state["reminders"].lists:
        state["reminders"].lists = demo.reminders()
    state["car"] = Cached("coche", 2 * 60, src.car if src else lambda: sources.car(ha))
    state["commute"] = {}
    yield
    await client.aclose()


app = FastAPI(title="Panel de cocina", lifespan=lifespan, docs_url=None, redoc_url=None)


def _energy_view(cached: dict) -> dict:
    prices = cached["data"] or []
    now = datetime.now(config.zone()).replace(tzinfo=None)
    recs = config.load()["energia"]["recomendaciones"]
    return {**cached, "data": energy.summary(prices, now, recs) if prices else None}


@app.get("/api/usuarios")
async def users():
    pantalla = config.load().get("pantalla") or {}
    return {"usuarios": config.public_users(), "volver_al_bloqueo_s": int(pantalla.get("volver_al_bloqueo_s", 120))}


@app.get("/api/hogar")
async def home():
    return {
        "ahora": datetime.now(config.zone()).isoformat(timespec="seconds"),
        "tiempo": await state["weather"].get(),
        "luz": _energy_view(await state["prices"].get()),
        "calendario": await state["calendar"].get(),
        "recordatorios": {"data": state["reminders"].view(config.reminder_lists()), "stale": False, "error": None},
        "coche": await state["car"].get(),
    }


@app.get("/api/usuario/{user_id}")
async def user(user_id: str):
    if config.user(user_id) is None:
        raise HTTPException(404, "Usuario desconocido")
    cache = state["commute"].setdefault(
        user_id, Cached(f"trayecto-{user_id}", 5 * 60,
                        (lambda: demo.commute(user_id)) if DEMO else (lambda: sources.commute(state["ha"], user_id))))
    return {"usuario": next(u for u in config.public_users() if u["id"] == user_id), "trayecto": await cache.get()}


@app.get("/api/salud")
async def health():
    out = {}
    for key in ("weather", "prices", "calendar", "car"):
        c = await state[key].get()
        out[key] = {"ok": not c["stale"] and c["data"] is not None, "error": c["error"], "updated": c["updated"]}
    out["recordatorios"] = {l["nombre"]: {"elementos": len(l["items"]), "updated": l["updated"]}
                            for l in state["reminders"].view(config.reminder_lists())}
    return out


@app.post("/api/recordatorios")
async def push_reminders(request: Request, x_panel_token: str | None = Header(default=None)):
    expected = config.panel_token()
    if not expected:
        raise HTTPException(503, "Falta PANEL_TOKEN en .env")
    if not x_panel_token or not hmac.compare_digest(x_panel_token, expected):
        raise HTTPException(401, "Token incorrecto")
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "El cuerpo no es JSON")
    try:
        updated = state["reminders"].update(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    unknown = [n for n in updated if n not in config.reminder_lists()]
    return {"ok": True, "actualizadas": updated,
            "aviso": f"Listas que el panel no enseña (añádelas en config.yaml): {', '.join(unknown)}" if unknown else None}


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
