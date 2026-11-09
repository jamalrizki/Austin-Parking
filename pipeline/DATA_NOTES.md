# Data recon notes

Recon run 2026-11-08 from Jamal's Mac (portals reachable). Metadata, field lists and
counts below were fetched live, not copied from catalog text.

ArcGIS base: `https://services.arcgis.com/0L95CJ0VTaxqcmED/arcgis/rest/services`
Socrata base: `https://data.austintexas.gov`

## Summary

| Spec layer | Status | What was actually found |
|---|---|---|
| Street segments | **Confirmed** | Socrata `8hf2-pdmb`, 68,847 rows, has `segment_id`, `road_class`, block ranges. `m5w3-uea6` is the old map view of the same data (same `rowsUpdatedAt`). |
| Meters / pay stations / zones (item `1882302d…`) | **Confirmed, but superseded** | `Parking_Inventory/FeatureServer` (layers 0–3). A newer view, `Parking_Inventory_FME_UPDATE_view/FeatureServer/0`, is what the city's own web maps use, and it is much richer (see below). |
| RPP streets | **Found (spec said gap)** | Curb-level RPP zones exist in `Parking_Inventory_FME_UPDATE_view/0` (`PARKING_TYPE = 'Residential Parking Permit'`). RPP district polygons and RPP property polygons also exist. |
| District hours | **Found as data** | `PayToParkAreas/FeatureServer/0`: 18 polygons with per-day hours, incl. "East Austin, Mon-Sat 8AM-Midnight, Sunday Non-metered". Per-zone hours also exist as machine-readable JSON. |
| Off-street parking `nura-qkf6` | Confirmed (pointer) | Socrata entry is an href to ArcGIS item `1e9bc1bee554450089b057199bce9af4` (`Off_Street_Parking_Locations/FeatureServer`). Downtown only. Not inspected further (v1 out of scope). |
| Lot entrances `ij6a-fwpi` | Confirmed | 181 rows, point lat/long, `access_type`. Optional. |
| Transactions `5bb2-gtef` | Confirmed | 18,964,518 rows, live (latest row today). Fields: `id, source, duration_min, start_time, end_time, amount, meter_id, zone_id, zone_group, payment_method, location_name, updated_at`. No geometry; would need a join by `meter_id`/`zone_id`. |

## 1. Street Centerline — Socrata `8hf2-pdmb`

- Geometry: `the_geom` (Socrata line, WGS84). Rows: 68,847. 1,363 fall in the rough East Austin box.
- Fields: `objectid, segment_id, prefix_direction, prefix_type, street_name, street_type,
  suffix_direction, left_from_address, left_to_address, right_from_address, right_to_address,
  left_block_from, left_block_to, right_block_from, right_block_to, full_street_name,
  road_class, speed_limit, elevation_from, elevation_to, one_way, cad_id, street_place_id,
  created_date, created_by, modified_by, modified_date, miles, seconds, built_status,
  shape_length, posted_speed_limit`
- `road_class` is a **numeric code with no legend in the metadata**:
  6 (47,683), 8 (7,934), 4 (5,271), 15 (4,151), 5 (1,489), 10 (960), 2 (730), 1 (599),
  plus a few singletons. **OPEN: the code → class mapping (highway/ramp/alley/private) is
  unconfirmed.** Do not guess; exclusions.json can't be written until this is known.

## 2. Parking Inventory (spec's item `1882302d40784b94a9036260cf518a7c`)

`Parking_Inventory/FeatureServer`, all layers EPSG:2277 (TX Central ftUS):

| id | name | geom | rows |
|---|---|---|---|
| 0 | PayStations | point | 886 |
| 1 | Parking_Spaces | point | 10,500 |
| 2 | Parking_Zones | polyline | 3,886 |
| 3 | Block_Segments | polyline | 2,762 |

All have `SEGMENT_ID`, `FULL_STREET_NAME`, `BLOCK_NAME`, `RATE`, `TIME_LIMIT`, `STATUS`,
`HOURS_OF_OPERATION`, `ZONE_DESCRIPTION`. Zones/spaces add per-day `*_HOURS` smallints.

### 2a. Better layer: `Parking_Inventory_FME_UPDATE_view/FeatureServer/0` ("Parking_Zones")

Item `a9e9e0ce8ab94b888a4fb8c3d28433c3`. Used by the city's RPP Zones & Districts and
Parking Inventory web maps. Polyline, EPSG:3857, 5,642 rows, maxRecordCount 2000.

Fields: `OBJECTID, GlobalID, Shape__Length, PARKING_ZONE_ID, BLOCK_NAME, PARKING_TYPE,
HOURS_OF_OPERATION, MOBILE_PAY_ID, PARKING_ORIENTATION, PARKING_SPACES, SEGMENT_ID (string),
ALL_RESTRICTION_TYPES, ZONE_TYPE, TIME_LIMIT, ZONE_DESCRIPTION, COMMENTS, METER_ROUTE,
RPP_DISTRICT, DAY_HOUR_CONCATENATE`

- **`SEGMENT_ID` joins directly to centerline `segment_id`** (no snapping needed for these).
- `DAY_HOUR_CONCATENATE` is machine-readable hours, one JSON array per line:
  `[{"days": ["mon","tue"], "start_time": "08:00", "end_time": "18:00"}]\r\n[...]`
  `end_time "00:00"` means midnight.
- `BLOCK_NAME` encodes side of street, e.g. `COLORADO ST 401 EC` (east curb).
- `PARKING_TYPE` (20 values): Paystation Zone 1627, No Parking 1451, Unrestricted Parking 713,
  Residential Parking Permit 674, Mobile Pay 289, Marked ADA Zone 198, Customer Service Zone
  187, Commercial Service Zone 125, Valet 66, Time Limited 61, Special Reserved 58, Other 53,
  Passenger Loading 47, Bicycle 36, Bus Stop 25, Police Only 24, Pedicab 3, Reserved 3,
  Car2Go 1, Parking Meter Zone 1.
- `ALL_RESTRICTION_TYPES`: 78 comma-joined combos, e.g. `Unrestricted Parking,Residential
  Parking Permit` (502) — curb that is RPP during posted hours, open otherwise.
- `ZONE_TYPE`: Regular 4102, Flex 1214, Hybrid 286, None 40. **OPEN: meaning of Flex/Hybrid.**
- `RPP_DISTRICT`: color name (Green/Pink/Red/Orange/Teal/Blue/Purple/None). Present on paid
  zones too, so it looks like "district the zone sits in", not "this curb is RPP".
- `HOURS_OF_OPERATION`: 335 distinct human strings; top is `Mon-Sun: All Day` (2382).
- No `RATE` field in this view (the older layers have `RATE`).

East Austin box (-97.737..-97.700, 30.255..30.285) zone counts: Unrestricted 319,
No Parking 272, Paystation 211, RPP 132, Customer Service 30, ADA 29, others <16.
**Only 372 of ~1,363 centerline segments in the box have any zone record.**

## 3. RPP

- `Residential_Parking_Permits/FeatureServer/1` "RPP Districts": 7 polygons, fields
  `RPP_DISTRICT_ID, RPP_DISTRICT` (colour), last modified 2022-02-11. Districts, not streets.
- `RPP_Properties_Edit_View/FeatureServer/0`: 3,397 polygons, fields `BLOCK_NO, STREET_NAME,
  ZONE_NO, NO_PERMITS_ELIGIBLE, RESTRICTION_TIME_DATE, MAX_RESIDENTS, PERMIT_STATUS, ...`.
  Properties eligible for permits, not curb restrictions. Useful as a secondary signal.
- Curb-level RPP: section 2a above.

## 4. Pay-to-park areas

- `PayToParkAreas/FeatureServer/0`: 18 polygons, EPSG:2277. Fields `Op_Hours, Area_Inter,
  Area, Monday..Sunday, Labels, Area_SqFt, Link`. Three rows have null `Area`.
- `COA_Pay_To_Park_Areas/FeatureServer/9`: 17 rows, same content with ids and modified dates,
  EPSG:6578. Probably the authoritative source; PayToParkAreas looks like a copy.
- East Austin: `Mon-Sat: 8AM-Midnight`, Sunday `Non-metered`. Also a separate
  "Mexican American Cultural Center" area `Mon-Sat 8AM-3AM` and "IH-35 Lot" `Mon-Sat 7PM-3AM`.

## Resolutions (2026-11-08)

1. **road_class legend** — found as a coded-value domain on
   `TRANSPORTATION_street_segment/FeatureServer/0`: 0=A00 Unknown, 1=A10 Interstate/Fwy/Toll,
   2=A20 US & State Hwy, 4=A30 Major Arterial, 5=A31 Minor Arterial, 6=A40 Local, 8=A45 Collector,
   9=A61 Cul-de-sac, 10=A63 Ramps, 11=A73 Alley, 12=A74 Driveway, 13=ROW border, 14=A50 Unimproved,
   15=A60 Private, 16=A70 Service road, 17=A72 Platted/unbuilt. Exclusions in `rules/exclusions.json`.
   IH-35 frontage roads (`SVRD`) are not class 1/2/10, so they are excluded by name pattern.
2. **Streets with no zone record** render grey ("unknown — check signs"), per Jamal.
3. **Rule source** — per-zone hours from city data are primary. `rules/districts.json` holds
   holidays, rates and the East Austin district hours used as a cross-check in tests.
4. **ZONE_TYPE Flex / Hybrid** — Hybrid = mixed pay-to-park + RPP (city RPP page). Flex is not
   defined publicly. The app does not use ZONE_TYPE for logic; it uses PARKING_TYPE +
   ALL_RESTRICTION_TYPES + hours, and shows ZONE_TYPE only for reference.

## How a zone's rules are read (verified against data)

`PARKING_TYPE` is the restriction **during** the posted hours; the other entry in
`ALL_RESTRICTION_TYPES` (if exactly one) applies **outside** them. Evidence: zones with
`PARKING_TYPE=Unrestricted Parking`, `ALL_RESTRICTION_TYPES=Mobile Pay,Unrestricted Parking`,
hours `Mon-Wed 8PM-10AM, Thu-Sat 12MID-10AM, Sun All Day` are exactly the complement of
Mueller's posted paid hours (Mon-Wed 10AM-8PM, Thu-Sat 10AM-Midnight, Sunday free).

- Single-type zone outside its hours: free if the type is a restriction (paid, permit,
  no parking, loading); **grey** if the type is "Unrestricted" (nothing recorded for other times).
- 3+ restriction types (3 zones): grey.

## Hours data quality

Both `DAY_HOUR_CONCATENATE` (JSON) and `HOURS_OF_OPERATION` (text) are parsed
(`pipeline/hours.py`) and compared minute-by-minute across the week:

| result | zones | treatment |
|---|---|---|
| both agree | 5,427 | used |
| one field blank/garbled, other parses | 82 | used, card shows a caveat |
| fields disagree | 79 | grey: "city records list two different sets of hours" |
| event-day only (Q2 stadium) | 19 | grey |
| neither parses | 7 | grey |
| 3+ types | 3 | grey |

The JSON field is sometimes truncated mid-string or split one object per line; `"23:59"` and
`"00:00"` as an end time both mean midnight; day tokens include `thur`, `tues`, `event_days`.

## Other sources checked

- **OpenStreetMap** (`parking:*` tags via Overpass): 108 tagged ways in East Austin, mostly
  `parking:both=no`. Used as a secondary, clearly labelled "community data" layer only where no
  city zone is within 20 m. A side shows green only with an explicit `fee=no`; otherwise grey.
- **City paid-parking page** (austintexas.gov/transportation-public-works/paid-parking):
  holidays not enforced (New Year's, July 4, Labor Day, Thanksgiving, Christmas), rates, district
  hours. Encoded in `rules/districts.json`.
- **SpotAngels / ChiCurb**: neither documents its data sources publicly; nothing reusable found.
  Chicago's equivalent maps are built from that city's open RPP-zone data, the same approach
  as here.
- **RPP_Properties_Edit_View** (eligible properties) and RPP district polygons: fetched for
  reference, not used in the rules — the curb-level zones are more precise.

## Known limits

- Posted signs not in city data (temporary no-parking, construction, street cleaning, tow-away
  events) are not covered. The footer says so on every screen.
- Holiday observed-day shifts (e.g. July 4 on a Saturday) are not applied; the city page lists
  only the holiday itself.

## Citywide expansion (2026-11-08)

Jamal asked for all of Austin rather than East Austin first.

- Fetch area is now `rules/areas/austin.geojson` (a box around the city). City zones were already
  citywide; centerlines went from 1,562 to 57,993 fetched / 49,002 kept; OSM tagged ways from 108 to 1,362.
- `rules/areas/east-austin.geojson` is kept for reference (the v1 area in SPEC.md) but nothing uses it.
- Output was split for load speed: zones + OSM in `segments.json` (critical path), streets in a
  packed `streets.json` loaded after first paint. Street geometry is rounded to ~1 m and simplified
  within 1.5 m; zone/OSM geometry ~1 m and 0.5 m.
- Street segment IDs are no longer shipped to the browser (they were debug-only and cost ~150 KB).
