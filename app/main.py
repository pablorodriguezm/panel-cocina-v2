"""Panel de cocina: API de solo lectura para la tablet y la propia web.

GET  /api/hogar           → lo común: tiempo, luz (y si calentar con gas o aire), calendario (y festivos, F1 y fútbol),
                            recordatorios y coche
POST /api/recordatorios   → el Atajo del iPhone envía las listas de Recordatorios (cabecera X-Panel-Token)
POST /api/recordatorios/recoger → el Atajo recoge lo pasado a la compra desde el panel (cabecera X-Panel-Token)
GET  /api/menu?semana=0   → menú de la semana (0 esta, 1 la siguiente) y sus ingredientes
GET  /api/tv              → canales de la pestaña TV
GET  /api/tv/hls?u=…&s=…  → intermediario de vídeo: solo direcciones firmadas por el panel (?k=… si llevan la clave IPTV)
GET  /api/tv/iptv         → «Mi lista»: grupos y canales en directo de la lista IPTV privada
GET  /api/tv/iptv/{id}    → la emisión de un canal de «Mi lista» (sin que su dirección con la clave salga de aquí)
GET  /api/podcasts        → podcasts de Overcast: «para seguir» y tus podcasts (docs/PODCASTS.md)
GET  /api/podcasts/podcast?ruta=…  → capítulos de un podcast
GET  /api/podcasts/episodio/{id}   → audio y por dónde ibas de un capítulo
POST /api/podcasts/progreso        → guarda en Overcast por dónde vas {id, segundos, terminado}
POST /api/podcasts/fijar           → fija un podcast arriba de la lista o lo quita {ruta, fijado}
GET  /api/cocina          → temporizadores y estado del fogón (docs/COCINA.md)
POST /api/cocina/temporizadores            → nuevo temporizador {minutos, nombre}
POST /api/cocina/temporizadores/{id}/sumar → suma minutos {minutos}
DELETE /api/cocina/temporizadores/{id}     → lo quita (o lo para si está sonando)
POST /api/cocina/fogon/visto               → la tablet deja de sonar por el aviso actual del fogón
POST /api/copias/ok       → el stack «copias» avisa de que la copia de seguridad ha terminado (X-Panel-Token)
POST /api/menu/cambiar    → cambia la comida o la cena de un día por otro plato del mismo tipo
POST /api/menu/compra     → pasa un ingrediente del menú a la compra (o lo quita si el Atajo aún no lo ha recogido)
GET  /api/casa            → calefacción, aire, temperaturas y música
GET  /api/consumo         → potencia de ahora, por aparato y consumo de hoy por horas
POST /api/casa/{orden}    → consigna, preset, modo, corriente o musica, solo sobre las entidades de config.yaml
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
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

import asyncio

from . import aire, avisos, calefaccion, calendarios, cocina, config, copias, iptv, podcasts, tv, demo, energy, house, menu, reminders, shelly, sources
from .cache import Cached

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
# httpx apunta cada dirección que pide, con su token o clave dentro (Shelly, IPTV): fuera del registro
logging.getLogger("httpx").setLevel(logging.WARNING)
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
    state["backups"] = copias.Store()
    state["tv"] = tv.TV(client)
    state["iptv"] = iptv.IPTV(client, state["tv"])
    state["podcasts"] = podcasts.Overcast()
    if DEMO and not state["reminders"].lists:
        state["reminders"].lists = demo.reminders()
    state["car"] = Cached("coche", 2 * 60, src.car if src else lambda: sources.car(ha))
    state["commute"] = {}
    async def _consumption():
        prices = (await state["prices"].get())["data"] or []
        return await (demo.consumption(prices) if DEMO else sources.consumption(ha, prices))
    state["consumption"] = Cached("consumo", 30, _consumption)
    # Sensores de temperatura exterior para «¿gas o aire?» (estados crudos; los combina app/calefaccion.py)
    async def _outdoor():
        ids = [s["entidad"] for s in calefaccion.cfg().get("sensores_exterior") or [] if isinstance(s, dict) and s.get("entidad")]
        if DEMO:
            return demo.outdoor_states(ids)
        return list((await ha.states(ids)).items()) if ids else []
    state["outdoor"] = Cached("exterior", 5 * 60, _outdoor)
    state["house"] = Cached("casa", 20, (lambda: demo.house()) if DEMO else (lambda: sources.house(ha)))
    # Consumo real del aire (circuito de climatización): cada 10 minutos
    state["air_store"] = aire.Store()
    async def _air():
        if DEMO:
            return demo.air_real()
        return await sources.air_real(ha, client, state["air_store"], (await state["prices"].get())["data"] or [],
                                      (await state["weather"].get())["data"])
    state["air"] = Cached("aire", 10 * 60, _air)
    # Precio de cada hora a la «Tarifa en vivo» de Shelly Cloud (solo con SHELLY_TARIFA_URL y fuera de la demo)
    async def _prices():
        return (await state["prices"].get())["data"] or []
    state["shelly"] = shelly.Sender(client, _prices)
    task = asyncio.create_task(state["shelly"].run()) if shelly.url() and not DEMO else None
    # Temporizadores y fogón olvidado: cada 30 s, también con la tablet bloqueada (en la demo, sin Home Assistant)
    state["kitchen"] = cocina.Kitchen(None if DEMO else ha)
    kitchen_task = asyncio.create_task(state["kitchen"].run())
    yield
    kitchen_task.cancel()
    if task:
        task.cancel()
    await client.aclose()


app = FastAPI(title="Panel de cocina", lifespan=lifespan, docs_url=None, redoc_url=None)


async def _heating() -> dict:
    """¿Gas o aire? Con el precio de la luz y la previsión del tiempo que ya tiene el panel."""
    prices, weather = await state["prices"].get(), await state["weather"].get()
    now = datetime.now(config.zone())
    internet = ((weather["data"] or {}).get("current") or {}).get("temperature_2m")
    sensors = (await state["outdoor"].get())["data"] or []
    outdoor = calefaccion.combine_outdoor(internet, calefaccion.sensor_readings(dict(sensors), now))
    data = calefaccion.forecast(prices["data"] or [], weather["data"], now, outdoor)
    if data:
        data["real"] = (await state["air"].get())["data"]
    return {"data": data, "stale": prices["stale"] or weather["stale"], "error": None}


def _energy_view(cached: dict, car: dict | None = None) -> dict:
    prices = cached["data"] or []
    now = datetime.now(config.zone()).replace(tzinfo=None)
    recs = config.load()["energia"]["recomendaciones"]
    c = config.load().get("coche") or {}
    need = energy.car_need(car, float(c.get("bateria_kwh", 75)), float(c.get("eficiencia_carga", 0.9)))
    return {**cached, "data": energy.summary(prices, now, recs, holidays=calendarios.national_holidays(),
                                             tax_factor=calefaccion.electricity_with_taxes(1.0), car=need) if prices else None}


@app.get("/api/usuarios")
async def users():
    pantalla = config.load().get("pantalla") or {}
    mode = str(pantalla.get("modo_oscuro", "auto")).lower()
    return {"usuarios": config.public_users(), "volver_al_bloqueo_s": int(pantalla.get("volver_al_bloqueo_s", 120)),
            "modo_oscuro": mode if mode in ("auto", "siempre", "nunca") else "auto"}


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
        "luz": _energy_view(await state["prices"].get(), (await state["car"].get())["data"]),
        "calefaccion": await _heating(),
        "calendario": await state["calendar"].get(),
        "calendarios_extra": {"data": (await state["extra"].get())["data"], "stale": False, "error": None},
        "recordatorios": {"data": _lists(), "stale": False, "error": None},
        "coche": await state["car"].get(),
        "avisos": await _alerts(),
    }


async def _alerts() -> list[dict]:
    return avisos.build(datetime.now(config.zone()),
                        sources={k: await state[k].get() for k in avisos.NOMBRES},
                        extra=(await state["extra"].get())["fuentes"],
                        lists=state["reminders"].view(config.reminder_lists()),
                        shelly=state["shelly"].status, backups=state["backups"].status(),
                        iptv=state["iptv"].status(), kitchen=state["kitchen"].health(),
                        podcasts=state["podcasts"].status())


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
            states = await state["ha"].states([entity]) if entity in house.climate_entities() else {}
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
    gas_warning = calefaccion.stale_gas_price(datetime.now(config.zone()).date())
    out["precio_gas"] = {"ok": gas_warning is None, "error": gas_warning}
    out["shelly_tarifa"] = state["shelly"].status
    out["copias"] = state["backups"].status()
    out["tv_mi_lista"] = state["iptv"].status()
    out["cocina"] = state["kitchen"].health()
    out["podcasts"] = state["podcasts"].status()
    out["avisos"] = await _alerts()
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


@app.get("/api/tv")
async def tv_channels():
    """Los canales de la pestaña TV, con su emisión (a través del intermediario), su reproductor incrustado o su web."""
    await state["tv"].refresh()
    return {"canales": state["tv"].channels(), "error": state["tv"].list_error, "mi_lista": state["iptv"].configured,
            "podcasts": state["podcasts"].configured}


def _podcasts():
    if not state["podcasts"].configured:
        raise HTTPException(404, "Sin podcasts: faltan OVERCAST_EMAIL y OVERCAST_CLAVE")
    return state["podcasts"]


@app.get("/api/podcasts")
async def podcasts_library():
    return await _podcasts().library()


@app.get("/api/podcasts/podcast")
async def podcasts_feed(ruta: str):
    try:
        return {"ruta": ruta, "capitulos": await _podcasts().feed(ruta)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except (httpx.HTTPError, podcasts.NotLoggedIn) as e:
        state["podcasts"]._fail(e)
        raise HTTPException(502, state["podcasts"].error)


@app.get("/api/podcasts/episodio/{episode_id}")
async def podcasts_episode(episode_id: str):
    try:
        return await _podcasts().episode(episode_id)
    except ValueError as e:
        state["podcasts"]._fail(e)
        raise HTTPException(400 if "desconocido" in str(e) else 502, str(e))
    except (httpx.HTTPError, podcasts.NotLoggedIn) as e:
        state["podcasts"]._fail(e)
        raise HTTPException(502, state["podcasts"].error)


@app.post("/api/podcasts/fijar")
async def podcasts_pin(body: dict):
    try:
        return {"fijados": _podcasts().pin(str(body.get("ruta") or ""), bool(body.get("fijado", True)))}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/podcasts/progreso")
async def podcasts_progress(body: dict):
    try:
        v = await _podcasts().progress(str(body.get("id")), float(body.get("segundos") or 0), bool(body.get("terminado")))
    except KeyError:
        raise HTTPException(404, "Ese capítulo no se ha abierto en el panel")
    except (TypeError, ValueError):
        raise HTTPException(400, "Se esperaba {id, segundos, terminado}")
    except (httpx.HTTPError, podcasts.NotLoggedIn) as e:
        state["podcasts"]._fail(e)
        raise HTTPException(502, state["podcasts"].error)
    return {"ok": True, "version": v}


@app.get("/api/tv/iptv")
async def tv_my_list():
    """«Mi lista»: grupos y canales en directo de la lista IPTV privada (sin sus direcciones)."""
    if not state["iptv"].configured:
        raise HTTPException(404, "Sin lista IPTV: faltan IPTV_SERVIDOR, IPTV_USUARIO e IPTV_CLAVE")
    await state["iptv"].refresh()
    return state["iptv"].listing()


@app.get("/api/tv/iptv/{stream_id}")
async def tv_my_list_stream(stream_id: int):
    """La emisión de un canal de «Mi lista», a través del intermediario."""
    url = state["iptv"].stream_url(stream_id)
    if not url:
        raise HTTPException(404, "Canal desconocido")
    if not state["tv"].public(url):  # el servidor de la lista tampoco puede estar en la red de casa
        raise HTTPException(403, "Dirección no permitida")
    return await _tv_send(url)


@app.get("/api/tv/hls")
async def tv_proxy(u: str | None = None, s: str | None = None, k: str | None = None):
    """Intermediario de vídeo: solo direcciones que ha dado el propio panel (firmadas o cifradas, ver app/tv.py)."""
    if k:
        url = state["tv"].unhide(k)
        if not url:
            raise HTTPException(403, "Dirección no válida")
        if not state["tv"].public(url):
            raise HTTPException(403, "Dirección no permitida")
    elif u:
        url = u
        if not state["tv"].permitted(url, s):
            raise HTTPException(403, "Dirección no permitida")
    else:
        raise HTTPException(400, "Falta la dirección")
    return await _tv_send(url)


async def _tv_send(u: str):
    log = logging.getLogger("panel.tv")
    where = state["tv"].redact(u)[:200]  # sin la clave de la lista IPTV
    try:
        body, ctype = await state["tv"].fetch(u)
    except PermissionError as e:
        log.warning("TV: %s → %s", where, e)
        raise HTTPException(403, str(e))
    except httpx.HTTPStatusError as e:
        final = state["tv"].redact(str(e.request.url))[:200]
        log.warning("TV: %s → la cadena responde %s (%s)", where, e.response.status_code, final)
        raise HTTPException(502, f"La cadena responde {e.response.status_code}")
    except httpx.HTTPError as e:
        log.warning("TV: %s → la cadena no responde: %s %s", where, e.__class__.__name__, state["tv"].redact(str(e))[:200])
        raise HTTPException(502, f"La cadena no responde: {e.__class__.__name__}")
    headers = {"Cache-Control": "no-store"}
    if isinstance(body, str):
        return Response(body, media_type=ctype, headers=headers)

    async def chunks():
        try:
            async for part in body.aiter_bytes():
                yield part
        finally:
            await body.aclose()
    return StreamingResponse(chunks(), media_type=ctype, headers=headers)


@app.get("/api/cocina")
async def kitchen_view():
    return state["kitchen"].view()


@app.post("/api/cocina/temporizadores")
async def kitchen_add_timer(body: dict):
    try:
        state["kitchen"].add_timer(float(body.get("minutos")), body.get("nombre"))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e) or "Se esperaba {minutos, nombre}")
    return state["kitchen"].view()


@app.post("/api/cocina/temporizadores/{timer_id}/sumar")
async def kitchen_add_time(timer_id: str, body: dict):
    try:
        state["kitchen"].add_time(timer_id, float(body.get("minutos", 1)))
    except KeyError:
        raise HTTPException(404, "No existe ese temporizador")
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))
    return state["kitchen"].view()


@app.delete("/api/cocina/temporizadores/{timer_id}")
async def kitchen_remove_timer(timer_id: str):
    try:
        state["kitchen"].remove_timer(timer_id)
    except (KeyError, ValueError):
        raise HTTPException(404, "No existe ese temporizador")
    return state["kitchen"].view()


@app.post("/api/cocina/fogon/visto")
async def kitchen_seen():
    state["kitchen"].mark_seen()
    return state["kitchen"].view()


@app.post("/api/copias/ok")
async def backup_done(x_panel_token: str | None = Header(default=None)):
    """El stack «copias» avisa de que la copia de seguridad de esta noche ha terminado bien."""
    _check_token(x_panel_token)
    state["backups"].ok()
    return {"ok": True}


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
    item = next((i for s in menu.shopping(state["menu"].plan(week)) for i in s["items"] if i["clave"] == clave), None)
    if item is None:
        raise HTTPException(404, "Ese ingrediente no está en el menú de esa semana")
    state["menu"].toggle(week.isoformat(), item)
    return _menu_view(week)


@app.post("/api/menu/cambiar")
async def menu_swap(request: Request):
    """Cambia la comida o la cena de un día (de esta semana o la siguiente) por otro plato del mismo tipo."""
    try:
        body = await request.json()
        fecha, meal = date.fromisoformat(str(body["fecha"])), str(body["momento"])
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(400, "Se esperaba {fecha, momento}")
    today = datetime.now(config.zone()).date()
    if meal not in menu.TOMAS or not 0 <= (menu.monday(fecha) - menu.monday(today)).days <= 7:
        raise HTTPException(400, "Solo la comida o la cena de esta semana o la siguiente")
    if not state["menu"].swap(fecha, meal):
        raise HTTPException(409, "No hay otro plato de ese tipo esta semana")
    return _menu_view(menu.monday(fecha))


@app.get("/")
async def index():
    return FileResponse(WEB / "index.html")


app.mount("/", StaticFiles(directory=WEB), name="web")
