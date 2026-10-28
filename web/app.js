// Panel de cocina: bloqueo con avatares y, al entrar, las vistas del marco original con su barra lateral:
// Hoy, Calendario, Tiempo, Casa y Tareas. Sin dependencias ni compilación.
"use strict";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 60_000;
const ES = "es-ES";
const CAL_NAME = "Rim y Pablo";

const state = {
  users: [], user: null, view: "hoy", home: null, house: null, power: null, trips: {}, list: null, weatherDay: null,
  pending: {}, busy: null, houseError: null,
  menu: [], menuWeek: 0, menuBusy: null,  // menú de esta semana y de la siguiente
  idleMs: 120_000, idleTimer: null,
};

// ---------- Iconos (trazos de Lucide, licencia ISC) ----------

const ICONS = {
  hoy: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18"/><rect x="7" y="13" width="4" height="4" rx="1"/>',
  calendario: '<rect x="3" y="4" width="18" height="18" rx="2"/><path d="M16 2v4M8 2v4M3 10h18M8 14h.01M12 14h.01M16 14h.01M8 18h.01M12 18h.01M16 18h.01"/>',
  tiempo: '<path d="M14 4v10.54a4 4 0 1 1-4 0V4a2 2 0 0 1 4 0Z"/>',
  casa: '<path d="M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8"/><path d="M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
  energia: '<path d="M4 14a1 1 0 0 1-.78-1.63l9.9-10.2a.5.5 0 0 1 .86.46l-1.92 6.02A1 1 0 0 0 13 10h7a1 1 0 0 1 .78 1.63l-9.9 10.2a.5.5 0 0 1-.86-.46l1.92-6.02A1 1 0 0 0 11 14z"/>',
  consumo: '<path d="m12 14 4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  tareas: '<path d="m3 17 2 2 4-4M3 7l2 2 4-4M13 6h8M13 12h8M13 18h8"/>',
  refresh: '<path d="M3 12a9 9 0 0 1 9-9 9.75 9.75 0 0 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/><path d="M21 12a9 9 0 0 1-9 9 9.75 9.75 0 0 1-6.74-2.74L3 16"/><path d="M8 16H3v5"/>',
  sleep: '<path d="M12 3a6 6 0 0 0 9 9 9 9 0 1 1-9-9Z"/>',
};
const LABELS = { hoy: "Hoy", calendario: "Calendario", tiempo: "Tiempo", casa: "Casa", energia: "Energía", consumo: "Consumo", tareas: "Tareas", refresh: "Actualizar", sleep: "Dormir" };
const icon = (name) => `<svg class="i" viewBox="0 0 24 24" aria-hidden="true">${ICONS[name]}</svg>`;

// ---------- Utilidades ----------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hm = (d) => d.toLocaleTimeString(ES, { hour: "2-digit", minute: "2-digit" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const euros = (v) => v == null ? "–" : v.toLocaleString(ES, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const dayKey = (d) => d.toLocaleDateString("sv-SE"); // AAAA-MM-DD en hora local
const startOfDay = (d) => new Date(d.getFullYear(), d.getMonth(), d.getDate());
const addDays = (d, n) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const localTime = (iso) => new Date(iso); // las horas de la luz vienen sin zona: el navegador las toma como locales
const wdShort = (d) => cap(d.toLocaleDateString(ES, { weekday: "short" }).replace(".", ""));

function dateLine(now) {
  return `<b>${cap(now.toLocaleDateString(ES, { weekday: "long" }))}</b> ${now.toLocaleDateString(ES, { day: "numeric", month: "long" })}`;
}

function dayLabel(d, today) {
  const diff = Math.round((startOfDay(d) - startOfDay(today)) / 86_400_000);
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Mañana";
  return cap(d.toLocaleDateString(ES, { weekday: "long", day: "numeric", month: "short" }));
}
const relDay = (d, now) => { const l = dayLabel(d, now); return l === "Hoy" || l === "Mañana" ? l.toLowerCase() : l; };

// WMO (Open-Meteo) → emoji y descripción
function wmo(code, isDay = true) {
  if (code === 0) return isDay ? "☀️" : "🌙";
  if (code <= 2) return isDay ? "🌤️" : "☁️";
  if (code === 3) return "☁️";
  if (code <= 48) return "🌫️";
  if (code <= 57) return "🌦️";
  if (code <= 67) return "🌧️";
  if (code <= 77) return "🌨️";
  if (code <= 82) return "🌧️";
  if (code <= 86) return "🌨️";
  return "⛈️";
}
function wmoText(code) {
  if (code === 0) return "Despejado";
  if (code <= 2) return "Parcialmente nuboso";
  if (code === 3) return "Nublado";
  if (code <= 48) return "Niebla";
  if (code <= 57) return "Llovizna";
  if (code <= 67) return "Lluvia";
  if (code <= 77) return "Nieve";
  if (code <= 82) return "Chubascos";
  if (code <= 86) return "Chubascos de nieve";
  return "Tormenta";
}

// Verde → ámbar → rojo según el precio entre el mínimo y el máximo del día (priceColor del original)
function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
}
function priceColor(v, min, max) {
  const t = max > min ? Math.min(1, Math.max(0, (v - min) / (max - min))) : 0;
  return t < 0.5 ? mix("#3BA55C", "#F5A623", t * 2) : mix("#F5A623", "#D9483B", (t - 0.5) * 2);
}

function head(ic, title, tint, extra = "") {
  return `<div class="head" style="--tint:${tint}"><span class="ic">${ic}</span><h2>${esc(title)}</h2>${extra}</div>`;
}
function staleNote(block) {
  if (!block || !block.stale || !block.updated) return "";
  return `<p class="stale">Sin actualizar desde las ${hm(new Date(block.updated * 1000))}</p>`;
}

// ---------- Datos derivados ----------

const weather = () => state.home?.tiempo?.data;
const energy = () => state.home?.luz?.data;
const car = () => state.home?.coche?.data;
const lists = () => state.home?.recordatorios?.data || [];

function dailyFor(d) {
  const w = weather();
  if (!w) return null;
  const i = w.daily.time.indexOf(dayKey(d));
  if (i < 0) return null;
  return { code: w.daily.weather_code[i], max: w.daily.temperature_2m_max[i], min: w.daily.temperature_2m_min[i],
    rain: w.daily.precipitation_probability_max[i], sunrise: w.daily.sunrise[i], sunset: w.daily.sunset[i] };
}

// El calendario de los dos y los extra que solo enseña el panel (festivos, F1 y fútbol), cada uno con su color
function events() {
  const own = (state.home?.calendario?.data || []).map((ev) => ({ ...ev, calendario: CAL_NAME, propio: true }));
  return own.concat(state.home?.calendarios_extra?.data || []).map((ev) => {
    const start = ev.all_day ? new Date(ev.start + "T00:00") : new Date(ev.start);
    const end = ev.end ? (ev.all_day ? new Date(ev.end + "T00:00") : new Date(ev.end)) : start;
    return { ...ev, startD: start, endD: end };
  }).sort((a, b) => a.startD - b.startD || (b.all_day - a.all_day));
}

// Los de un día: los de todo el día que lo cubren y los que empiezan ese día
function eventsOn(day, all) {
  const from = startOfDay(day), to = addDays(from, 1);
  return all.filter((e) => e.all_day ? e.startD < to && e.endD > from : e.startD >= from && e.startD < to);
}

// ---------- Cielo y reloj ----------

function skyFor(now) {
  const d = dailyFor(now);
  const base = startOfDay(now);
  const rise = d ? new Date(d.sunrise) : new Date(+base + 8 * 3600e3);
  const set = d ? new Date(d.sunset) : new Date(+base + 19 * 3600e3);
  const m = 60_000;
  if (now < rise - 45 * m || now > +set + 60 * m) return "night";
  if (now < +rise + 60 * m) return "dawn";
  if (now < set - 60 * m) return "day";
  return "dusk";
}

function tick() {
  const now = new Date();
  const sky = skyFor(now);
  $("lock").dataset.sky = sky;
  $("band").dataset.sky = sky;
  $("lock-clock").textContent = hm(now);
  $("clock").textContent = hm(now);
  $("lock-date").innerHTML = dateLine(now);
  $("date").innerHTML = dateLine(now);
  const [h, m] = hm(now).split(":");
  $("rail-clock").innerHTML = `<span>${h}</span><span>${m}</span>`;
  if (state.user && state.view === "hoy") renderNext();
}

// ---------- Bloqueo, personas y navegación ----------

const initial = (u) => esc(u.nombre.charAt(0).toUpperCase());
const faceStyle = (u) => `--c:${esc(u.color)}${u.foto ? `;background-image:url('${esc(u.foto)}')` : ""}`;

function renderAvatars() {
  $("avatars").innerHTML = state.users.map((u) => `
    <button class="avatar" data-id="${esc(u.id)}" aria-label="Entrar como ${esc(u.nombre)}">
      <span class="face" style="${faceStyle(u)}">${u.foto ? "" : initial(u)}</span>
      <span class="name">${esc(u.nombre)}</span>
    </button>`).join("");
  $("avatars").querySelectorAll(".avatar").forEach((b) => b.addEventListener("click", () => enter(b.dataset.id)));
}

function enter(id) {
  state.user = state.users.find((u) => u.id === id) || null;
  if (!state.user) return;
  const me = $("me");
  me.setAttribute("style", faceStyle(state.user));
  me.textContent = state.user.foto ? "" : state.user.nombre.charAt(0).toUpperCase();
  $("lock").hidden = true;
  $("main").hidden = false;
  go("hoy");
  loadTrips();
  resetIdle();
}

function lock() {
  state.user = null;
  state.list = null;
  closeModal();
  $("main").hidden = true;
  $("lock").hidden = false;
}

function go(view) {
  state.view = view;
  if (view === "casa") loadHouse();
  if (view === "consumo") loadConsumption();
  if (view === "tareas") loadMenu();
  document.querySelectorAll(".view").forEach((v) => { v.hidden = v.dataset.view !== view; });
  document.querySelectorAll(".nav[data-go]").forEach((b) => {
    const on = b.dataset.go === view;
    b.classList.toggle("on", on);
    b.setAttribute("aria-current", on ? "page" : "false");
  });
  render();
}

function setupRail() {
  document.querySelectorAll(".nav").forEach((b) => {
    const name = b.dataset.go || b.dataset.action;
    b.innerHTML = `${icon(name)}<span>${LABELS[name]}</span>`;
    b.addEventListener("click", () => {
      if (b.dataset.go) go(b.dataset.go);
      else if (name === "refresh") { loadHome(); loadTrips(); loadHouse(); loadConsumption(); }
      else if (name === "sleep") lock();
    });
  });
  $("me").addEventListener("click", lock);
}

function resetIdle() {
  clearTimeout(state.idleTimer);
  if (state.user) state.idleTimer = setTimeout(lock, state.idleMs);
}

// ---------- Detalle de una cita ----------

function openEvent(ev) {
  const d = ev.startD;
  let when = cap(d.toLocaleDateString(ES, { weekday: "long", day: "numeric", month: "long" }));
  if (ev.all_day) {
    const last = addDays(ev.endD, -1);
    when += last > d ? ` – ${last.toLocaleDateString(ES, { weekday: "long", day: "numeric", month: "long" })}` : " · Todo el día";
  } else {
    when += ` · ${hm(d)}${ev.endD > d ? "–" + hm(ev.endD) : ""}`;
  }
  const card = $("modal").querySelector(".modal-card");
  if (ev.color) card.setAttribute("style", `--event:${ev.color}`); else card.removeAttribute("style");
  $("modal-cal").textContent = (ev.calendario || CAL_NAME).toUpperCase();
  $("modal-title").textContent = ev.title;
  $("modal-when").textContent = when;
  $("modal-extra").textContent = [ev.location, ev.description].filter(Boolean).join("\n");
  $("modal").hidden = false;
  $("modal-close").focus();
}
function closeModal() { $("modal").hidden = true; }

// ---------- Menú semanal ----------

const MEALS = [["comida", "🍽️", "Comida"], ["cena", "🌙", "Cena"]];
const menuFor = (d) => state.menu.flatMap((w) => w?.dias || []).find((x) => x.fecha === dayKey(d));

function mealLines(day) {
  const m = menuFor(day);
  if (!m) return "";
  return `<button class="meals" data-meal="${m.fecha}" aria-label="Menú del día">${MEALS.filter(([k]) => m[k])
    .map(([k, ic]) => `<span><i>${ic}</i>${esc(m[k].nombre)}</span>`).join("")}</button>`;
}

function openMeal(fecha) {
  const m = menuFor(new Date(fecha + "T12:00"));
  if (!m) return;
  const per = state.menu[0]?.personas || 2;
  $("modal").querySelector(".modal-card").setAttribute("style", "--event:#2E9E5B");
  $("modal-cal").textContent = "MENÚ DEL DÍA";
  $("modal-title").textContent = cap(new Date(fecha + "T12:00").toLocaleDateString(ES, { weekday: "long", day: "numeric", month: "long" }));
  $("modal-when").textContent = `Para ${per} ${per === 1 ? "persona" : "personas"} · los ingredientes, en Tareas`;
  $("modal-extra").textContent = MEALS.filter(([k]) => m[k]).map(([k, ic, label]) =>
    `${ic} ${label}: ${m[k].nombre}\n${m[k].ingredientes.map((i) => `${i.nombre} ${i.texto}`).join(" · ")}`).join("\n\n");
  $("modal").hidden = false;
  $("modal-close").focus();
}

function bindMeals(root) {
  root.querySelectorAll("[data-meal]").forEach((b) => b.addEventListener("click", () => openMeal(b.dataset.meal)));
}

function renderMenuList() {
  const w = state.menu[state.menuWeek];
  const tabs = `<div class="seg week-tabs">${["Esta semana", "La siguiente"].map((t, i) =>
    `<button class="sg${i === state.menuWeek ? " on" : ""}" data-week="${i}">${t}</button>`).join("")}</div>`;
  if (!w) {
    $("menu-list").innerHTML = head("🥗", "Ingredientes del menú", "#E8604C") + `<p class="empty">Cargando…</p>`;
    return;
  }
  const n = w.compra.reduce((a, s) => a + s.items.length, 0);
  const moved = w.compra.reduce((a, s) => a + s.items.filter((i) => i.pasado).length, 0);
  const sections = w.compra.map((s) => `<p class="sub-h">${esc(s.seccion)}</p><ul class="items">${s.items.map((i) => {
    const st = i.pasado ? `<span class="mi-st ok">✓ En la compra</span>` : i.en_lista ? `<span class="mi-st">ya en la lista</span>` : `<span class="mi-add">+</span>`;
    return `<li><button class="mi${i.pasado ? " moved" : ""}" data-k="${esc(i.clave)}" ${state.menuBusy === i.clave ? "disabled" : ""}
      title="${esc(i.platos.join(" · "))}"><span class="grow">${esc(i.nombre)} <small>${esc(i.texto)}</small></span>${st}</button></li>`;
  }).join("")}</ul>`).join("");
  $("menu-list").innerHTML = head("🥗", "Ingredientes del menú", "#E8604C", `<span class="pill" style="--tint:#E8604C">${moved}/${n}</span>`)
    + tabs + `<p class="note mi-hint">Para ${w.personas} personas, comida y cena de toda la semana. Toca para pasarlo a «${esc(w.lista)}».</p>`
    + `<div class="scroll">${sections}<p class="note">No incluye lo de la despensa de siempre: ${esc(w.basicos.join(", ").toLowerCase())}.</p></div>`;
  $("menu-list").querySelectorAll("[data-week]").forEach((b) => b.addEventListener("click", () => { state.menuWeek = +b.dataset.week; renderMenuList(); }));
  $("menu-list").querySelectorAll("[data-k]").forEach((b) => b.addEventListener("click", () => toShopping(b.dataset.k)));
}

async function toShopping(clave) {
  if (state.menuBusy) return;
  const week = state.menuWeek;
  state.menuBusy = clave;
  renderMenuList();
  try {
    const r = await fetch("/api/menu/compra", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ semana: week, clave }) });
    if (r.ok) state.menu[week] = await r.json();
  } catch (e) { console.warn(e); }
  state.menuBusy = null;
  await loadHome();  // la Compra ya lo enseña
}

async function loadMenu() {
  await Promise.all([0, 1].map(async (i) => {
    try { state.menu[i] = await getJSON(`/api/menu?semana=${i}`); }
    catch (e) { console.warn(e); }
  }));
  render();
}

function evButtons(list) {
  const now = new Date();
  // Las de hoy que ya han terminado, atenuadas
  const tint = (e) => e.color ? ` style="--event:${esc(e.color)}"` : "";
  return list.map((e) => e.all_day
    ? `<button class="allday${e.festivo ? " festivo" : ""}" data-ev="${e.idx}"${tint(e)}>${esc(e.title)}</button>`
    : `<button class="ev${e.endD < now ? " done" : ""}" data-ev="${e.idx}"${tint(e)}><span class="t">${hm(e.startD)}</span><div class="s">${esc(e.title)}</div></button>`).join("");
}
function bindEvents(root, all) {
  root.querySelectorAll("[data-ev]").forEach((b) => b.addEventListener("click", () => openEvent(all[+b.dataset.ev])));
}

// ---------- Hoy ----------

function renderLockWeather() {
  const w = weather();
  const luz = energy();
  const today = dailyFor(new Date());
  if (w && today) {
    $("lock-weather").innerHTML = `<span class="big">${wmo(w.current.weather_code, w.current.is_day)} ${Math.round(w.current.temperature_2m)}°</span>
      <span>${Math.round(today.min)}° / ${Math.round(today.max)}°${today.rain >= 40 ? ` · lluvia ${today.rain} %` : ""}</span>`;
  }
  $("lock-power").textContent = luz?.now ? `Luz ahora: ${euros(luz.now.eur_kwh)} €/kWh` : "";
}

function renderBandWeather() {
  const w = weather();
  const now = new Date();
  const today = dailyFor(now);
  if (!w || !today) { $("weather").innerHTML = `<p class="note">Sin datos del tiempo</p>`; return; }
  const rain = (p) => `<span class="rain${p >= 40 ? " wet" : ""}">💧 ${p ?? 0} %</span>`;
  let html = `<div class="wnow"><span class="icon">${wmo(w.current.weather_code, w.current.is_day)}</span>
    <span class="t">${Math.round(w.current.temperature_2m)}°</span>
    <span class="mm">${Math.round(today.min)}° / ${Math.round(today.max)}°</span>${rain(today.rain)}</div>`;
  for (let i = 1; i <= 5; i++) {
    const day = addDays(now, i), d = dailyFor(day);
    if (!d) continue;
    html += `<div class="wday"><span class="d">${wdShort(day)}</span><span class="icon">${wmo(d.code)}</span>
      <span class="mx">${Math.round(d.max)}°</span><span class="mn">${Math.round(d.min)}°</span>${rain(d.rain)}</div>`;
  }
  $("weather").innerHTML = html;
}

function renderNext() {
  const now = new Date();
  const all = events();
  const next = all.find((e) => e.propio && !e.all_day && e.endD > now);  // lo de los dos, no la F1 ni el fútbol
  const el = $("next");
  if (!next) {
    el.className = "next none";
    el.innerHTML = `<div class="row"><span class="lbl">LO PRÓXIMO</span></div><h3>Nada en el calendario</h3><span class="when">${esc(CAL_NAME)}</span>`;
    el.onclick = null;
    return;
  }
  const mins = Math.round((next.startD - now) / 60_000);
  const cd = mins <= 0 ? "ahora" : mins < 60 ? `en ${mins} min` : mins < 48 * 60 ? `en ${Math.floor(mins / 60)} h ${mins % 60} min` : `en ${Math.round(mins / 1440)} días`;
  el.className = "next";
  el.innerHTML = `<div class="row"><span class="lbl">LO PRÓXIMO</span><span class="cd">${cd}</span></div>
    <h3>${esc(next.title)}</h3><span class="when">${dayLabel(next.startD, now)} · ${hm(next.startD)}${next.endD > next.startD ? "–" + hm(next.endD) : ""}</span>`;
  el.onclick = () => openEvent(next);
}

function dayColumn(day, all, now, { weatherLine = false } = {}) {
  const list = eventsOn(day, all);
  const isToday = dayKey(day) === dayKey(now);
  const past = startOfDay(day) < startOfDay(now);
  const d = weatherLine ? dailyFor(day) : null;
  const w = d ? `<div class="dw"><span>${wmo(d.code)} ${Math.round(d.max)}° ${Math.round(d.min)}°</span><span class="rain${d.rain >= 40 ? " wet" : ""}">💧${d.rain}%</span></div>` : "";
  const holiday = list.some((e) => e.festivo);
  return `<div class="dcol${isToday ? " today" : ""}${past ? " past" : ""}${holiday ? " festivo" : ""}">
    <div class="dhead"><span class="dn">${isToday ? "Hoy" : wdShort(day)}</span><span class="dd">${day.getDate()}</span></div>
    ${w}${evButtons(list)}${mealLines(day)}</div>`;
}

function renderWeek() {
  const now = new Date();
  const all = events().map((e, idx) => ({ ...e, idx }));
  let html = "";
  for (let i = 0; i < 7; i++) html += dayColumn(addDays(now, i), all, now);
  $("week").innerHTML = html;
  bindEvents($("week"), all);
  bindMeals($("week"));
}

function gauge(level, color, w = 150) {
  const pct = Math.max(0, Math.min(1, (level ?? 0) / 100));
  const r = 62, cx = 75, cy = 78, a = Math.PI * (1 - pct);
  const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
  const bg = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  const fg = pct > 0 ? `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}` : "";
  return `<svg viewBox="0 0 150 84" width="${w}" aria-hidden="true"><path d="${bg}" stroke="#EFE6DA" stroke-width="16" fill="none" stroke-linecap="round"/>
    ${fg ? `<path d="${fg}" stroke="${color}" stroke-width="16" fill="none" stroke-linecap="round"/>` : ""}</svg>`;
}
const carColor = (c) => c.cargando ? "#1E90E8" : c.bateria > 50 ? "#3BA55C" : c.bateria >= 20 ? "#F5A623" : "#D9483B";

function priceBars(day, e, now) {
  return day.map((p) => {
    const t = localTime(p.time);
    const h = e.max > 0 ? Math.max(3, (p.eur_kwh / e.max) * 100) : 3;
    const cls = dayKey(t) === dayKey(now) && t.getHours() === now.getHours() ? "now" : (t < now ? "past" : "");
    return `<div class="bar ${cls}" style="height:${h}%;background:${priceColor(p.eur_kwh, e.min, e.max)}"></div>`;
  }).join("");
}

function renderHoyBottom() {
  const now = new Date();
  // Trayecto de quien ha entrado
  const t = state.trips[state.user.id]?.data;
  $("commute").setAttribute("style", `--tint:${state.user.color}`);
  $("commute").innerHTML = `<span class="lbl">🚙 AL TRABAJO</span>` + (t
    ? `<span class="big">${t.minutos != null ? Math.round(t.minutos) : "–"} <small>min</small></span><span class="sub">${t.ruta ? "Por " + esc(t.ruta) : ""}</span>`
    : `<span class="sub">${state.trips[state.user.id] ? "Sin trayecto configurado" : "Cargando…"}</span>`);

  // Compra
  const [shop] = lists();
  const n = shop?.items.length || 0;
  $("shop-mini").setAttribute("style", "--tint:#2E9E5B");
  $("shop-mini").innerHTML = `<span class="lbl">🛒 ${esc((shop?.nombre || "Compra").toUpperCase())}</span>
    <span class="big">${n ? `${n} ${n === 1 ? "cosa" : "cosas"}` : "Nada pendiente"}</span>
    <span class="sub">${shop ? shop.items.slice(0, 5).map((i) => esc(i.titulo)).join(" · ") : ""}</span>`;
  $("shop-mini").onclick = () => go("tareas");

  // Luz y coche
  const e = energy(), c = car();
  const day = e ? e.today : [];
  $("energy-mini").setAttribute("style", "--tint:#F5A623");
  $("energy-mini").innerHTML = `<span class="lbl">⚡ ${c ? "LUZ Y COCHE" : "LUZ"}${e?.now ? ` <span class="pill solid" style="--tint:${priceColor(e.now.eur_kwh, e.min, e.max)};margin-left:auto">${euros(e.now.eur_kwh)} €/kWh</span>` : ""}</span>
    <div class="energy-mini">
      ${c ? `<div class="gauge">${gauge(c.bateria, carColor(c), 104)}<div class="pct" style="text-align:center;font-weight:600">${Math.round(c.bateria ?? 0)} %</div></div>` : ""}
      <div class="bars">${e ? priceBars(day, e, now) : ""}</div>
    </div>`;
  $("energy-mini").onclick = () => go("energia");
}

// ---------- Calendario ----------

function renderCalendar() {
  const now = new Date();
  const monday = addDays(now, -((now.getDay() + 6) % 7));
  const all = events().map((e, idx) => ({ ...e, idx }));
  let html = "";
  for (let i = 0; i < 14; i++) html += dayColumn(addDays(monday, i), all, now, { weatherLine: true });
  $("cal").innerHTML = html;
  bindEvents($("cal"), all);
  bindMeals($("cal"));
}

// ---------- Tiempo ----------

function smoothPath(pts) {
  // Catmull-Rom a Bézier: curva suave que pasa por todos los puntos
  let d = `M ${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const [p0, p1, p2, p3] = [pts[i - 1] || pts[i], pts[i], pts[i + 1], pts[i + 2] || pts[i + 1]];
    const c1 = [p1[0] + (p2[0] - p0[0]) / 6, p1[1] + (p2[1] - p0[1]) / 6];
    const c2 = [p2[0] - (p3[0] - p1[0]) / 6, p2[1] - (p3[1] - p1[1]) / 6];
    d += ` C ${c1[0].toFixed(1)} ${c1[1].toFixed(1)}, ${c2[0].toFixed(1)} ${c2[1].toFixed(1)}, ${p2[0].toFixed(1)} ${p2[1].toFixed(1)}`;
  }
  return d;
}

function renderWeatherFull() {
  const w = weather();
  const now = new Date();
  if (!w) { $("weather-full").innerHTML = `<p class="empty">Sin datos del tiempo.</p>`; return; }
  const sel = state.weatherDay && state.weatherDay >= dayKey(now) ? state.weatherDay : dayKey(now);
  const isToday = sel === dayKey(now);
  const selDate = new Date(sel + "T12:00");
  const d = dailyFor(selDate);
  const idx = w.hourly.time.map((t, i) => [t, i]).filter(([t]) => t.startsWith(sel)).map(([, i]) => i);
  const temps = idx.map((i) => w.hourly.temperature_2m[i]);
  const big = isToday ? { code: w.current.weather_code, day: w.current.is_day, t: w.current.temperature_2m } : { code: d?.code, day: 1, t: d?.max };

  const hours = idx.map((i, h) => `<div><span>${wmo(w.hourly.weather_code[i], w.hourly.is_day?.[i] ?? 1)}</span><small>${String(h).padStart(2, "0")}</small></div>`).join("");
  let days = "";
  for (let i = 0; i < 7; i++) {
    const day = addDays(now, i), dd = dailyFor(day);
    if (!dd) continue;
    days += `<button class="wf-day${dayKey(day) === sel ? " on" : ""}" data-day="${dayKey(day)}">
      <span class="d">${day.toLocaleDateString(ES, { weekday: "short", day: "numeric" }).replace(".", "")}</span>
      <span class="icon">${wmo(dd.code)}</span><b>${Math.round(dd.max)}°</b> <b class="mn">${Math.round(dd.min)}°</b></button>`;
  }
  const humidity = isToday ? `${w.current.relative_humidity_2m ?? "–"}<small>%</small>` : "–";
  const wind = isToday ? `${Math.round(w.current.wind_speed_10m ?? 0)}<small> km/h</small>` : "–";

  $("weather-full").innerHTML = `
    <div class="wf-top">
      <span class="icon">${wmo(big.code, big.day)}</span><span class="temp">${Math.round(big.t ?? 0)}°</span>
      <div><div class="desc">${wmoText(big.code)}</div>
        <div class="mm">${isToday ? "Ahora" : cap(selDate.toLocaleDateString(ES, { weekday: "long", day: "numeric" }))} · Máx ${Math.round(d?.max ?? 0)}° · Mín ${Math.round(d?.min ?? 0)}°</div></div>
      <div class="wf-chips">
        <div class="wf-chip">Lluvia<b>${d?.rain ?? 0}<small>%</small></b></div>
        <div class="wf-chip">Humedad<b>${humidity}</b></div>
        <div class="wf-chip">Viento<b>${wind}</b></div>
      </div>
    </div>
    <div class="wf-scroll"><div class="wf-inner">
      <div class="curve" id="curve"></div>
      <div class="hours">${hours}</div>
    </div></div>
    <div class="wf-days">${days}</div>`;
  $("weather-full").querySelectorAll(".wf-day").forEach((b) => b.addEventListener("click", () => { state.weatherDay = b.dataset.day; renderWeatherFull(); }));
  drawCurve(temps, isToday ? now.getHours() : null);
  // En el móvil las 24 horas no caben: se abre con la hora de ahora a la vista
  const scroller = $("weather-full").querySelector(".wf-scroll");
  if (isToday && scroller.scrollWidth > scroller.clientWidth) {
    scroller.scrollLeft = (now.getHours() / 24) * scroller.scrollWidth - scroller.clientWidth / 3;
  }
}

// Curva de temperaturas del día (00 a 23), dibujada al tamaño real del hueco para que el texto no se deforme
function drawCurve(temps, nowHour) {
  const box = $("curve");
  const W = Math.max(300, box.clientWidth), H = Math.max(120, box.clientHeight);
  if (temps.length < 2) { box.innerHTML = ""; return; }
  const top = 30, bottom = 10;
  const min = Math.min(...temps), max = Math.max(...temps);
  const y = (v) => top + (max > min ? (max - v) / (max - min) : 0.5) * (H - top - bottom);
  const x = (i) => (i + 0.5) * (W / 24);
  const pts = temps.map((v, i) => [x(i), y(v)]);
  const line = smoothPath(pts);
  const area = `${line} L ${pts.at(-1)[0]} ${H} L ${pts[0][0]} ${H} Z`;
  const band = nowHour != null ? `<rect x="${x(nowHour) - 15}" y="0" width="30" height="${H}" rx="8" fill="#F5A623" opacity=".18"/>` : "";
  const labels = pts.map(([px, py], i) => `<text x="${px}" y="${py - 11}">${Math.round(temps[i])}</text>`).join("");
  const dots = pts.map(([px, py]) => `<circle cx="${px}" cy="${py}" r="4.5" fill="#F5A623" stroke="#FFFDF9" stroke-width="2"/>`).join("");
  box.innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" aria-label="Temperatura por horas">
    <defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#F5A623" stop-opacity=".28"/><stop offset="1" stop-color="#F5A623" stop-opacity="0"/></linearGradient></defs>
    ${band}<path d="${area}" fill="url(#g)"/><path d="${line}" fill="none" stroke="#F5A623" stroke-width="3"/>${dots}${labels}</svg>`;
}

// ---------- Casa: luz, coche y trayectos ----------

function renderEnergy() {
  const block = state.home?.luz;
  const e = block?.data;
  const now = new Date();
  if (!e) {
    $("energy").innerHTML = head("⚡", "Luz hoy", "#F5A623") + `<p class="empty">Sin precios todavía.</p>` + staleNote(block);
    $("best").innerHTML = head("🕑", "Mejores horas", "#3BA55C") + `<p class="empty">Sin precios todavía.</p>`;
    return;
  }
  const at = (p) => p ? hm(localTime(p.time)).slice(0, 2) + "h" : "";
  const minP = e.today.reduce((a, p) => (!a || p.eur_kwh < a.eur_kwh ? p : a), null);
  const maxP = e.today.reduce((a, p) => (!a || p.eur_kwh > a.eur_kwh ? p : a), null);
  const nowColor = e.now ? priceColor(e.now.eur_kwh, e.min, e.max) : "#A6998A";
  $("energy").innerHTML = head("⚡", "Luz hoy", "#F5A623") + `
    <div class="chips">
      <div class="chip now" style="background:${nowColor}"><small>Ahora</small><b>${euros(e.now?.eur_kwh)}</b></div>
      <div class="chip"><small>Media</small><b>${euros(e.avg)}</b></div>
      <div class="chip"><small>Mín ${at(minP)}</small><b>${euros(e.min)}</b></div>
      <div class="chip"><small>Máx ${at(maxP)}</small><b>${euros(e.max)}</b></div>
    </div>
    <div class="bars">${priceBars(e.today, e, now)}</div>
    <div class="axis"><span>0</span><span>3</span><span>6</span><span>9</span><span>12</span><span>15</span><span>18</span><span>21</span><span>23</span></div>` + staleNote(block);

  const recs = e.recommendations.filter((r) => r.tramo).map((r) => {
    const s = localTime(r.tramo.start), f = localTime(r.tramo.end);
    return `<div class="rec ok"><span class="e">${esc(r.emoji)}</span><div class="t"><small>${esc(r.nombre)}</small>
      <b>${relDay(s, now)} ${hm(s)}–${hm(f)}</b></div><span class="p">${euros(r.tramo.avg_eur_kwh)} €</span></div>`;
  }).join("");
  const wait = e.wait_for_tomorrow ? `<div class="rec"><span class="e">⏳</span><div class="t note">Lo que queda de hoy es caro: mejor esperar al precio de mañana (sale sobre las 20:30).</div></div>` : "";
  const avoid = e.avoid ? (() => {
    const s = localTime(e.avoid.start), f = localTime(e.avoid.end);
    return `<div class="rec bad"><span class="e">⛔</span><div class="t"><small>Mejor evitar</small><b>hoy ${hm(s)}–${hm(f)}</b></div><span class="p">${euros(e.avoid.avg_eur_kwh)} €</span></div>`;
  })() : "";
  $("best").innerHTML = head("🕑", "Mejores horas", "#3BA55C") + `<div class="recs">${recs}${wait}${avoid}</div>`;
}

function renderCar() {
  const block = state.home?.coche;
  const c = block?.data;
  if (!c) { $("car").innerHTML = head("🚗", "Coche", "#3BA55C") + `<p class="empty">Sin datos del coche.</p>`; return; }
  const color = carColor(c);
  const status = c.cargando ? `⚡ cargando${c.potencia_kw ? ` a ${c.potencia_kw.toLocaleString(ES, { maximumFractionDigits: 1 })} kW` : ""}`
    : c.enchufado ? "Enchufado, sin cargar" : "Desenchufado";
  const names = { del_izq: "DI", del_der: "DD", tras_izq: "TI", tras_der: "TD" };
  const tires = c.ruedas ? `<div class="tires">${Object.entries(c.ruedas).map(([k, v]) =>
    `<div class="tire${v != null && v < 2.5 ? " low" : ""}"><b>${v != null ? v.toLocaleString(ES, { minimumFractionDigits: 1, maximumFractionDigits: 1 }) : "–"}</b><small>${names[k] || esc(k)}</small></div>`).join("")}</div>
    <p class="tires-unit">Presión de las ruedas en ${esc(c.ruedas_unidad || "bar")}</p>` : "";
  $("car").className = `card fill${c.cargando ? " charging" : ""}`;
  $("car").innerHTML = head("🚗", c.nombre, color) + `
    <div class="battery">
      <div class="cell"><div class="lvl" style="width:${Math.max(0, Math.min(100, c.bateria ?? 0))}%;background:${color}"></div>
        <span class="pct">${c.bateria != null ? Math.round(c.bateria) + " %" : "–"}</span></div>
      <div class="range"><b>${c.autonomia != null ? Math.round(c.autonomia) + " " + esc(c.autonomia_unidad) : "–"}</b><small>${status}</small></div>
    </div>
    <div class="facts">
      ${c.limite_carga ? `<div class="fact">Límite de carga<b>${Math.round(c.limite_carga)} %</b></div>` : ""}
      ${c.km ? `<div class="fact">Kilómetros<b>${Math.round(c.km).toLocaleString(ES)}</b></div>` : ""}
    </div>${tires}` + staleNote(block);
}

function renderTrips() {
  const rows = state.users.map((u) => {
    const t = state.trips[u.id]?.data;
    return `<div class="trip"><span class="face" style="${faceStyle(u)}">${u.foto ? "" : initial(u)}</span>
      <div class="who">${esc(u.nombre)}<small>${t?.ruta ? "Por " + esc(t.ruta) : "Al trabajo"}</small></div>
      <div class="mins">${t?.minutos != null ? `<b>${Math.round(t.minutos)}</b> <small>min</small>` : `<small>–</small>`}</div></div>`;
  }).join("");
  $("commutes").innerHTML = head("🚙", "Al trabajo", "#3F7FD9") + rows;

  // Precio de mañana, desde que REE lo publica
  const e = energy();
  const now = new Date();
  if (e?.tomorrow_known && e.tomorrow.length) {
    const vals = e.tomorrow.map((p) => p.eur_kwh);
    const tmin = Math.min(...vals), tmax = Math.max(...vals);
    const ref = { min: tmin, max: tmax };
    const bars = e.tomorrow.map((p) => `<div class="bar" style="height:${Math.max(3, (p.eur_kwh / tmax) * 100)}%;background:${priceColor(p.eur_kwh, ref.min, ref.max)}"></div>`).join("");
    $("tomorrow").innerHTML = head("📅", "Luz mañana", "#F5A623", `<span class="pill" style="--tint:#6E6358">mín ${euros(tmin)} · máx ${euros(tmax)}</span>`)
      + `<div class="bars">${bars}</div><div class="axis"><span>0</span><span>6</span><span>12</span><span>18</span><span>23</span></div>`;
  } else {
    $("tomorrow").innerHTML = head("📅", "Luz mañana", "#F5A623") + `<p class="empty">Red Eléctrica publica el precio de mañana sobre las 20:30.</p>`;
  }
}

// ---------- Casa: calefacción, aire, temperaturas y música ----------

const deg = (v) => v == null ? "–" : v.toLocaleString(ES, { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const houseData = () => state.house?.data;

async function houseCommand(action, body, busyKey) {
  state.busy = busyKey;
  state.houseError = null;
  renderHouse();
  try {
    const r = await fetch(`/api/casa/${action}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    const data = await r.json();
    if (!r.ok) throw new Error(data.detail || "No se ha podido");
    state.house = data;
  } catch (e) {
    state.houseError = e.message || "No se ha podido";
  }
  state.busy = null;
  renderHouse();
}

// La consigna se cambia en la pantalla al momento y se envía 1 s después del último toque
function nudge(c, delta) {
  const cur = state.pending[c.entidad]?.value ?? c.consigna ?? c.actual ?? 20;
  const value = Math.min(c.max ?? 30, Math.max(c.min ?? 7, Math.round((cur + delta) / (c.paso || 0.5)) * (c.paso || 0.5)));
  clearTimeout(state.pending[c.entidad]?.timer);
  state.pending[c.entidad] = { value, timer: setTimeout(() => {
    delete state.pending[c.entidad];
    houseCommand("consigna", { entidad: c.entidad, grados: value }, c.entidad);
  }, 1000) };
  renderHouse();
}

function setpoint(c, big = false) {
  const value = state.pending[c.entidad]?.value ?? c.consigna;
  const off = c.modo === "off";
  return `<div class="sp${big ? " big" : ""}${off ? " off" : ""}">
    <button class="rb" data-nudge="${esc(c.entidad)}" data-d="-1" aria-label="Bajar consigna" ${off ? "disabled" : ""}>−</button>
    <span class="v">${off ? "–" : deg(value) + "°"}</span>
    <button class="rb" data-nudge="${esc(c.entidad)}" data-d="1" aria-label="Subir consigna" ${off ? "disabled" : ""}>+</button>
  </div>`;
}

function chipsFor(c, kind) {
  const items = kind === "preset" ? c.presets : c.modos;
  const current = kind === "preset" ? c.preset : c.modo;
  return `<div class="seg">${items.map((x) => `<button class="sg${x.id === current ? " on" : ""}" data-${kind}="${esc(x.id)}" data-entity="${esc(c.entidad)}"
    ${state.busy ? "disabled" : ""}>${esc(x.nombre)}</button>`).join("")}</div>`;
}

const heatingNow = (c) => c.accion === "heating";

function renderHeating(h) {
  if (!h?.termostato) { $("heating").innerHTML = head("🔥", "Calefacción", "#D9483B") + `<p class="empty">Añade el termostato en config.yaml (casa → calefaccion).</p>`; return; }
  const t = h.termostato;
  const status = !t.disponible ? "No disponible" : heatingNow(t) ? "🔥 Calentando" : t.modo === "off" ? "Apagada" : "En espera";
  const valves = (h.valvulas || []).map((v) => `<div class="room">
      <div class="who">${esc(v.nombre)}<small>${heatingNow(v) ? "🔥 calentando" : "en espera"}</small></div>
      <span class="now">${deg(v.actual)}°</span>${setpoint(v)}</div>`).join("");
  $("heating").innerHTML = head("🔥", `${h.nombre} · ${t.nombre}`, "#D9483B", `<span class="pill" style="--tint:${heatingNow(t) ? "#D9483B" : "#6E6358"}">${status}</span>`) + `
    <div class="thermo">
      <div><small>Ahora</small><b class="huge">${deg(t.actual)}°</b></div>
      <div class="target"><small>Consigna</small>${setpoint(t, true)}</div>
    </div>
    ${t.presets.length ? chipsFor(t, "preset") : ""}
    ${valves ? `<div class="sub-h">Habitaciones</div><div class="scroll">${valves}</div>` : ""}
    ${state.houseError ? `<p class="err">${esc(state.houseError)}</p>` : ""}`;
}

function renderAircon(list) {
  if (!list?.length) { $("aircon").hidden = true; return; }
  $("aircon").hidden = false;
  $("aircon").innerHTML = head("❄️", "Aire acondicionado", "#1E90E8") + list.map((a) => `
    <div class="ac${a.disponible ? "" : " na"}">
      <div class="ac-top"><div class="who">${esc(a.nombre)}<small>${a.disponible ? `ahora ${deg(a.actual)}°${a.accion === "cooling" ? " · enfriando" : a.accion === "heating" ? " · calentando" : ""}` : "no disponible"}</small></div>
        ${a.disponible ? setpoint(a) : ""}</div>
      ${a.disponible ? chipsFor(a, "modo") : ""}
    </div>`).join("");
}

function renderRooms(list) {
  $("rooms").innerHTML = head("🌡️", "Temperatura en casa", "#F5A623") + (list?.length
    ? `<div class="temps">${list.map((t) => `<div class="tcell"><small>${esc(t.nombre)}</small><b>${deg(t.temp)}°</b></div>`).join("")}</div>`
    : `<p class="empty">Añade sensores en config.yaml (casa → temperaturas).</p>`);
}

function renderMusic(m) {
  if (!m) { $("music").innerHTML = head("🎵", "Música", "#8E5BC8") + `<p class="empty">Añade el altavoz en config.yaml (casa → musica).</p>`; return; }
  const playing = m.estado === "playing";
  const na = m.estado === "unavailable";
  const status = na ? "No disponible" : playing ? "▶ Sonando" : m.titulo ? "⏸ En pausa" : "Sin música";
  const vol = m.volumen ?? 0;
  const dis = na || state.busy ? "disabled" : "";
  $("music").innerHTML = head("🎵", "Música", "#8E5BC8") + `
    <div class="track">
      <div class="art">🎵</div>
      <div class="meta"><b>${esc(m.titulo || "Nada sonando")}</b><span>${esc(m.artista || "")}</span>
        <small>${status} · ${esc(m.nombre)}</small></div>
    </div>
    <div class="player">
      <button class="rb" data-music="previous" aria-label="Anterior" ${dis}>⏮</button>
      <button class="rb play" data-music="play_pause" aria-label="${playing ? "Pausar" : "Reproducir"}" ${dis}>${playing ? "⏸" : "▶"}</button>
      <button class="rb" data-music="next" aria-label="Siguiente" ${dis}>⏭</button>
    </div>
    <div class="vol">
      <button class="rb sm" data-vol="-0.05" aria-label="Bajar volumen" ${dis}>🔉</button>
      <div class="vbar"><div style="width:${Math.round(vol * 100)}%"></div></div>
      <button class="rb sm" data-vol="0.05" aria-label="Subir volumen" ${dis}>🔊</button>
    </div>
    <p class="note" style="margin-top:auto">Para elegir qué suena: «Alexa, pon…» en la cocina.</p>`;
}

function renderHouse() {
  if (state.view !== "casa") return;
  const h = houseData();
  if (!h) {
    ["heating", "rooms", "music"].forEach((id) => { $(id).innerHTML = `<p class="empty">${state.house?.error ? "Home Assistant no responde." : "Cargando…"}</p>`; });
    $("aircon").hidden = true;
    return;
  }
  renderHeating(h.calefaccion);
  renderAircon(h.aire);
  renderRooms(h.temperaturas);
  renderMusic(h.musica);
  const all = [h.calefaccion?.termostato, ...(h.calefaccion?.valvulas || []), ...(h.aire || [])].filter(Boolean);
  const find = (id) => all.find((c) => c.entidad === id);
  const root = $("v-casa");
  root.querySelectorAll("[data-nudge]").forEach((b) => b.addEventListener("click", () => nudge(find(b.dataset.nudge), +b.dataset.d * (find(b.dataset.nudge).paso || 0.5))));
  root.querySelectorAll("[data-preset]").forEach((b) => b.addEventListener("click", () => houseCommand("preset", { entidad: b.dataset.entity, preset: b.dataset.preset }, b.dataset.entity)));
  root.querySelectorAll("[data-modo]").forEach((b) => b.addEventListener("click", () => houseCommand("modo", { entidad: b.dataset.entity, modo: b.dataset.modo }, b.dataset.entity)));
  root.querySelectorAll("[data-music]").forEach((b) => b.addEventListener("click", () => houseCommand("musica", { accion: b.dataset.music }, "music")));
  root.querySelectorAll("[data-vol]").forEach((b) => b.addEventListener("click", () => {
    const level = Math.min(1, Math.max(0, (h.musica?.volumen ?? 0) + +b.dataset.vol));
    houseCommand("musica", { accion: "volumen", nivel: level }, "music");
  }));
}

// ---------- Consumo eléctrico ----------

const watts = (w) => w == null ? "–" : w >= 1000 ? `${(w / 1000).toLocaleString(ES, { maximumFractionDigits: 2 })} kW` : `${Math.round(w)} W`;

function renderConsumption() {
  const block = state.power;
  const c = block?.data;
  if (!c) {
    const msg = block?.error ? "Home Assistant no responde." : block ? "Añade la sección «consumo» en config.yaml." : "Cargando…";
    ["power-now", "power-hours", "power-devices"].forEach((id) => { $(id).innerHTML = `<p class="empty">${msg}</p>`; });
    return;
  }
  const e = energy();
  const color = e?.now ? priceColor(e.now.eur_kwh, e.min, e.max) : "#6E6358";
  $("power-now").innerHTML = head("⚡", "Consumo ahora", "#F5A623",
    c.ahora_eur_h != null ? `<span class="pill solid" style="--tint:${color}">${euros(c.ahora_eur_h)} €/h</span>` : "") + `
    <div class="pnow"><b>${c.ahora_w == null ? "–" : c.ahora_w >= 1000 ? (c.ahora_w / 1000).toLocaleString(ES, { maximumFractionDigits: 2 }) : Math.round(c.ahora_w)}</b>
      <span>${c.ahora_w != null && c.ahora_w >= 1000 ? "kW" : "W"}</span></div>
    <p class="note">${[c.tension != null ? `${Math.round(c.tension)} V` : "", c.intensidad != null ? `${c.intensidad.toLocaleString(ES, { maximumFractionDigits: 1 })} A` : "",
      e?.now ? `luz a ${euros(e.now.eur_kwh)} €/kWh` : ""].filter(Boolean).join(" · ")}</p>` + staleNote(block);

  // Hoy hora a hora: barras de kWh del color del precio de esa hora
  const hours = c.horas || [];
  const maxK = Math.max(0.01, ...hours.map((h) => h.kwh));
  const priceOf = (t) => e?.today.find((p) => p.time === t)?.eur_kwh;
  const slots = Array.from({ length: Math.max(24, hours.length) }, (_, i) => hours[i]); // 25 el día del cambio de hora
  const bars = slots.map((h) => h
    ? `<div class="bar" style="height:${Math.max(3, (h.kwh / maxK) * 100)}%;background:${priceOf(h.time) != null ? priceColor(priceOf(h.time), e.min, e.max) : "#A6998A"}"
        title="${h.time.slice(11)} · ${h.kwh.toLocaleString(ES)} kWh"></div>`
    : `<div class="bar empty-bar"></div>`).join("");
  const total = c.hoy_kwh != null ? `<span class="pill" style="--tint:#3F7FD9">${c.hoy_kwh.toLocaleString(ES, { maximumFractionDigits: 1 })} kWh${c.hoy_eur != null ? ` · ${c.hoy_eur.toLocaleString(ES, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} €` : ""}</span>` : "";
  $("power-hours").innerHTML = head("📊", "Hoy, hora a hora", "#3F7FD9", total) + (hours.length
    ? `<div class="bars">${bars}</div><div class="axis"><span>0</span><span>3</span><span>6</span><span>9</span><span>12</span><span>15</span><span>18</span><span>21</span><span>23</span></div>
       <p class="note" style="margin-top:8px">Cada barra, del color del precio de la luz a esa hora.${c.horas_fuente === "potencia" ? " Calculado con la potencia de la casa." : ""}</p>`
    : `<p class="empty">Añade la potencia de la casa (consumo → potencia_total) o un contador de energía (consumo → energia_total) en config.yaml.</p>`);

  const devs = c.aparatos || [];
  const ref = Math.max(1, c.ahora_w || 0, ...devs.map((d) => d.w || 0));
  $("power-devices").innerHTML = head("🔌", "Por aparato", "#8E5BC8") + (devs.length
    ? `<div class="scroll">${devs.map((d) => `<div class="dev${d.disponible ? "" : " na"}">
        <div class="dev-top"><span>${esc(d.nombre)}</span><b>${d.disponible ? watts(d.w) : "sin datos"}</b></div>
        <div class="dbar"><div style="width:${d.disponible ? Math.min(100, ((d.w || 0) / ref) * 100) : 0}%"></div></div></div>`).join("")}</div>
       ${c.ahora_w ? `<p class="note">Las barras, sobre el total de la casa (${watts(c.ahora_w)}).</p>` : ""}`
    : `<p class="empty">Añade aparatos en config.yaml (consumo → aparatos).</p>`);
}

async function loadConsumption() {
  try { state.power = await getJSON("/api/consumo"); }
  catch (e) { console.warn(e); }
  if (state.view === "consumo") renderConsumption();
}

// ---------- Tareas: Recordatorios ----------

function dueLabel(v, now) {
  if (!v) return "";
  const d = new Date(v.length <= 10 ? v + "T00:00" : v);
  if (isNaN(d)) return "";
  const late = d < startOfDay(now);
  return `<span class="due${late ? " late" : ""}">${late ? "vencido " : ""}${esc(relDay(d, now).toLowerCase())}</span>`;
}

function listCard(l, now, ic, tint) {
  const items = l.items.length
    ? `<ul class="items">${l.items.map((i) => `<li><div class="grow">${esc(i.titulo)}${i.notas ? ` <small>${esc(i.notas)}</small>` : ""}</div>${i.panel ? `<span class="due from-panel">desde el panel</span>` : ""}${dueLabel(i.vence, now)}</li>`).join("")}</ul>`
    : `<p class="empty">${l.updated ? "No queda nada pendiente." : "Esta lista aún no ha llegado desde el iPhone."}</p>`;
  const old = l.updated && Date.now() / 1000 - l.updated > 12 * 3600
    ? `<p class="stale">Recibida por última vez ${relDay(new Date(l.updated * 1000), now)} a las ${hm(new Date(l.updated * 1000))}</p>` : "";
  const count = l.items.length ? `<span class="pill">${l.items.length}</span>` : "";
  return head(ic, l.nombre, tint, count) + `<div class="scroll">${items}</div>` + old;
}

function renderLists() {
  const now = new Date();
  const [shop, ...others] = lists();
  $("shopping").innerHTML = shop ? listCard(shop, now, "🛒", "#2E9E5B") : head("🛒", "Compra", "#2E9E5B") + `<p class="empty">Sin listas configuradas.</p>`;
  $("lists").innerHTML = others.length
    ? others.map((l) => `<article class="card fill">${listCard(l, now, "✅", "#3F7FD9")}</article>`).join("")
    : `<article class="card fill">${head("✅", "Tareas", "#3F7FD9")}<p class="empty">Añade más listas de Recordatorios en config.yaml.</p></article>`;
}

// ---------- Pintar ----------

function render() {
  tick();
  renderLockWeather();
  if (!state.user) return;
  switch (state.view) {
    case "hoy": renderBandWeather(); renderNext(); renderWeek(); renderHoyBottom(); break;
    case "calendario": renderCalendar(); break;
    case "tiempo": renderWeatherFull(); break;
    case "casa": renderHouse(); break;
    case "energia": renderEnergy(); renderCar(); renderTrips(); break;
    case "consumo": renderConsumption(); break;
    case "tareas": renderLists(); renderMenuList(); break;
  }
}

// ---------- Datos ----------

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

async function loadHome() {
  try { state.home = await getJSON("/api/hogar"); $("offline").hidden = true; }
  catch (e) { console.warn(e); $("offline").hidden = false; }
  render();
}

async function loadHouse() {
  try { state.house = await getJSON("/api/casa"); }
  catch (e) { console.warn(e); }
  if (state.view === "casa" && !state.busy && !Object.keys(state.pending).length) renderHouse();
}

async function loadTrips() {
  await Promise.all(state.users.map(async (u) => {
    try { state.trips[u.id] = (await getJSON(`/api/usuario/${encodeURIComponent(u.id)}`)).trayecto; }
    catch (e) { console.warn(e); }
  }));
  render();
}

async function start() {
  setupRail();
  $("modal-close").addEventListener("click", closeModal);
  $("modal").addEventListener("click", (e) => { if (e.target === $("modal")) closeModal(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeModal(); });
  tick();
  try {
    const info = await getJSON("/api/usuarios");
    state.users = info.usuarios;
    state.idleMs = (info.volver_al_bloqueo_s || 120) * 1000;
  } catch (e) { console.warn(e); $("offline").hidden = false; }
  renderAvatars();
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, resetIdle, { passive: true }));
  // Al girar el móvil, la curva del tiempo se vuelve a dibujar al tamaño nuevo
  let resizing;
  addEventListener("resize", () => { clearTimeout(resizing); resizing = setTimeout(render, 150); });
  await loadHome();
  loadMenu();
  loadHouse();
  setInterval(tick, 10_000);
  // La casa cambia más a menudo (alguien enciende el aire, cambia la canción): cada 15 s mientras se mira
  setInterval(() => { if (state.user && state.view === "casa") loadHouse(); }, 15_000);
  setInterval(() => { if (state.user && state.view === "consumo") loadConsumption(); }, 15_000);
  setInterval(() => { loadHome(); if (state.user) loadTrips(); }, REFRESH_MS);
  setInterval(loadMenu, 30 * 60_000);  // cambia el lunes; lo pasado a la compra se recoge al tocar
}

start();
