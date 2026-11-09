import { evaluate, evaluateSide, meetsWindow, nowIndex, toIndex, fromIndex, fmtUntil } from "./engine.js";

const REPO = "jamalrizki/Austin-Parking";
const PARK_ATX = "https://parkatx.com";
const START = { center: [-97.7330, 30.2660], zoom: 14 };
const AUSTIN_BBOX = "-97.94,30.10,-97.56,30.52";
const COLORS = { green: "#22c55e", amber: "#f5a524", red: "#ef4444", grey: "#6b7280" };
const DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { data: null, streets: null, compassSide: null, types: {}, t: nowIndex(), live: true, filter: "any", selected: null };
const saved = (() => { try { return localStorage.getItem("minWindow"); } catch { return null; } })();
if (saved) state.filter = saved;

// ---------- map ----------
const map = new maplibregl.Map({
  container: "map",
  style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
  center: START.center, zoom: START.zoom, minZoom: 10, maxZoom: 19,
  attributionControl: { compact: true },
  dragRotate: false, pitchWithRotate: false,
});
map.touchZoomRotate.disableRotation();
window.parkingMap = map; // handy for debugging in devtools

// Critical path: curb zones (small). Citywide grey streets load after first paint.
const getJSON = (u) => fetch(u).then((r) => { if (!r.ok) throw new Error(`${u} ${r.status}`); return r.json(); });
const dataReady = getJSON("data/segments.json");

const CLICK_LAYERS = ["zones", "side-L", "side-R", "side-L-none", "side-R-none"];
const width = (base) => ["interpolate", ["linear"], ["zoom"], 12, base * 0.5, 15, base, 18, base * 2.4];
// Colours live in feature-state so changing the time only updates states, never re-uploads geometry.
const C = ["feature-state", "c"];
const color = ["match", ["coalesce", C, "grey"], "green", COLORS.green, "amber", COLORS.amber, "red", COLORS.red, COLORS.grey];
const opacity = ["case", ["boolean", ["feature-state", "dim"], false], 0.18, 1];

map.on("load", async () => {
  let fc;
  try { fc = await dataReady; } catch (e) { toast("Couldn't load parking data. Try reloading."); return; }
  state.data = fc;
  state.types = fc.meta.zone_types;
  fc.features.forEach((f, i) => { f.id = i; });
  setAsOf(fc.meta.built_from_fetch);

  map.addSource("areas", { type: "geojson", data: "data/areas.json" });
  map.addLayer({ id: "areas-line", type: "line", source: "areas",
    paint: { "line-color": "#60a5fa", "line-opacity": 0.25, "line-width": 1, "line-dasharray": [2, 2] } });

  // Every street side from the city sign inventory. Each side is its own layer, offset ~5 m
  // from the centreline (same place the city's curb zones sit). Colour comes from feature-state
  // for sides with sign rules; "no parking signs" sides default to green, "no records" are dashed grey.
  map.addSource("streets", { type: "geojson", data: { type: "FeatureCollection", features: [] }, tolerance: 0.5 });
  const sideOffset = (dir) => ["interpolate", ["exponential", 2], ["zoom"], 12, 0.3 * dir, 16, 2.7 * dir, 17, 5.4 * dir, 19, 21.6 * dir];
  for (const [S, dir] of [["L", -1], ["R", 1]]) {
    const code = ["get", S];
    map.addLayer({ id: `side-${S}`, type: "line", source: "streets", minzoom: 11,
      filter: ["any", ["==", code, -2], [">=", code, 0]],
      layout: { "line-cap": "butt" },
      paint: { "line-color": ["match", ["coalesce", ["feature-state", `${S}c`], "green"],
                 "green", COLORS.green, "amber", COLORS.amber, "red", COLORS.red, COLORS.grey],
               "line-width": width(2.6), "line-offset": sideOffset(dir),
               "line-opacity": ["case", ["boolean", ["feature-state", `${S}d`], false], 0.18, 0.9] } });
    map.addLayer({ id: `side-${S}-none`, type: "line", source: "streets", minzoom: 12, filter: ["==", code, -3],
      layout: { "line-cap": "butt" },
      paint: { "line-color": "#a3abb8", "line-width": 1.6, "line-offset": sideOffset(dir), "line-opacity": 0.7, "line-dasharray": [1.5, 1.5] } });
  }
  map.addLayer({ id: "sel-st", type: "line", source: "streets", filter: ["==", ["id"], -1],
    paint: { "line-color": "#ffffff", "line-width": width(9), "line-opacity": 0.3 } }, "side-L");

  map.addSource("seg", { type: "geojson", data: fc });
  map.addLayer({ id: "zones", type: "line", source: "seg", filter: ["==", ["get", "k"], "z"],
    layout: { "line-cap": "round" },
    paint: { "line-color": color, "line-width": width(3.5), "line-opacity": opacity } });
  map.addLayer({ id: "sel", type: "line", source: "seg", filter: ["==", ["id"], -1],
    paint: { "line-color": "#ffffff", "line-width": width(7), "line-opacity": 0.35 } }, "zones");

  for (const id of CLICK_LAYERS) {
    map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", onMapClick);
  render();
  loadStreets();
});

async function loadStreets() {
  try {
    const [mod, packed] = await Promise.all([import("./streets.js"), getJSON("data/streets.json")]);
    state.compassSide = mod.compassSide;
    state.streets = mod.decodeStreets(packed);
    map.getSource("streets").setData(state.streets.fc);
    streetIndex = null; // rebuild search index with all streets
    renderStreets();
  } catch (e) {
    console.error(e);
    toast("Couldn't load the street layer; coloured curbs still work.");
  }
}

function onMapClick(e) {
  const pad = 10;
  const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
  const hits = map.queryRenderedFeatures(box, { layers: CLICK_LAYERS.filter((l) => map.getLayer(l)) });
  if (!hits.length) { closeCard(); return; }
  // City curb zones first, then signed street sides; nearest-drawn wins among equals.
  hits.sort((a, b) => (a.layer.id === "zones" ? 0 : 1) - (b.layer.id === "zones" ? 0 : 1));
  const h = hits[0];
  if (h.layer.id === "zones") openCard("seg", h.id);
  else openCard("streets", h.id, h.layer.id.includes("-L") ? "L" : "R");
}

// ---------- evaluation + render ----------
function render() {
  if (!state.data) return;
  if (state.live) state.t = nowIndex();
  const feats = state.data.features;
  for (let i = 0; i < feats.length; i++) {
    const r = evaluate(feats[i].properties, state.types, state.t);
    map.setFeatureState({ source: "seg", id: i }, { c: r.color, dim: !meetsWindow(r, state.filter, state.t) });
  }
  renderStreets();
  if (state.selected) openCard(state.selected.src, state.selected.id, state.selected.side);
}

// Only sides with sign rules change with time; "no parking signs" sides are always free.
function renderStreets() {
  if (!state.streets) return;
  const { fc, tables, withRules } = state.streets;
  for (const id of withRules) {
    const p = fc.features[id].properties;
    const st = {};
    for (const S of ["L", "R"]) {
      if (p[S] < 0) continue;
      const r = evaluateSide(p[S], tables, state.types, state.t);
      st[`${S}c`] = r.color;
      st[`${S}d`] = !meetsWindow(r, state.filter, state.t);
    }
    map.setFeatureState({ source: "streets", id }, st);
  }
}

// ---------- card ----------
function openCard(src, id, side) {
  const f = src === "streets" ? state.streets?.fc.features[id] : state.data.features[id];
  if (!f) return;
  state.selected = { src, id, side };
  map.setFilter("sel", ["==", ["id"], src === "seg" ? id : -1]);
  map.setFilter("sel-st", ["==", ["id"], src === "streets" ? id : -1]);
  const p = src === "streets" ? { ...f.properties, side: state.compassSide(f.geometry, side) } : f.properties;
  const r = src === "streets" ? evaluateSide(p[side], state.streets.tables, state.types, state.t) : evaluate(p, state.types, state.t);
  const meta = state.data.meta;
  let until = "";
  if (r.color === "green" || r.color === "amber") until = r.until == null ? "Free all week (no change in the next 8 days)" : `Free until ${fmtUntil(state.t, r.until)}`;
  else if (r.color === "red") until = r.until == null ? "All week" : `Until ${fmtUntil(state.t, r.until)}`;
  const where = [p.blk, p.side].filter(Boolean).join(" · ");
  const srcName = meta.sources[p.src] || p.src;
  const rows = [];
  if (p.k === "z") {
    rows.push(["Posted hours", p.hrs || "—"]);
    if (p.s) rows.push(["Outside hours", state.types[p.s]?.label || p.s]);
    if (p.tlr && p.tlr !== "All Day") rows.push(["Time limit", p.tlr]);
    if (p.sp) rows.push(["Spaces", p.sp]);
    if (p.pa) rows.push(["Pay area", p.pa]);
    if (p.rpp) rows.push(["RPP district", p.rpp]);
    if (p.cmt) rows.push(["City note", p.cmt]);
    rows.push(["Zone ID", p.id]);
  }
  const sy = state.streets?.tables.surveyYears;
  rows.push(["Source", src === "streets" ? `City of Austin sign inventory${sy ? ` (collected ${sy[0]}–${sy[2]})` : ""}` : srcName]);
  rows.push(["Data fetched", localDate(meta.built_from_fetch)]);

  const issue = new URL(`https://github.com/${REPO}/issues/new`);
  issue.searchParams.set("title", `Data problem: ${p.st || "street"} ${p.blk || ""} ${p.side || ""}`.trim());
  issue.searchParams.set("body", `Location: ${p.st} ${where}\nMap says: ${r.title} — ${r.reason}\nFeature: ${src === "streets" ? `street ${p.st} ${p.blk || ""} ${side}` : `zone ${p.id}`}\nWhen viewed: ${describeTime()}\n\nWhat the signs actually say:\n`);

  $("cardBody").innerHTML = `
    <h2>${esc(p.st || "Street")}</h2>
    <div class="sub">${esc(where || "")}</div>
    <div class="status"><span class="dot ${r.color}"></span>${esc(r.title)}</div>
    ${until ? `<p><strong>${esc(until)}</strong>${state.live ? "" : ` <span style="color:var(--muted)">(${esc(describeTime())})</span>`}</p>` : ""}
    <p>${esc(r.reason)}</p>
    ${r.caveat ? `<p class="caveat">${esc(r.caveat)}</p>` : ""}
    ${r.signs && r.signs.length ? `<p class="signs-h">Signs on this side</p><ul class="signs">${r.signs.map((m) => `<li>${esc(m)}</li>`).join("")}</ul>` : ""}
    <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("")}</dl>
    <div class="links">
      ${r.cat === "paid" ? `<a href="${PARK_ATX}" target="_blank" rel="noopener">Pay with Park ATX</a>` : ""}
      <a href="${esc(issue.toString())}" target="_blank" rel="noopener">Report a problem with this street</a>
    </div>`;
  $("card").hidden = false;
}

function closeCard() {
  state.selected = null;
  $("card").hidden = true;
  if (map.getLayer("sel")) { map.setFilter("sel", ["==", ["id"], -1]); map.setFilter("sel-st", ["==", ["id"], -1]); }
}
$("close").addEventListener("click", closeCard);

// ---------- time controls ----------
function buildDayOptions() {
  const sel = $("day");
  const today = fromIndex(nowIndex());
  const base = toIndex(today.y, today.mo, today.d);
  sel.innerHTML = "";
  for (let i = 0; i < 7; i++) {
    const di = fromIndex(base + i * 1440);
    const o = document.createElement("option");
    o.value = String(base + i * 1440);
    o.textContent = i === 0 ? "Today" : i === 1 ? "Tomorrow" : `${DOW[di.dow]} ${di.mo}/${di.d}`;
    sel.appendChild(o);
  }
}

function syncControls() {
  const t = fromIndex(state.t);
  const dayBase = toIndex(t.y, t.mo, t.d);
  $("day").value = String(dayBase);
  $("time").value = `${String(t.h).padStart(2, "0")}:${String(t.mi).padStart(2, "0")}`;
  $("now").classList.toggle("on", state.live);
  $("now").style.opacity = state.live ? 0.5 : 1;
}

function fromControls() {
  const [h, m] = ($("time").value || "00:00").split(":").map(Number);
  state.t = Number($("day").value) + h * 60 + m;
  state.live = false;
  syncControls();
  render();
}
$("day").addEventListener("change", fromControls);
$("time").addEventListener("change", fromControls);
$("now").addEventListener("click", () => { state.live = true; buildDayOptions(); render(); syncControls(); });

function describeTime() {
  const t = fromIndex(state.t);
  return `${DOW[t.dow]} ${t.mo}/${t.d} ${fmtUntil(state.t - 1, state.t).replace(/^\w+ /, "")}`;
}

document.querySelectorAll(".seg button").forEach((b) => {
  b.addEventListener("click", () => {
    state.filter = b.dataset.w;
    try { localStorage.setItem("minWindow", state.filter); } catch { /* private mode */ }
    markFilter();
    render();
  });
});
function markFilter() {
  document.querySelectorAll(".seg button").forEach((x) => {
    const on = x.dataset.w === state.filter;
    x.classList.toggle("on", on);
    x.setAttribute("aria-checked", String(on));
  });
}

// Keep "now" fresh.
setInterval(() => { if (state.live) { render(); syncControls(); } }, 60000);

// ---------- near me ----------
let meMarker = null;
$("locate").addEventListener("click", () => {
  if (!("geolocation" in navigator)) { toast("Location isn't available in this browser."); return; }
  $("locate").classList.add("busy");
  navigator.geolocation.getCurrentPosition((pos) => {
    $("locate").classList.remove("busy");
    const ll = [pos.coords.longitude, pos.coords.latitude];
    if (!meMarker) {
      const el = document.createElement("div");
      el.style.cssText = "width:16px;height:16px;border-radius:50%;background:#60a5fa;border:3px solid #fff;box-shadow:0 0 0 6px rgba(96,165,250,.25)";
      meMarker = new maplibregl.Marker({ element: el });
    }
    meMarker.setLngLat(ll).addTo(map);
    map.flyTo({ center: ll, zoom: Math.max(map.getZoom(), 16.5) });
  }, (err) => {
    $("locate").classList.remove("busy");
    toast(err.code === 1 ? "Location permission denied — search or pan the map instead." : "Couldn't get your location.");
  }, { enableHighAccuracy: true, timeout: 10000, maximumAge: 60000 });
});

// ---------- search: local streets first, then OpenStreetMap geocoder ----------
const results = $("results");
let searchTimer = null;
let streetIndex = null;

const PLACES = [
  { label: "East Austin", center: [-97.7225, 30.2645], zoom: 15 },
  { label: "Downtown", center: [-97.7430, 30.2685], zoom: 15.5 },
  { label: "Rainey Street", center: [-97.7385, 30.2585], zoom: 16.3 },
  { label: "South Congress", center: [-97.7495, 30.2490], zoom: 15.5 },
  { label: "Mueller", center: [-97.7055, 30.2985], zoom: 15.3 },
  { label: "Zilker", center: [-97.7710, 30.2665], zoom: 15 },
  { label: "West Campus", center: [-97.7465, 30.2895], zoom: 15.5 },
  { label: "Hyde Park", center: [-97.7290, 30.3050], zoom: 15 },
];

function buildStreetIndex() {
  const m = new Map();
  const add = (f) => {
    const name = f.properties.st;
    if (!name || f.properties.k === "o") return;
    const g = f.geometry;
    const lines = g.type === "LineString" ? [g.coordinates] : g.coordinates;
    let e = m.get(name);
    if (!e) { e = { name, lc: name.toLowerCase(), minx: 180, miny: 90, maxx: -180, maxy: -90 }; m.set(name, e); }
    for (const line of lines) for (const [x, y] of line) {
      if (x < e.minx) e.minx = x; if (y < e.miny) e.miny = y; if (x > e.maxx) e.maxx = x; if (y > e.maxy) e.maxy = y;
    }
  };
  state.data.features.forEach(add);
  if (state.streets) state.streets.fc.features.forEach(add);
  return [...m.values()];
}

function showResults(items) {
  results.innerHTML = items.map((it, i) => `<li data-i="${i}">${esc(it.label)}${it.sub ? `<small>${esc(it.sub)}</small>` : ""}</li>`).join("");
  results.hidden = !items.length;
  results.querySelectorAll("li").forEach((li) => li.addEventListener("click", () => {
    const it = items[Number(li.dataset.i)];
    results.hidden = true;
    $("q").blur();
    if (it.bbox) map.fitBounds(it.bbox, { padding: 60, maxZoom: 17 });
    else map.flyTo({ center: it.center, zoom: it.zoom || 17 });
  }));
}

async function search(q) {
  if (!state.data) return;
  streetIndex ||= buildStreetIndex();
  const needle = q.toLowerCase().replace(/\b(street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd)\b\.?/g, "").trim();
  const ql = q.toLowerCase();
  const places = PLACES.filter((p) => p.label.toLowerCase().includes(ql)).map((p) => ({ ...p, sub: "Neighborhood" }));
  const local = needle.length < 2 ? [] : streetIndex
    .filter((s) => s.lc.includes(needle))
    .sort((a, b) => (b.lc.startsWith(needle) - a.lc.startsWith(needle)) || a.name.length - b.name.length)
    .slice(0, 6)
    .map((s) => ({ label: s.name, sub: "Street", bbox: [[s.minx, s.miny], [s.maxx, s.maxy]] }));
  local.unshift(...places);
  showResults(local);
  if (q.length < 4 || !/\d|,/.test(q)) return; // only geocode things that look like addresses
  try {
    const u = new URL("https://nominatim.openstreetmap.org/search");
    u.search = new URLSearchParams({ q: `${q}, Austin, TX`, format: "jsonv2", limit: "4", viewbox: AUSTIN_BBOX, bounded: "1" });
    const res = await fetch(u, { headers: { Accept: "application/json" } });
    const js = await res.json();
    if ($("q").value !== q) return;
    const geo = js.map((g) => ({ label: g.display_name.split(",").slice(0, 2).join(","), sub: "Address", center: [Number(g.lon), Number(g.lat)] }));
    showResults([...local, ...geo]);
  } catch { /* offline or rate-limited: local results still shown */ }
}

const showPlaces = () => showResults(PLACES.map((p) => ({ ...p, sub: "Neighborhood" })));
$("q").addEventListener("focus", (e) => { if (!e.target.value.trim()) showPlaces(); });
$("q").addEventListener("blur", () => setTimeout(() => { results.hidden = true; }, 200));
$("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) { showPlaces(); return; }
  searchTimer = setTimeout(() => search(q), 350);
});
$("search").addEventListener("submit", (e) => {
  e.preventDefault();
  const first = results.querySelector("li");
  if (first) first.click();
});

// ---------- misc ----------
let toastTimer;
function toast(msg) {
  const el = $("toast");
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 4000);
}

function localDate(iso) {
  if (!iso) return "unknown";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleDateString("en-US", { timeZone: "America/Chicago", month: "short", day: "numeric", year: "numeric" });
}

function setAsOf(iso) {
  if (iso) $("asof").textContent = `City data as of ${localDate(iso)}.`;
}

buildDayOptions();
markFilter();
syncControls();
