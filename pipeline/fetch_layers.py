"""Download source layers as GeoJSON (WGS84) into pipeline/raw/.

Standard library only so it runs anywhere (including GitHub Actions) with no installs.
Sources and field choices are documented in pipeline/DATA_NOTES.md.
"""
import json
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "pipeline" / "raw"
UA = "austin-free-parking-pipeline/1.0 (+https://github.com/jamalrizki/Austin-Parking)"

ARCGIS = "https://services.arcgis.com/0L95CJ0VTaxqcmED/arcgis/rest/services"
ARCGIS_LAYERS = {
    # Curb-level zones: type, hours (JSON), segment id, RPP district. Primary source.
    "zones": f"{ARCGIS}/Parking_Inventory_FME_UPDATE_view/FeatureServer/0",
    # Pay-to-park area polygons with per-day hours. District fallback / context.
    "pay_areas": f"{ARCGIS}/COA_Pay_To_Park_Areas/FeatureServer/9",
    # Austin full-purpose city limits: the city's parking zones and signs only cover these streets.
    "city_limits": f"{ARCGIS}/BOUNDARIES_jurisdictions/FeatureServer/0",
    # RPP district polygons (context only).
    "rpp_districts": f"{ARCGIS}/Residential_Parking_Permits/FeatureServer/1",
    # Painted parking markings (stall lines, "L"/"T" space marks): marked curb parking, per side.
    "markings": f"{ARCGIS}/Markings_Specialty_Point_Read_Only/FeatureServer/0",
}
SIGNS = f"{ARCGIS}/Sign_Assets_Maint_Public_View/FeatureServer"
SOCRATA_CENTERLINE = "https://data.austintexas.gov/resource/8hf2-pdmb.geojson"
OVERPASS = "https://overpass-api.de/api/interpreter"


def get(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=360) as r:
                return json.load(r)
        except Exception as e:  # network hiccups: back off and retry
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} after error: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def area_polygon():
    gj = json.loads((ROOT / "rules" / "areas" / "austin.geojson").read_text())
    return gj["features"][0]["geometry"]["coordinates"][0]  # [[lon, lat], ...]


ARCGIS_WHERE = {
    "city_limits": "JURISDICTION_LABEL='AUSTIN FULL PURPOSE'",
    # Type 5 = Parking in the layer's subtype table (its field domain wrongly labels 4 as Parking).
    "markings": "SPECIALTY_POINT_TYPE=5",
}


def fetch_arcgis(name, url):
    meta = get(f"{url}?f=json")
    page = min(meta.get("maxRecordCount", 1000), 2000)
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": ARCGIS_WHERE.get(name, "1=1"), "outFields": "*", "outSR": 4326, "f": "geojson",
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": page,
        })
        chunk = get(f"{url}/query?{q}")
        got = chunk.get("features", [])
        feats += got
        print(f"  {name}: {len(feats)}")
        if len(got) < page and not chunk.get("properties", {}).get("exceededTransferLimit"):
            break
        offset += len(got)
        if not got:
            break
    return {"type": "FeatureCollection", "features": feats}


def fetch_query(name, url, where, fields, geometry=True):
    """Paged ArcGIS query with a filter; geometry optional (attribute-only tables are much smaller)."""
    feats, offset, page = [], 0, 2000
    while True:
        q = urllib.parse.urlencode({
            "where": where, "outFields": fields, "outSR": 4326, "returnGeometry": str(geometry).lower(),
            "f": "geojson", "orderByFields": "OBJECTID_1", "resultOffset": offset, "resultRecordCount": page,
        })
        got = get(f"{url}/query?{q}").get("features", [])
        feats += got
        if len(feats) % 20000 < page:
            print(f"  {name}: {len(feats)}")
        if len(got) < page:
            break
        offset += len(got)
    print(f"  {name}: {len(feats)}")
    return {"type": "FeatureCollection", "features": feats}


CURB_CUTS = f"{ARCGIS}/impervious_cover_2023/FeatureServer/0"


def fetch_curb_cuts(path):
    """Driveways and parking lots from the city's impervious-cover survey (aerial imagery up to 2023).
    Written as JSON lines [feature, outer_ring] to keep memory flat (~570k polygons)."""
    where = "FEATURE IN ('Paved Driveway','Unpaved Driveway','Paved Parking','Unpaved Parking')"
    offset, n = 0, 0
    with open(path, "w") as out:
        while True:
            q = urllib.parse.urlencode({
                "where": where, "outFields": "FEATURE", "outSR": 4326, "f": "json", "geometryPrecision": 6,
                "maxAllowableOffset": 0.000005, "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 2000,
            })
            got = get(f"{CURB_CUTS}/query?{q}").get("features", [])
            for f in got:
                rings = (f.get("geometry") or {}).get("rings")
                if rings:
                    out.write(json.dumps([f["attributes"]["FEATURE"], rings[0]], separators=(",", ":")) + "\n")
                    n += 1
            offset += len(got)
            if offset % 50000 < 2000:
                print(f"  curb_cuts: {offset}")
            if len(got) < 2000:
                break
    print(f"  curb_cuts: {n} polygons")
    return n


def fetch_roads(path):
    """Paved-road outlines (impervious_cover_2023) used as curb lines for parked-car evidence."""
    offset, n = 0, 0
    with open(path, "w") as out:
        while True:
            q = urllib.parse.urlencode({
                "where": "FEATURE='Paved Road'", "outFields": "FEATURE", "outSR": 4326, "f": "json", "geometryPrecision": 6,
                "maxAllowableOffset": 0.000004, "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 500,
            })
            got = get(f"{CURB_CUTS}/query?{q}").get("features", [])
            for f in got:
                rings = (f.get("geometry") or {}).get("rings")
                if rings:
                    out.write(json.dumps(rings, separators=(",", ":")) + "\n")
                    n += 1
            offset += len(got)
            if len(got) < 500:
                break
    print(f"  roads: {n} outlines")
    return n


def fetch_centerline(poly):
    wkt = "MULTIPOLYGON(((" + ",".join(f"{x} {y}" for x, y in poly) + ")))"
    feats, offset, page = [], 0, 5000
    while True:
        q = urllib.parse.urlencode({
            "$where": f"intersects(the_geom, '{wkt}')",
            "$limit": page, "$offset": offset, "$order": "objectid",
        })
        chunk = get(f"{SOCRATA_CENTERLINE}?{q}")
        got = chunk.get("features", [])
        feats += got
        print(f"  centerline: {len(feats)}")
        if len(got) < page:
            break
        offset += page
    return {"type": "FeatureCollection", "features": feats}


def fetch_osm(poly):
    polystr = " ".join(f"{y} {x}" for x, y in poly)
    query = f'[out:json][timeout:300];way["highway"](poly:"{polystr}")[~"^parking:"~"."];out tags geom;'
    data = get(OVERPASS, data=urllib.parse.urlencode({"data": query}).encode())
    feats = []
    for el in data.get("elements", []):
        if el.get("type") != "way" or "geometry" not in el:
            continue
        coords = [[round(p["lon"], 6), round(p["lat"], 6)] for p in el["geometry"]]
        feats.append({"type": "Feature", "id": el["id"],
                      "geometry": {"type": "LineString", "coordinates": coords},
                      "properties": {"osm_id": el["id"], **el.get("tags", {})}})
    print(f"  osm: {len(feats)}")
    return {"type": "FeatureCollection", "features": feats,
            "osm_base_timestamp": data.get("osm3s", {}).get("timestamp_osm_base")}


def main():
    RAW.mkdir(parents=True, exist_ok=True)
    poly = area_polygon()
    out = {}
    for name, url in ARCGIS_LAYERS.items():
        out[name] = fetch_arcgis(name, url)
    # Active parking signs (city sign inventory) and every sign location's street segment.
    # Locations of ANY sign tell us which blocks the city's sign survey covered.
    out["parking_signs"] = fetch_query(
        "parking_signs", f"{SIGNS}/0", "ASSET_STATUS=1 AND upper(SIGN_MESSAGE) like '%PARK%'",
        "SIGN_MESSAGE,MUTCD_CODE,ASSET_LOCATION_ID,ASSET_CATEGORY,PHOTO_URL,DATA_COLLECTION_DATE")
    out["sign_locations"] = fetch_query(
        "sign_locations", f"{SIGNS}/1", "1=1", "ASSET_LOCATION_ID,SEGMENT_ID,DATA_COLLECTION_DATE")
    # Transportation network: lane layout, on-street parking flag, pavement width per segment.
    ctn = fetch_query("ctn", f"{ARCGIS}/Comprehensive_Transportation_Network_Maint_Non_Edit_View/FeatureServer/0", "1=1",
                      "SEGMENT_ID,CROSS_SECTION_DETAIL,CROSS_SECTION_GENERAL,BICYCLE_FACILITY,TOTAL_LANE_COUNT,PAVEMENT_WIDTH",
                      geometry=False)
    (RAW / "ctn.json").write_text(json.dumps([f["properties"] for f in ctn["features"]]))
    if fetch_curb_cuts(RAW / "curb_cuts.jsonl") < 400000:
        sys.exit("ERROR: curb-cut fetch looks incomplete")
    if fetch_roads(RAW / "roads.jsonl") < 10000:
        sys.exit("ERROR: road-outline fetch looks incomplete")
    out["centerline"] = fetch_centerline(poly)
    out["osm"] = fetch_osm(poly)
    for name, fc in out.items():
        if not fc["features"]:
            sys.exit(f"ERROR: {name} returned 0 features; refusing to overwrite raw data")
        (RAW / f"{name}.geojson").write_text(json.dumps(fc))
    (RAW / "fetched_at.txt").write_text(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    print("done")


if __name__ == "__main__":
    main()
