"""La casa: calefacción (Netatmo), aire acondicionado (Daikin), temperaturas de las estancias y la música del Echo.

Es la única parte del panel que da órdenes a Home Assistant. Para que la tablet no pueda hacer cualquier cosa:
- solo se aceptan las entidades que están en config.yaml (sección «casa»);
- solo estas órdenes: consigna, preset y modo de un climate.*, y reproducir, pausar, saltar y volumen del Echo;
- la consigna se ajusta a los límites y al paso que da la propia entidad, y los modos y presets tienen que estar
  tanto en config.yaml como en la entidad.
"""
from __future__ import annotations

from . import config

MODE_NAMES = {"off": "Apagado", "heat": "Calor", "cool": "Frío", "heat_cool": "Auto", "auto": "Auto",
              "fan_only": "Ventilador", "dry": "Seco"}
PRESET_NAMES = {"schedule": "Programa", "away": "Fuera", "boost": "Boost", "frost_guard": "Antihielo",
                "none": "Normal", "comfort": "Confort", "eco": "Eco", "home": "Casa", "sleep": "Noche"}
MUSIC_ACTIONS = {"play_pause": "media_play_pause", "next": "media_next_track", "previous": "media_previous_track"}


def cfg() -> dict:
    return config.load().get("casa") or {}


def _modes(values) -> list[str]:
    # YAML lee «off» sin comillas como False: se vuelve a «off»
    return [("off" if v is False else "on" if v is True else str(v)) for v in values]


def _named(items) -> list[dict]:
    """Admite «- climate.x» o «- {entidad: climate.x, nombre: X}»."""
    out = []
    for it in items or []:
        out.append({"entidad": it, "nombre": None} if isinstance(it, str) else {"entidad": it["entidad"], "nombre": it.get("nombre")})
    return out


def entities() -> list[str]:
    c = cfg()
    heat = c.get("calefaccion") or {}
    ids = []
    if heat.get("termostato"):
        ids.append(heat["termostato"])
    ids += [v["entidad"] for v in _named(heat.get("valvulas"))]
    ids += [a["entidad"] for a in _named((c.get("aire") or {}).get("equipos"))]
    ids += [t["entidad"] for t in _named(c.get("temperaturas"))]
    if (c.get("musica") or {}).get("entidad"):
        ids.append(c["musica"]["entidad"])
    return ids


def climate_entities() -> set[str]:
    return {e for e in entities() if e.startswith("climate.")}


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _climate(st: dict | None, name: str | None, allowed_modes=None, allowed_presets=None) -> dict | None:
    if not st:
        return None
    a = st.get("attributes", {})
    modes = [m for m in a.get("hvac_modes", []) if allowed_modes is None or m in allowed_modes]
    presets = [p for p in a.get("preset_modes") or [] if allowed_presets is None or p in allowed_presets]
    return {
        "entidad": st["entity_id"],
        "nombre": name or a.get("friendly_name"),
        "disponible": st.get("state") not in ("unavailable", "unknown"),
        "modo": st.get("state"),
        "accion": a.get("hvac_action"),  # heating / idle / cooling / off
        "actual": _num(a.get("current_temperature")),
        "consigna": _num(a.get("temperature")),
        "min": _num(a.get("min_temp")), "max": _num(a.get("max_temp")), "paso": _num(a.get("target_temp_step")) or 0.5,
        "preset": a.get("preset_mode"),
        "modos": [{"id": m, "nombre": MODE_NAMES.get(m, m)} for m in modes],
        "presets": [{"id": p, "nombre": (allowed_presets or {}).get(p) or PRESET_NAMES.get(p, p)} for p in presets],
    }


def build(states: dict[str, dict | None]) -> dict:
    """Lo que pinta la vista Casa a partir de los estados de Home Assistant."""
    c = cfg()
    heat = c.get("calefaccion") or {}
    presets = heat.get("presets") or {"schedule": "Programa", "away": "Fuera", "boost": "Boost", "frost_guard": "Antihielo"}
    out: dict = {}
    if heat.get("termostato"):
        out["calefaccion"] = {
            "nombre": heat.get("nombre", "Calefacción"),
            "termostato": _climate(states.get(heat["termostato"]), heat.get("nombre_termostato"), allowed_presets=presets),
            "valvulas": [v for v in (_climate(states.get(x["entidad"]), x["nombre"], allowed_presets=presets)
                                     for x in _named(heat.get("valvulas"))) if v],
        }
    aire = c.get("aire") or {}
    if aire.get("equipos"):
        modes = _modes(aire.get("modos") or ["off", "heat", "cool", "heat_cool"])
        out["aire"] = [v for v in (_climate(states.get(x["entidad"]), x["nombre"], allowed_modes=modes, allowed_presets={})
                                   for x in _named(aire["equipos"])) if v]
    temps = []
    for t in _named(c.get("temperaturas")):
        st = states.get(t["entidad"])
        if st:
            temps.append({"nombre": t["nombre"] or st["attributes"].get("friendly_name"), "temp": _num(st.get("state"))})
    if temps:
        out["temperaturas"] = temps
    music = c.get("musica") or {}
    st = states.get(music.get("entidad")) if music.get("entidad") else None
    if st:
        a = st.get("attributes", {})
        out["musica"] = {
            "nombre": music.get("nombre") or a.get("friendly_name"),
            "estado": st.get("state"),  # playing / paused / idle / unavailable
            "titulo": a.get("media_title"), "artista": a.get("media_artist"), "album": a.get("media_album_name"),
            "volumen": _num(a.get("volume_level")),
        }
    return out


def _round_step(value: float, step: float) -> float:
    return round(round(value / step) * step, 2)


def command(action: str, body: dict, states: dict[str, dict | None]) -> tuple[str, str, dict]:
    """Valida una orden de la tablet y la traduce a (dominio, servicio, datos) de Home Assistant.
    `states`: estado actual de la entidad afectada, para comprobar límites, modos y presets."""
    c = cfg()
    if action == "musica":
        entity = (c.get("musica") or {}).get("entidad")
        if not entity:
            raise ValueError("No hay altavoz configurado")
        what = body.get("accion")
        if what in MUSIC_ACTIONS:
            return "media_player", MUSIC_ACTIONS[what], {"entity_id": entity}
        if what == "volumen":
            level = _num(body.get("nivel"))
            if level is None:
                raise ValueError("Falta «nivel» (0 a 1)")
            return "media_player", "volume_set", {"entity_id": entity, "volume_level": round(min(1.0, max(0.0, level)), 2)}
        raise ValueError("Orden de música desconocida")

    entity = body.get("entidad")
    if entity not in climate_entities():
        raise ValueError("Esa entidad no está en la configuración de la casa")
    st = states.get(entity)
    if not st or st.get("state") in ("unavailable", "unknown"):
        raise ValueError("El equipo no está disponible ahora")
    a = st.get("attributes", {})

    if action == "consigna":
        value = _num(body.get("grados"))
        if value is None:
            raise ValueError("Falta «grados»")
        lo, hi = _num(a.get("min_temp")) or 7, _num(a.get("max_temp")) or 30
        value = _round_step(min(hi, max(lo, value)), _num(a.get("target_temp_step")) or 0.5)
        return "climate", "set_temperature", {"entity_id": entity, "temperature": value}

    if action == "preset":
        preset = body.get("preset")
        heat = c.get("calefaccion") or {}
        allowed = set((heat.get("presets") or {"schedule": 1, "away": 1, "boost": 1, "frost_guard": 1}).keys())
        if preset not in allowed or preset not in (a.get("preset_modes") or []):
            raise ValueError("Ese modo no está permitido")
        return "climate", "set_preset_mode", {"entity_id": entity, "preset_mode": preset}

    if action == "modo":
        mode = body.get("modo")
        allowed = set(_modes((c.get("aire") or {}).get("modos") or ["off", "heat", "cool", "heat_cool"]))
        if mode not in allowed or mode not in (a.get("hvac_modes") or []):
            raise ValueError("Ese modo no está permitido")
        return "climate", "set_hvac_mode", {"entity_id": entity, "hvac_mode": mode}

    raise ValueError("Orden desconocida")
