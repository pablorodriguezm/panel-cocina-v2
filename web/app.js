// Panel de cocina: bloqueo con avatares, vista común y la de cada persona. Sin dependencias ni compilación.
"use strict";

const $ = (id) => document.getElementById(id);
const REFRESH_MS = 60_000;
const ES = "es-ES";

const state = { list: null, users: [], user: null, home: null, mine: null, idleMs: 120_000, idleTimer: null, online: true };

// ---------- Utilidades ----------

const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const hm = (d) => d.toLocaleTimeString(ES, { hour: "2-digit", minute: "2-digit" });
const cap = (s) => s.charAt(0).toUpperCase() + s.slice(1);
const euros = (v) => v == null ? "–" : v.toLocaleString(ES, { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const localTime = (iso) => new Date(iso); // las horas de la luz vienen sin zona: el navegador las toma como locales

function dateLine(now) {
  const wd = cap(now.toLocaleDateString(ES, { weekday: "long" }));
  const rest = now.toLocaleDateString(ES, { day: "numeric", month: "long" });
  return `<b>${wd}</b> ${rest}`;
}

function dayLabel(d, today) {
  const diff = Math.round((new Date(d.getFullYear(), d.getMonth(), d.getDate()) - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86_400_000);
  if (diff === 0) return "Hoy";
  if (diff === 1) return "Mañana";
  return cap(d.toLocaleDateString(ES, { weekday: "long", day: "numeric", month: "short" }));
}

function relDay(d, now) {
  const l = dayLabel(d, now);
  return l === "Hoy" || l === "Mañana" ? l.toLowerCase() : l;
}

// WMO (Open-Meteo) → emoji
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

// Verde → ámbar → rojo según el precio entre el mínimo y el máximo del día (como priceColor del original)
function mix(a, b, t) {
  const p = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16));
  const [x, y] = [p(a), p(b)];
  return `rgb(${x.map((v, i) => Math.round(v + (y[i] - v) * t)).join(",")})`;
}
function priceColor(v, min, max) {
  const t = max > min ? Math.min(1, Math.max(0, (v - min) / (max - min))) : 0;
  return t < 0.5 ? mix("#3BA55C", "#F5A623", t * 2) : mix("#F5A623", "#D9483B", (t - 0.5) * 2);
}

function head(icon, title, tint, extra = "") {
  return `<div class="head" style="--tint:${tint}"><span class="ic">${icon}</span><h2>${esc(title)}</h2>${extra}</div>`;
}
function staleNote(block) {
  if (!block || !block.stale || !block.updated) return "";
  return `<p class="stale">Sin actualizar desde las ${hm(new Date(block.updated * 1000))}</p>`;
}

// ---------- Cielo ----------

function skyFor(now) {
  const daily = state.home?.tiempo?.data?.daily;
  const i = daily ? daily.time.indexOf(now.toLocaleDateString("sv-SE")) : -1;
  const rise = i >= 0 ? new Date(daily.sunrise[i]) : new Date(now.getFullYear(), now.getMonth(), now.getDate(), 8);
  const set = i >= 0 ? new Date(daily.sunset[i]) : new Date(now.getFullYear(), now.getMonth(), now.getDate(), 19);
  const m = 60_000;
  if (now < rise - 45 * m || now > +set + 60 * m) return "night";
  if (now < +rise + 60 * m) return "dawn";
  if (now < set - 60 * m) return "day";
  return "dusk";
}

// ---------- Reloj ----------

function tick() {
  const now = new Date();
  const sky = skyFor(now);
  $("lock").dataset.sky = sky;
  $("band").dataset.sky = sky;
  $("lock-clock").textContent = hm(now);
  $("clock").textContent = hm(now);
  $("lock-date").innerHTML = dateLine(now);
  $("date").innerHTML = dateLine(now);
}

// ---------- Bloqueo y personas ----------

function initial(u) { return esc(u.nombre.charAt(0).toUpperCase()); }
function faceStyle(u) { return `--c:${esc(u.color)}${u.foto ? `;background-image:url('${esc(u.foto)}')` : ""}`; }

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
  state.mine = null;
  renderAll();
  loadMine();
  resetIdle();
}

function lock() {
  state.user = null;
  state.list = null;
  $("main").hidden = true;
  $("lock").hidden = false;
}

function resetIdle() {
  clearTimeout(state.idleTimer);
  if (state.user) state.idleTimer = setTimeout(lock, state.idleMs);
}

// ---------- Tarjetas ----------

function renderLockWeather() {
  const w = state.home?.tiempo?.data;
  const luz = state.home?.luz?.data;
  if (w) {
    const c = w.current, d = w.daily;
    $("lock-weather").innerHTML = `<span class="big">${wmo(c.weather_code, c.is_day)} ${Math.round(c.temperature_2m)}°</span>
      <span>${Math.round(d.temperature_2m_min[0])}° / ${Math.round(d.temperature_2m_max[0])}°${d.precipitation_probability_max[0] >= 40 ? ` · lluvia ${d.precipitation_probability_max[0]} %` : ""}</span>`;
  }
  $("lock-power").textContent = luz?.now ? `Luz ahora: ${euros(luz.now.eur_kwh)} €/kWh` : "";
}

function renderWeather() {
  const w = state.home?.tiempo?.data;
  if (!w) { $("weather").innerHTML = `<p class="note">Sin datos del tiempo</p>`; return; }
  const c = w.current, d = w.daily;
  const rain = (p) => `<span class="rain${p >= 40 ? " wet" : ""}">💧 ${p ?? 0} %</span>`;
  let html = `<div class="wnow"><span class="icon">${wmo(c.weather_code, c.is_day)}</span>
    <span class="t">${Math.round(c.temperature_2m)}°</span>
    <span class="mm">${Math.round(d.temperature_2m_min[0])}° / ${Math.round(d.temperature_2m_max[0])}°</span>${rain(d.precipitation_probability_max[0])}</div>`;
  for (let i = 1; i < Math.min(6, d.time.length); i++) {
    const day = new Date(d.time[i] + "T12:00");
    html += `<div class="wday"><span class="d">${cap(day.toLocaleDateString(ES, { weekday: "short" }).replace(".", ""))}</span>
      <span class="icon">${wmo(d.weather_code[i])}</span><span class="mx">${Math.round(d.temperature_2m_max[i])}°</span>
      <span class="mn">${Math.round(d.temperature_2m_min[i])}°</span>${rain(d.precipitation_probability_max[i])}</div>`;
  }
  $("weather").innerHTML = html;
}

function renderCommute() {
  const block = state.mine?.trayecto;
  const t = block?.data;
  const u = state.user;
  if (!u) return;
  let body;
  if (!state.mine) body = `<p class="empty">Cargando…</p>`;
  else if (!t) body = `<p class="empty">Sin trayecto configurado para ${esc(u.nombre)}.</p>`;
  else body = `<div class="mins"><b>${t.minutos != null ? Math.round(t.minutos) : "–"}</b><span>min</span></div>
    ${t.ruta ? `<div class="route">Por ${esc(t.ruta)}</div>` : ""}`;
  $("commute").innerHTML = head("🚙", `Al ${(t?.destino || "trabajo").toLowerCase()}`, u.color) + body + staleNote(block);
}

function renderCalendar() {
  const block = state.home?.calendario;
  const startOf = (ev) => ev.all_day ? new Date(ev.start + "T00:00") : new Date(ev.start);
  const events = [...(block?.data || [])].sort((a, b) => startOf(a) - startOf(b));
  const now = new Date();
  let html = "";
  let last = "";
  for (const ev of events) {
    const start = startOf(ev);
    if (!ev.all_day && ev.end && new Date(ev.end) < now) continue; // ya terminado
    const label = dayLabel(start, now);
    if (label !== last) { html += `<div class="day-label">${esc(label)}</div>`; last = label; }
    html += `<div class="event"><span class="when">${ev.all_day ? "Todo el día" : hm(start)}</span>
      <div><div class="what">${esc(ev.title)}</div>${ev.location ? `<div class="where">${esc(ev.location)}</div>` : ""}</div></div>`;
  }
  if (!html) html = `<p class="empty">Nada en el calendario estos días.</p>`;
  $("calendar").innerHTML = head("📅", "Rim y Pablo", "#E8604C") + `<div class="scroll">${html}</div>` + staleNote(block);
}

function renderEnergy() {
  const block = state.home?.luz;
  const e = block?.data;
  const now = new Date();
  if (!e) {
    $("energy").innerHTML = head("⚡", "Luz", "#F5A623") + `<p class="empty">Sin precios todavía.</p>` + staleNote(block);
    return;
  }
  const pill = e.now ? `<span class="pill solid" style="--tint:${priceColor(e.now.eur_kwh, e.min, e.max)}">${euros(e.now.eur_kwh)} €</span>` : "";
  const bars = e.today.map((p) => {
    const t = localTime(p.time);
    const h = e.max > 0 ? Math.max(4, (p.eur_kwh / e.max) * 100) : 4;
    const cls = t.getHours() === now.getHours() ? "now" : (t < now ? "past" : "");
    return `<div class="bar ${cls}" style="height:${h}%;background:${priceColor(p.eur_kwh, e.min, e.max)}" title="${t.getHours()} h · ${euros(p.eur_kwh)} €"></div>`;
  }).join("");
  const recs = e.recommendations.map((r) => {
    if (!r.tramo) return "";
    const s = localTime(r.tramo.start), f = localTime(r.tramo.end);
    return `<div class="rec ok"><span class="e">${esc(r.emoji)}</span><div class="t"><small>${esc(r.nombre)}</small>
      <b>${relDay(s, now)} ${hm(s)}–${hm(f)}</b></div><span class="p">${euros(r.tramo.avg_eur_kwh)} €</span></div>`;
  }).join("");
  const wait = e.wait_for_tomorrow ? `<div class="rec"><span class="e">⏳</span><div class="t note">Lo que queda de hoy es caro: mejor esperar al precio de mañana (sale sobre las 20:30).</div></div>` : "";
  const avoid = e.avoid ? (() => {
    const s = localTime(e.avoid.start), f = localTime(e.avoid.end);
    return `<div class="rec bad"><span class="e">⛔</span><div class="t"><small>Mejor evitar</small><b>${hm(s)}–${hm(f)}</b></div><span class="p">${euros(e.avoid.avg_eur_kwh)} €</span></div>`;
  })() : "";
  $("energy").innerHTML = head("⚡", "Luz hoy", "#F5A623", pill) +
    `<div class="price-now"><b>${euros(e.avg)}</b><span>€/kWh de media · mín ${euros(e.min)} · máx ${euros(e.max)}</span></div>
     <div class="bars" aria-hidden="true">${bars}</div>
     <div class="axis"><span>0 h</span><span>6 h</span><span>12 h</span><span>18 h</span><span>23 h</span></div>
     <div class="recs scroll">${recs}${wait}${avoid}</div>
     ${e.tomorrow_known ? "" : `<p class="note">El precio de mañana se publica sobre las 20:30.</p>`}` + staleNote(block);
}

function gauge(level, color) {
  // Semicírculo como los «gauge» de Home Assistant
  const pct = Math.max(0, Math.min(1, (level ?? 0) / 100));
  const r = 62, cx = 75, cy = 78;
  const a = Math.PI * (1 - pct);
  const x = cx + r * Math.cos(a), y = cy - r * Math.sin(a);
  const bg = `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${cx + r} ${cy}`;
  const fg = pct > 0 ? `M ${cx - r} ${cy} A ${r} ${r} 0 0 1 ${x.toFixed(1)} ${y.toFixed(1)}` : "";
  return `<svg viewBox="0 0 150 84" aria-hidden="true"><path d="${bg}" stroke="#EFE6DA" stroke-width="16" fill="none" stroke-linecap="round"/>
    ${fg ? `<path class="fill" d="${fg}" stroke="${color}" stroke-width="16" fill="none" stroke-linecap="round"/>` : ""}</svg>`;
}

function renderCar() {
  const block = state.home?.coche;
  const c = block?.data;
  if (!c) { $("car").hidden = true; return; }
  $("car").hidden = false;
  const lvl = c.bateria;
  const color = c.cargando ? "#1E90E8" : lvl > 50 ? "#3BA55C" : lvl >= 20 ? "#F5A623" : "#D9483B";
  const status = c.cargando ? `Cargando${c.potencia_kw ? ` a ${c.potencia_kw.toLocaleString(ES, { maximumFractionDigits: 1 })} kW` : ""}`
    : c.enchufado ? "Enchufado, sin cargar" : "Desenchufado";
  const names = { del_izq: "Del. izq.", del_der: "Del. der.", tras_izq: "Tras. izq.", tras_der: "Tras. der." };
  const tires = c.ruedas ? `<div class="tires">${Object.entries(c.ruedas).map(([k, v]) =>
    `<span>${names[k] || esc(k)} <b>${v != null ? v.toLocaleString(ES, { maximumFractionDigits: 1 }) : "–"}</b></span>`).join("")}</div>` : "";
  $("car").className = `card${c.cargando ? " charging" : ""}`;
  $("car").innerHTML = head("🚗", c.nombre, color) + `<div class="car">
    <div class="gauge">${gauge(lvl, color)}<div class="pct">${lvl != null ? Math.round(lvl) + " %" : "–"}</div>
      <div class="rng">${c.autonomia != null ? Math.round(c.autonomia) + " " + esc(c.autonomia_unidad) : ""}</div></div>
    <div class="car-facts"><b>${status}</b>${c.limite_carga ? `<span>Límite de carga ${Math.round(c.limite_carga)} %</span>` : ""}
      ${c.km ? `<span>${Math.round(c.km).toLocaleString(ES)} km</span>` : ""}${tires}</div></div>` + staleNote(block);
}

function dueLabel(v, now) {
  if (!v) return "";
  const d = new Date(v.length <= 10 ? v + "T00:00" : v);
  if (isNaN(d)) return "";
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
  const late = d < today;
  return `<span class="due${late ? " late" : ""}">${late ? "vencido " : ""}${esc(relDay(d, now).toLowerCase())}</span>`;
}

function renderReminders() {
  const lists = state.home?.recordatorios?.data || [];
  const now = new Date();
  if (!lists.length) { $("shopping").innerHTML = head("🛒", "Compra", "#2E9E5B") + `<p class="empty">Sin listas configuradas.</p>`; return; }
  // Una pestaña por lista de Recordatorios; la primera (la compra) es la de siempre
  const active = lists.find((l) => l.nombre === state.list) || lists[0];
  const tabs = lists.length > 1 ? `<div class="tabs" role="tablist">${lists.map((l) =>
    `<button role="tab" class="tab${l === active ? " on" : ""}" data-list="${esc(l.nombre)}" aria-selected="${l === active}">${esc(l.nombre)}${l.items.length ? ` <b>${l.items.length}</b>` : ""}</button>`).join("")}</div>` : "";
  const body = active.items.length
    ? `<ul class="items">${active.items.map((i) => `<li><div>${esc(i.titulo)}${i.notas ? ` <small>${esc(i.notas)}</small>` : ""}${dueLabel(i.vence, now)}</div></li>`).join("")}</ul>`
    : `<p class="empty">${active.updated ? "No queda nada pendiente." : "Esta lista aún no ha llegado desde el iPhone."}</p>`;
  // Si el Atajo lleva mucho sin enviar, se avisa: la lista puede no estar al día
  const old = active.updated && Date.now() / 1000 - active.updated > 12 * 3600
    ? `<p class="stale">Recibida por última vez ${relDay(new Date(active.updated * 1000), now).toLowerCase()} a las ${hm(new Date(active.updated * 1000))}</p>` : "";
  const icon = active === lists[0] ? "🛒" : "✅";
  const tint = active === lists[0] ? "#2E9E5B" : "#3F7FD9";
  $("shopping").innerHTML = head(icon, lists.length > 1 ? "Recordatorios" : active.nombre, tint) + tabs + `<div class="scroll">${body}</div>` + old;
  $("shopping").querySelectorAll(".tab").forEach((b) => b.addEventListener("click", () => { state.list = b.dataset.list; renderReminders(); }));
}

function renderAll() {
  tick();
  renderLockWeather();
  if (!state.user) return;
  renderWeather();
  renderCommute();
  renderCalendar();
  renderEnergy();
  renderCar();
  renderReminders();
}

// ---------- Datos ----------

async function getJSON(url) {
  const r = await fetch(url, { cache: "no-store" });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

function setOnline(ok) {
  state.online = ok;
  $("offline").hidden = ok;
}

async function loadHome() {
  try { state.home = await getJSON("/api/hogar"); setOnline(true); }
  catch (e) { console.warn(e); setOnline(false); }
  renderAll();
}

async function loadMine() {
  if (!state.user) return;
  const id = state.user.id;
  try {
    const mine = await getJSON(`/api/usuario/${encodeURIComponent(id)}`);
    if (state.user?.id === id) state.mine = mine;
  } catch (e) { console.warn(e); }
  renderAll();
}

async function start() {
  tick();
  try {
    const info = await getJSON("/api/usuarios");
    state.users = info.usuarios;
    state.idleMs = (info.volver_al_bloqueo_s || 120) * 1000;
  } catch (e) { console.warn(e); setOnline(false); }
  renderAvatars();
  $("me").addEventListener("click", lock);
  ["pointerdown", "keydown"].forEach((ev) => document.addEventListener(ev, resetIdle, { passive: true }));
  await loadHome();
  setInterval(tick, 10_000);
  setInterval(() => { loadHome(); loadMine(); }, REFRESH_MS);
}

start();
