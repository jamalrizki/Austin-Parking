"""Work out what is known about each SIDE of each street segment.

Per side, in priority order:
  Z  the city curb-zone inventory covers this side (zones are drawn instead)
  S  the city sign inventory has parking signs on this side -> rules from the sign text
  N  the city's sign survey covered this block (it has other signs on record) and recorded
     no parking signs on this side
  U  no city sign records for this block at all -> unknown
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


def build_side_info(kept, pay_areas, props=None):
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
    stats["median_sides"] = len(medians)
    out = {}
    for seg in kept:
        for side in ("L", "R"):
            if (seg, side) in medians:
                out[(seg, side)] = "M"
            elif (seg, side) in zone_sides:
                out[(seg, side)] = "Z"
            elif (seg, side) in entries:
                out[(seg, side)] = entries[(seg, side)]
            elif seg in surveyed:
                out[(seg, side)] = "N"
            else:
                out[(seg, side)] = "U"
    years = sorted(datetime.datetime.fromtimestamp(t / 1000, datetime.timezone.utc).year for t in survey_dates)
    stats["survey_years"] = [years[0], years[len(years) // 2], years[-1]] if years else None
    return out, stats
