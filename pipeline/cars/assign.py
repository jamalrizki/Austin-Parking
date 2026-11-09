"""Assign detected vehicles to street sides: our own 'cars park here' evidence.

A detection counts as curb-parked on (segment, side) when:
  - its centre is in that side's curb band: from (half pavement width - 1.9 m) to (half width + 0.6 m)
    from the centreline (a parked car's centre sits ~1.1 m in from the curb; a car driving in the
    travel lane sits closer to the centreline and is excluded on normal two-lane streets),
  - it projects onto the segment (not past either end, i.e. not in the intersection),
  - it is not inside a mapped driveway or parking-lot polygon (impervious_cover_2023).
Output: pipeline/raw/curb_cars.json  {"<seg>|<L|R>": {"<source>": count, ...}, ...}
"""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import sides as S  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[2]
RAW = ROOT / "pipeline" / "raw"
OUT_DIR = ROOT / "pipeline" / "cars" / "out"
FT = 0.3048
DEFAULT_WIDTH_FT = 30


def in_ring(x, y, ring):
    inside = False
    for (x1, y1), (x2, y2) in zip(ring, ring[1:]):
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def main(kept_lines, widths, bbox=None):
    det = {}
    for p in sorted(OUT_DIR.glob("cars_*.geojson")):
        fc = json.loads(p.read_text())
        det[fc["source"]] = [f["geometry"]["coordinates"] for f in fc["features"] if f["properties"]["conf"] >= 0.5]
    if not det:
        return {}
    pts_all = [pt for v in det.values() for pt in v]
    lo_x, lo_y = min(p[0] for p in pts_all) - 0.002, min(p[1] for p in pts_all) - 0.002
    hi_x, hi_y = max(p[0] for p in pts_all) + 0.002, max(p[1] for p in pts_all) + 0.002

    def inside_box(p):
        return lo_x <= p[0] <= hi_x and lo_y <= p[1] <= hi_y

    # Driveway / lot polygons near the detections (metric rings), grid-indexed.
    lots = S.Grid(cell=40)
    rings = []
    with open(RAW / "curb_cuts.jsonl") as fh:
        for line in fh:
            _, ring = json.loads(line)
            if not inside_box(ring[0]):
                continue
            i = len(rings)
            rings.append([S._xy(p) for p in ring])
            lots.add(i, [ring])

    segs = {s: ls for s, ls in kept_lines.items() if any(inside_box(p) for line in ls for p in line)}
    grid = S.Grid(cell=60)
    geo = {}
    for s, ls in segs.items():
        grid.add(s, ls)
        geo[s] = S._pieces(ls)[0]

    out = {}
    for src, pts in det.items():
        for pt in pts:
            x, y = S._xy(pt)
            if any(in_ring(x, y, rings[i]) for i in lots.near(pt)):
                continue
            best = None
            for s in grid.near(pt):
                if not geo[s]:
                    continue
                along, d, side, clamped = S._project(x, y, geo[s])
                if clamped:
                    continue
                half = (widths.get(s) or DEFAULT_WIDTH_FT) * FT / 2
                if half - 1.9 <= d <= half + 0.6 and (best is None or d < best[0]):
                    best = (d, s, side)
            if best:
                k = f"{best[1]}|{best[2]}"
                out.setdefault(k, {})
                out[k][src] = out[k].get(src, 0) + 1
    (RAW / "curb_cars.json").write_text(json.dumps(out))
    return out
