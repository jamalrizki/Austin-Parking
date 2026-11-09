"""Build public/data/segments.geojson from pipeline/raw/*.

Three kinds of features, by property k:
  z  City curb zone (one side of one block). Primary source. Carries its own hours.
  o  OpenStreetMap curb side (community data) for streets with no city zone nearby.
  c  Street centerline segment. Rendered grey: "no parking data on record".

Time-of-day evaluation happens in the browser (public/engine.js). This script only
normalises data; it never decides that something is free.
"""
import json
import math
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hours import HoursError, minute_set, parse_human_hours, parse_json_hours  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "pipeline" / "raw"
RULES = ROOT / "rules"
OUT = ROOT / "public" / "data"
PREC = 6  # ~0.1 m; zones are only ~5 m off the centreline so keep precision

SIDE_NAMES = {"NC": "north side", "SC": "south side", "EC": "east side", "WC": "west side"}
ZONE_SOURCE = "City of Austin Parking Inventory (Parking_Inventory_FME_UPDATE_view)"
CENTERLINE_SOURCE = "City of Austin Street Centerline (data.austintexas.gov 8hf2-pdmb)"
OSM_SOURCE = "OpenStreetMap contributors (community-mapped)"


def load(name):
    return json.loads((RAW / f"{name}.geojson").read_text())


def rnd(coords):
    if isinstance(coords[0], (int, float)):
        return [round(coords[0], PREC), round(coords[1], PREC)]
    return [rnd(c) for c in coords]


# ---------- geometry helpers (no shapely needed) ----------
KX = 111320 * math.cos(math.radians(30.27))
KY = 110540


def xy(p):
    return p[0] * KX, p[1] * KY


def seg_dist(p, a, b):
    x, y = xy(p)
    ax, ay = xy(a)
    bx, by = xy(b)
    dx, dy = bx - ax, by - ay
    L = dx * dx + dy * dy
    t = 0 if L == 0 else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / L))
    return math.hypot(x - ax - t * dx, y - ay - t * dy)


def lines_of(geom):
    if not geom:
        return []
    if geom["type"] == "LineString":
        return [geom["coordinates"]]
    if geom["type"] == "MultiLineString":
        return geom["coordinates"]
    return []


class SegIndex:
    """Grid index of line segments for 'is this point within N metres of a zone'."""

    def __init__(self, cell=30.0):
        self.cell, self.grid = cell, {}

    def _key(self, p):
        x, y = xy(p)
        return int(x // self.cell), int(y // self.cell)

    def add_line(self, line):
        for a, b in zip(line, line[1:]):
            ka, kb = self._key(a), self._key(b)
            for i in range(min(ka[0], kb[0]) - 1, max(ka[0], kb[0]) + 2):
                for j in range(min(ka[1], kb[1]) - 1, max(ka[1], kb[1]) + 2):
                    self.grid.setdefault((i, j), []).append((a, b))

    def near(self, p, metres):
        return any(seg_dist(p, a, b) <= metres for a, b in self.grid.get(self._key(p), ()))


def point_in_poly(pt, rings):
    x, y = pt
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def polys_of(geom):
    if geom["type"] == "Polygon":
        return [geom["coordinates"]]
    if geom["type"] == "MultiPolygon":
        return geom["coordinates"]
    return []


def midpoint(geom):
    pts = [p for line in lines_of(geom) for p in line]
    return pts[len(pts) // 2] if pts else None


# ---------- zones ----------
def parse_time_limit(s):
    if not s:
        return None
    m = re.fullmatch(r"\s*(\d+)\s*(hr|hrs|hour|hours|min|mins|minutes)\s*", s, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n * 60 if m.group(2).lower().startswith("h") else n


def resolve_hours(p):
    """Return (windows, quality, note)."""
    try:
        jw, event = parse_json_hours(p.get("DAY_HOUR_CONCATENATE"))
        jerr = None
    except HoursError as e:
        jw, event, jerr = None, False, str(e)
    if event:
        return [], "event", "Restrictions apply on stadium event days only"
    try:
        hw = parse_human_hours(p.get("HOURS_OF_OPERATION"))
    except HoursError:
        hw = None
    if jw is not None and hw is not None:
        if minute_set(jw) == minute_set(hw):
            return jw, "ok", None
        return [], "conflict", "City records list two different sets of hours for this curb"
    if jw is not None:
        return jw, "one", "Hours from one city field only (the other was blank or unreadable)"
    if hw is not None:
        return hw, "one", "Hours from one city field only (the other was blank or unreadable)"
    return [], "none", f"Hours missing or unreadable in city data ({jerr})"


def build_zones(zone_types, pay_areas, unknown_types):
    feats, index, covered = [], SegIndex(), set()
    for f in load("zones")["features"]:
        p, g = f["properties"], f["geometry"]
        if not g or not lines_of(g):
            continue
        types = [t.strip() for t in (p.get("ALL_RESTRICTION_TYPES") or "").split(",") if t.strip()]
        primary = (p.get("PARKING_TYPE") or "").strip()
        if not types and primary:
            types = [primary]
        others = [t for t in dict.fromkeys(types) if t != primary]
        for t in [primary] + others:
            if t not in zone_types:
                unknown_types[t] = unknown_types.get(t, 0) + 1
        windows, q, note = resolve_hours(p)
        if len(others) > 1:
            q, note = "complex", "More than two overlapping restriction types; can't tell which applies when"
        if primary not in zone_types:
            q, note = "none", f"Unrecognised zone type '{primary}'"
        block = (p.get("BLOCK_NAME") or "").strip()
        m = re.match(r"^(.*?)\s+(\d+)\s+(NC|SC|EC|WC)$", block)
        street, num, side = (m.group(1), m.group(2), m.group(3)) if m else (block, None, None)
        seg = (p.get("SEGMENT_ID") or "").strip() or None
        if seg:
            covered.add(seg)
        mid = midpoint(g)
        pa = next((a["name"] for a in pay_areas if mid and any(point_in_poly(mid, r) for r in a["polys"])), None)
        props = {
            "k": "z",
            "id": p.get("PARKING_ZONE_ID") or str(p.get("OBJECTID")),
            "st": street.title() if street else None,
            "blk": f"{num} block" if num else None,
            "side": SIDE_NAMES.get(side),
            "t": primary,
            "s": others[0] if len(others) == 1 else None,
            "w": [list(x) for x in windows],
            "q": q,
            "hrs": p.get("HOURS_OF_OPERATION"),
            "tl": parse_time_limit(p.get("TIME_LIMIT")),
            "tlr": p.get("TIME_LIMIT"),
            "sp": p.get("PARKING_SPACES"),
            "rpp": p.get("RPP_DISTRICT") if p.get("RPP_DISTRICT") not in (None, "None") else None,
            "pa": pa,
            "seg": seg,
            "zt": p.get("ZONE_TYPE"),
            "src": "zones",
        }
        if note:
            props["note"] = note
        if p.get("COMMENTS"):
            props["cmt"] = p["COMMENTS"]
        feats.append({"type": "Feature", "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])}, "properties": props})
        for line in lines_of(g):
            index.add_line(line)
    return feats, index, covered


# ---------- centerline ----------
def build_centerline(excl, covered):
    name_re = re.compile("|".join(excl["name_patterns"]), re.I)
    feats, dropped = [], 0
    for f in load("centerline")["features"]:
        p, g = f["properties"], f["geometry"]
        rc = str(p.get("road_class") or "0")
        bs = int(p.get("built_status") or 0)
        name = (p.get("full_street_name") or "").strip()
        if rc in excl["road_class"] or bs not in excl["built_status_keep"] or name_re.search(name) or not g:
            dropped += 1
            continue
        lo = [p.get(k) for k in ("left_from_address", "left_to_address", "right_from_address", "right_to_address")]
        nums = [int(float(x)) for x in lo if x not in (None, "", "0")]
        rng = f"{min(nums)}-{max(nums)}" if nums else None
        seg = str(p.get("segment_id"))
        feats.append({"type": "Feature", "geometry": {"type": g["type"], "coordinates": rnd(g["coordinates"])},
                      "properties": {"k": "c", "st": name.title(), "blk": rng, "seg": seg,
                                     "cov": seg in covered, "src": "centerline"}})
    return feats, dropped


# ---------- OSM ----------
NO_VALUES = {"no", "no_parking", "no_stopping", "fire_lane", "separate"}
YES_VALUES = {"yes", "lane", "street_side", "on_kerb", "half_on_kerb", "shoulder", "parallel", "diagonal", "perpendicular", "marked"}


def osm_side(tags, side):
    def tag(*keys):
        for k in keys:
            if k in tags:
                return tags[k]
        return None

    present = tag(f"parking:{side}", "parking:both", f"parking:lane:{side}", "parking:lane:both")
    restriction = tag(f"parking:{side}:restriction", "parking:both:restriction")
    conditional = tag(f"parking:{side}:restriction:conditional", "parking:both:restriction:conditional",
                      f"parking:condition:{side}:conditional", "parking:condition:both:conditional")
    fee = tag(f"parking:{side}:fee", "parking:both:fee")
    cond_old = tag(f"parking:condition:{side}", "parking:condition:both")
    if present is None and restriction is None and cond_old is None:
        return None
    if (present in NO_VALUES) or restriction in ("no_parking", "no_stopping", "loading_only", "no") or cond_old in ("no_parking", "no_stopping"):
        return {"v": "no", "why": "No parking (OpenStreetMap)"}
    if conditional:
        return {"v": "unknown", "why": f"Time-based restriction in OpenStreetMap: {conditional}"}
    if present in YES_VALUES or cond_old in ("free", "ticket", "customers", "residents"):
        if fee == "yes" or cond_old == "ticket":
            return {"v": "paid", "why": "Paid parking (OpenStreetMap)"}
        if cond_old == "residents":
            return {"v": "permit", "why": "Residents only (OpenStreetMap)"}
        if fee == "no" or cond_old == "free":
            return {"v": "free", "why": "Parking allowed, no fee (OpenStreetMap)"}
        return {"v": "unknown", "why": "Parking exists per OpenStreetMap, but fee/permit status isn't recorded"}
    return {"v": "unknown", "why": f"Unrecognised OpenStreetMap tag value '{present}'"}


def build_osm(excl, zone_index):
    raw = load("osm")
    feats, skipped_near_city = [], 0
    for f in raw["features"]:
        t, g = f["properties"], f["geometry"]
        if t.get("highway") in excl["osm_highway_exclude"]:
            continue
        pts = g["coordinates"]
        near = sum(1 for p in pts if zone_index.near(p, 20))
        if near / len(pts) > 0.5:
            skipped_near_city += 1  # city data wins where it exists
            continue
        for side, off in (("left", -1), ("right", 1)):
            r = osm_side(t, side)
            if not r:
                continue
            feats.append({"type": "Feature", "geometry": {"type": "LineString", "coordinates": rnd(pts)},
                          "properties": {"k": "o", "st": t.get("name") or "Unnamed street", "side": f"{side} side (OSM way direction)",
                                         "off": off, "v": r["v"], "why": r["why"], "osm": t["osm_id"], "src": "osm"}})
    return feats, skipped_near_city, raw.get("osm_base_timestamp")


def main():
    zone_types = {k: v for k, v in json.loads((RULES / "zone_types.json").read_text()).items() if not k.startswith("_")}
    excl = json.loads((RULES / "exclusions.json").read_text())
    pay_areas = [{"name": f["properties"].get("AREA_NAME"), "hours": f["properties"].get("OP_HOURS"), "polys": polys_of(f["geometry"])}
                 for f in load("pay_areas")["features"] if f.get("geometry")]
    unknown_types = {}
    zones, zindex, covered = build_zones(zone_types, pay_areas, unknown_types)
    centre, dropped = build_centerline(excl, covered)
    osm, osm_skipped, osm_ts = build_osm(excl, zindex)
    fetched = (RAW / "fetched_at.txt").read_text().strip()
    OUT.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection",
          "meta": {"built_from_fetch": fetched, "osm_base": osm_ts,
                   "sources": {"zones": ZONE_SOURCE, "centerline": CENTERLINE_SOURCE, "osm": OSM_SOURCE},
                   "zone_types": zone_types},
          "features": centre + osm + zones}
    (OUT / "segments.geojson").write_text(json.dumps(fc, separators=(",", ":")))
    areas = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])},
         "properties": {"name": f["properties"].get("AREA_NAME"), "hours": f["properties"].get("OP_HOURS")}}
        for f in load("pay_areas")["features"] if f.get("geometry")]}
    (OUT / "areas.geojson").write_text(json.dumps(areas, separators=(",", ":")))
    q = {}
    for z in zones:
        q[z["properties"]["q"]] = q.get(z["properties"]["q"], 0) + 1
    print(f"zones {len(zones)} quality {q}")
    print(f"centerline kept {len(centre)} dropped {dropped} (covered by zones: {sum(1 for c in centre if c['properties']['cov'])})")
    print(f"osm sides {len(osm)} (ways skipped near city zones: {osm_skipped})")
    if unknown_types:
        print(f"WARNING unknown zone types: {unknown_types}")
    print(f"segments.geojson {(OUT / 'segments.geojson').stat().st_size / 1e6:.2f} MB")


if __name__ == "__main__":
    main()
