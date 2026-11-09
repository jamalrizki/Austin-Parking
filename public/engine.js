// Rule engine: given a feature's properties and a wall-clock time in Austin,
// return its colour, label, reason and "until" time.
//
// Time is a "local minute index": minutes since 1970-01-01 00:00 *Austin wall clock*
// (computed with Date.UTC on local parts). Rules are written in wall-clock terms,
// so this sidesteps DST entirely.

export const AMBER_MINUTES = 120;
const DAY = 1440;
const HORIZON_DAYS = 8;
const DOW = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

export function toIndex(y, mo, d, h = 0, mi = 0) {
  return Math.floor(Date.UTC(y, mo - 1, d, h, mi) / 60000);
}

export function fromIndex(t) {
  const dt = new Date(t * 60000);
  return { y: dt.getUTCFullYear(), mo: dt.getUTCMonth() + 1, d: dt.getUTCDate(),
           h: dt.getUTCHours(), mi: dt.getUTCMinutes(), dow: dt.getUTCDay() };
}

export function nowIndex(date = new Date()) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Chicago", year: "numeric", month: "numeric", day: "numeric",
    hour: "numeric", minute: "numeric", hourCycle: "h23",
  }).formatToParts(date).map((p) => [p.type, p.value]));
  return toIndex(+parts.year, +parts.month, +parts.day, +parts.hour % 24, +parts.minute);
}

// ---- meter holidays (rules/districts.json: holidays_not_enforced) ----
function nthWeekday(y, mo, dow, n) {
  const first = new Date(Date.UTC(y, mo - 1, 1)).getUTCDay();
  return 1 + ((dow - first + 7) % 7) + 7 * (n - 1);
}

export function isMeterHoliday(t) {
  const { y, mo, d } = fromIndex(t);
  if (mo === 1 && d === 1) return "New Year's Day";
  if (mo === 7 && d === 4) return "Independence Day";
  if (mo === 12 && d === 25) return "Christmas Day";
  if (mo === 9 && d === nthWeekday(y, 9, 1, 1)) return "Labor Day";
  if (mo === 11 && d === nthWeekday(y, 11, 4, 4)) return "Thanksgiving Day";
  return null;
}

// ---- formatting ----
export function fmtTime(t) {
  const { h, mi } = fromIndex(t);
  const ap = h < 12 ? "AM" : "PM";
  const hh = h % 12 === 0 ? 12 : h % 12;
  return mi === 0 ? `${hh} ${ap}` : `${hh}:${String(mi).padStart(2, "0")} ${ap}`;
}

export function fmtUntil(now, until) {
  if (until == null) return "all week";
  const a = fromIndex(now), b = fromIndex(until);
  const sameDay = a.y === b.y && a.mo === b.mo && a.d === b.d;
  if (until - now <= DAY && fromIndex(until).h === 0 && fromIndex(until).mi === 0) return "midnight";
  return sameDay ? fmtTime(until) : `${DOW[b.dow]} ${fmtTime(until)}`;
}

// ---- zone evaluation ----
const RED_CATS = new Set(["paid", "permit", "noparking", "loading", "ada"]);

function dayStart(t) { return Math.floor(t / DAY) * DAY; }

// Concrete window instances [start, end) overlapping [from, to).
function instances(windows, from, to) {
  const out = [];
  for (let ds = dayStart(from) - DAY; ds < to; ds += DAY) {
    const dow = fromIndex(ds).dow;
    for (const [d, a, b] of windows) {
      if (d === dow) out.push([ds + a, ds + b]);
    }
  }
  return out;
}

function zoneState(p, types, t, inst) {
  const active = inst.some(([a, b]) => a <= t && t < b);
  const cat = (name) => (types[name] ? types[name].cat : "other");
  let name = active ? p.t : p.s;
  let c = name ? cat(name) : "none";
  if (c === "paid") {
    const hol = isMeterHoliday(t);
    if (hol) return { key: "holiday", c: "holiday", name, hol };
  }
  if (c === "none") {
    // Outside the posted hours of a single-type zone.
    if (cat(p.t) === "free" || cat(p.t) === "other") return { key: "unrecorded", c: "unrecorded", name: null };
    return { key: "outside", c: "outside", name: p.t };
  }
  return { key: `${c}|${name}`, c, name };
}

function describe(st, p, types) {
  const label = st.name && types[st.name] ? types[st.name].label : st.name;
  switch (st.c) {
    case "holiday": return { color: "green", title: "Free (meter holiday)", reason: `Meters aren't enforced on ${st.hol}.` };
    case "outside": return { color: "green", title: "Free now", reason: `${label} only during posted hours (${p.hrs || "see sign"}). Outside those hours the city lists no restriction.` };
    case "free": return { color: "green", title: "Free now", reason: p.s && st.name === p.t ? `Unrestricted during posted hours; ${types[p.s]?.label?.toLowerCase() || p.s} otherwise.` : "City lists this curb as unrestricted parking." };
    case "timed": return { color: "green", title: "Free, time-limited", reason: `${label}${p.tlr ? ` (${p.tlr})` : ""}.` };
    case "paid": return { color: "red", title: "Paid", reason: `${label}.` };
    case "permit": return { color: "red", title: "Permit only", reason: `${label}${p.rpp ? ` (${p.rpp} district)` : ""}.` };
    case "noparking": case "loading": case "ada": return { color: "red", title: label, reason: `${label}.` };
    case "unrecorded": return { color: "grey", title: "Unknown", reason: `City records cover only the posted hours (${p.hrs || "?"}); nothing is recorded for other times.` };
    default: return { color: "grey", title: "Unknown", reason: `Restriction type "${st.name}" isn't something this map can interpret.` };
  }
}

export function evaluateZone(p, types, t) {
  if (!["ok", "one"].includes(p.q)) {
    return { color: "grey", title: "Unknown — check signs", reason: p.note || "Hours missing in city data.", until: null };
  }
  const end = t + HORIZON_DAYS * DAY;
  const inst = instances(p.w, t, end);
  const st = zoneState(p, types, t, inst);
  // Next change: check every window boundary and midnight (holidays flip at midnight).
  const cands = new Set();
  for (const [a, b] of inst) { if (a > t && a < end) cands.add(a); if (b > t && b < end) cands.add(b); }
  for (let m = dayStart(t) + DAY; m < end; m += DAY) cands.add(m);
  // "Until" tracks what matters to a driver: free stays free across a change of reason
  // (e.g. holiday -> outside meter hours at midnight); restrictions compare exactly.
  const FREE = new Set(["holiday", "outside", "free", "timed"]);
  const group = (s) => (FREE.has(s.c) ? "free" : s.key);
  let until = null;
  for (const c of [...cands].sort((x, y) => x - y)) {
    if (group(zoneState(p, types, c, inst)) !== group(st)) { until = c; break; }
  }
  const d = describe(st, p, types);
  return { ...d, until, cat: st.c, caveat: p.q === "one" ? p.note : null };
}

export function evaluateOsm(p) {
  const map = {
    free: { color: "green", title: "Free (community data)" },
    no: { color: "red", title: "No parking" },
    paid: { color: "red", title: "Paid" },
    permit: { color: "red", title: "Permit only" },
    unknown: { color: "grey", title: "Unknown — check signs" },
  };
  const m = map[p.v] || map.unknown;
  return { ...m, reason: p.why, until: null, caveat: "Community-mapped in OpenStreetMap; not verified by the city." };
}

// ---- street sides from the city sign inventory ----
// code: -2 surveyed, no parking signs; -3 no sign records; >=0 entry index (see public/streets.js).
const RANK = { red: 3, grey: 2, amber: 1, green: 0 };
const group = (c) => (c === "green" || c === "amber" ? "free" : c);

function ruleResults(rules, types, t) {
  return rules.map((r) => evaluate({ k: "z", t: r.t, s: null, w: r.w, q: r.q, tl: r.tl,
    tlr: r.tl ? (r.tl % 60 ? `${r.tl} min` : `${r.tl / 60} hr`) : null, hrs: "the hours on the sign", note: r.note }, types, t));
}

function combine(results) {
  let worst = results[0];
  for (const r of results) if (RANK[r.color] > RANK[worst.color]) worst = r;
  const free = results.filter((r) => r.color === "green" || r.color === "amber");
  return { ...worst, freeMins: worst.color === "green" || worst.color === "amber" ? Math.min(...free.map((r) => r.freeMins)) : 0 };
}

export function evaluateSide(code, tables, types, t) {
  const surveyed = tables.surveyYears ? `${tables.surveyYears[0]}–${tables.surveyYears[2]}` : "";
  if (code === -3 || code == null || code === -1) {
    return { color: "grey", title: "No sign records", until: null, freeMins: 0, signs: [],
      reason: "The city has no sign records for this block, so this map can't tell what's posted here." };
  }
  const entry = code >= 0 ? tables.entries[code] : [[], []];
  const signs = entry[1].map((i) => tables.messages[i]);
  const rules = entry[0].map((i) => tables.rules[i]);
  if (!rules.length) {
    return { color: "green", title: "No parking signs", until: null, freeMins: Infinity, signs, cat: "nosigns",
      reason: `The city's sign records (collected ${surveyed}) show no parking-restriction signs on this side of the block. Austin doesn't post "free parking" signs; an unsigned curb is open parking.`
        + (signs.length ? " The signs listed below cover only a few spaces." : "") };
  }
  const now = combine(ruleResults(rules, types, t));
  const cands = [...new Set(ruleResults(rules, types, t).map((r) => r.until).filter((x) => x != null))].sort((a, b) => a - b);
  let until = null;
  for (const c of cands) {
    if (group(combine(ruleResults(rules, types, c)).color) !== group(now.color)) { until = c; break; }
  }
  const freeMins = now.color === "green" || now.color === "amber" ? Math.min(now.freeMins, until == null ? Infinity : until - t) : 0;
  let color = now.color, title = now.title;
  if (color === "green" && freeMins < AMBER_MINUTES) { color = "amber"; title = title.replace("Free now", "Free, ending soon"); }
  return { color, title, reason: now.reason, until, freeMins, signs, cat: now.cat,
    caveat: "Based on posted signs in the city's sign records. A sign may cover only part of the block." };
}

export function evaluateCenterline(p) {
  return { color: "grey", title: "No sign records", until: null,
    reason: "The city has no sign records for this block, so this map can't tell what's posted here." };
}

export function evaluate(p, types, t) {
  let r;
  if (p.k === "z") r = evaluateZone(p, types, t);
  else if (p.k === "o") r = evaluateOsm(p);
  else r = evaluateCenterline(p);
  // Free-window length, capped by any time limit.
  if (r.color === "green") {
    let mins = r.until == null ? Infinity : r.until - t;
    if (p.k === "z" && p.tl && (r.cat === "timed" || r.cat === "free")) mins = Math.min(mins, p.tl);
    r.freeMins = mins;
    if (mins < AMBER_MINUTES) { r.color = "amber"; r.title = r.title.replace("Free now", "Free, ending soon"); }
  } else {
    r.freeMins = 0;
  }
  return r;
}

// Minimum-free-window filter. "overnight" = free until at least 8 AM next morning.
export function meetsWindow(r, filter, t) {
  if (filter === "any") return true;
  if (!(r.color === "green" || r.color === "amber")) return false;
  if (filter === "overnight") {
    const { h } = fromIndex(t);
    const target = dayStart(t) + (h < 8 ? 0 : DAY) + 8 * 60;
    return r.freeMins >= target - t;
  }
  return r.freeMins >= Number(filter);
}
