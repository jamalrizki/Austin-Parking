"""Assign detected vehicles to street sides: our own 'cars park here' evidence.

Curb lines come from the city's paved-road outlines (impervious_cover_2023 'Paved Road', traced
from the same aerial imagery as the detections), not from the street centreline, which can be
several metres off. For each detected vehicle:
  1. find the nearest street segment within 25 m (for its direction only, taken from the piece
     of it nearest the car) and skip cars within 8 m of either end of it (intersections);
  2. cast a line across the road through the car, both ways, and measure the distance to the
     paved edge on each side (dL, dR);
  3. it is curb-parked when it is on the paved road (both edges found), within 3.2 m of one edge,
     and the road there is at least 6 m wide; the nearer edge gives the side (L/R relative to the
     segment's direction, same convention as the rest of the pipeline).
  4. per side and survey, the survey counts as "cars park here" only if >= 2 cars hug the curb
     (<= 1.6 m from the edge) and they outnumber cars further out in the lane 2:1, which separates
     parked rows from traffic in a curb lane (Camino La Costa, Cameron Rd, frontage roads).
Detections closer than 1.5 m to one already kept are the same car reported twice (tile overlaps,
or both vehicle classes firing) and are dropped first, so one car can't meet the 2-car rule alone.
Returns ({"<seg>|<L|R>": {"<source>": hugging_count, ...}, ...}, [sources]); the same dict is also
written to pipeline/raw/curb_cars.json for inspection (the build does not read it back).
"""
import gzip
import json
import math
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import sides as S  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "pipeline" / "raw"
OUT_DIR = ROOT / "pipeline" / "cars" / "out"
CELL = 15.0
RAY_M = 40.0
CURB_M = 3.2       # anything this close to an edge is "at the curb or in the curb lane"
HUG_M = 1.6        # parked cars: median 1.2 m from the paved edge, 77% within 1.5 m (measured on
                   # St. John's residential streets); moving traffic median 2.8 m, 21% within 1.5 m
MIN_ROAD_M = 6.0
END_CLEAR_M = 8.0
DUP_M = 1.5        # two car centres can't be this close: 2-3% of detections are such repeats


def dedupe(cars):
    """[[lon, lat, conf], ...] -> [[lon, lat], ...] without repeats of the same car; the most
    confident detection of each car is the one kept."""
    cells, out = {}, []
    for lon, lat, _ in sorted(cars, key=lambda c: -c[2]):
        x, y = S._xy((lon, lat))
        cx, cy = int(x // DUP_M), int(y // DUP_M)
        if any((x - qx) ** 2 + (y - qy) ** 2 < DUP_M ** 2
               for i in (-1, 0, 1) for j in (-1, 0, 1) for qx, qy in cells.get((cx + i, cy + j), ())):
            continue
        cells.setdefault((cx, cy), []).append((x, y))
        out.append([lon, lat])
    return out


def _cell(x, y):
    return int(x // CELL), int(y // CELL)


def load_edges(box):
    """Grid of road-outline edges (metric) inside box (lon/lat)."""
    lo_x, lo_y, hi_x, hi_y = box
    grid = {}
    with open(RAW / "roads.jsonl") as fh:
        for line in fh:
            for ring in json.loads(line):
                prev = None
                for p in ring:
                    inside = lo_x <= p[0] <= hi_x and lo_y <= p[1] <= hi_y
                    cur = S._xy(p)
                    if prev is not None and (inside or prev[2]):
                        (ax, ay), (bx, by) = prev[:2], cur
                        e = (ax, ay, bx, by)
                        n = max(1, int(math.hypot(bx - ax, by - ay) // CELL) + 1)
                        for i in range(n + 1):
                            k = _cell(ax + (bx - ax) * i / n, ay + (by - ay) * i / n)
                            grid.setdefault(k, set()).add(e)
                    prev = (cur[0], cur[1], inside)
    return grid


def _ray_hits(grid, x, y, ux, uy):
    """Sorted distances along (ux, uy) from (x, y) where the ray crosses a road edge, up to RAY_M."""
    edges = set()
    t = 0.0
    while t <= RAY_M:
        cx, cy = _cell(x + ux * t, y + uy * t)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                edges |= grid.get((cx + dx, cy + dy), set())
        t += CELL
    hits = []
    for ax, ay, bx, by in edges:
        ex, ey = bx - ax, by - ay
        den = ux * ey - uy * ex
        if abs(den) < 1e-12:
            continue
        s = ((ax - x) * ey - (ay - y) * ex) / den      # distance along the ray
        u = ((ax - x) * uy - (ay - y) * ux) / den      # position along the edge
        if 0 < s <= RAY_M and 0 <= u <= 1:
            hits.append(s)
    return sorted(hits)


def main(kept_lines, widths=None):
    det = {}
    for p in sorted(OUT_DIR.glob("cars_*.json.gz")):  # citywide surveys (run_city.py --merge)
        d = json.loads(gzip.decompress(p.read_bytes()))
        det[d["source"]] = dedupe([c for c in d["c"] if c[2] >= 0.5])
    for p in sorted(OUT_DIR.glob("cars_*.geojson")):  # bbox test runs (detect.py); citywide wins
        fc = json.loads(p.read_text())
        if fc["source"] not in det:
            det[fc["source"]] = dedupe([f["geometry"]["coordinates"][:2] + [f["properties"]["conf"]]
                                        for f in fc["features"] if f["properties"]["conf"] >= 0.5])
    if not det:
        return {}, []
    if not (RAW / "roads.jsonl").exists():
        # Without curb lines every side would silently lose its aerial evidence.
        sys.exit("ERROR: car detections exist but pipeline/raw/roads.jsonl is missing; run pipeline/fetch_layers.py")
    pts = [pt for v in det.values() for pt in v]
    box = (min(p[0] for p in pts) - 0.003, min(p[1] for p in pts) - 0.003,
           max(p[0] for p in pts) + 0.003, max(p[1] for p in pts) + 0.003)
    edges = load_edges(box)
    segs = {s: ls for s, ls in kept_lines.items()
            if any(box[0] <= p[0] <= box[2] and box[1] <= p[1] <= box[3] for line in ls for p in line)}
    sgrid = S.Grid(cell=60)
    geo = {}
    for s, ls in segs.items():
        sgrid.add(s, ls)
        geo[s] = S._pieces(ls)

    out, stats = {}, {"cars": 0, "curb": 0}
    for src, plist in det.items():
        for pt in plist:
            stats["cars"] += 1
            x, y = S._xy(pt)
            best = None
            for s in sgrid.near(pt):
                pieces, total = geo[s]
                if not pieces:
                    continue
                along, d, _, clamped, q = S._project(x, y, pieces)
                if clamped or d > 25:
                    continue
                if best is None or d < best[0]:
                    best = (d, s, along, total, q)
            if not best:
                continue
            _, s, along, total, q = best
            if along < END_CLEAR_M or along > total - END_CLEAR_M:
                continue
            # local direction of the segment at the car: the piece of it nearest the car
            _, _, dx, dy, L, _ = q
            ux, uy = dx / L, dy / L
            nx, ny = -uy, ux  # left normal
            left = _ray_hits(edges, x, y, nx, ny)
            right = _ray_hits(edges, x, y, -nx, -ny)
            if not left or not right:
                continue
            # on the paved road: the first crossing each way must be the road's own edge, i.e. the
            # car sits between them, which odd crossing parity to one side confirms
            if len(left) % 2 == 0 and len(right) % 2 == 0:
                continue
            dL, dR = left[0], right[0]
            if min(dL, dR) > CURB_M or dL + dR < MIN_ROAD_M:
                continue
            side = "L" if dL < dR else "R"
            k = f"{s}|{side}"
            rec = out.setdefault(k, {}).setdefault(src, [0, 0])  # [hugging the curb, further out in the lane]
            rec[0 if min(dL, dR) <= HUG_M else 1] += 1
            stats["curb"] += 1
    # A survey shows parking on a side when parked-looking cars dominate: at least 2 hugging the
    # curb and at least twice as many as cars sitting further out (traffic in the curb lane).
    final = {}
    for k, per in out.items():
        final[k] = {src: hug for src, (hug, lane) in per.items() if hug >= 2 and hug >= 2 * lane}
    (RAW / "curb_cars.json").write_text(json.dumps(final))
    print(f"  curb-parked vehicles: {stats['curb']} of {stats['cars']} detections in {sorted(det)}")
    return final, sorted(det)
