import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import { evaluate, toIndex, isMeterHoliday, meetsWindow, fmtUntil, nowIndex } from "../public/engine.js";

const types = JSON.parse(readFileSync(new URL("../rules/zone_types.json", import.meta.url)));

// East Austin meter: Mon-Sat 08:00-midnight (as the city encodes it).
const MON_SAT = [1, 2, 3, 4, 5, 6];
const eastPaid = { k: "z", t: "Paystation Zone", s: null, q: "ok", hrs: "Mon-Sat: 8AM-12MID",
  w: MON_SAT.map((d) => [d, 480, 1440]) };
// Nov 2026: Sun 8, Mon 9, Tue 10, Sat 14; Thanksgiving Thu 26.
const T = (d, h, m = 0, mo = 11, y = 2026) => toIndex(y, mo, d, h, m);

test("paid zone is red during enforcement with correct until", () => {
  const r = evaluate(eastPaid, types, T(9, 10));
  assert.equal(r.color, "red");
  assert.equal(r.until, T(10, 0)); // midnight Mon->Tue
  assert.equal(fmtUntil(T(9, 10), r.until), "midnight");
});

test("paid zone just before 8 AM is amber with until 8 AM", () => {
  const r = evaluate(eastPaid, types, T(9, 7, 0));
  assert.equal(r.color, "amber");
  assert.equal(r.until, T(9, 8));
});

test("midnight rollover: 00:30 Tuesday is free until 8 AM", () => {
  const r = evaluate(eastPaid, types, T(10, 0, 30));
  assert.equal(r.color, "green");
  assert.equal(r.until, T(10, 8));
});

test("23:59 Saturday still paid; Sunday free until Monday 8 AM", () => {
  assert.equal(evaluate(eastPaid, types, T(14, 23, 59)).color, "red");
  const r = evaluate(eastPaid, types, T(8, 10));
  assert.equal(r.color, "green");
  assert.equal(r.until, T(9, 8));
  assert.equal(fmtUntil(T(8, 10), r.until), "Mon 8 AM");
});

test("enforcement holidays", () => {
  assert.equal(isMeterHoliday(T(26, 12)), "Thanksgiving Day");
  assert.equal(isMeterHoliday(toIndex(2026, 9, 7, 12)), "Labor Day");
  assert.equal(isMeterHoliday(toIndex(2026, 7, 4, 12)), "Independence Day");
  assert.equal(isMeterHoliday(T(27, 12)), null);
  const r = evaluate(eastPaid, types, T(26, 12));
  assert.equal(r.color, "green");
  assert.match(r.title, /holiday/);
  assert.equal(r.until, T(27, 8)); // next day enforcement resumes at 8
});

test("Christmas falling on a weekday is free; day after is paid", () => {
  assert.equal(evaluate(eastPaid, types, toIndex(2026, 12, 25, 12)).color, "green");
  assert.equal(evaluate(eastPaid, types, toIndex(2026, 12, 26, 12)).color, "red");
});

test("overnight window crossing midnight (18:00-08:00) for RPP flex curb", () => {
  // Unrestricted Mon-Fri 6PM-8AM, permit-only otherwise (Willow Springs Rd pattern).
  const p = { k: "z", t: "Unrestricted Parking", s: "Residential Parking Permit", q: "ok",
    w: [1, 2, 3, 4, 5].map((d) => [d, 1080, 1920]) };
  assert.equal(evaluate(p, types, T(9, 12)).color, "red");     // Mon noon permit
  const night = evaluate(p, types, T(9, 23));                   // Mon 11 PM free
  assert.equal(night.color, "green");
  assert.equal(night.until, T(10, 8));
  assert.equal(evaluate(p, types, T(10, 3)).color, "green");   // Tue 3 AM (spill from Mon)
  assert.equal(evaluate(p, types, T(14, 3)).color, "green");   // Sat 3 AM (spill from Fri)
  assert.equal(evaluate(p, types, T(14, 12)).color, "red");    // Sat noon permit
  assert.ok(meetsWindow(night, "overnight", T(9, 23)));
});

test("secondary paid type is free on a holiday", () => {
  const p = { k: "z", t: "Unrestricted Parking", s: "Mobile Pay", q: "ok",
    w: [0, 1, 2, 3, 4, 5, 6].map((d) => [d, 1200, 1440 + 600]) };
  assert.equal(evaluate(p, types, T(25, 12)).color, "red");
  assert.equal(evaluate(p, types, T(26, 12)).color, "green");
});

test("single-type unrestricted zone is grey outside its hours (never assume free)", () => {
  const p = { k: "z", t: "Unrestricted Parking", s: null, q: "ok", hrs: "Mon-Sun: 6PM-8AM",
    w: [0, 1, 2, 3, 4, 5, 6].map((d) => [d, 1080, 1920]) };
  assert.equal(evaluate(p, types, T(9, 12)).color, "grey");
  assert.equal(evaluate(p, types, T(9, 20)).color, "green");
});

test("bad-quality zones and centerlines are never green", () => {
  for (const q of ["conflict", "none", "event", "complex"]) {
    assert.equal(evaluate({ ...eastPaid, q }, types, T(8, 10)).color, "grey");
  }
  assert.equal(evaluate({ k: "c", cov: false }, types, T(8, 10)).color, "grey");
  assert.equal(evaluate({ k: "o", v: "unknown" }, types, T(8, 10)).color, "grey");
});

test("time limit caps the free window", () => {
  const p = { k: "z", t: "Time Limited Parking", s: null, q: "ok", tl: 120, tlr: "2 hr",
    w: [0, 1, 2, 3, 4, 5, 6].map((d) => [d, 0, 1440]) };
  const r = evaluate(p, types, T(9, 12));
  assert.equal(r.freeMins, 120);
  assert.ok(meetsWindow(r, "120", T(9, 12)));
  assert.ok(!meetsWindow(r, "240", T(9, 12)));
});

test("nowIndex uses America/Chicago across DST", () => {
  // 2026-11-01 is DST end; 15:00 UTC on Nov 8 = 09:00 CST.
  assert.equal(nowIndex(new Date(Date.UTC(2026, 10, 8, 15, 0))), T(8, 9));
  // July: 15:00 UTC = 10:00 CDT.
  assert.equal(nowIndex(new Date(Date.UTC(2026, 6, 8, 15, 0))), toIndex(2026, 7, 8, 10));
});

// ---- acceptance checks against the real built data ----
const dataPath = new URL("../public/data/segments.geojson", import.meta.url);
test("real data: no missing-data segment renders green at any sampled time", { skip: !existsSync(dataPath) }, () => {
  const fc = JSON.parse(readFileSync(dataPath));
  const times = [];
  for (let d = 8; d <= 14; d++) for (const h of [0, 3, 7, 9, 13, 18, 23]) times.push(T(d, h));
  times.push(T(26, 12));
  let checked = 0;
  for (const f of fc.features) {
    const p = f.properties;
    const missing = p.k === "c" || (p.k === "z" && !["ok", "one"].includes(p.q)) || (p.k === "o" && p.v !== "free");
    if (!missing) continue;
    for (const t of times) {
      const c = evaluate(p, fc.meta.zone_types, t).color;
      assert.ok(c !== "green" && c !== "amber", `feature ${p.k}:${p.id || p.seg || p.osm} green at ${t}`);
      checked++;
    }
  }
  assert.ok(checked > 1000);
});

test("real data: East Austin paid curbs red Mon-Sat 08:00-23:59, green Sunday and after midnight", { skip: !existsSync(dataPath) }, () => {
  const fc = JSON.parse(readFileSync(dataPath));
  const east = fc.features.filter((f) => f.properties.k === "z" && f.properties.pa === "East Austin"
    && fc.meta.zone_types[f.properties.t]?.cat === "paid" && !f.properties.s && f.properties.q === "ok"
    && f.properties.hrs === "Mon-Sat: 8AM-12MID");
  assert.ok(east.length > 20, `expected East Austin paid zones, got ${east.length}`);
  for (const f of east) {
    const p = f.properties;
    for (const t of [T(9, 8), T(11, 14), T(14, 23, 59)]) assert.equal(evaluate(p, fc.meta.zone_types, t).color, "red");
    assert.notEqual(evaluate(p, fc.meta.zone_types, T(8, 12)).color, "red");     // Sunday
    assert.notEqual(evaluate(p, fc.meta.zone_types, T(10, 0, 30)).color, "red"); // Tue 00:30
  }
});
