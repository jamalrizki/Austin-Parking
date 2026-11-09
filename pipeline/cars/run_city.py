"""Citywide parked-car detection: resumable, safe to stop and restart at any time.

  start / resume:  .venv/bin/python pipeline/cars/run_city.py
  progress:        .venv/bin/python pipeline/cars/run_city.py --status
  merge results:   .venv/bin/python pipeline/cars/run_city.py --merge   (also runs automatically when a survey finishes)

Every finished tile is appended to pipeline/cars/progress/<source>.jsonl, so a restart skips it.
Only tiles that contain streets on the map (public/data/streets.json) are processed.
Each tile image is deleted after detection to keep disk use small.
Surveys run in order: city2023 (fastest, newest), sm2020, sm2019.
"""
import concurrent.futures as cf
import json
import math
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import detect as D  # noqa: E402

ROOT = D.ROOT
PROGRESS = ROOT / "pipeline" / "cars" / "progress"
ORDER = ["city2023", "sm2020", "sm2019"]
WORKERS = 4  # parallel downloads; detection itself runs one tile at a time on the GPU


def street_tiles():
    """Mercator tile origins (x, y) whose square contains part of a street on the map."""
    d = json.loads((ROOT / "public" / "data" / "streets.json").read_text())
    S = d["s"]
    px, py = round(d["o"][0] * S), round(d["o"][1] * S)
    start = 10 if d["v"] >= 8 else 8 if d["v"] == 7 else 6
    step = (D.TILE_PX - D.OVERLAP_PX) * D.GSD
    tiles = set()
    for row in d["f"]:
        pts = []
        for part in row[start:]:
            for k in range(0, len(part), 2):
                px += part[k]
                py += part[k + 1]
                pts.append((px / S, py / S))
        # sample every ~20 m along the street
        for (ax, ay), (bx, by) in zip(pts, pts[1:]) if len(pts) > 1 else [(pts[0], pts[0])]:
            n = max(1, int(math.hypot((bx - ax) * 96000, (by - ay) * 111000) / 20))
            for i in range(n + 1):
                x, y = D.merc(ax + (bx - ax) * i / n, ay + (by - ay) * i / n)
                tiles.add((math.floor(x / step) * step, math.floor(y / step) * step))
    return sorted(tiles)


def done_tiles(src):
    p = PROGRESS / f"{src}.jsonl"
    if not p.exists():
        return set()
    out = set()
    for line in p.read_text().splitlines():
        try:
            out.add(tuple(json.loads(line)["t"]))
        except (ValueError, KeyError):
            pass  # a half-written last line from a hard stop: that tile is simply redone
    return out


def merge(src):
    feats, seen = [], set()
    p = PROGRESS / f"{src}.jsonl"
    if not p.exists():
        return 0
    for line in p.read_text().splitlines():
        try:
            rec = json.loads(line)
        except ValueError:
            continue
        for lon, lat, conf, length, cls in rec["c"]:
            key = (round(lon, 5), round(lat, 5))
            if key in seen:
                continue
            seen.add(key)
            feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                          "properties": {"conf": conf, "len_m": length, "cls": cls}})
    D.OUT.mkdir(parents=True, exist_ok=True)
    (D.OUT / f"cars_{src}.geojson").write_text(json.dumps({"type": "FeatureCollection", "source": src, "features": feats}))
    return len(feats)


def status(tiles):
    for src in ORDER:
        n = len(done_tiles(src))
        print(f"{src:9} {n:6d} / {len(tiles)} tiles ({n / len(tiles):.1%})")


def run(tiles):
    from ultralytics import YOLO
    model = YOLO(str(D.MODELS / "yolov8m-obb.pt"))
    names = model.names
    keep = {i for i, n in names.items() if n in ("small vehicle", "large vehicle")}
    span = D.TILE_PX * D.GSD
    PROGRESS.mkdir(parents=True, exist_ok=True)
    for src in ORDER:
        done = done_tiles(src)
        todo = [t for t in tiles if t not in done]
        if not todo:
            print(f"{src}: complete ({len(tiles)} tiles)")
            continue
        print(f"{src}: {len(done)} done, {len(todo)} to go", flush=True)
        tdir = D.TILES / src
        tdir.mkdir(parents=True, exist_ok=True)
        t0, n = time.time(), 0

        def fetch(t):
            path = tdir / f"{int(t[0])}_{int(t[1])}.jpg"
            try:
                D.fetch_tile(src, t[0], t[1], t[0] + span, t[1] + span, path)
                return t, path
            except Exception as e:  # noqa: BLE001
                print(f"  download failed {t}: {e}", flush=True)
                return t, None

        with open(PROGRESS / f"{src}.jsonl", "a") as log, cf.ThreadPoolExecutor(WORKERS) as pool:
            for t, path in pool.map(fetch, todo):
                if path is None:
                    continue  # left undone; the next run retries it
                res = model.predict(str(path), imgsz=D.TILE_PX, conf=0.35, device="mps", verbose=False)[0]
                cars = []
                if res.obb is not None:
                    for (cx, cy, w, h, _), c, k in zip(res.obb.xywhr.tolist(), res.obb.conf.tolist(), res.obb.cls.tolist()):
                        if int(k) in keep:
                            lon, lat = D.unmerc(t[0] + cx * D.GSD, t[1] + span - cy * D.GSD)
                            cars.append([round(lon, 7), round(lat, 7), round(c, 3), round(max(w, h) * D.GSD, 1), names[int(k)]])
                log.write(json.dumps({"t": list(t), "c": cars}) + "\n")
                log.flush()
                path.unlink(missing_ok=True)
                n += 1
                if n % 200 == 0:
                    rate = n / (time.time() - t0)
                    left = (len(todo) - n) / rate / 3600
                    print(f"  {src}: {len(done) + n}/{len(tiles)}  {rate:.2f} tiles/s  ~{left:.1f} h left", flush=True)
        print(f"{src}: finished, {merge(src)} vehicles merged", flush=True)


if __name__ == "__main__":
    tiles = street_tiles()
    if "--status" in sys.argv:
        status(tiles)
    elif "--merge" in sys.argv:
        for s in ORDER:
            print(s, merge(s))
    else:
        print(f"{len(tiles)} tiles contain streets", flush=True)
        if "--limit" in sys.argv:  # quick test: only the first N tiles of the first unfinished survey
            n = int(sys.argv[sys.argv.index("--limit") + 1])
            ORDER[:] = [s for s in ORDER if len(done_tiles(s)) < len(tiles)][:1]
            tiles = [t for t in tiles if t not in done_tiles(ORDER[0])][:n] + list(done_tiles(ORDER[0]))
        run(tiles)
