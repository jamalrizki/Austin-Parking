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
     road with no listed parking lane (W, "busy"), or the city lists a parking lane at one curb
     only and nothing on record shows it is this side (W, "oneside"). Shown grey, never green.
     Added after Jamal walked La Calma Dr and La Posada Dr (divided, not in CTN, no parking).
  M  median side of a divided road (one-way carriageway, no addresses on that side, the
     opposite carriageway of the same street right beside it) -> not drawn

One deliberate exception to the order above: a side with no car-length gap between driveways
(X, "driveways") is red even when a sign rule exists for it, because block-wide sign rules were
being applied to frontage that is all curb cut (104 E 35th St).

Side is left/right relative to the centreline's digitised direction, which is also how
MapLibre's line-offset works (positive = right), so the browser can draw each side.

Signs with arrows cover only part of a side: a single-arrow sign marks one end of a stretch and
the stretch runs from the sign in the arrow's direction to the sign closing it (or the block's
end). sign_stretches() splits such sides; build_segments.py draws each stretch separately and the
uncovered part of the side is judged like a side with no signs (it still needs evidence of room).
"""
import datetime
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from hours import HoursError, minute_set, parse_human_hours  # noqa: E402
from signs import arrow, classify  # noqa: E402

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
        # Register the cells along the whole line, not only at its vertices: a long straight block
        # has vertices at its ends only, and near() looks just one cell around a point. Samples are
        # under half a cell apart, so near() finds every line within 0.75 cell of the point.
        step = self.cell / 2
        for line in lines:
            if len(line) == 1:
                self.g.setdefault(self.key(line[0]), set()).add(seg)
            for a, b in zip(line, line[1:]):
                ax, ay = _xy(a)
                bx, by = _xy(b)
                n = int(math.hypot(bx - ax, by - ay) // step) + 1
                for i in range(n + 1):
                    k = int((ax + (bx - ax) * i / n) // self.cell), int((ay + (by - ay) * i / n) // self.cell)
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


def arrow_dir(arr, side):
    """+1 / -1 = the arrow points toward higher / lower distance along the centreline, 0 = both
    ways, None = no arrow. Read as someone standing in the street facing the sign: on the left side
    (of the digitised direction) their right hand points forward, on the right side backward.
    Calibrated 2026-11-10 against aerial parked cars on 2,367 sides with one single-arrow sign: the
    predicted no-parking stretch holds 8% of the curb-parked cars (14% if arrows meant nothing), and
    the cars fit this reading at 1,256 signs vs 196 the other way. The city's DIRECTION_FACING field
    predicted no better than chance and is not used."""
    if arr is None:
        return None
    if arr == "both":
        return 0
    return 1 if (arr == "right") == (side == "L") else -1


def sign_stretches(signs, side, total):
    """Split one side of a block by where its signs apply.
    signs: [(along_m, arrow, rule or None for spot signs, message)].
    Returns [(lo_m, hi_m, rules, messages)] covering 0..total, or None when the block rules all
    cover the whole side (no arrows, or no sign closing the stretch they start).

    Per rule, a sign pointing forward starts a stretch that runs to the next sign of the same rule
    pointing back (else to the block's end), and vice versa; a double-arrow sign sits inside a
    stretch that runs both ways to the signs closing it. A gap between stretches too short for a
    car (or for a car plus the 20 ft corner clearance at a block end) is folded into the stretches
    beside it, so the map never shows a sliver as open."""
    blocks = [s for s in signs if s[2] is not None]
    if not blocks or total <= 0:
        return None
    groups = {}
    for s in blocks:
        groups.setdefault(json.dumps(s[2], sort_keys=True), []).append(s)
    spans = []
    for key, ss in groups.items():
        dirs = sorted(((a, arrow_dir(arr, side)) for a, arr, _, _ in ss), key=lambda x: x[0])
        if any(d is None for _, d in dirs):
            spans.append((0.0, total, key))
            continue
        for i, (a, d) in enumerate(dirs):
            lo = hi = a
            if d >= 0:
                hi = next((b for b, e in dirs[i + 1:] if e == -1), total)
            if d <= 0:
                lo = next((b for b, e in reversed(dirs[:i]) if e == 1), 0.0)
            spans.append((max(0.0, lo), min(total, hi), key))
    cuts = sorted({0.0, total} | {x for lo, hi, _ in spans for x in (lo, hi)})
    pieces = []
    for a, b in zip(cuts, cuts[1:]):
        if b - a < 0.01:
            continue
        m = (a + b) / 2
        keys = frozenset(k for lo, hi, k in spans if lo <= m <= hi)
        if pieces and pieces[-1][2] == keys:
            pieces[-1][1] = b
        else:
            pieces.append([a, b, keys])
    # fold uncovered gaps too short to park in into their neighbours (most restrictive: both)
    for i, p in enumerate(pieces):
        need = CAR_M + (CORNER_CLEAR_M if i == 0 or i == len(pieces) - 1 else 0)
        if not p[2] and p[1] - p[0] < need:
            p[2] = frozenset().union(*[pieces[j][2] for j in (i - 1, i + 1) if 0 <= j < len(pieces)])
    # slivers under 1 m (two signs on one post, rounding) take the longer neighbour's rules
    for i, p in enumerate(pieces):
        nb = [pieces[j] for j in (i - 1, i + 1) if 0 <= j < len(pieces)]
        if p[1] - p[0] < 1.0 and nb:
            p[2] = max(nb, key=lambda q: q[1] - q[0])[2]
    merged = []
    for p in pieces:
        if merged and merged[-1][2] == p[2]:
            merged[-1][1] = p[1]
        else:
            merged.append(list(p))
    if len(merged) < 2:
        return None
    out = []
    for lo, hi, keys in merged:
        msgs = []
        for a, _, rule, msg in sorted(signs, key=lambda s: s[0]):
            covers = rule is not None and json.dumps(rule, sort_keys=True) in keys
            if (covers or (rule is None and lo <= a <= hi)) and msg not in msgs:
                msgs.append(msg)
        rules = [json.loads(k) for k in sorted(keys)]
        out.append((lo, hi, rules, msgs))
    return out


def cut_lines(lines, a, b):
    """The parts of a polyline (lon/lat) between along-distances a and b in metres, measured the
    same way as _pieces (zero-length pieces skipped, separate lines chained)."""
    out, s0 = [], 0.0
    for line in lines:
        cur = []
        for p, q in zip(line, line[1:]):
            L = math.hypot((q[0] - p[0]) * KX, (q[1] - p[1]) * KY)
            if L == 0:
                continue
            s1 = s0 + L
            if s1 > a and s0 < b:
                t0, t1 = max(0.0, (a - s0) / L), min(1.0, (b - s0) / L)
                if not cur:
                    cur.append([p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0])
                cur.append([p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1])
            elif cur:
                out.append(cur)
                cur = []
            s0 = s1
        if len(cur) > 1:
            out.append(cur)
    return out


# Painted parking-space markings (city markings inventory, type 5 = Parking): stall lines and the
# "L"/"T" marks at the ends of spaces. Handicap symbols, scooter/bike boxes and "X" are left out.
SPACE_MARKS = {1, 2, 3}
MIN_MARKS = 2  # one stray mark could be a mislinked point; a marked row has several


def marking_counts(lines, grid):
    """{(seg, side): number of painted parking-space marks} from raw/markings.geojson, if present."""
    path = RAW / "markings.geojson"
    if not path.exists():
        return {}
    out = {}
    for f in json.loads(path.read_text())["features"]:
        p, g = f["properties"], f.get("geometry")
        if not g or p.get("SPECIALTY_POINT_SUB_TYPE") not in SPACE_MARKS:
            continue
        if (p.get("LOCATION_STATUS") or "ACTIVE").strip().upper() != "ACTIVE":
            continue
        pt = g["coordinates"]
        seg = str(int(float(p["SEGMENT_ID"]))) if p.get("SEGMENT_ID") else None
        side, d = side_of(pt, lines[seg]) if seg in lines else (None, float("inf"))
        if d > MAX_LINK_M:
            best = (None, None, float("inf"))
            for s in grid.near(pt):
                sd, dd = side_of(pt, lines[s])
                if dd < best[2]:
                    best = (s, sd, dd)
            if best[2] > MAX_NEAREST_M:
                continue
            seg, side, d = best
        out[(seg, side)] = out.get((seg, side), 0) + 1
    return out


PARK_EDGES = {"P", "BL/P"}


def lane_listing(ctn_row):
    """0 = the city lists no parking lane, 1 = it lists one, 2 = it lists one at ONE curb only
    (parking edge at one end of the cross-section, travel or bike lane at the other: 621 of the
    2,797 kept segments with a listed lane).

    The record does not say which side that is. Checked against aerial parked cars (2026-11-09):
    the cross-section reads in compass order, not in the centreline's direction. On north-south
    streets the first code is the west curb in 103 of 115 cases; on east-west streets it is
    inconclusive (63 of 112). Not reliable enough to colour a side, so build_side_info asks for
    per-side evidence instead."""
    if not ctn_row or not physical(ctn_row)[2]:
        return 0
    det = (ctn_row.get("CROSS_SECTION_DETAIL") or "").upper()
    edges = [t.strip() for t in det.split("-")] if det and det != "UNMARKED" else []
    if len(edges) >= 2 and (edges[0] in PARK_EDGES) != (edges[-1] in PARK_EDGES):
        return 2
    return 1


def build_side_info(kept, pay_areas, props=None, ctn=None, osm_side_fn=None):
    """kept: {segment_id(str): raw geometry} for streets shown on the map; props: centreline attributes.
    Returns (side_of_segment dict {(seg, 'L'|'R'): code_or_entry}, stats)."""
    lines = {s: lines_of(g) for s, g in kept.items()}
    geo = {s: _pieces(ls) for s, ls in lines.items()}
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
    placed = {}  # (seg, side) -> [(along_m, arrow, rule or None, message)] for sign_stretches
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
        along = _project(*_xy(pt), geo[seg][0])[0] if geo[seg][0] else 0.0
        if grp == "spot":
            stats["spot"] += 1
            placed.setdefault((seg, side), []).append((along, None, None, msg))
            continue
        rule = dict(rule)
        if rule["q"] == "area":
            rule["w"], rule["q"], rule["note"] = pay_rule(seg)
        rule["w"] = [list(w) for w in rule["w"]]
        if rule not in e["rules"]:
            e["rules"].append(rule)
        placed.setdefault((seg, side), []).append((along, arrow(msg), rule, msg))
        stats["signs_used"] += 1

    medians = median_sides(kept, props, lines) if props else set()
    room, why, fits, fit_why, car_ok, one_side = {}, {}, {}, {}, {}, {}
    for seg in kept:
        row = (ctn or {}).get(seg)
        r, reason, has_lane = physical(row)
        room[seg], why[seg] = r, reason
        one_side[seg] = lane_listing(row) == 2
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
        # Parked cars seen from the air count as evidence on local streets and collectors only. On
        # arterials (class 4/5 and others) cars beside the road are usually in an adjacent lot or
        # stopped in traffic: Cameron Rd 7800 block passed the curb test from lot cars in 2 surveys.
        car_ok[seg] = rc in ("6", "8", "9")
    stats["median_sides"] = len(medians)
    widths = {seg: ((ctn or {}).get(seg) or {}).get("PAVEMENT_WIDTH") for seg in kept}
    one_way = {seg: ((props or {}).get(seg) or {}).get("one_way") for seg in kept}
    clear, clear_stats = clearance_spans(geo, grid, widths, one_way)
    stats.update({f"clearance_{k}": v for k, v in clear_stats.items()})
    spaces, n_cuts = curb_spaces(lines, widths, RAW / "curb_cuts.jsonl", clear)
    stats["curb_cut_polygons"] = n_cuts
    # Presence/absence evidence beyond city records.
    osm = osm_evidence(lines, osm_side_fn) if osm_side_fn else {}
    # Aerial parked-car evidence comes straight from assign.main, never from a curb_cars.json left
    # over from an earlier build: stale evidence must not survive missing inputs.
    cars, car_surveys = {}, []
    if any((RAW.parent / "cars" / "out").glob("cars_*.*")):
        sys.path.insert(0, str(RAW.parent / "cars"))
        import assign  # noqa: E402  (pipeline/cars/assign.py)
        per_side, car_surveys = assign.main(lines, widths)
        for k, v in per_side.items():
            seg, side = k.split("|")
            cars[(seg, side)] = sum(1 for n in v.values() if n > 0)  # number of survey years with cars at this curb
    marks = marking_counts(lines, grid)
    marked = {k for k, n in marks.items() if n >= MIN_MARKS}
    stats["marked_sides"] = len(marked)
    split = {k: sign_stretches(placed.get(k, []), k[1], geo[k[0]][1]) for k, e in entries.items() if e["rules"]}

    def sign_says(seg, sd):
        """'lane' if a curb zone, painted spaces or a sign shows parking is regulated (so it exists)
        on this side, 'banned' if its signs forbid parking all week along the whole side (the usual
        'No parking, bike lane' side). Signs whose arrows cover only part of the side settle
        nothing: Ohlen Rd 1800 had a corner No Parking sign on the parking-lane side."""
        rules = entries.get((seg, sd), {"rules": ()})["rules"]
        timed = [r for r in rules if r["t"] == "No Parking" and r["q"] == "ok" and len(minute_set(r["w"])) < 7 * 1440]
        if (seg, sd) in zone_sides or (seg, sd) in marked or timed or any(r["t"] != "No Parking" for r in rules):
            return "lane"  # includes No Parking during set hours: parking is allowed outside them
        whole = any(r["t"] == "No Parking" and r["q"] == "ok" for r in rules) and not split.get((seg, sd))
        return "banned" if whole else None

    def lane_side(seg):
        """Sides ('L', 'R', 'LR' or '') that hold the parking lane on a block where the city lists
        one at a single curb. City records settle it first: a curb zone or regulating sign on a
        side, or all-week No Parking signs on one side only (the lane is then at the other curb).
        Failing that, the side where parked cars were seen in more aerial surveys than the other;
        a tie settles nothing unless both sides pass the usual 2-survey test on their own."""
        says = {sd: sign_says(seg, sd) for sd in ("L", "R")}
        strong = "".join(sd for sd in ("L", "R") if says[sd] == "lane")
        if strong:
            return strong
        banned = [sd for sd in ("L", "R") if says[sd] == "banned"]
        if banned:
            return "" if len(banned) == 2 else "R" if banned[0] == "L" else "L"
        n = {sd: cars.get((seg, sd), 0) if car_ok[seg] else 0 for sd in ("L", "R")}
        if n["L"] != n["R"]:
            return "L" if n["L"] > n["R"] else "R"
        return "LR" if n["L"] >= 2 else ""

    stats["one_sided_lane_segments"] = sum(1 for v in one_side.values() if v)

    def side_code(seg, side, entry):
        """Code for one side (or one stretch of it) given its sign entry ({"rules", "msgs"} or None)."""
        osm_yes = osm.get((seg, side)) == "yes"
        if one_side[seg]:
            # The listed lane is at one curb and the other has a travel or bike lane, so neither
            # the lane nor the street's width is evidence for a side until something says which.
            has_evidence = osm_yes or (seg, side) in marked or side in lane_side(seg)
        else:
            has_evidence = (fits.get(seg) or osm_yes or (seg, side) in marked
                            or (car_ok[seg] and cars.get((seg, side), 0) >= 2))
        if (seg, side) in medians:
            return "M"
        if (seg, side) in zone_sides:
            return "Z"
        if spaces.get((seg, side)) == 0 and seg in surveyed and room.get(seg) is not False:
            return ("X", "driveways")
        if entry and entry["rules"]:
            return entry
        if room.get(seg) is False:
            return ("X", why[seg])
        if osm.get((seg, side)) == "no":
            return ("X", "osm")
        if seg not in surveyed:
            return "U"
        if not has_evidence:
            return ("W", "oneside" if one_side[seg] else fit_why[seg])
        return entry if entry else "N"

    evidence, out, stretches = {}, {}, {}
    for seg in kept:
        for side in ("L", "R"):
            out[(seg, side)] = code = side_code(seg, side, entries.get((seg, side)))
            if isinstance(code, dict) and code["rules"]:
                st = split.get((seg, side))
                if st:
                    stretches[(seg, side)] = [(lo, hi, side_code(seg, side, {"rules": r, "msgs": m} if r or m else None))
                                              for lo, hi, r, m in st]
            ev = ((1 if osm.get((seg, side)) == "yes" else 0) | (min(cars.get((seg, side), 0), 3) << 1)
                  | (8 if (seg, side) in marked else 0))
            if ev:
                evidence[(seg, side)] = ev
    stats["no_room_sides"] = sum(1 for v in out.values() if isinstance(v, tuple) and v[1] in ("lane", "bike", "narrow"))
    stats["split_sides"] = len(stretches)
    stats["stretches"] = stretches
    years = sorted(datetime.datetime.fromtimestamp(t / 1000, datetime.timezone.utc).year for t in survey_dates)
    stats["survey_years"] = [years[0], years[len(years) // 2], years[-1]] if years else None
    stats["spaces"] = spaces
    stats["evidence"] = evidence
    stats["osm_sides"] = len(osm)
    stats["car_sides"] = len(cars)
    stats["car_surveys"] = car_surveys
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
    """(along_m, dist_m, side, clamped, piece) of a metric point on the polyline.
    clamped: the point lies beyond one of the polyline's two ends. A point on the outside of a
    bend between two pieces is not clamped. piece: the nearest piece, which gives the street's
    direction at the point."""
    best = None
    last = len(pieces) - 1
    for i, q in enumerate(pieces):
        ax, ay, dx, dy, L, s0 = q
        t = ((x - ax) * dx + (y - ay) * dy) / (L * L)
        tc = max(0.0, min(1.0, t))
        d = math.hypot(x - ax - tc * dx, y - ay - tc * dy)
        if best is None or d < best[1]:
            side = "L" if dx * (y - ay) - dy * (x - ax) > 0 else "R"
            best = (s0 + tc * L, d, side, (t < 0 and i == 0) or (t > 1 and i == last), q)
    return best


HYDRANT_M = 15 * FT    # Tex. Transp. Code 545.302(b)(2): no parking within 15 ft of a fire hydrant
APPROACH_M = 30 * FT   # 545.302(b)(4): ... within 30 ft on the approach to a stop/yield sign or traffic signal
NEAR_END_M = 30.0      # a stop/yield sign this close to a block end controls that end


def _link(pt, geo, grid, widths, extra_m):
    """(seg, along, side, total) of the street a roadside point belongs to: the nearest segment whose
    curb is within extra_m of the point (not beyond either end), else None."""
    x, y = _xy(pt)
    best = None
    for s in grid.near(pt):
        pieces, total = geo[s]
        if not pieces:
            continue
        along, d, side, clamped, _ = _project(x, y, pieces)
        if clamped or d > (widths.get(s) or 30) * FT / 2 + extra_m:
            continue
        if best is None or d < best[0]:
            best = (d, s, along, side, total)
    return best and best[1:]


def clearance_spans(geo, grid, widths, one_way):
    """{(seg, side): [(a_m, b_m)]} curb stretches where Texas law bans parking: 15 ft either side of a
    fire hydrant, and 30 ft on the approach to a stop/yield sign (measured back from the sign) or to
    a traffic signal (measured back from the corner, which the corner clearance places 20 ft from
    the centreline end). Approach = the curb on the right of traffic heading to that end: R side at
    the far end, L side at the near end; on one-way streets both curbs at the downstream end.
    Missing files (optional fetches) are skipped. Returns (spans, stats)."""
    spans, st = {}, {"hydrants": 0, "stop_yield": 0, "signal_ends": 0}

    def load_pts(name):
        p = RAW / f"{name}.geojson"
        return [f["geometry"]["coordinates"] for f in json.loads(p.read_text())["features"]] if p.exists() else []

    def approach(seg, side, at_end):
        ow = (one_way.get(seg) or "").upper()
        if ow == "FT":
            return at_end
        if ow == "TF":
            return not at_end
        return (side == "R") == at_end

    for pt in load_pts("hydrants"):
        hit = _link(pt, geo, grid, widths, 6.0)
        if hit:
            seg, a, side, _ = hit
            spans.setdefault((seg, side), []).append((a - HYDRANT_M, a + HYDRANT_M))
            st["hydrants"] += 1
    for pt in load_pts("stop_signs"):
        hit = _link(pt, geo, grid, widths, 10.0)
        if not hit:
            continue
        seg, a, side, total = hit
        # centreline ends sit mid-intersection; a stop sign stands behind the crosswalk, ~6-20 m back
        near_start, near_end = a <= NEAR_END_M, total - a <= NEAR_END_M
        if not (near_start or near_end):
            continue  # mid-block
        at_end = near_end and (not near_start or total - a <= a)  # the nearer end on short blocks
        if not approach(seg, side, at_end):
            continue  # it faces the cross street or the other direction
        spans.setdefault((seg, side), []).append((a - APPROACH_M, a) if at_end else (a, a + APPROACH_M))
        st["stop_yield"] += 1
    reach = APPROACH_M + CORNER_CLEAR_M
    for pt in load_pts("signals"):
        x, y = _xy(pt)
        for s in grid.near(pt):
            pieces, total = geo[s]
            if not pieces:
                continue
            ends = [(False, pieces[0][0], pieces[0][1])]
            q = pieces[-1]
            ends.append((True, q[0] + q[2], q[1] + q[3]))
            for at_end, ex, ey in ends:
                if math.hypot(ex - x, ey - y) > 25:
                    continue
                for side in ("L", "R"):
                    if approach(s, side, at_end):
                        spans.setdefault((s, side), []).append((total - reach, total) if at_end else (0.0, reach))
                st["signal_ends"] += 1
    return spans, st


def curb_spaces(lines, widths, path, extra=None):
    """{(seg, side): car spaces} counting curb gaps between driveways/lots, minus corner clearance
    and the legal clearances in `extra` ({(seg, side): [(a, b)]}). Returns ({}, 0) if the curb-cut
    file is missing."""
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
                    s, d, side, clamped, _ = _project(x, y, pieces)
                    if d <= reach and not clamped:
                        by_side.setdefault(side, []).append((s, d))
                for side, v in by_side.items():
                    if len(v) < 2 or min(d for _, d in v) > touch:
                        continue
                    a, b = min(s for s, _ in v), max(s for s, _ in v)
                    if 1.5 <= b - a <= 150:
                        cuts.setdefault((seg, side), []).append((a, b))
    for k, v in (extra or {}).items():
        cuts.setdefault(k, []).extend(v)
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
                along, d, _, clamped, q = _project(*_xy(mid), geo[s])
                if d < 8 and not clamped and (best is None or d < best[0]):
                    best = (d, s, q)
            if not best:
                continue
            s, q = best[1], best[2]
            # q is our segment's piece nearest the midpoint: its direction decides left/right
            same = (bx - ax) * q[2] + (by - ay) * q[3] >= 0
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
