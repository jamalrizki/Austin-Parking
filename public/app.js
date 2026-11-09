import { evaluate, meetsWindow, nowIndex, toIndex, fromIndex, fmtUntil } from "./engine.js";

const REPO = "jamalrizki/Austin-Parking";
const PARK_ATX = "https://parkatx.com";
const START = { center: [-97.7225, 30.2645], zoom: 14.6 };
const AUSTIN_BBOX = "-97.94,30.10,-97.56,30.52";
const COLORS = { green: "#22c55e", amber: "#f5a524", red: "#ef4444", grey: "#6b7280" };
const DOW = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const state = { data: null, types: {}, t: nowIndex(), live: true, filter: "any", selected: null };
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

const dataReady = fetch("data/segments.geojson").then((r) => {
  if (!r.ok) throw new Error(`data ${r.status}`);
  return r.json();
});

map.on("load", async () => {
  let fc;
  try { fc = await dataReady; } catch (e) { toast("Couldn't load parking data. Try reloading."); return; }
  state.data = fc;
  state.types = fc.meta.zone_types;
  fc.features.forEach((f, i) => { f.id = i; });
  setAsOf(fc.meta.built_from_fetch);

  map.addSource("areas", { type: "geojson", data: "data/areas.geojson" });
  map.addLayer({ id: "areas-line", type: "line", source: "areas",
    paint: { "line-color": "#60a5fa", "line-opacity": 0.25, "line-width": 1, "line-dasharray": [2, 2] } });

  map.addSource("seg", { type: "geojson", data: fc, generateId: false });
  const width = (base) => ["interpolate", ["linear"], ["zoom"], 12, base * 0.5, 15, base, 18, base * 2.4];
  const color = ["match", ["get", "_c"], "green", COLORS.green, "amber", COLORS.amber, "red", COLORS.red, COLORS.grey];
  const opacity = ["case", ["==", ["get", "_dim"], true], 0.18, 1];

  map.addLayer({ id: "centre", type: "line", source: "seg", filter: ["==", ["get", "k"], "c"],
    layout: { "line-cap": "butt" },
    paint: { "line-color": "#a3abb8", "line-width": ["case", ["get", "cov"], 1, 2],
             "line-opacity": ["case", ["get", "cov"], 0.3, 0.75], "line-dasharray": [1.5, 1.5] } });
  map.addLayer({ id: "osm", type: "line", source: "seg", filter: ["==", ["get", "k"], "o"],
    layout: { "line-cap": "round" },
    paint: { "line-color": color, "line-width": width(3), "line-opacity": opacity,
             "line-offset": ["interpolate", ["linear"], ["zoom"], 13, ["*", ["get", "off"], 1.5], 17, ["*", ["get", "off"], 6]] } });
  map.addLayer({ id: "zones", type: "line", source: "seg", filter: ["==", ["get", "k"], "z"],
    layout: { "line-cap": "round" },
    paint: { "line-color": color, "line-width": width(3.5), "line-opacity": opacity } });
  map.addLayer({ id: "sel", type: "line", source: "seg", filter: ["==", ["id"], -1],
    paint: { "line-color": "#ffffff", "line-width": width(7), "line-opacity": 0.35 } }, "centre");

  for (const id of ["zones", "osm", "centre"]) {
    map.on("mouseenter", id, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", id, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("click", onMapClick);
  render();
});

function onMapClick(e) {
  const pad = 10;
  const box = [[e.point.x - pad, e.point.y - pad], [e.point.x + pad, e.point.y + pad]];
  const hits = map.queryRenderedFeatures(box, { layers: ["zones", "osm", "centre"] });
  if (!hits.length) { closeCard(); return; }
  // Prefer city zones, then OSM, then centreline; among equals, nearest to the tap.
  const rank = { zones: 0, osm: 1, centre: 2 };
  hits.sort((a, b) => rank[a.layer.id] - rank[b.layer.id]);
  openCard(hits[0].id);
}

// ---------- evaluation + render ----------
function render() {
  if (!state.data) return;
  if (state.live) state.t = nowIndex();
  for (const f of state.data.features) {
    const r = evaluate(f.properties, state.types, state.t);
    f.properties._c = r.color;
    f.properties._dim = !meetsWindow(r, state.filter, state.t);
  }
  map.getSource("seg").setData(state.data);
  if (state.selected != null) openCard(state.selected);
}

// ---------- card ----------
function openCard(id) {
  const f = state.data.features[id];
  if (!f) return;
  state.selected = id;
  map.setFilter("sel", ["==", ["id"], id]);
  const p = f.properties;
  const r = evaluate(p, state.types, state.t);
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
  if (p.k === "c" && p.seg) rows.push(["Segment ID", p.seg]);
  if (p.k === "o") rows.push(["OSM way", `<a href="https://www.openstreetmap.org/way/${encodeURIComponent(p.osm)}" target="_blank" rel="noopener">${esc(p.osm)}</a>`]);
  rows.push(["Source", srcName]);
  rows.push(["Data fetched", localDate(meta.built_from_fetch)]);

  const issue = new URL(`https://github.com/${REPO}/issues/new`);
  issue.searchParams.set("title", `Data problem: ${p.st || "street"} ${p.blk || ""} ${p.side || ""}`.trim());
  issue.searchParams.set("body", `Location: ${p.st} ${where}\nMap says: ${r.title} — ${r.reason}\nFeature: ${p.k}:${p.id || p.seg || p.osm}\nWhen viewed: ${describeTime()}\n\nWhat the signs actually say:\n`);

  $("cardBody").innerHTML = `
    <h2>${esc(p.st || "Street")}</h2>
    <div class="sub">${esc(where || "")}</div>
    <div class="status"><span class="dot ${r.color}"></span>${esc(r.title)}</div>
    ${until ? `<p><strong>${esc(until)}</strong>${state.live ? "" : ` <span style="color:var(--muted)">(${esc(describeTime())})</span>`}</p>` : ""}
    <p>${esc(r.reason)}</p>
    ${r.caveat ? `<p class="caveat">${esc(r.caveat)}</p>` : ""}
    <dl>${rows.map(([k, v]) => `<dt>${esc(k)}</dt><dd>${k === "OSM way" ? v : esc(v)}</dd>`).join("")}</dl>
    <div class="links">
      ${r.cat === "paid" ? `<a href="${PARK_ATX}" target="_blank" rel="noopener">Pay with Park ATX</a>` : ""}
      <a href="${esc(issue.toString())}" target="_blank" rel="noopener">Report a problem with this street</a>
    </div>`;
  $("card").hidden = false;
}

function closeCard() {
  state.selected = null;
  $("card").hidden = true;
  if (map.getLayer("sel")) map.setFilter("sel", ["==", ["id"], -1]);
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

function buildStreetIndex() {
  const m = new Map();
  for (const f of state.data.features) {
    const name = f.properties.st;
    if (!name || f.properties.k === "o") continue;
    const coords = f.geometry.type === "LineString" ? f.geometry.coordinates : f.geometry.coordinates.flat();
    const e = m.get(name) || { name, minx: 180, miny: 90, maxx: -180, maxy: -90 };
    for (const [x, y] of coords) { e.minx = Math.min(e.minx, x); e.miny = Math.min(e.miny, y); e.maxx = Math.max(e.maxx, x); e.maxy = Math.max(e.maxy, y); }
    m.set(name, e);
  }
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
    else map.flyTo({ center: it.center, zoom: 17 });
  }));
}

async function search(q) {
  if (!state.data) return;
  streetIndex ||= buildStreetIndex();
  const needle = q.toLowerCase().replace(/\b(street|st|avenue|ave|road|rd|drive|dr|boulevard|blvd)\b\.?/g, "").trim();
  const local = needle.length < 2 ? [] : streetIndex
    .filter((s) => s.name.toLowerCase().includes(needle))
    .slice(0, 5)
    .map((s) => ({ label: s.name, sub: "Street on the map", bbox: [[s.minx, s.miny], [s.maxx, s.maxy]] }));
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

$("q").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if (!q) { results.hidden = true; return; }
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
