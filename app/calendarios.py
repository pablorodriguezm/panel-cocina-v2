"""Calendarios extra que solo enseña el panel: festivos de Madrid, Fórmula 1 y partidos de fútbol.

No pasan por Home Assistant ni se escriben en el calendario de Apple: el panel los descarga él solo de fuentes
públicas y los mezcla con el de «RIM Y PABLO» en Hoy y Calendario, cada uno con su color.

- Festivos: app/festivos.yaml (BOE, BOCM y Ayuntamiento de Madrid). Hay que añadir cada año.
- Fórmula 1: API pública Jolpica (la continuación de Ergast), todas las sesiones de cada Gran Premio.
- Equipos: un calendario .ics público por equipo (todas las competiciones). Si juegan entre ellos, sale una vez.

En config.yaml (opcional; sin la sección, todo activado con Real Madrid y Barça):

    calendarios_extra:
      festivos: true
      f1: true
      equipos:
        - {nombre: Real Madrid, ics: https://ics.fixtur.es/v2/real-madrid.ics, color: "#7A5BC2"}
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import yaml

from . import config
from .cache import Cached

FESTIVOS = Path(__file__).with_name("festivos.yaml")
JOLPICA = "https://api.jolpi.ca/ergast/f1/{year}.json"
TIMEOUT = httpx.Timeout(20.0, connect=5.0)
UTC = ZoneInfo("UTC")

COLOR_FESTIVO = "#C8243B"
COLOR_F1 = "#1F1F27"
EQUIPOS = [
    {"nombre": "Real Madrid", "ics": "https://ics.fixtur.es/v2/real-madrid.ics", "color": "#7A5BC2"},
    {"nombre": "Barça", "ics": "https://ics.fixtur.es/v2/fc-barcelona.ics", "color": "#004D98"},
]
AMBITO = {"nacional": "Festivo nacional", "comunidad": "Festivo de la Comunidad de Madrid", "local": "Festivo local de Madrid"}

# Sesiones de un Gran Premio en la API: clave, nombre y duración aproximada en minutos
SESIONES_F1 = [
    ("FirstPractice", "Libres 1", 60), ("SecondPractice", "Libres 2", 60), ("ThirdPractice", "Libres 3", 60),
    ("SprintQualifying", "Clasificación sprint", 45), ("SprintShootout", "Clasificación sprint", 45),
    ("Sprint", "Sprint", 60), ("Qualifying", "Clasificación", 60),
]


def cfg() -> dict:
    c = config.load().get("calendarios_extra")
    return c if isinstance(c, dict) else {}


def teams() -> list[dict]:
    t = cfg().get("equipos", EQUIPOS)
    return [x for x in (t or []) if isinstance(x, dict) and x.get("ics")]


def window(now: datetime) -> tuple[datetime, datetime]:
    """Lo que enseña el panel: desde el lunes de esta semana, tres semanas."""
    start = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=now.weekday())
    return start, start + timedelta(days=21)


def _event(title: str, start: datetime | date, end: datetime | date | None, *, calendario: str, color: str,
           location: str | None = None, description: str | None = None) -> dict:
    all_day = not isinstance(start, datetime)
    fmt = (lambda d: d.isoformat()) if all_day else (lambda d: d.isoformat(timespec="minutes"))
    return {"title": title, "start": fmt(start), "end": fmt(end) if end else None, "all_day": all_day,
            "location": location or None, "description": description or None, "calendario": calendario, "color": color}


def _inside(ev: dict, start: datetime, end: datetime) -> bool:
    s = ev["start"]
    if ev["all_day"]:
        return start.date().isoformat() <= s < end.date().isoformat()
    return start <= datetime.fromisoformat(s) < end


# ---------- Festivos ----------

@lru_cache
def holidays_file() -> dict:
    with FESTIVOS.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def holidays(start: datetime, end: datetime) -> list[dict]:
    out = []
    for year in range(start.year, end.year + 1):
        for h in holidays_file().get(str(year)) or []:
            d = h["fecha"] if isinstance(h["fecha"], date) else date.fromisoformat(str(h["fecha"]))
            ev = _event(h["nombre"], d, d + timedelta(days=1), calendario="Festivos", color=COLOR_FESTIVO,
                        description=AMBITO.get(h.get("ambito"), "Festivo"))
            ev["festivo"] = True
            if _inside(ev, start, end):
                out.append(ev)
    return out


def missing_holiday_years(now: datetime) -> list[int]:
    """Años que el panel enseña y que aún no están en festivos.yaml (para /api/salud)."""
    start, end = window(now)
    return [y for y in range(start.year, end.year + 1) if str(y) not in holidays_file()]


# ---------- Fórmula 1 ----------

def _at(d: str, t: str | None) -> datetime | date:
    if not t:
        return date.fromisoformat(d)
    return datetime.fromisoformat(f"{d}T{t.replace('Z', '+00:00')}")


def f1_from_jolpica(data: dict, zone: ZoneInfo) -> list[dict]:
    out = []
    for race in data.get("MRData", {}).get("RaceTable", {}).get("Races", []):
        gp = race.get("raceName", "Gran Premio").replace(" Grand Prix", " GP")
        c = race.get("Circuit", {})
        loc = c.get("Location", {})
        place = ", ".join(x for x in (c.get("circuitName"), loc.get("locality"), loc.get("country")) if x)
        sessions = [(key, name, mins) for key, name, mins in SESIONES_F1 if race.get(key)]
        for key, name, mins in sessions + [("", "Carrera", 120)]:
            s = race[key] if key else {"date": race["date"], "time": race.get("time")}
            start = _at(s["date"], s.get("time"))
            if isinstance(start, datetime):
                start = start.astimezone(zone)
                end = start + timedelta(minutes=mins)
            else:
                end = start + timedelta(days=1)
            out.append(_event(f"🏎️ {name} · {gp}", start, end, calendario="Fórmula 1", color=COLOR_F1, location=place))
    return out


# ---------- Calendarios .ics ----------

def _unescape(v: str) -> str:
    return v.replace("\\n", "\n").replace("\\N", "\n").replace("\\,", ",").replace("\\;", ";").replace("\\\\", "\\")


def _ics_time(value: str, params: dict, zone: ZoneInfo) -> datetime | date:
    if params.get("VALUE") == "DATE" or len(value) == 8:
        return datetime.strptime(value[:8], "%Y%m%d").date()
    naive = datetime.strptime(value.rstrip("Z")[:15], "%Y%m%dT%H%M%S")
    if value.endswith("Z"):
        return naive.replace(tzinfo=UTC).astimezone(zone)
    try:
        tz = ZoneInfo(params["TZID"]) if "TZID" in params else zone
    except (KeyError, ValueError):
        tz = zone
    return naive.replace(tzinfo=tz).astimezone(zone)


def parse_ics(text: str, zone: ZoneInfo, *, calendario: str, color: str) -> list[dict]:
    """Lo justo de iCalendar (RFC 5545) para leer partidos: VEVENT con SUMMARY, DTSTART, DTEND, LOCATION y
    DESCRIPTION. Las líneas largas vienen partidas (una línea que empieza por espacio sigue a la anterior)."""
    lines: list[str] = []
    for raw in text.replace("\r\n", "\n").split("\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        elif raw:
            lines.append(raw)
    out, cur = [], None
    for line in lines:
        if line == "BEGIN:VEVENT":
            cur = {}
        elif line == "END:VEVENT" and cur is not None:
            if "DTSTART" in cur and "SUMMARY" in cur:
                start = _ics_time(*cur["DTSTART"], zone)
                end = _ics_time(*cur["DTEND"], zone) if "DTEND" in cur else None
                if end is None and isinstance(start, datetime):
                    end = start + timedelta(hours=2)
                get = lambda k: _unescape(cur[k][0]).strip() if k in cur else None  # noqa: E731
                out.append(_event(get("SUMMARY"), start, end, calendario=calendario, color=color,
                                  location=get("LOCATION"), description=get("DESCRIPTION")))
            cur = None
        elif cur is not None and ":" in line:
            head, value = line.split(":", 1)
            name, *params = head.split(";")
            cur[name.upper()] = (value, dict(p.split("=", 1) for p in params if "=" in p))
    return out


def _words(title: str) -> set[str]:
    t = unicodedata.normalize("NFD", title.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    return {w for w in re.findall(r"[a-z0-9]+", t) if len(w) > 2 and w not in {"vs", "the"}}


def dedupe_matches(events: list[dict]) -> list[dict]:
    """El mismo partido en los dos calendarios (Real Madrid - Barcelona) sale una vez: misma hora y al menos dos
    palabras en común en el título. Partidos distintos a la misma hora (última jornada) no comparten palabras."""
    out: list[dict] = []
    for ev in events:
        if not any(o["start"] == ev["start"] and len(_words(o["title"]) & _words(ev["title"])) >= 2 for o in out):
            out.append(ev)
    return out


# ---------- Todo junto ----------

class Extra:
    """Una caché por fuente: si una falla, las demás se siguen viendo (y la que falla, con su última copia)."""

    def __init__(self, client: httpx.AsyncClient):
        self.client = client
        self.sources: dict[str, Cached] = {}

    def _source(self, key: str, max_age: int, fetch) -> Cached:
        if key not in self.sources:
            self.sources[key] = Cached(key, max_age, fetch)
        return self.sources[key]

    async def _f1(self) -> list[dict]:
        now = datetime.now(config.zone())
        out = []
        for year in sorted({now.year, window(now)[1].year}):
            r = await self.client.get(JOLPICA.format(year=year), timeout=TIMEOUT)
            r.raise_for_status()
            out += f1_from_jolpica(r.json(), config.zone())
        return out

    def _team(self, team: dict):
        async def fetch() -> list[dict]:
            r = await self.client.get(team["ics"], timeout=TIMEOUT, follow_redirects=True)
            r.raise_for_status()
            return parse_ics(r.text, config.zone(), calendario=team.get("nombre", "Fútbol"),
                             color=team.get("color", "#2E9E5B"))
        return fetch

    async def get(self) -> dict:
        now = datetime.now(config.zone())
        start, end = window(now)
        c = cfg()
        events, status = [], {}
        if c.get("festivos", True):
            events += holidays(start, end)
            missing = missing_holiday_years(now)
            status["festivos"] = {"ok": not missing, "error": f"Faltan los festivos de {missing} en app/festivos.yaml" if missing else None}
        blocks = []
        if c.get("f1", True):
            blocks.append(("Fórmula 1", await self._source("f1", 6 * 3600, self._f1).get()))
        matches = []
        for t in teams():
            block = await self._source(f"equipo:{t['ics']}", 3 * 3600, self._team(t)).get()
            blocks.append((t.get("nombre", t["ics"]), block))
            matches += [e for e in (block["data"] or []) if _inside(e, start, end)]
        for name, block in blocks:
            status[name] = {"ok": block["data"] is not None and not block["stale"], "error": block["error"], "updated": block["updated"]}
            if name == "Fórmula 1":
                events += [e for e in (block["data"] or []) if _inside(e, start, end)]
        events += dedupe_matches(sorted(matches, key=lambda e: e["start"]))
        return {"data": sorted(events, key=lambda e: e["start"]), "fuentes": status}
