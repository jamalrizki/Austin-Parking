# Austin Free Parking Finder

A phone-friendly map that answers one question: **where can I park on the street for free, right now or at a time I pick?** Covers Austin city limits. No account, no ads, no pop-ups.

- Each side of each street is coloured separately: one side can be free while the other is not.
- **Green** = free now · **Amber** = free, but that ends within 2 hours · **Red** = no parking, paid, permit-only, or no room to park · **Dashed grey** = we don't have enough evidence either way.
- Green is only shown when there is positive evidence that curb parking exists on that side (see below). Absence of a "No Parking" sign is never enough on its own.
- Tap any street to see why it's that colour and which evidence it's based on.
- **Always check posted signs.** This map is a guide, not a guarantee.

Spec: [SPEC.md](SPEC.md) · Data findings and decisions: [pipeline/DATA_NOTES.md](pipeline/DATA_NOTES.md)

## The core problem

Knowing the rules is not enough; you also need to know where parking physically *exists*. Cities that do this well (Seattle, San Francisco) publish a "blockface" inventory saying, for each side of each block, whether there is curb parking. Austin does not publish one. Apps like SpotAngels fill the gap with crowdsourced sign photos.

This project builds that inventory from public data instead. Every street side is classified by the evidence available for it:

| Evidence | Effect |
|---|---|
| City curb zone (meter, permit, loading, etc.) | Coloured by that zone's rules and hours |
| Posted parking sign in the city's sign inventory | Coloured by the sign's rules |
| City lists a parking lane on that street (Transportation Network) | Parking exists |
| Wide local residential street (28 ft+, 2 lanes or fewer) | Parking exists |
| OpenStreetMap tags a parking lane on that side | Parking exists |
| **Parked cars seen at that curb in 2 or more aerial surveys** | Parking exists (local streets and collectors only) |
| "No Parking" sign, no curb space between driveways, median side of a divided road, too narrow, bike lane at the curb, OSM "no parking" | Red |
| None of the above | Dashed grey |

## Aerial parked-car detection (machine learning)

To fill gaps where the city has no records, we look for parked cars in public aerial photos.

- **Model.** A pretrained deep-learning object detector: [Ultralytics](https://github.com/ultralytics/ultralytics) YOLOv8m-OBB, trained on the DOTA aerial-imagery dataset, using its "small vehicle" and "large vehicle" classes. We use the model as-is: it is not retrained on Austin data.
- **Imagery.** Three public surveys, so a single snapshot can't decide the answer:
  - City of Austin 2023 aerials (~15 cm per pixel)
  - TxGIO StratMap 2020 (7.6 cm, downsampled to 15 cm to match the model)
  - TxGIO StratMap 2019 (15 cm)
- **Coverage.** Only image tiles that contain streets are processed: 26,852 tiles per survey, about 550,000 vehicles found across the 2023 and 2020 surveys.
- **Parked vs. moving.** A photo can't show motion, so this is decided by pattern, not per car:
  1. The car must be on the paved road (using the city's paved-road outlines, traced from the same imagery), at least 8 m from an intersection.
  2. Parked cars sit close to the edge of the road: we measured a median of 1.2 m for parked cars against 2.8 m for moving traffic. Only cars within 1.6 m of the edge count.
  3. A survey counts for a side only if at least 2 cars hug the curb there, and they outnumber cars further out in the lane by 2 to 1.
  4. At least **2 of the 3 surveys**, taken in different years, must agree.
- **Exclusion.** Arterial roads are excluded: cars next to a big road are usually in an adjacent lot or in traffic. This was found by spot-checking against the imagery.
- **Known limits.** A curb where people park illegally every day will look like parking (a No Parking sign in the city's records still wins). Heavy congestion hugging an unmarked edge in two separate years could fool it.

The detection runs locally, on a Mac's GPU, and is resumable: it can be stopped and restarted at any time. Results are stored compactly in `pipeline/cars/out/cars_<survey>.json.gz` (~2.6 MB each), so the weekly automated rebuild reuses them without re-running the model.

## How the site works

Static site, no backend. A Python pipeline (standard library only) downloads city and OpenStreetMap data and writes:

- `public/data/segments.json`: citywide curb zones (~0.3 MB gzipped). This loads first, so coloured curbs appear quickly.
- `public/data/streets.json`: every street in city limits, both sides, in a compact delta-encoded format (~0.56 MB gzipped), decoded by `public/streets.js`.

The browser evaluates the rules for any day and time (`public/engine.js`), including meter holidays and overnight windows. Colours are applied with MapLibre feature-state, so changing the time re-colours the whole city without re-uploading geometry.

| Data | Source |
|---|---|
| Curb zones with hours, type and side of street | City of Austin `Parking_Inventory_FME_UPDATE_view` |
| Posted parking signs, per side of street | City of Austin Sign Inventory (`Sign_Assets_Maint_Public_View`) |
| Parking lanes, pavement width, lane counts, bike lanes | City of Austin Comprehensive Transportation Network |
| Driveways and paved-road outlines | City of Austin `impervious_cover_2023` |
| Street centerlines | City of Austin Street Centerline `8hf2-pdmb` |
| Pay-to-park areas, residential permit districts | City of Austin ArcGIS layers |
| City limits | City of Austin `BOUNDARIES_jurisdictions` (full purpose) |
| Parking-lane tags | OpenStreetMap (Overpass API) |
| Aerial imagery | City of Austin 2023 aerials; TxGIO StratMap 2019 and 2020 |
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

### Re-running the aerial detection (optional)

Not needed for a normal build: the stored detections are used automatically. Needs a Python virtual environment with `ultralytics` (installs PyTorch, several GB) and the `yolov8m-obb.pt` weights in `pipeline/models/`. On an M1 Mac the city's 2023 survey took about 3½ hours; the 2020 survey took about 11 hours, limited by the state imagery server's download speed.

Start or resume:

```
.venv/bin/python pipeline/cars/run_city.py
```

Check progress:

```
.venv/bin/python pipeline/cars/run_city.py --status
```

Then rebuild with `python3 pipeline/build_segments.py`.

## Layout

```
pipeline/       fetch_layers.py, build_segments.py, sides.py (evidence per street side),
                signs.py (sign text → rules), hours.py, validate.py, DATA_NOTES.md
pipeline/cars/  detect.py, run_city.py (citywide resumable run), assign.py (cars → street sides), out/
rules/          zone_types.json, exclusions.json, districts.json, areas/austin.geojson
public/         index.html, app.js, engine.js, streets.js, styles.css, data/
tests/          engine.test.mjs, spot-checks.md
```

## Deploy

`.github/workflows/deploy.yml` deploys `public/` to GitHub Pages on every push to `main`, and every Monday re-fetches the city data, rebuilds, validates, runs the tests, and commits the new data if anything changed.

## Found a wrong street?

Tap it and use **Report a problem with this street**: it opens a pre-filled GitHub issue.

## Licences

Ultralytics YOLO is AGPL-3.0; it is used only in the offline data pipeline, not in the website. City of Austin and TxGIO data are public. OpenStreetMap data © OpenStreetMap contributors (ODbL).
