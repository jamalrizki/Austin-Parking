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
    # RPP district polygons (context only).
    "rpp_districts": f"{ARCGIS}/Residential_Parking_Permits/FeatureServer/1",
}
SOCRATA_CENTERLINE = "https://data.austintexas.gov/resource/8hf2-pdmb.geojson"
OVERPASS = "https://overpass-api.de/api/interpreter"


def get(url, data=None, tries=4):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.load(r)
        except Exception as e:  # network hiccups: back off and retry
            if i == tries - 1:
                raise
            print(f"  retry {i + 1} after error: {e}", file=sys.stderr)
            time.sleep(3 * (i + 1))


def area_polygon():
    gj = json.loads((ROOT / "rules" / "areas" / "east-austin.geojson").read_text())
    return gj["features"][0]["geometry"]["coordinates"][0]  # [[lon, lat], ...]


def fetch_arcgis(name, url):
    meta = get(f"{url}?f=json")
    page = min(meta.get("maxRecordCount", 1000), 2000)
    feats, offset = [], 0
    while True:
        q = urllib.parse.urlencode({
            "where": "1=1", "outFields": "*", "outSR": 4326, "f": "geojson",
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
    query = f'[out:json][timeout:120];way["highway"](poly:"{polystr}")[~"^parking:"~"."];out tags geom;'
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
