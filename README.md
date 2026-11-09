# Austin Free Parking Finder

A phone-friendly map that answers one question: **where can I park on the street for free, right now or at a time I pick?** Covers all of Austin. No account, no ads, no pop-ups.

- Green = free now (city record) · Light green = free unless signed (no meter or permit zone on record, outside paid areas) · Amber = free but ends within 2 hours · Red = paid, permit-only, or no parking · Dashed grey = unknown
- Each side of the street is coloured separately when the city records it that way.
- Tap any street to see why it's that colour, where the data came from, and when it was fetched.
- **Always check posted signs.** This map is a guide, not a guarantee.

Spec: [SPEC.md](SPEC.md) · Data findings and decisions: [pipeline/DATA_NOTES.md](pipeline/DATA_NOTES.md)

## How it works

Static site, no backend. A Python pipeline (standard library only) downloads city and OpenStreetMap data and writes two files:

- `public/data/segments.json`: citywide curb zones and OSM curb tags (~0.34 MB gzipped). This loads first, so coloured curbs appear quickly.
- `public/data/streets.json`: citywide street centerlines in a compact delta-encoded format (~0.72 MB gzipped), decoded by `public/streets.js`. This loads after first paint and draws the dashed grey "unknown" base.

The browser evaluates the rules for any day and time (`public/engine.js`). Colours are applied with MapLibre feature-state, so changing the time re-colours ~7,400 curbs in tens of milliseconds without re-uploading geometry.

Files are `.json` rather than `.geojson` so static hosts reliably gzip them.

| Data | Source |
|---|---|
| Curb zones with hours, paid/permit/no-parking type, side of street | City of Austin `Parking_Inventory_FME_UPDATE_view` (ArcGIS) |
| Street centerlines (grey "unknown" base) | City of Austin Street Centerline `8hf2-pdmb` |
| Pay-to-park area outlines | City of Austin `COA_Pay_To_Park_Areas` |
| Community curb tags where the city has none | OpenStreetMap `parking:*` |
| Meter holidays, rates | City paid-parking page, encoded in `rules/districts.json` |

## Run it locally

Requires Python 3.11+ and Node 20+.

```
npm run build-data
```

```
npm test
```

```
npm run serve
```

Then open http://localhost:8080.

## Layout

```
pipeline/   fetch_layers.py, hours.py, build_segments.py, validate.py, DATA_NOTES.md
rules/      zone_types.json, exclusions.json, districts.json, areas/austin.geojson (fetch area)
public/     index.html, app.js, engine.js, streets.js, styles.css, data/
tests/      engine.test.mjs, spot-checks.md
```

## Deploy

`.github/workflows/deploy.yml` deploys `public/` to GitHub Pages on every push to `main`, and every Monday re-fetches the data, validates it, runs the tests, and commits the new data if anything changed.

## Found a wrong street?

Tap it and use **Report a problem with this street** — it opens a pre-filled GitHub issue.
