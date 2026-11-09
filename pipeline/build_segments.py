"""Build public/data/segments.geojson from pipeline/raw/*.

Three kinds of features, by property k:
  z  City curb zone (one side of one block). Primary source. Carries its own hours.
  o  OpenStreetMap curb side (community data) for streets with no city zone nearby.
  c  Street centerline segment. Rendered grey: "no parking data on record".

Time-of-day evaluation happens in the browser (public/engine.js). This script only
normalises data; it never decides that something is free.
"""
import gzip
import json
import math
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hours import HoursError, minute_set, parse_human_hours, parse_json_hours  # noqa: E402
from sides import build_side_info  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "pipeline" / "raw"
RULES = ROOT / "rules"
OUT = ROOT / "public" / "data"
PREC = 6  # used for pay-area polygons only

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


def rnd5(line):
    """~1 m precision: plenty for a grey 'unknown' base line, ~40% smaller output."""
    out = []
    for x, y in line:
        p = [round(x, 5), round(y, 5)]
        if not out or out[-1] != p:
            out.append(p)
    return out if len(out) > 1 else [out[0], out[0]]


def simplify(line, tol_m):
    """Douglas-Peucker in metres."""
    if len(line) < 3:
        return line
    a, b = line[0], line[-1]
    i, dmax = 0, 0.0
    for k in range(1, len(line) - 1):
        d = seg_dist(line[k], a, b)
        if d > dmax:
            i, dmax = k, d
    if dmax <= tol_m:
        return [a, b]
    return simplify(line[:i + 1], tol_m)[:-1] + simplify(line[i:], tol_m)


def compact_geom(g, tol_m):
    """~1 m precision + Douglas-Peucker; zones sit ~5 m off the centreline, so this is visually lossless."""
    lines = [simplify(rnd5(line), tol_m) for line in lines_of(g)]
    return {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}


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
            "zt": p.get("ZONE_TYPE"),
            "src": "zones",
        }
        if note:
            props["note"] = note
        if p.get("COMMENTS"):
            props["cmt"] = p["COMMENTS"]
        feats.append({"type": "Feature", "geometry": compact_geom(g, 0.5), "properties": props})
        for line in lines_of(g):
            index.add_line(line)
    return feats, index, covered


# ---------- centerline ----------
def build_centerline(excl, covered, pay_areas):
    name_re = re.compile("|".join(excl["name_patterns"]), re.I)
    feats, dropped, kept, kept_props = [], 0, {}, {}
    limits = [poly for f in load("city_limits")["features"] if f.get("geometry") for poly in polys_of(f["geometry"])]
    outside = 0
    for f in load("centerline")["features"]:
        p, g = f["properties"], f["geometry"]
        rc = str(p.get("road_class") or "0")
        bs = int(p.get("built_status") or 0)
        name = (p.get("full_street_name") or "").strip()
        if rc in excl["road_class"] or bs not in excl["built_status_keep"] or name_re.search(name) or not g:
            dropped += 1
            continue
        mid = midpoint(g)
        if not mid or not any(point_in_poly(mid, rings) for rings in limits):
            outside += 1  # other cities / county roads: Austin's zone and sign records don't cover them
            continue
        lo = [p.get(k) for k in ("left_from_address", "left_to_address", "right_from_address", "right_to_address")]
        nums = [int(float(x)) for x in lo if x not in (None, "", "0")]
        rng = (min(nums) // 100) if nums else None  # hundred block, e.g. 11 -> "1100 block"
        seg = str(p.get("segment_id"))
        props = {"st": name.title(), "seg": seg}
        if rng is not None:
            props["blk"] = rng
        kept[seg] = g
        kept_props[seg] = p
        lines = [simplify(rnd5(line), 1.5) for line in lines_of(g)]
        geom = {"type": "LineString", "coordinates": lines[0]} if len(lines) == 1 else {"type": "MultiLineString", "coordinates": lines}
        feats.append({"type": "Feature", "geometry": geom, "properties": props})
    sides, stats = build_side_info(kept, pay_areas, kept_props)
    stats["outside_city_limits"] = outside
    for f in feats:
        seg = f["properties"]["seg"]
        f["properties"]["L"] = sides[(seg, "L")]
        f["properties"]["R"] = sides[(seg, "R")]
    return feats, dropped, stats


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
            feats.append({"type": "Feature", "geometry": compact_geom(g, 0.5),
                          "properties": {"k": "o", "st": t.get("name") or "Unnamed street", "side": f"{side} side (OSM way direction)",
                                         "off": off, "v": r["v"], "why": r["why"], "osm": t["osm_id"], "src": "osm"}})
    return feats, skipped_near_city, raw.get("osm_base_timestamp")


def pack_streets(feats, survey_years):
    """Compact street format, decoded in public/streets.js.
    {"v":5, "s":1e5, "o":[x0,y0], "n":[names], "m":[sign messages], "r":[rules], "e":[side entries],
     "sy":[first, median, last survey year],
     "f":[[name_i, hundred_block(-1 = none), left, right, part, part...], ...]}
    left/right: -1 curb zones cover this side, -2 surveyed with no parking signs,
                -3 no city sign records, -4 median side of a divided road, >=0 index into e.
    e[i] = [[rule_i...], [message_i...]];  r[j] = {"t","w","q","tl"?,"note"?}
    Parts are flat int coordinate deltas chained across the file (features sorted spatially)."""
    S = 100000
    names, name_i = [], {}
    msgs, msg_i, rules, rule_i, ents, ent_i = [], {}, [], {}, [], {}
    ox, oy = -97.95, 30.08
    CODE = {"Z": -1, "N": -2, "U": -3, "M": -4}

    def intern(lst, idx, key, val):
        i = idx.get(key)
        if i is None:
            i = idx[key] = len(lst)
            lst.append(val)
        return i

    def side_code(v):
        if isinstance(v, str):
            return CODE[v]
        r = [intern(rules, rule_i, json.dumps(x, sort_keys=True), {k: x[k] for k in x if x[k] is not None}) for x in v["rules"]]
        m = [intern(msgs, msg_i, x, x) for x in v["msgs"]]
        return intern(ents, ent_i, json.dumps([r, m]), [r, m])

    def key(f):
        g = f["geometry"]
        x, y = (g["coordinates"] if g["type"] == "LineString" else g["coordinates"][0])[0]
        row = int((y - oy) * 100)
        return (row, x if row % 2 == 0 else -x)

    out = []
    px, py = round(ox * S), round(oy * S)
    for f in sorted(feats, key=key):
        p = f["properties"]
        ni = intern(names, name_i, p["st"], p["st"])
        g = f["geometry"]
        parts = [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"]
        row = [ni, p.get("blk", -1), side_code(p["L"]), side_code(p["R"])]
        for line in parts:
            flat = []
            for x, y in line:
                ix, iy = round(x * S), round(y * S)
                flat += [ix - px, iy - py]
                px, py = ix, iy
            row.append(flat)
        out.append(row)
    return {"v": 5, "s": S, "o": [ox, oy], "n": names, "m": msgs, "r": rules, "e": ents, "sy": survey_years, "f": out}


def write(path, obj):
    path.write_text(json.dumps(obj, separators=(",", ":")))


def main():
    zone_types = {k: v for k, v in json.loads((RULES / "zone_types.json").read_text()).items() if not k.startswith("_")}
    excl = json.loads((RULES / "exclusions.json").read_text())
    pay_areas = [{"name": f["properties"].get("AREA_NAME"), "hours": f["properties"].get("OP_HOURS"), "polys": polys_of(f["geometry"])}
                 for f in load("pay_areas")["features"] if f.get("geometry")]
    unknown_types = {}
    zones, zindex, covered = build_zones(zone_types, pay_areas, unknown_types)
    centre, dropped, side_stats = build_centerline(excl, covered, pay_areas)
    osm, osm_skipped, osm_ts = build_osm(excl, zindex)
    fetched = (RAW / "fetched_at.txt").read_text().strip()
    OUT.mkdir(parents=True, exist_ok=True)
    for stale in ("segments.geojson", "areas.geojson"):
        (OUT / stale).unlink(missing_ok=True)
    # .json (not .geojson) so static hosts reliably gzip it.
    fc = {"type": "FeatureCollection",
          "meta": {"built_from_fetch": fetched, "osm_base": osm_ts,
                   "sources": {"zones": ZONE_SOURCE, "centerline": CENTERLINE_SOURCE, "osm": OSM_SOURCE},
                   "zone_types": zone_types},
          # OSM community tags are no longer shipped: the city sign inventory covers ~98% of
          # Austin's streets, and a second, unofficial source only produced conflicts.
          "features": zones}
    write(OUT / "segments.json", fc)
    write(OUT / "streets.json", pack_streets(centre, side_stats["survey_years"]))
    areas = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": f["geometry"]["type"], "coordinates": rnd(f["geometry"]["coordinates"])},
         "properties": {"name": f["properties"].get("AREA_NAME"), "hours": f["properties"].get("OP_HOURS")}}
        for f in load("pay_areas")["features"] if f.get("geometry")]}
    write(OUT / "areas.json", areas)
    q = {}
    for z in zones:
        q[z["properties"]["q"]] = q.get(z["properties"]["q"], 0) + 1
    print(f"zones {len(zones)} quality {q}")
    sc = {}
    for c in centre:
        for k in ("L", "R"):
            v = c["properties"][k]
            code = v if isinstance(v, str) else ("S-rules" if v["rules"] else "S-spot-only")
            sc[code] = sc.get(code, 0) + 1
    print(f"centerline kept {len(centre)} dropped {dropped}")
    print(f"street sides {sc}  (Z curb zones, S signs, N surveyed/no parking signs, U no sign records)")
    print(f"sign linking {side_stats}")
    print(f"osm sides {len(osm)} (ways skipped near city zones: {osm_skipped})")
    if unknown_types:
        print(f"WARNING unknown zone types: {unknown_types}")
    for n in ("segments.json", "streets.json", "areas.json"):
        raw = (OUT / n).read_bytes()
        print(f"{n} {len(raw) / 1e6:.2f} MB raw, {len(gzip.compress(raw)) / 1e6:.2f} MB gzip")


if __name__ == "__main__":
    main()
