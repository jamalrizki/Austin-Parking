# Austin Free Parking Finder — Build Spec

Nov 8, 2026 · @jamal

## Goal and scope

Build a phone-friendly web map that answers one question: where can I park on the street for free, right now or at a time I pick? Start with East Austin, then expand citywide. Paid rates and garages are a secondary layer.

Method (same idea as the Chicago "ChiCurb" app): take every street segment, subtract segments that are paid, permit-only or restricted at the chosen day/time, and color what remains green.

Design principles (Jamal found SpotAngels annoying and unreliable, so v1 must be the opposite):

- One screen, map first, no account, no sign-up, no ads, no pop-ups.
- Honest confidence: every segment says why it is green or red and where that came from; unknown is shown as unknown, never as free.
- Fast on a phone: precomputed static data, loads in under 2 seconds on LTE.
- Default view = "free now near me"; everything else is optional.

Out of scope for v1: real-time open-spot detection, payments, native iOS/Android apps.

## Read first: data sources and what is unverified

None of these datasets have been downloaded or inspected yet. The IDs below come from public catalog listings (data.gov mirrors of data.austintexas.gov). Field names, geometry types and coverage are unknown. Claude Code's first task is to fetch each one and confirm it before writing any app logic.

| Layer | Source | Status | Notes |
|---|---|---|---|
| Street segments (base map) | Street Centerline, 8hf2-pdmb | Listed in catalog, unverified | Newer listing (2025). Older ID m5w3-uea6 also exists; use whichever is current. Fallback: OpenStreetMap roads. |
| Meters, pay stations, paid zones | ArcGIS item 1882302d… | Listed in catalog, unverified | Catalog text says it holds pay stations, meters and parking zones. Need to find the FeatureServer URL and fields for hours/rates. |
| Garages and surface lots | Off-Street Parking, nura-qkf6 | Listed in catalog, unverified | Downtown only. Secondary layer. |
| Lot entrances/exits | ij6a-fwpi | Listed in catalog, unverified | Optional. |
| Parking transactions | 5bb2-gtef | Listed in catalog, unverified | Optional busyness layer. Catalog notes no ParkATX app transactions since Oct 2025, kiosk only, so it undercounts. |
| Residential Permit Parking (RPP) streets | No public dataset found | Gap | Highest risk. See below. |
| District hours (e.g., East Austin Mon–Sat 8 a.m.–midnight) | City paid-parking page | Read from web page | Must be hand-encoded into a rules file. |

### Known gaps to resolve before trusting the map

- RPP streets are the main ticket risk and no open dataset turned up. Options, in order: check the ArcGIS item above for an RPP or "parking zones" layer; search the city's ArcGIS org for "RPP" or "residential permit"; email transportation.data@austintexas.gov; otherwise ship v1 with RPP marked as "unknown — check signs" in East Austin rather than green.
- Posted signs (no parking, loading zones, time limits, tow-away) are not in any dataset found. The app must say "always check posted signs" and never claim certainty.
- Network access: the data portals were blocked from Claude's chat workspace. Run the fetch scripts locally on Jamal's machine via Claude Code.

## Free-parking logic

Each street segment gets a status for a given day and time. Rules are evaluated in this order; the first match wins.

1. Excluded road (highway, frontage road, ramp, alley, private road) → hidden, not shown as free.
2. RPP zone → red "Permit only", or grey "Unknown — check signs" if RPP coverage is unconfirmed for that area.
3. Paid zone, inside enforcement hours → red "Paid until HH:MM" (with rate if known).
4. Paid zone, outside enforcement hours → green "Free until HH:MM" (next enforcement start).
5. No known restriction → green "No paid or permit zone on record — check signs".
6. Missing data → grey, never green.

Matching a meter/zone to a street: join by segment ID if the parking layer has one; otherwise snap points/zone polygons to the nearest segment within ~15 m and the same street name.

Rules file: `rules/districts.json`, hand-maintained, one entry per district with zone IDs or polygon, days, start/end times, holidays not enforced, and a source URL plus a last_checked date. Example entry: East Austin, Mon–Sat 08:00–00:00, source = city paid-parking page.

Color legend: green = free now, amber = free but ends within 2 hours, red = paid or permit, grey = unknown.

## Features

### v1 (East Austin)

- Full-screen map, dark basemap, streets colored by the legend above.
- "Near me" button (browser geolocation; works without it too).
- Address/street search box.
- Day + time picker defaulting to now (like ChiCurb's slider).
- "Minimum free window" filter: any, 2h+, 4h+, overnight.
- Tap a street → card: street name and block range, status, free until/paid until, reason, data source and last-checked date.
- Persistent footer: "Always check posted signs."

### Later

- Citywide coverage, neighborhood quick-picks (East Austin, SoCo, Rainey, Mueller, Downtown, Zilker).
- Paid layer: rates, and a link to the Park ATX app to pay.
- Garages/lots layer.
- Busyness heatmap from kiosk transactions (labelled as partial).
- "Report a problem with this street" link (to a simple form or GitHub issue) to fix bad data.
- Installable PWA; native apps only if the web version proves useful.

## Architecture and stack

Static site, no backend: a Python pipeline builds GeoJSON once, and the browser does the time-of-day math.

| Part | Choice | Why |
|---|---|---|
| Data pipeline | Python 3 + geopandas + shapely + requests | Fetch, clean, snap and join layers; output small GeoJSON |
| Output | public/data/segments.geojson (geometry + segment rules, not precomputed per hour) | Browser evaluates rules for any day/time |
| Map | MapLibre GL JS + free CARTO dark basemap | Same stack as ChiCurb; no API key |
| Frontend | Plain HTML/JS or Vite + vanilla TS | Small, fast, easy to host |
| Hosting | GitHub Pages (or self-host behind Cloudflare Tunnel on the homelab) | Free, matches existing AI playground setup |
| Refresh | GitHub Action, weekly: re-run pipeline, commit new data if changed | Keeps zones current |

Repo layout:

```
pipeline/   fetch_*.py, build_segments.py, validate.py
rules/      districts.json, exclusions.json
public/     index.html, app.js, styles.css, data/
tests/      rule-engine tests
```

## Build steps for Claude Code

Before you start: run on a machine with open internet access (the city portals must be reachable). Requires Python 3.11+, Node 20+, git. Do not invent field names: if a dataset's schema differs from this spec, stop and report what you found.

1. Scaffold the repo layout above; add a README and this spec as SPEC.md.
2. Recon the data (no app code yet). For each source in the data table: fetch metadata and 5 sample rows, record geometry type, CRS, row count and fields in pipeline/DATA_NOTES.md. For the ArcGIS item, find its FeatureServer layers and list them. Search the city ArcGIS org for an RPP layer. Report findings to Jamal before step 3.
3. Fetch scripts that download each confirmed layer as GeoJSON to pipeline/raw/ (paginate ArcGIS queries; use SoQL $limit/$offset on Socrata).
4. Clip to East Austin (bounding polygon roughly I-35 to Airport Blvd, Lady Bird Lake to MLK; store it in rules/areas/east-austin.geojson).
5. Build segments: filter excluded road classes, join meters/zones and RPP to segments, attach the rule from rules/districts.json, write public/data/segments.geojson. Keep it under ~5 MB.
6. Rule engine (JS) with unit tests: given a segment and a datetime (America/Chicago), return status, label and "until" time. Cover midnight rollover, Sunday, and enforcement holidays.
7. Map UI per the Features list; mobile first; test at 390 px width.
8. Validate: spot-check 10 East Austin blocks against Google Street View or a walk, log results in tests/spot-checks.md.
9. Deploy to GitHub Pages; add the weekly refresh Action.
10. Expand citywide once East Austin checks pass.

## Acceptance checks

- [ ] Every data source in the table is confirmed or marked as a gap in DATA_NOTES.md.
- [ ] No segment with missing data renders green.
- [ ] East Austin paid streets show red Mon–Sat 08:00–23:59 and green on Sunday and after midnight.
- [ ] Tapping any segment shows its reason and source.
- [ ] Page loads and becomes usable in under 2 s on a phone over LTE.
- [ ] Works with location permission denied.
- [ ] 10 real-world spot checks logged; any mismatch fixed or marked grey.

## Sources

- City of Austin paid parking
- Park ATX
- Parking Transactions (data.gov listing)
- Off-Street Parking (data.gov listing)
- Street Centerline (data.gov listing)
