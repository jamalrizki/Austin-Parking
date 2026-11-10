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

## Revert of "free unless signed" (2026-11-08)

Jamal rejected recolouring unrecorded streets green from inference alone. Reverted (aed48d9).

## City sign inventory (2026-11-08)

`Sign_Assets_Maint_Public_View` (item 14445469b72342788bffa280fd356094): 268,087 sign assets
(layer 0: MUTCD code, SIGN_MESSAGE, PHOTO_URL, DATA_COLLECTION_DATE, ASSET_LOCATION_ID) and 78,398
sign locations (layer 1: SEGMENT_ID, coordinates). Mostly collected 2021, updated through 2026.

- 33,033 active signs mention PARK. `pipeline/signs.py` classifies the text: 24,800 become block
  rules (no parking 20.5k, permit 2.1k, pay 1.7k, time limit 270), 1,085 are spot signs (ADA,
  loading, bus stop, "here to corner": listed on the card, don't colour the block), the rest are
  street names / info. 22 rule signs are unreadable and render grey.
- Signs are tied to segments via ASSET_LOCATION_ID -> SEGMENT_ID (re-linked to the nearest street
  within 25 m if > 30 m away). Side of street = which side of the centreline the sign point is on.
- **Survey coverage:** inside Austin full-purpose city limits only 2.4% of segments have no sign
  records near them. Outside city limits (Pflugerville, West Lake Hills, county roads) ~98% have
  none: the city doesn't keep those streets' signs. The map now covers city limits only
  (`BOUNDARIES_jurisdictions`, `AUSTIN FULL PURPOSE`).
- A block counts as surveyed if it has sign records on it or within 30 m of either end.
- **Divided roads:** one-way carriageways (one_way FT/TF) whose side has no addresses and faces the
  same street's opposite carriageway within 45 m are median sides and are not drawn (2,854 sides).
- Mapillary (token in `.env`) was compared: in a 1.5 x 1 km East Austin box it classified 5 parking
  signs vs 654 in the city inventory. Not used.
- OpenStreetMap curb tags are no longer shown (second, unofficial source; conflicts only).

Per street side (inside city limits): no parking signs on record 44,197; sign rules 7,277;
city curb zones 2,734; median 2,854; no sign records 1,302.

## Physical room to park (2026-11-08)

Source: CTN `Comprehensive_Transportation_Network_Maint_Non_Edit_View` (SEGMENT_ID join; 53,280 of
57,993 centreline segments matched). Fields used: CROSS_SECTION_GENERAL / _DETAIL, PAVEMENT_WIDTH,
BICYCLE_FACILITY. No published legend for the cross-section codes; meanings were checked against
our own sign/zone data: `P` edges carry most paid zones (parking lane); general suffix `-OP` pairs
with `P-T-CL-T-P` (on-street parking) and `-N` with `T-CL-T` (none).

Width calibration on CTN 2-lane streets with a parking flag: under 24 ft, 3 with parking vs 114
without; 24-28 ft, 30 vs 154; 28 ft+, 2,456 vs 181.

Rules (only where no sign rule or curb zone applies):
- red "No parking space": `-N`, or travel/bike lane at both curbs with no P, or bike lane listed
  with no lane data, or pavement < 24 ft.
- green requires a listed parking lane or pavement >= 28 ft. Otherwise grey: 24-27 ft "room
  unconfirmed", or no CTN width "no street-width data".

Jamal's walk (La Calma Dr, La Posada Dr) found green sides with no physical parking. Both are
divided roads absent from CTN; that is what prompted the >= 28 ft / parking-lane requirement.

## Root cause and evidence model (2026-11-08)

Research (SpotAngels, Coord, Seattle/SF blockface data, Berlin OSM + aerial studies) showed every
working system first records where parking physically exists per curb side, then applies rules.
Austin publishes no such citywide inventory, so this map combines evidence:
- presence: city curb zones; signs that regulate parking (permit / pay / time limit); CTN listed
  parking lane (-OP, P edge); on local residential streets (class 6/9, <=2 lanes) 28 ft+ pavement
  with no restriction signs
- absence: No Parking signs; CTN -N or travel/bike lane at the curb; < 24 ft; no car-length gap
  between driveways/lots (impervious_cover_2023, 571,638 polygons) after 20 ft corner clearance
- collectors/arterials/multi-lane with no presence evidence: grey "parking not confirmed" (-11)
  (Cameron Rd, Norwood Park Blvd reports)
Next: OSM per-side parking tags as a labelled second source; parked-car detection on public aerial
imagery (City 2023 15 cm, StratMap 2019 15 cm, StratMap 2020 7.6 cm) as our own presence evidence.
Austin publishes no geolocated parking-citation data on its open-data portal (checked).

## Parked-car evidence: curb lines and traffic (2026-11-08)

- Street centrelines can sit several metres off the real roadway in the imagery (seen on Bethune
  Ave area tiles), so curb lines now come from `impervious_cover_2023` "Paved Road" outlines
  (12,277 polygons, traced from the same imagery). A car's side is the nearer paved edge measured
  across the road; only the segment's direction is used.
- Traffic in a curb lane sits near the edge too. Measured distance to the paved edge: parked cars
  on St. John's residential streets median 1.2 m (77% <= 1.5 m); moving traffic on Camino La Costa,
  Cameron Rd, La Posada, La Calma, IH-35 frontage median 2.8 m (21% <= 1.5 m). Rule per side and
  survey: >= 2 cars within 1.6 m of the edge and at least twice as many as cars further out.
  Evidence needs this in 2+ of the 3 surveys. Test area: 48 sides confirmed, all residential; none
  of Jamal's no-parking streets.
- Citywide detection runs locally and resumably (`pipeline/cars/run_city.py`), ~3 tiles/s for the
  2023 survey with 4 parallel downloads.

## 2026-11-09: citywide aerial detections (2023 + 2020)

- city2023: 26,852 street tiles, 388,014 vehicles; sm2020: 26,844 tiles (8 failed with HTTP 504,
  retried on the next run), 256,502 vehicles. sm2019 still running.
- Stored as `pipeline/cars/out/cars_<survey>.json.gz` (`{"source","c":[[lon,lat,conf]]}`, conf >= 0.5,
  ~2.6 MB each) so the weekly CI rebuild keeps the evidence. The raw 63 MB GeoJSON is no longer kept.
- 105k of 552k detections are curb-parked. With 2 surveys, 213 street sides moved from grey to green
  (parked cars at that curb in both years).
- Spot check against 2023 imagery: residential/collector samples (Dove Springs Dr, Brownie Dr,
  Forest Hill Dr, Dorchester Dr, Crestmont Dr) show cars parked along the curb. Cameron Rd 7800
  (5-lane arterial) was a false positive: cars in the adjacent lot. Arterials (road_class 4/5 and
  anything not 6/8/9) are now excluded from car evidence; they need a listed parking lane or OSM.
- None of the walked no-parking streets (La Calma, La Posada, Camino La Costa, Cameron Rd near
  Anderson, Norwood Park Blvd) gained green.

## 2026-11-09: code review fixes (take effect at the next rebuild)

Measured on a 4 x 4 km sample (St. John's / Windsor Park: 1,059 segments, 35,233 detections) unless
marked citywide. Old vs new code on the sample: 7 of 2,118 sides change, all green -> grey.

- **Parking lane listed at one curb only.** Citywide, 621 of the 2,797 kept segments with a listed
  lane have the `P` edge at one end of `CROSS_SECTION_DETAIL` and a travel/bike lane at the other
  (`P…BL` 167, `BL…P` 146, `OW…P` 120, `T…P` 45, `CTT…P` 44). Both sides used to count as having
  the lane. The string's order was tested against aerial cars: it is compass order, not the
  centreline's direction. On north-south streets the first code is the west curb in 103 of 115
  cases; on east-west streets it is inconclusive (63 of 112). Not used. Instead, per side: a curb
  zone or regulating sign on that side, or all-week No Parking signs on the other side only, or
  parked cars in more aerial surveys than the other side. Otherwise grey, code -13. Street width
  is not evidence on these blocks. `parking_lane` in streets.json is now 0 / 1 / 2 (2 = one curb).
- **Duplicate detections.** 2-3% of detections lie within 1.5 m of another (tile overlaps; the
  merge's 1 m rounding misses pairs that straddle a rounding boundary). One car counted twice could
  meet the 2-car rule: Hermitage Dr seg 2040132 was green from that alone. `assign.py` now drops
  repeats, keeping the most confident.
- **Spatial index.** `sides.Grid` registered only a line's vertices, so the middle of a long
  straight block was invisible to lookups: 2.5% of detections were dropped and mid-block driveways
  went unmatched (curb-space counts corrected on 130 of 2,118 sides, 4,421 -> 3,700 spaces).
- **Street direction on curves.** The piece of a segment used for a car's (or OSM way's) direction
  was chosen by distance to its infinite line: 7% of cars were measured across a line 20-90 degrees
  off. Now the nearest piece. Points on the outside of a bend are no longer treated as beyond the
  segment's end.
- **Silent loss of evidence.** The build no longer reads a leftover `curb_cars.json`; `assign.py`
  stops with an error if detections exist but `roads.jsonl` is missing; `validate.py` requires
  >= 1,500 sides with cars in 2+ surveys (2,843 today) and fails if any block in
  `rules/never_green.json` (the walked no-parking streets) is always-green.
- Checked and left alone: the 40 m limit on the on-pavement parity test (9 of 5,264 accepted cars
  were off the pavement, 1 of them counted as hugging the curb).
- Not changed, worth a look: `median_sides` accepts a carriageway that lies beyond the segment's
  end (17 of 124 median sides in the sample, upper bound). 802 always-green sides in the sample
  rest on "local street, 28 ft+" alone; 472 of them had no passing car survey.

## 2026-11-09: other sources found (not yet used)

From the city's ArcGIS directory (services.arcgis.com/0L95CJ0VTaxqcmED, 2,212 services) and the
city/state image servers:

- **More aerial years, same 0.5 ft resolution, same fast city server as 2023:**
  `AerialMosaics/Aerials2017`, `2018`, `2019`, `2021`, `2025` (maps.austintexas.gov/image). TxGIO
  also has `StratMap21_NCCIR_CapArea_Brazos_Kerr` (Jan 2021, 15 cm). With 2019/2020/2023 that
  makes up to 7 survey years. The evidence bits in streets.json hold 0-3 surveys only; more years
  need a wider field and a rule expressed as a share of surveys.
- **Painted parking markings:** `Markings_Specialty_Point_Read_Only`, SPECIALTY_POINT_TYPE = 5
  (Parking): 3,593 points (stall lines 1,739, "L" 1,290, "T" 492, handicap 51), each with
  SEGMENT_ID and a point location, so the side is known. 399 segments; 154 of them (1,128
  markings) have no city curb zone. Note the field's coded-value domain mislabels 4 as Parking;
  the subtype table is right (4 = Other: crosshatch, green bike pads; 5 = Parking).
- Listed but not yet examined: `Parking_Inventory` (vs the `_FME_UPDATE_view` in use),
  `On_Street_Parking_SXSW24`, `Parking_Lot_Entrances_and_Exits`, `TRANSPORTATION_bicycle_facilities`,
  `Transit_Bus_Stops_(Moped)_Public_View`, `2026_All_Hydrants_Map_WFL1` (15 ft hydrant rule),
  type-4 "Diagonal crosshatch" markings (painted no-parking areas).

## 2026-11-10: sm2019 complete; citywide rebuild with the review fixes

- All three surveys complete (26,852 tiles each; the 44 tiles that failed in a state-server outage
  were retried). Compact files, conf >= 0.5: sm2020 195,556 and sm2019 327,480 vehicles (the larger
  counts in run.log are the old merge, which kept every confidence). After removing repeats,
  852,295 detections; 169,760 curb-parked.
- Sides by number of surveys with parked cars: 0: 44,043; 1: 8,689; 2: 3,563; 3: 2,187.
- Changes vs the previous build (row by row): 226 sides turned green, 224 of them from parked cars
  now seen in 2+ surveys (mostly -11 collectors, also -9/-8). 161 lost green: 152 to the new
  "lane at one curb only" rule (-13; 158 sides in total), 6 to -11 (a repeated detection or a
  re-measured side lost its second survey), the rest to driveways/width codes.
- Spot check: 12 random newly green sides against the city's 2023 and 2025 aerials. 10 show cars
  parked along that curb; Wycliff Ln 12400 (42 ft collector, cars in 2019 + 2020, none since) and
  Crawford Ave 3700 east side (by a traffic island; parked-looking row in 2025) are plausible. None
  contradicted. None of the walked no-parking streets is green (validate.py checks this now).

## 2026-11-10: signs apply where their arrows point; painted parking spaces

**Problem.** Every parking sign was applied to the whole side of its block. Checked against the
city's own records, sides with all-week No Parking signs showed parked cars in 2+ aerial surveys
as often as sides with permit/time-limit signs (13.1% vs 13.2%), while sides with no physical room
showed them ~1% of the time. 90% of the signs on those red-with-cars sides carry an arrow, and 483
of the 881 sides have a single sign: "from here to the corner".

**Arrow direction, calibrated.** Read as someone standing in the street facing the sign: on the left
side of the centreline's digitised direction a RIGHT arrow points forward, on the right side
backward. On 2,367 sides with exactly one single-arrow sign, the predicted no-parking stretch holds
8% of the curb-parked cars (14% expected if arrows meant nothing); the cars fit at 1,256 signs and
go the other way at 196. The sign layer's DIRECTION_FACING field predicts no better than chance and
is not used.

**Rule** (`sides.sign_stretches`), per rule on a side: a forward arrow starts a stretch running to
the next sign of that rule pointing back, else to the block end (and mirror-wise); a double arrow
sits inside a stretch running both ways to its closing signs; a sign with no arrow covers the side.
Uncovered gaps shorter than one car (plus 20 ft corner clearance at a block end) are folded into the
stretches beside them. The uncovered part of a side goes through the same evidence tests as an
unsigned side (room, width/lane, OSM, cars, markings). The one-curb parking-lane rule now counts a
side as "banned" only if its No Parking signs cover the whole side (Ohlen Rd 1800: a corner sign on
the parking-lane side had pointed the lane to the wrong curb).

**Result.** 3,656 sides split into 7,676 drawn stretches (streets.json v9, column 10 = stretch flag;
curb-space counts are per block, so stretches carry -1). Curb length: all-week No Parking red
1,114 -> 748 km; unsigned green 4,141 -> 4,428 km; grey +65 km (open stretch without evidence of
room); no-room red +40 km; time-dependent sign rules 77 -> 53 km. Spot check, 2023 city aerials:
24 random green stretches on split sides (two samples of 12, signs and detections marked); cars
parked in the open stretch on most, quiet residential curbs on the rest, none contradicted. None of
the walked no-parking streets is green.

**Painted parking spaces.** `Markings_Specialty_Point_Read_Only`, SPECIALTY_POINT_TYPE = 5 (the
subtype table; the field domain mislabels 4 as Parking), sub-types 1 "L", 2 "T", 3 stall line,
ACTIVE only, fetched as `raw/markings.geojson`. 3,490 marks link to 508 sides; 406 sides have 2+
(the evidence threshold; evidence bit 3 in streets.json). Mostly on blocks with curb zones or sign
rules already; adds parking evidence to ~10 grey sides and settles the side of a one-curb lane.

## 2026-11-10: sign arrows by type checked against city zones; legal clearances

**Arrows on pay / permit / time-limit signs.** Where a side has both a city curb zone and arrow
signs of the same type, the stretch the signs cover (as built) was compared with the zone's extent
along the curb (mean overlap, IoU; "covered" = share of the zone the signs cover):
pay 1,051 sides 57% (95% covered) vs arrows read backwards 33% vs whole side 45%; permit 468
sides 66% (94%) vs 43% vs 51%; time limit 29 sides 67% vs 38% vs 48%. The arrow reading is
confirmed by city data, and paid/permit stretches are almost never left looking free. No Parking
signs vs the city's No Parking zones: 35% / 39% / 42%, i.e. those signs and zones don't describe
the same stretches either way, so this test says nothing for No Parking; the parked-car calibration
(86% fit) stands. Sides with a city zone are drawn from the zone and are not split.

**Legal clearances in curb-space counts** (Tex. Transp. Code 545.302(b), text checked): 15 ft each
side of a fire hydrant; 30 ft on the approach to a stop sign, yield sign or traffic signal; 20 ft
from a crosswalk at an intersection (already used). Sources, fetched optionally (a failed fetch
keeps the previous file): `2026_All_Hydrants_Map_WFL1` (fire department inspection map, 28,718
hydrants; its name carries the year), stop/yield signs from the sign inventory (MUTCD R1-1/R1-2,
16,463), `TRANSPORTATION_signals2` (turned-on/flashing traffic signals, 1,108; pedestrian beacons
left out). Linked: 14,444 hydrants (within half the pavement width + 6 m of a kept street), 13,668
stop/yield signs (within 30 m of a block end, on the curb of traffic heading to that end; one-way
streets by direction), 4,003 signalised block ends. Counted spaces 812,895 -> 773,465 (-4.9%);
"no car-length gap" red sides 495 -> 639. Spot check of 6 newly red sides: short stub blocks
(cul-de-sac necks) where a stop sign, hydrant and corner clearance leave no legal car length.

## 2026-11-10: Street View check; red / yellow painted curbs

Street View survey of 20 random green sides (tests/spot-checks.md #4-23): 18 match, 1 partly
(Tower Trl 5200: red-painted curb around a hydrant, no sign), 1 can't tell (only 2011 imagery).

Painted curbs mean no parking without any sign, so the sign inventory misses them. Source:
`Markings_Specialty_Line_Read_Only`, SPECIALTY_LINE_TYPE = 'Curbs', COLOR Red/Yellow, ACTIVE
(794 lines; optional fetch as `raw/painted_curbs.geojson`). Lines whose middle is within 60% of
half the pavement width of the centreline are median noses / islands and are skipped (~220);
"Channelizer" comments skipped. Each remaining line is an all-week No Parking stretch on its side
(`sides.painted_curbs`, `sign_stretches(painted=...)`) and is removed from the curb-space count.
435 sides affected; median marking length 5.5 m (corners, hydrants), so the effect is small:
green 4,423.5 -> 4,421.2 km. The inventory is incomplete: the Tower Trl curb is not in it.
