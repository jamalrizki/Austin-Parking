// Decode the compact street file written by pipeline/build_segments.py (pack_streets).
// Format v3: {"v":3,"s":1e5,"o":[x0,y0],"n":[names],"f":[[name_i, hundred_block, cov, part...]]}
// Parts are flat int deltas chained across the whole file.
export function decodeStreets(d) {
  if (d.v !== 3) throw new Error(`unknown streets format ${d.v}`);
  const S = d.s;
  let px = Math.round(d.o[0] * S), py = Math.round(d.o[1] * S);
  const features = new Array(d.f.length);
  for (let i = 0; i < d.f.length; i++) {
    const row = d.f[i];
    const parts = [];
    for (let j = 3; j < row.length; j++) {
      const flat = row[j];
      const line = new Array(flat.length / 2);
      for (let k = 0; k < flat.length; k += 2) {
        px += flat[k]; py += flat[k + 1];
        line[k / 2] = [px / S, py / S];
      }
      parts.push(line);
    }
    const props = { k: "c", st: d.n[row[0]], src: "centerline" };
    if (row[1] >= 0) props.blk = `${row[1] * 100} block`;
    if (row[2]) props.cov = true;
    features[i] = { type: "Feature", id: i, properties: props,
      geometry: parts.length === 1 ? { type: "LineString", coordinates: parts[0] } : { type: "MultiLineString", coordinates: parts } };
  }
  return { type: "FeatureCollection", features };
}
