// Decode the compact street file written by pipeline/build_segments.py (pack_streets).
// Format v7:
//   {"v":7,"s":1e5,"o":[x0,y0],"n":[names],"m":[sign messages],"r":[rules],"e":[side entries],
//    "sy":[first, median, last survey year],
//    "f":[[name_i, hundred_block, left, right, pavement_ft(-1 unknown), parking_lane(0/1),
//          spaces_left, spaces_right (car-length curb gaps between driveways, -1 unknown), part...]]}
// left/right: -1 city curb zones cover this side (drawn from segments.json instead)
//             -2 city sign survey covered the block and recorded no parking signs on this side
//             -3 no city sign records
//             -4 median side of a divided road (not drawn)
//             -5 / -6 / -7 no physical parking space: travel lane at curb / bike lane at curb / under 24 ft
//             -8 / -9 no parking signs, but room unconfirmed: 24-27 ft with no parking lane / no width data
//             -10 no car-length gap between driveways/lots and corner clearance
//             -11 collector/arterial/multi-lane road with no evidence that curb parking exists
//             >=0 index into e: [[rule_i...], [message_i...]]
// Parts are flat int deltas chained across the whole file.
export const SIDE_ZONES = -1, SIDE_NO_SIGNS = -2, SIDE_NO_RECORDS = -3, SIDE_MEDIAN = -4;
export const SIDE_NO_ROOM = [-5, -6, -7, -10];

export function decodeStreets(d) {
  if (d.v !== 7) throw new Error(`unknown streets format ${d.v}`);
  const S = d.s;
  let px = Math.round(d.o[0] * S), py = Math.round(d.o[1] * S);
  const features = new Array(d.f.length);
  const withRules = [];
  for (let i = 0; i < d.f.length; i++) {
    const row = d.f[i];
    const parts = [];
    for (let j = 8; j < row.length; j++) {
      const flat = row[j];
      const line = new Array(flat.length / 2);
      for (let k = 0; k < flat.length; k += 2) {
        px += flat[k]; py += flat[k + 1];
        line[k / 2] = [px / S, py / S];
      }
      parts.push(line);
    }
    const props = { k: "c", st: d.n[row[0]], src: "signs", L: row[2], R: row[3] };
    if (row[1] >= 0) props.blk = `${row[1] * 100} block`;
    if (row[4] > 0) props.w = row[4];
    if (row[5]) props.pk = 1;
    props.spL = row[6];
    props.spR = row[7];
    if (row[2] >= 0 || row[3] >= 0) withRules.push(i);
    features[i] = { type: "Feature", id: i, properties: props,
      geometry: parts.length === 1 ? { type: "LineString", coordinates: parts[0] } : { type: "MultiLineString", coordinates: parts } };
  }
  return {
    fc: { type: "FeatureCollection", features },
    tables: { messages: d.m, rules: d.r, entries: d.e, surveyYears: d.sy },
    withRules,
  };
}

// Compass side ("north side") for a street side, from the line's overall direction.
export function compassSide(geometry, side) {
  const lines = geometry.type === "LineString" ? [geometry.coordinates] : geometry.coordinates;
  const a = lines[0][0], last = lines[lines.length - 1], b = last[last.length - 1];
  const dx = (b[0] - a[0]) * Math.cos((a[1] * Math.PI) / 180), dy = b[1] - a[1];
  // Left of travel = direction rotated 90 degrees counter-clockwise.
  const [nx, ny] = side === "L" ? [-dy, dx] : [dy, -dx];
  if (nx === 0 && ny === 0) return side === "L" ? "left side" : "right side";
  return Math.abs(nx) > Math.abs(ny) ? (nx > 0 ? "east side" : "west side") : (ny > 0 ? "north side" : "south side");
}
