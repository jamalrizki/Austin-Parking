"""Detect parked cars in public aerial imagery (our own 'parking exists here' evidence).

Sources (all public ArcGIS ImageServers, exportImage):
  city2023  City of Austin 2023 aerials, 0.5 ft (~15 cm)
  sm2019    TxGIO StratMap 2019 Capital Area, 15 cm, leaf-off (Jan 2019)
  sm2020    TxGIO StratMap 2020 Capital Area/McLennan, 7.6 cm, leaf-off (Jan 2020)
Model: Ultralytics YOLOv8m-OBB trained on DOTA (aerial imagery; classes include 'small vehicle').

Usage: .venv/bin/python pipeline/cars/detect.py WEST SOUTH EAST NORTH [sources...]
Writes pipeline/cars/out/cars_<source>.geojson (car centre points with confidence).
"""
import json
import math
import pathlib
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[2]
TILES = ROOT / "pipeline" / "cars" / "tiles"
OUT = ROOT / "pipeline" / "cars" / "out"
MODELS = ROOT / "pipeline" / "models"
UA = "austin-free-parking-pipeline/1.0 (+https://github.com/jamalrizki/Austin-Parking)"

SOURCES = {
    "city2023": "https://maps.austintexas.gov/image/rest/services/AerialMosaics/Aerials2023/ImageServer",
    "sm2019": "https://imagery.geographic.texas.gov/server/rest/services/StratMap/StratMap19_NCCIR_CapArea/ImageServer",
    "sm2020": "https://imagery.geographic.texas.gov/server/rest/services/StratMap/StratMap20_NCCIR_CapArea_McLennan/ImageServer",
}
GSD = 0.15          # metres per pixel we request (downsample 7.6 cm imagery to match the model's training scale)
TILE_PX = 1024
OVERLAP_PX = 96
R = 6378137.0


def merc(lon, lat):
    return R * math.radians(lon), R * math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def unmerc(x, y):
    return math.degrees(x / R), math.degrees(2 * math.atan(math.exp(y / R)) - math.pi / 2)


def fetch_tile(src, x0, y0, x1, y1, path):
    if path.exists() and path.stat().st_size > 1000:
        return path
    q = urllib.parse.urlencode({
        "bbox": f"{x0},{y0},{x1},{y1}", "bboxSR": 3857, "imageSR": 3857, "size": f"{TILE_PX},{TILE_PX}",
        "format": "jpg", "compression": 85, "bandIds": "0,1,2", "interpolation": "RSP_BilinearInterpolation", "f": "image",
    })
    for i in range(4):
        try:
            req = urllib.request.Request(f"{SOURCES[src]}/exportImage?{q}", headers={"User-Agent": UA})
            data = urllib.request.urlopen(req, timeout=120).read()
            if data[:2] != b"\xff\xd8":
                raise ValueError(data[:200])
            path.write_bytes(data)
            return path
        except Exception as e:  # noqa: BLE001
            if i == 3:
                raise
            time.sleep(3 * (i + 1))


def main():
    west, south, east, north = map(float, sys.argv[1:5])
    sources = sys.argv[5:] or list(SOURCES)
    from ultralytics import YOLO  # imported late so the tile download works without it
    MODELS.mkdir(parents=True, exist_ok=True)
    model = YOLO(str(MODELS / "yolov8m-obb.pt"))
    names = model.names
    keep = {i for i, n in names.items() if n in ("small vehicle", "large vehicle")}
    x0, y0 = merc(west, south)
    x1, y1 = merc(east, north)
    span = TILE_PX * GSD
    step = (TILE_PX - OVERLAP_PX) * GSD
    OUT.mkdir(parents=True, exist_ok=True)
    for src in sources:
        (TILES / src).mkdir(parents=True, exist_ok=True)
        feats, seen = [], set()
        tx = x0
        while tx < x1:
            ty = y0
            while ty < y1:
                path = TILES / src / f"{int(tx)}_{int(ty)}.jpg"
                fetch_tile(src, tx, ty, tx + span, ty + span, path)
                res = model.predict(str(path), imgsz=TILE_PX, conf=0.35, device="mps", verbose=False)[0]
                if res.obb is not None:
                    for (cx, cy, w, h, _), c, k in zip(res.obb.xywhr.tolist(), res.obb.conf.tolist(), res.obb.cls.tolist()):
                        if int(k) not in keep:
                            continue
                        mx, my = tx + cx * GSD, ty + span - cy * GSD
                        key = (round(mx / 2), round(my / 2))  # de-duplicate across tile overlaps (~2 m)
                        if key in seen:
                            continue
                        seen.add(key)
                        lon, lat = unmerc(mx, my)
                        feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]},
                                      "properties": {"conf": round(c, 3), "len_m": round(max(w, h) * GSD, 1), "cls": names[int(k)]}})
                ty += step
            tx += step
        (OUT / f"cars_{src}.geojson").write_text(json.dumps({"type": "FeatureCollection", "source": src, "features": feats}))
        print(f"{src}: {len(feats)} vehicles")


if __name__ == "__main__":
    main()
