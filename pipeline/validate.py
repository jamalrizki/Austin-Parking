"""Sanity checks on public/data/segments.geojson. Exit non-zero on failure so the
weekly refresh never publishes a broken or half-fetched dataset."""
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SEG = ROOT / "public" / "data" / "segments.json"
STREETS = ROOT / "public" / "data" / "streets.json"
MAX_MB = 5.0
MAX_STREETS_MB = 4.0
MIN = {"z": 4000}  # well below current count (5,617); catches partial fetches
MIN_STREETS = 40000  # currently ~49,000
QUALITY = {"ok", "one", "conflict", "none", "event", "complex"}

errors = []
size = SEG.stat().st_size / 1e6
if size > MAX_MB:
    errors.append(f"segments.json is {size:.2f} MB (limit {MAX_MB})")
ssize = STREETS.stat().st_size / 1e6
if ssize > MAX_STREETS_MB:
    errors.append(f"streets.json is {ssize:.2f} MB (limit {MAX_STREETS_MB})")
streets = json.loads(STREETS.read_text())
if streets.get("v") != 3:
    errors.append(f"streets.json format v{streets.get('v')} (expected 3)")
if len(streets["f"]) < MIN_STREETS:
    errors.append(f"only {len(streets['f'])} streets (expected >= {MIN_STREETS}); fetch may be incomplete")
fc = json.loads(SEG.read_text())
types = fc["meta"]["zone_types"]
counts, quality = {}, {}
for f in fc["features"]:
    p = f["properties"]
    counts[p["k"]] = counts.get(p["k"], 0) + 1
    if not f.get("geometry"):
        errors.append(f"feature without geometry: {p}")
    if p["k"] == "z":
        quality[p["q"]] = quality.get(p["q"], 0) + 1
        if p["q"] not in QUALITY:
            errors.append(f"zone {p['id']} bad quality {p['q']}")
        if p["q"] in ("ok", "one") and not p["w"]:
            errors.append(f"zone {p['id']} marked usable but has no hour windows")
        for d, a, b in p["w"]:
            if not (0 <= d <= 6 and 0 <= a < 1440 and a < b <= a + 1440):
                errors.append(f"zone {p['id']} bad window {(d, a, b)}")
        if p["t"] not in types:
            errors.append(f"zone {p['id']} unknown type {p['t']}")
for k, n in MIN.items():
    if counts.get(k, 0) < n:
        errors.append(f"only {counts.get(k, 0)} '{k}' features (expected >= {n}); fetch may be incomplete")
usable = (quality.get("ok", 0) + quality.get("one", 0)) / max(1, counts.get("z", 0))
if usable < 0.9:
    errors.append(f"only {usable:.0%} of zones have usable hours; city data format may have changed")

print(f"segments {size:.2f} MB, streets {ssize:.2f} MB ({len(streets['f'])}), counts {counts}, zone quality {quality}")
if errors:
    print("VALIDATION FAILED:")
    for e in errors[:50]:
        print("  -", e)
    sys.exit(1)
print("validation ok")
