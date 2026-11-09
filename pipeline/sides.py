"""Work out what is known about each SIDE of each street segment.

Per side, in priority order:
  Z  the city curb-zone inventory covers this side (zones are drawn instead)
  S  the city sign inventory has parking signs on this side -> rules from the sign text
  N  the city's sign survey covered this block (it has other signs on record) and recorded
     no parking signs on this side
  U  no city sign records for this block at all -> unknown
  X  no physical parking space, per the city's transportation network (CTN): the street is
     listed without on-street parking, has a travel/bike lane at the curb, or is under 24 ft wide.
     Only applied where no sign or curb zone says otherwise. Stored as ("X", reason).
  W  no parking signs, but no evidence of physical room: no CTN record / width (W, "nodata"),
     or pavement 24-27 ft with no parking lane listed (W, "tight"), or a collector/arterial/multi-lane
     road with no listed parking lane (W, "busy"). Shown grey, never green.
     Added after Jamal walked La Calma Dr and La Posada Dr (divided, not in CTN, no parking).
  M  median side of a divided road (one-way carriageway, no addresses on that side, the
     opposite carriageway of the same street right beside it) -> not drawn

Side is left/right relative to the centreline's digitised direction, which is also how
MapLibre's line-offset works (positive = right), so the browser can draw each side.
"""
import datetime
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hours import HoursError, parse_human_hours  # noqa: E402
from signs import classify  # noqa: E402

RAW = pathlib.Path(__file__).resolve().parent / "raw"
KX = 111320 * math.cos(math.radians(30.27))
KY = 110540
MAX_LINK_M = 30      # a sign further than this from its linked segment is re-linked
MAX_NEAREST_M = 25   # fallback: nearest kept segment within this distance


def load(name):
    return json.loads((RAW / f"{name}.geojson").read_text())


def lines_of(g):
    if not g:
        return []
    return [g["coordinates"]] if g["type"] == "LineString" else g["coordinates"] if g["type"] == "MultiLineString" else []


def _xy(p):
    return p[0] * KX, p[1] * KY


def side_of(pt, lines):
    """('L'|'R', distance_m) of pt relative to the nearest piece of the line."""
    x, y = _xy(pt)
    best = (None, float("inf"))
    for line in lines:
        for a, b in zip(line, line[1:]):
            ax, ay = _xy(a)
            bx, by = _xy(b)
            dx, dy = bx - ax, by - ay
            L = dx * dx + dy * dy
            t = 0 if L == 0 else max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / L))
            d = math.hypot(x - ax - t * dx, y - ay - t * dy)
            if d < best[1]:
                cross = dx * (y - ay) - dy * (x - ax)
                best = ("L" if cross > 0 else "R", d)
    return best


class Grid:
    def __init__(self, cell=50.0):
        self.cell, self.g = cell, {}

    def key(self, p):
        x, y = _xy(p)
        return int(x // self.cell), int(y // self.cell)

    def add(self, seg, lines):
        keys = {self.key(p) for line in lines for p in line}
        for k in keys:
            self.g.setdefault(k, set()).add(seg)

    def near(self, p):
        kx, ky = self.key(p)
        out = set()
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                out |= self.g.get((kx + dx, ky + dy), set())
        return out


def _midpoint(g):
    pts = [p for line in lines_of(g) for p in line]
    return pts[len(pts) // 2] if pts else None


def _in_poly(pt, rings):
    x, y = pt
    inside = False
    for ring in rings:
        for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
            if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                inside = not inside
    return inside


def _no_addresses(p, side):
    keys = ("left_from_address", "left_to_address") if side == "L" else ("right_from_address", "right_to_address")
    return all(str(p.get(k) or "0").strip() in ("", "0") for k in keys)


def median_sides(kept, props, lines):
    """{(seg, side)} that face the median of a divided road."""
    by_name = {}
    for seg, p in props.items():
        if (p.get("one_way") or "").upper() in ("FT", "TF"):
            by_name.setdefault((p.get("full_street_name") or "").upper(), []).append(seg)
    out = set()
    for segs in by_name.values():
        if len(segs) < 2:
            continue
        mids = {s: _midpoint(kept[s]) for s in segs}
        for seg in segs:
            for side in ("L", "R"):
                if not _no_addresses(props[seg], side):
                    continue
                for other in segs:
                    if other == seg or not mids[other]:
                        continue
                    sd, d = side_of(mids[other], lines[seg])
                    if sd == side and d < 45:
                        out.add((seg, side))
                        break
    return out


NARROW_FT = 24      # calibrated: of CTN 2-lane streets under 24 ft, 3 have parking and 114 don't
TIGHT_FT = 28       # 24-28 ft: mostly no parking on collectors; shown as a caveat, not a colour
NO_ROOM_EDGES = {"T", "BL", "BBL", "PBL", "TL", "CTT", "OW", "TO"}
BIKE_AT_CURB = {"Bike Lane", "Bike Lane - Buffered", "Bike Lane - Protected One-Way",
                "Bike Lane - Protected Two-Way", "Bike Lane - Colored"}


def physical(ctn_row):
    """(room, reason, has_lane): room False = no physical parking space on either side."""
    if not ctn_row:
        return None, None, False
    gen = (ctn_row.get("CROSS_SECTION_GENERAL") or "").upper()
    det = (ctn_row.get("CROSS_SECTION_DETAIL") or "").upper()
    width = ctn_row.get("PAVEMENT_WIDTH") or 0
    bike = ctn_row.get("BICYCLE_FACILITY") or ""
    edges = [t.strip() for t in det.split("-")] if det and det != "UNMARKED" else []
    ends = {edges[0], edges[-1]} if edges else set()
    if gen.endswith("-OP") or "P" in ends or "BL/P" in ends or bike == "Bike Lane - wParking":
        return True, None, True
    if gen.endswith("-N"):
        return False, "lane", False
    if ends and ends <= NO_ROOM_EDGES:
        return False, "bike" if ends & {"BL", "BBL", "PBL"} else "lane", False
    if bike in BIKE_AT_CURB and not ends:
        return False, "bike", False
    if 0 < width < NARROW_FT:
        return False, "narrow", False
    return None, None, False


def build_side_info(kept, pay_areas, props=None, ctn=None, osm_side_fn=None):
    """kept: {segment_id(str): raw geometry} for streets shown on the map; props: centreline attributes.
    Returns (side_of_segment dict {(seg, 'L'|'R'): code_or_entry}, stats)."""
    lines = {s: lines_of(g) for s, g in kept.items()}
    grid = Grid()
    for s, ls in lines.items():
        grid.add(s, ls)

    # Z: curb-zone sides
    zone_sides = set()
    for f in load("zones")["features"]:
        seg = (f["properties"].get("SEGMENT_ID") or "").strip()
        mid = _midpoint(f["geometry"])
        if seg in lines and mid:
            side, d = side_of(mid, lines[seg])
            if d < 40:
                zone_sides.add((seg, side))

    # Survey coverage: any sign location on the segment
    loc_seg, surveyed, survey_dates = {}, set(), []
    for f in load("sign_locations")["features"]:
        p = f["properties"]
        if p.get("SEGMENT_ID") is None:
            continue
        seg = str(int(p["SEGMENT_ID"]))
        loc_seg[p["ASSET_LOCATION_ID"]] = seg
        surveyed.add(seg)
        if p.get("DATA_COLLECTION_DATE"):
            survey_dates.append(p["DATA_COLLECTION_DATE"])

    # Signs sit at intersections and are linked to only one of the meeting segments, so a block
    # also counts as surveyed when the city has sign records within 30 m of either of its ends.
    loc_grid = Grid(cell=40)
    loc_cells = {}
    for f in load("sign_locations")["features"]:
        if f["geometry"]:
            pt = f["geometry"]["coordinates"]
            loc_cells.setdefault(loc_grid.key(pt), []).append(_xy(pt))

    def has_sign_near(pt, m=30):
        kx, ky = loc_grid.key(pt)
        x, y = _xy(pt)
        return any(math.hypot(qx - x, qy - y) <= m
                   for dx in (-1, 0, 1) for dy in (-1, 0, 1) for qx, qy in loc_cells.get((kx + dx, ky + dy), ()))

    for seg, ls in lines.items():
        if seg not in surveyed and ls and (has_sign_near(ls[0][0]) or has_sign_near(ls[-1][-1])):
            surveyed.add(seg)

    # Pay-area hours for pay signs that don't print their hours
    def pay_rule(seg):
        mid = _midpoint(kept[seg])
        for a in pay_areas:
            if mid and any(_in_poly(mid, r) for r in a["polys"]):
                try:
                    return [list(w) for w in parse_human_hours(a["hours"])], "ok", f"Hours from the {a['name']} pay-to-park area"
                except HoursError:
                    return [], "none", f"Pay sign in the {a['name']} area; its hours can't be read"
        return [], "none", "Pay sign, but its hours aren't on record"

    # S: signs
    entries, stats = {}, {"signs_used": 0, "relinked": 0, "dropped_far": 0, "spot": 0, "ignored": 0}
    for f in load("parking_signs")["features"]:
        p, g = f["properties"], f["geometry"]
        if not g:
            continue
        grp, rule = classify(p.get("SIGN_MESSAGE"))
        if grp in ("ignore", "info"):
            stats["ignored"] += 1
            continue
        pt = g["coordinates"]
        seg = loc_seg.get(p.get("ASSET_LOCATION_ID"))
        side, d = side_of(pt, lines[seg]) if seg in lines else (None, float("inf"))
        if d > MAX_LINK_M:
            best = (None, None, float("inf"))
            for s in grid.near(pt):
                sd, dd = side_of(pt, lines[s])
                if dd < best[2]:
                    best = (s, sd, dd)
            if best[2] > MAX_NEAREST_M:
                stats["dropped_far"] += 1
                continue
            seg, side, d = best
            stats["relinked"] += 1
        e = entries.setdefault((seg, side), {"rules": [], "msgs": []})
        msg = " ".join((p.get("SIGN_MESSAGE") or "").split())
        if msg not in e["msgs"]:
            e["msgs"].append(msg)
        if grp == "spot":
            stats["spot"] += 1
            continue
        rule = dict(rule)
        if rule["q"] == "area":
            rule["w"], rule["q"], rule["note"] = pay_rule(seg)
        rule["w"] = [list(w) for w in rule["w"]]
        if rule not in e["rules"]:
            e["rules"].append(rule)
        stats["signs_used"] += 1

    medians = median_sides(kept, props, lines) if props else set()
    room, why, fits, fit_why = {}, {}, {}, {}
    for seg in kept:
        row = (ctn or {}).get(seg)
        r, reason, has_lane = physical(row)
        room[seg], why[seg] = r, reason
        width = (row or {}).get("PAVEMENT_WIDTH") or 0
        # Green needs positive evidence that curb parking exists:
        #  - any road: the city lists a parking lane (CTN -OP / P edge / bike lane with parking)
        #  - local residential streets only (class 6 local, 9 cul-de-sac, <= 2 lanes): >= 28 ft pavement
        # Collectors and arterials are often wide because of extra travel lanes (Cameron Rd,
        # Norwood Park Blvd), so width says nothing about parking there.
        rc = str(((props or {}).get(seg) or {}).get("road_class"))
        lanes = (row or {}).get("TOTAL_LANE_COUNT") or 0
        local = rc in ("6", "9") and lanes <= 2
        fits[seg] = has_lane or (local and width >= TIGHT_FT)
        fit_why[seg] = "busy" if not local else ("tight" if width else "nodata")
    stats["median_sides"] = len(medians)
    widths = {seg: ((ctn or {}).get(seg) or {}).get("PAVEMENT_WIDTH") for seg in kept}
    spaces, n_cuts = curb_spaces(lines, widths, RAW / "curb_cuts.jsonl")
    stats["curb_cut_polygons"] = n_cuts
    # Presence/absence evidence beyond city records.
    osm = osm_evidence(lines, osm_side_fn) if osm_side_fn else {}
    cars_path = RAW / "curb_cars.json"
    if any((RAW.parent / "cars" / "out").glob("cars_*.geojson")):
        sys.path.insert(0, str(RAW.parent / "cars"))
        import assign  # noqa: E402  (pipeline/cars/assign.py)
        assign.main(lines, widths)
    cars = {}
    if cars_path.exists():
        for k, v in json.loads(cars_path.read_text()).items():
            seg, side = k.split("|")
            cars[(seg, side)] = sum(1 for n in v.values() if n > 0)  # number of survey years with cars at this curb
    evidence = {}
    out = {}
    for seg in kept:
        for side in ("L", "R"):
            if (seg, side) in medians:
                out[(seg, side)] = "M"
            elif (seg, side) in zone_sides:
                out[(seg, side)] = "Z"
            elif spaces.get((seg, side)) == 0 and seg in surveyed and room.get(seg) is not False:
                out[(seg, side)] = ("X", "driveways")
            elif (seg, side) in entries and entries[(seg, side)]["rules"]:
                out[(seg, side)] = entries[(seg, side)]
            elif room.get(seg) is False:
                out[(seg, side)] = ("X", why[seg])
                stats["no_room_sides"] = stats.get("no_room_sides", 0) + 1
            elif osm.get((seg, side)) == "no":
                out[(seg, side)] = ("X", "osm")
            elif seg not in surveyed:
                out[(seg, side)] = "U"
            elif not (fits.get(seg) or osm.get((seg, side)) == "yes" or cars.get((seg, side), 0) >= 2):
                out[(seg, side)] = ("W", fit_why[seg])
            elif (seg, side) in entries:
                out[(seg, side)] = entries[(seg, side)]
            else:
                out[(seg, side)] = "N"
            ev = (1 if osm.get((seg, side)) == "yes" else 0) | (min(cars.get((seg, side), 0), 3) << 1)
            if ev:
                evidence[(seg, side)] = ev
    years = sorted(datetime.datetime.fromtimestamp(t / 1000, datetime.timezone.utc).year for t in survey_dates)
    stats["survey_years"] = [years[0], years[len(years) // 2], years[-1]] if years else None
    stats["spaces"] = spaces
    stats["evidence"] = evidence
    stats["osm_sides"] = len(osm)
    stats["car_sides"] = len(cars)
    return out, stats


# ---------- curb space between driveways (city impervious-cover survey) ----------
CORNER_CLEAR_M = 6.1   # 20 ft: Texas Transp. Code 545.302 - no parking within 20 ft of a crosswalk at an intersection
CAR_M = 6.4            # ~21 ft per parallel space
FT = 0.3048


def _pieces(lines):
    """Metric pieces (ax, ay, dx, dy, length, start_offset) along the whole polyline."""
    out, s0 = [], 0.0
    for line in lines:
        for a, b in zip(line, line[1:]):
            ax, ay = _xy(a)
            bx, by = _xy(b)
            dx, dy = bx - ax, by - ay
            L = math.hypot(dx, dy)
            if L > 0:
                out.append((ax, ay, dx, dy, L, s0))
                s0 += L
    return out, s0


def _project(x, y, pieces):
    """(along_m, dist_m, side, clamped) of a metric point on the polyline."""
    best = None
    for ax, ay, dx, dy, L, s0 in pieces:
        t = ((x - ax) * dx + (y - ay) * dy) / (L * L)
        tc = max(0.0, min(1.0, t))
        d = math.hypot(x - ax - tc * dx, y - ay - tc * dy)
        if best is None or d < best[1]:
            side = "L" if dx * (y - ay) - dy * (x - ax) > 0 else "R"
            best = (s0 + tc * L, d, side, t < 0 or t > 1)
    return best


def curb_spaces(lines, widths, path):
    """{(seg, side): car spaces} counting curb gaps between driveways/lots, minus corner clearance.
    Returns ({}, 0) if the curb-cut file is missing."""
    if not path.exists():
        return {}, 0
    geo = {s: _pieces(ls) for s, ls in lines.items()}
    grid = Grid(cell=60)
    for s, ls in lines.items():
        grid.add(s, ls)
    cuts, n = {}, 0
    with open(path) as fh:
        for line in fh:
            _, ring = json.loads(line)
            n += 1
            pts = [_xy(p) for p in ring]
            cands = set()
            for p in ring[:: max(1, len(ring) // 4)]:
                cands |= grid.near(p)
            for seg in cands:
                pieces, _ = geo[seg]
                if not pieces:
                    continue
                half = (widths.get(seg) or 30) * FT / 2
                reach, touch = half + 6.0, half + 3.0
                by_side = {}
                for x, y in pts:
                    s, d, side, clamped = _project(x, y, pieces)
                    if d <= reach and not clamped:
                        by_side.setdefault(side, []).append((s, d))
                for side, v in by_side.items():
                    if len(v) < 2 or min(d for _, d in v) > touch:
                        continue
                    a, b = min(s for s, _ in v), max(s for s, _ in v)
                    if 1.5 <= b - a <= 150:
                        cuts.setdefault((seg, side), []).append((a, b))
    out = {}
    for seg, (pieces, total) in geo.items():
        for side in ("L", "R"):
            lo, hi = CORNER_CLEAR_M, total - CORNER_CLEAR_M
            spaces, cur = 0, lo
            for a, b in sorted(cuts.get((seg, side), [])):
                if b <= cur:
                    continue
                if a > cur:
                    spaces += int((min(a, hi) - cur) // CAR_M) if min(a, hi) > cur else 0
                cur = max(cur, b)
                if cur >= hi:
                    break
            if cur < hi:
                spaces += int((hi - cur) // CAR_M)
            out[(seg, side)] = spaces
    return out, n


# ---------- OpenStreetMap per-side parking tags (community data) ----------
def osm_evidence(lines, osm_side_fn):
    """{(seg, side): "no" | "yes"} from OSM parking:* tags, matched to our segments.
    A way's left/right is relative to its own direction, so it is flipped when the way runs
    opposite to our centreline. "yes" = a parking lane/street-side parking is mapped (any fee/permit
    status); "no" = no parking/no stopping."""
    path = RAW / "osm.geojson"
    if not path.exists():
        return {}
    geo = {s: _pieces(ls)[0] for s, ls in lines.items()}
    grid = Grid(cell=60)
    for s, ls in lines.items():
        grid.add(s, ls)
    votes = {}
    for f in json.loads(path.read_text())["features"]:
        tags, pts = f["properties"], f["geometry"]["coordinates"]
        if tags.get("highway") in ("motorway", "motorway_link", "trunk_link", "service", "footway", "cycleway", "path"):
            continue
        sides = {sd: osm_side_fn(tags, sd) for sd in ("left", "right")}
        if not any(sides.values()):
            continue
        for a, b in zip(pts, pts[1:]):
            mid = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2]
            ax, ay = _xy(a)
            bx, by = _xy(b)
            best = None
            for s in grid.near(mid):
                if not geo[s]:
                    continue
                along, d, _, clamped = _project(*_xy(mid), geo[s])
                if d < 8 and not clamped and (best is None or d < best[0]):
                    best = (d, s)
            if not best:
                continue
            s = best[1]
            # direction of our segment piece nearest the midpoint
            mx, my = _xy(mid)
            px, py, pdx, pdy, _, _ = min(geo[s], key=lambda q: abs((mx - q[0]) * q[3] - (my - q[1]) * q[2]) / q[4])
            same = (bx - ax) * pdx + (by - ay) * pdy >= 0
            for sd, r in sides.items():
                if not r or r["v"] == "unknown":
                    continue
                our = ("L" if sd == "left" else "R") if same else ("R" if sd == "left" else "L")
                v = "no" if r["v"] == "no" else "yes"
                votes.setdefault((s, our), []).append(v)
    out = {}
    for k, vs in votes.items():
        out[k] = "no" if vs.count("no") > vs.count("yes") else "yes"
    return out
