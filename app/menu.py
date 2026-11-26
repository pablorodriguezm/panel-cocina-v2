"""Menú semanal saludable y la lista de sus ingredientes.

- Por defecto («menu.modo: planes») sigue tal cual los planes nutricionales de app/planes.yaml, uno cada semana y
  por turnos, con sus cinco tomas: desayuno, media mañana, comida, merienda y cena.
- Con «menu.modo: recetario», comida y cena salen del recetario (app/recetario.yaml) con un plan fijo de grupos por
  día, para que la semana quede equilibrada: legumbre tres veces, pescado unas tres, huevo dos, carne roja una… Qué
  receta toca de cada grupo se elige al azar con la semana como semilla: el mismo menú para los dos y tras un
  reinicio, sin guardar nada.
- Cada plato se puede cambiar a mano por otro del mismo grupo (Store.swap).
- Solo se enseña en el panel (Hoy, Calendario y Tareas): no se escribe en el calendario de Apple.
- Los ingredientes de la semana se suman y se pueden pasar a la lista de la compra tocándolos. Lo pasado queda
  «pendiente» en el panel (sale ya en la Compra) hasta que el Atajo lo recoge (`POST /api/recordatorios/recoger`),
  lo añade a Recordatorios y vuelve a enviar la lista. Si en ese envío no viene, se vuelve a ofrecer.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
import time
import unicodedata
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from . import config

RECETARIO = Path(__file__).with_name("recetario.yaml")
PLANES = Path(__file__).with_name("planes.yaml")
DATA_PATH = Path(os.environ.get("PANEL_DATA", "/data")) / "menu.json"

# Grupo de cada día, de lunes a domingo
COMIDAS = ["legumbre", "pescado", "carne_blanca", "legumbre", "cereal", "legumbre", "carne_roja"]
CENAS = ["verdura", "huevo", "pescado", "carne_blanca", "pescado", "huevo", "verdura"]

# Las tomas del día, en orden. En modo recetario solo hay comida y cena.
TOMAS = ["desayuno", "media_manana", "comida", "merienda", "cena"]
GRUPOS_TOMAS = {"desayuno", "tentempie"}  # grupos de desayuno, media mañana y merienda
LIBRE = "libre"

SECCIONES = ["Fruta y verdura", "Pescadería", "Carnicería", "Huevos y lácteos", "Panadería", "Despensa", "Congelados"]
PLURAL = {"diente": "dientes", "lata": "latas", "manojo": "manojos", "barra": "barras"}


def cfg() -> dict:
    c = config.load().get("menu")
    return c if isinstance(c, dict) else {}


def personas() -> int:
    try:
        return max(1, int(cfg().get("personas", 2)))
    except (TypeError, ValueError):
        return 2


def shopping_list_name() -> str:
    lists = config.reminder_lists()
    return str(cfg().get("lista_compra") or (lists[0] if lists else "Compra"))


@lru_cache
def recetario() -> dict:
    with RECETARIO.open(encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return {"basicos": data.get("basicos") or [], "recetas": data.get("recetas") or []}


@lru_cache
def planes() -> dict:
    try:
        with PLANES.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    except OSError:
        data = {}
    return {"desde": data.get("desde") or date(2026, 11, 23), "planes": data.get("planes") or []}


def mode() -> str:
    """«planes» (los planes nutricionales por turnos, por defecto) o «recetario» (comida y cena sorteadas)."""
    return "recetario" if cfg().get("modo") == "recetario" or not planes()["planes"] else "planes"


def week_plan(week: date) -> dict | None:
    """El plan nutricional de esa semana: por turnos desde la semana de «desde» (o «menu.planes_desde»)."""
    if mode() != "planes":
        return None
    start = cfg().get("planes_desde") or planes()["desde"]
    if isinstance(start, str):
        start = date.fromisoformat(start)
    all_plans = planes()["planes"]
    return all_plans[((monday(week) - monday(start)).days // 7) % len(all_plans)]


def norm(s: str) -> str:
    """Minúsculas y sin tildes, para comparar nombres."""
    s = unicodedata.normalize("NFD", str(s).strip().lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn")


def monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _main(recipe: dict) -> str:
    """El ingrediente principal (el primero): que no salga pavo dos días seguidos aunque sean platos distintos."""
    ings = recipe.get("ingredientes") or [{}]
    return "main:" + norm(ings[0].get("nombre", ""))


def _pick(rng: random.Random, pool: list[dict], used: set[str]) -> dict | None:
    """Una receta del grupo que no haya salido esta semana, a ser posible con otro ingrediente principal."""
    fresh = [r for r in pool if r["id"] not in used]
    varied = [r for r in fresh if _main(r) not in used]
    choice = rng.choice(varied or fresh or pool) if pool else None
    if choice:
        used.update((choice["id"], _main(choice)))
    return choice


ESTACIONES = ["invierno"] * 2 + ["primavera"] * 3 + ["verano"] * 3 + ["otoño"] * 3 + ["invierno"]


def season(week: date) -> str:
    """Estación de la semana (la de su jueves): diciembre-febrero invierno, marzo-mayo primavera…"""
    return ESTACIONES[(monday(week) + timedelta(days=3)).month - 1]


def pool(meal: str, group: str, when: str) -> list[dict]:
    """Recetas de ese momento del día y grupo que tocan en esa estación (sin «temporada», todo el año)."""
    return [r for r in recetario()["recetas"]
            if r.get(meal) and r.get("grupo") == group and (not r.get("temporada") or when in r["temporada"])]


def plan(week: date, changes: dict[str, str] | None = None) -> list[dict]:
    """Comida y cena de cada día de la semana que empieza el lunes `week`. `changes` son los platos cambiados a
    mano: {"AAAA-MM-DD|comida": id de receta}."""
    week = monday(week)
    by_id = {r["id"]: r for r in recetario()["recetas"]}
    days = []
    fixed = week_plan(week)
    if fixed:
        for i in range(7):
            cells = (fixed.get("dias") or [])[i] if i < len(fixed.get("dias") or []) else {}
            day = {"fecha": (week + timedelta(days=i)).isoformat()}
            for t in TOMAS:
                v = (cells or {}).get(t)
                day[t] = _free() if v == LIBRE else _dish(by_id.get(v)) if v else None
            days.append(day)
    else:
        year, num, _ = week.isocalendar()
        rng = random.Random(f"{year}-{num}")
        when = season(week)
        used: set[str] = set()
        for i in range(7):
            lunch = _pick(rng, pool("comida", COMIDAS[i], when), used)
            dinner = _pick(rng, pool("cena", CENAS[i], when), used)
            days.append({"fecha": (week + timedelta(days=i)).isoformat(), "desayuno": None, "media_manana": None,
                         "comida": _dish(lunch), "merienda": None, "cena": _dish(dinner)})
    for key, recipe_id in (changes or {}).items():
        fecha, meal = key.split("|")
        day = next((d for d in days if d["fecha"] == fecha), None)
        if day and recipe_id in by_id and meal in TOMAS:
            day[meal] = {**_dish(by_id[recipe_id]), "cambiado": True}
    return days


def _scale(qty: float, unit: str) -> float:
    q = qty * personas() / 2
    if unit in ("g", "ml"):
        return max(10, round(q / 10) * 10)
    return max(1, -(-q // 1))  # hacia arriba: no se compra medio limón


def _ingredients(recipe: dict) -> list[dict]:
    basics = {norm(b) for b in recetario()["basicos"]}
    out = []
    for ing in recipe.get("ingredientes") or []:
        name = ing["nombre"]
        if norm(name) in basics or ing.get("cantidad") is None:
            continue
        unit = ing.get("unidad", "ud")
        out.append({"nombre": name, "cantidad": _scale(float(ing["cantidad"]), unit), "unidad": unit,
                    "seccion": ing.get("seccion") or "Despensa"})
    return out


def _free() -> dict:
    """Una toma sin plato («Libre» en el plan): ni ingredientes ni cambio."""
    return {"id": None, "nombre": "Libre", "grupo": None, "libre": True, "ingredientes": []}


def _dish(recipe: dict | None) -> dict | None:
    if not recipe:
        return None
    return {"id": recipe["id"], "nombre": recipe["nombre"], "grupo": recipe.get("grupo"),
            "ingredientes": [{**i, "texto": amount(i["cantidad"], i["unidad"])} for i in _ingredients(recipe)]}


def amount(qty: float, unit: str) -> str:
    q = int(qty) if float(qty).is_integer() else qty
    if unit == "g":
        return f"{q / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " kg" if q >= 1000 else f"{q} g"
    if unit == "ml":
        return f"{q / 1000:.2f}".rstrip("0").rstrip(".").replace(".", ",") + " l" if q >= 1000 else f"{q} ml"
    if unit == "ud":
        return str(q)
    return f"{q} {PLURAL.get(unit, unit) if q != 1 else unit}"


def key(name: str, unit: str) -> str:
    return f"{norm(name)}|{unit}"


def shopping(days: list[dict]) -> list[dict]:
    """Ingredientes de toda la semana, sumados y por secciones del súper."""
    total: dict[str, dict] = {}
    for d in days:
        for meal in TOMAS:
            for ing in (d.get(meal) or {}).get("ingredientes", []):
                k = key(ing["nombre"], ing["unidad"])
                item = total.setdefault(k, {"clave": k, "nombre": ing["nombre"], "unidad": ing["unidad"],
                                            "seccion": ing["seccion"], "cantidad": 0, "platos": []})
                item["cantidad"] += ing["cantidad"]
                if d[meal]["nombre"] not in item["platos"]:
                    item["platos"].append(d[meal]["nombre"])
    for item in total.values():
        item["texto"] = amount(item["cantidad"], item["unidad"])
        item["recordatorio"] = f"{item['nombre']} ({item['texto']})"
    order = {s: i for i, s in enumerate(SECCIONES)}
    sections: dict[str, list] = {}
    for item in sorted(total.values(), key=lambda x: (order.get(x["seccion"], 99), norm(x["nombre"]))):
        sections.setdefault(item["seccion"], []).append(item)
    return [{"seccion": s, "items": items} for s, items in sections.items()]


def in_list(name: str, titles: list[str]) -> bool:
    """¿Ya está en la lista de la compra? «Huevos camperos» cuenta para «Huevos»; «Leche» no cuenta para
    «Leche de coco ligera»."""
    n = norm(name)
    return any(norm(t).startswith(n) for t in titles)


class Store:
    """Lo pasado a la compra desde el panel, hasta que el Atajo lo mete en Recordatorios."""

    def __init__(self, path: Path | None = None):
        self.path = path or DATA_PATH
        self.pending: list[dict] = []
        self.changes: dict[str, dict[str, str]] = {}  # platos cambiados a mano, por semana
        self.last_collect: dict | None = None
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
            self.pending = saved.get("pendientes", [])
            self.changes = saved.get("cambios", {})
        except (OSError, ValueError, AttributeError):
            self.pending, self.changes = [], {}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".menu-")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump({"pendientes": self.pending, "cambios": self.changes}, f, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)

    def plan(self, week: date) -> list[dict]:
        """El menú de la semana con los platos cambiados a mano."""
        return plan(week, self.changes.get(monday(week).isoformat()))

    def swap(self, fecha: date, meal: str) -> bool:
        """Cambia ese plato por el siguiente de su grupo y estación que no esté ya en la semana. Dando vueltas se
        vuelve al original. Devuelve False si no hay otro."""
        week = monday(fecha)
        key, wk = f"{fecha.isoformat()}|{meal}", week.isoformat()
        days = self.plan(week)
        current = next(d for d in days if d["fecha"] == fecha.isoformat())[meal]
        original = next(d for d in plan(week) if d["fecha"] == fecha.isoformat())[meal]
        if not current:
            return False
        taken = {d[m]["id"] for d in days for m in TOMAS if d.get(m)} - {current["id"]}
        if current.get("libre") or not current.get("grupo"):
            return False
        # Desayunos y tentempiés se repiten en la semana: no se excluyen los que ya salen otro día
        taken = set() if current["grupo"] in GRUPOS_TOMAS else taken
        options = [r["id"] for r in pool(meal, current["grupo"], season(week)) if r["id"] not in taken]
        others = [o for o in options if o != current["id"]]
        if not others:
            return False
        i = options.index(current["id"]) if current["id"] in options else -1
        chosen = options[(i + 1) % len(options)]
        mine = self.changes.setdefault(wk, {})
        if original and chosen == original["id"]:
            mine.pop(key, None)
        else:
            mine[key] = chosen
        # Las semanas pasadas ya no hacen falta
        limit = (monday(date.today()) - timedelta(days=7)).isoformat()
        self.changes = {w: c for w, c in self.changes.items() if w >= limit and c}
        self._save()
        return True

    def toggle(self, week: str, item: dict) -> bool:
        """Pasa el ingrediente a la compra, o lo quita si aún no lo ha recogido el Atajo. Devuelve si queda pasado."""
        for p in self.pending:
            if p["semana"] == week and p["clave"] == item["clave"]:
                if p["entregado"]:
                    return True  # ya está en Recordatorios: desde aquí no se puede quitar
                self.pending.remove(p)
                self._save()
                return False
        self.pending.append({"semana": week, "clave": item["clave"], "titulo": item["recordatorio"],
                             "entregado": False, "t": time.time()})
        self._save()
        return True

    def moved(self, week: str) -> set[str]:
        return {p["clave"] for p in self.pending if p["semana"] == week}

    def collect(self) -> list[str]:
        """Lo que el Atajo tiene que añadir a Recordatorios; queda marcado como entregado."""
        out = [p["titulo"] for p in self.pending if not p["entregado"]]
        for p in self.pending:
            if not p["entregado"]:
                p.update(entregado=True, entregado_t=time.time())
        self.last_collect = {"t": time.time(), "items": len(out)}
        if out:
            self._save()
        return out

    def shopping_list_arrived(self, titles: list[str]) -> None:
        """Llega la lista de la compra desde el iPhone. Lo entregado que viene dentro ya es de Recordatorios y deja de
        ser del panel. Lo entregado que no viene es que el Atajo no llegó a añadirlo (el envío va justo después de
        recogerlo): vuelve a pendiente para que lo recoja en la siguiente vuelta, en vez de perderse."""
        have = {norm(t) for t in titles}
        changed = False
        for p in list(self.pending):
            if not p["entregado"]:
                continue
            changed = True
            if norm(p["titulo"]) in have:
                self.pending.remove(p)
            else:
                p.update(entregado=False, fallos=p.get("fallos", 0) + 1)
        if changed:
            self._save()

    def status(self) -> dict:
        """Para /api/salud: si el Atajo recoge y lo que no ha llegado a Recordatorios."""
        return {"pendientes": [p["titulo"] for p in self.pending if not p["entregado"]],
                "entregados": [p["titulo"] for p in self.pending if p["entregado"]],
                "sin_llegar": {p["titulo"]: p["fallos"] for p in self.pending if p.get("fallos")},
                "ultima_recogida": self.last_collect}

    def merge_into(self, lists: list[dict]) -> list[dict]:
        """Añade a la lista de la compra lo pasado desde el panel que aún no ha llegado en la lista del iPhone."""
        name = shopping_list_name()
        out = []
        for l in lists:
            if l["nombre"] == name and self.pending:
                have = {norm(i["titulo"]) for i in l["items"]}
                extra = [{"titulo": p["titulo"], "notas": None, "vence": None, "panel": True}
                         for p in self.pending if norm(p["titulo"]) not in have]
                l = {**l, "items": l["items"] + extra}
            out.append(l)
        return out


def week_view(week: date, store: Store, shopping_titles: list[str]) -> dict[str, Any]:
    week = monday(week)
    days = store.plan(week)
    moved = store.moved(week.isoformat())
    sections = shopping(days)
    for s in sections:
        for item in s["items"]:
            item["pasado"] = item["clave"] in moved
            item["en_lista"] = in_list(item["nombre"], shopping_titles)
    fixed = week_plan(week)
    return {"semana": week.isoformat(), "estacion": season(week), "personas": personas(), "dias": days, "compra": sections,
            "basicos": recetario()["basicos"], "lista": shopping_list_name(), "modo": mode(),
            "plan": fixed.get("nombre") if fixed else None,
            "tomas": [t for t in TOMAS if any(d.get(t) for d in days)]}
