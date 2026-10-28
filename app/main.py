"""Panel de cocina: API de solo lectura para la tablet y la propia web.

GET  /api/hogar           → lo común: tiempo, luz, calendario (y festivos, F1 y fútbol), recordatorios y coche
POST /api/recordatorios   → el Atajo del iPhone envía las listas de Recordatorios (cabecera X-Panel-Token)
POST /api/recordatorios/recoger → el Atajo recoge lo pasado a la compra desde el panel (cabecera X-Panel-Token)
GET  /api/menu?semana=0   → menú de la semana (0 esta, 1 la siguiente) y sus ingredientes
POST /api/menu/compra     → pasa un ingrediente del menú a la compra (o lo quita si el Atajo aún no lo ha recogido)
GET  /api/casa            → calefacción, aire, temperaturas y música
GET  /api/consumo         → potencia de ahora, por aparato y consumo de hoy por horas
POST /api/casa/{orden}    → consigna, preset, modo o musica, solo sobre las entidades de config.yaml
GET /api/usuario/{id}     → lo de cada uno: su trayecto
GET /api/usuarios         → avatares de la pantalla de bloqueo y ajustes de pantalla
GET /api/salud            → estado de cada fuente (para depurar)
"""
from __future__ import annotations

import hmac
import logging
import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from . import calendarios, config, demo, energy, house, menu, reminders, sources
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
    state["extra"] = demo if DEMO else calendarios.Extra(client)
    state["reminders"] = reminders.Store()
    state["menu"] = menu.Store()
    if DEMO and not state["reminders"].lists:
        state["reminders"].lists = demo.reminders()
    state["car"] = Cached("coche", 2 * 60, src.car if src else lambda: sources.car(ha))
    state["commute"] = {}
    async def _consumption():
        prices = (await state["prices"].get())["data"] or []
        return await (demo.consumption(prices) if DEMO else sources.consumption(ha, prices))
    state["consumption"] = Cached("consumo", 30, _consumption)
    state["house"] = Cached("casa", 20, (lambda: demo.house()) if DEMO else (lambda: sources.house(ha)))
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


def _lists() -> list[dict]:
    """Las listas de Recordatorios, con lo pasado a la compra desde el panel que aún no ha vuelto del iPhone."""
    return state["menu"].merge_into(state["reminders"].view(config.reminder_lists()))


def _check_token(given: str | None) -> None:
    expected = config.panel_token()
    if not expected:
        raise HTTPException(503, "Falta PANEL_TOKEN en .env")
    if not given or not hmac.compare_digest(given, expected):
        raise HTTPException(401, "Token incorrecto")


@app.get("/api/hogar")
async def home():
    return {
        "ahora": datetime.now(config.zone()).isoformat(timespec="seconds"),
        "tiempo": await state["weather"].get(),
        "luz": _energy_view(await state["prices"].get()),
        "calendario": await state["calendar"].get(),
        "calendarios_extra": {"data": (await state["extra"].get())["data"], "stale": False, "error": None},
        "recordatorios": {"data": _lists(), "stale": False, "error": None},
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


@app.get("/api/casa")
async def home_house():
    return await state["house"].get()


@app.get("/api/consumo")
async def home_consumption():
    return await state["consumption"].get()


@app.post("/api/casa/{action}")
async def house_command(action: str, request: Request):
    try:
        body = await request.json()
    except ValueError:
        raise HTTPException(400, "El cuerpo no es JSON")
    entity = body.get("entidad") if isinstance(body, dict) else None
    try:
        if DEMO:
            demo.house_command(action, body)
        else:
            states = {entity: await state["ha"].state(entity)} if entity in house.climate_entities() else {}
            domain, service, data = house.command(action, body, states)
            await state["ha"].call(domain, service, data)
            await asyncio.sleep(1.5)  # que Home Assistant recoja el cambio antes de volver a leer
    except ValueError as e:
        raise HTTPException(400, str(e))
    state["house"].invalidate()
    return await state["house"].get()


@app.get("/api/salud")
async def health():
    out = {}
    for key in ("weather", "prices", "calendar", "car", "house", "consumption"):
        c = await state[key].get()
        out[key] = {"ok": not c["stale"] and c["data"] is not None, "error": c["error"], "updated": c["updated"]}
    out["recordatorios"] = {l["nombre"]: {"elementos": len(l["items"]), "updated": l["updated"]}
                            for l in state["reminders"].view(config.reminder_lists())}
    out["menu_a_la_compra"] = state["menu"].status()
    out["calendarios_extra"] = (await state["extra"].get())["fuentes"]
    return out


@app.post("/api/recordatorios")
async def push_reminders(request: Request, x_panel_token: str | None = Header(default=None)):
    _check_token(x_panel_token)
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(400, "El cuerpo no es JSON")
    try:
        updated = state["reminders"].update(payload)
    except ValueError as e:
        raise HTTPException(400, str(e))
    if menu.shopping_list_name() in updated:
        [shop] = state["reminders"].view([menu.shopping_list_name()])
        state["menu"].shopping_list_arrived([i["titulo"] for i in shop["items"]])
    unknown = [n for n in updated if n not in config.reminder_lists()]
    return {"ok": True, "actualizadas": updated,
            "aviso": f"Listas que el panel no enseña (añádelas en config.yaml): {', '.join(unknown)}" if unknown else None}


@app.post("/api/recordatorios/recoger")
async def collect_pending(x_panel_token: str | None = Header(default=None)):
    """Para el Atajo: lo que hay que añadir a Recordatorios antes de enviar la lista."""
    _check_token(x_panel_token)
    items = state["menu"].collect()
    return {"lista": menu.shopping_list_name(), "items": items, "texto": "\n".join(items)}


def _week(semana) -> date:
    try:
        offset = max(0, min(1, int(semana)))
    except (TypeError, ValueError):
        raise HTTPException(400, "«semana» es 0 (esta) o 1 (la siguiente)")
    return menu.monday(datetime.now(config.zone()).date()) + timedelta(weeks=offset)


def _menu_view(week) -> dict:
    name = menu.shopping_list_name()
    titles = [i["titulo"] for l in _lists() if l["nombre"] == name for i in l["items"]]
    return menu.week_view(week, state["menu"], titles)


@app.get("/api/menu")
async def weekly_menu(semana: int = 0):
    return _menu_view(_week(semana))


@app.post("/api/menu/compra")
async def menu_to_shopping(request: Request):
    try:
        body = await request.json()
        week, clave = _week(body.get("semana", 0)), str(body["clave"])
    except (ValueError, KeyError, AttributeError):
        raise HTTPException(400, "Se esperaba {semana, clave}")
    item = next((i for s in menu.shopping(menu.plan(week)) for i in s["items"] if i["clave"] == clave), None)
    if item is None:
        raise HTTPException(404, "Ese ingrediente no está en el menú de esa semana")
    state["menu"].toggle(week.isoformat(), item)
    return _menu_view(week)


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
