"""Geometry and evidence helpers in the pipeline. Run: python3 -m unittest discover -s tests"""
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
sys.path.insert(0, str(ROOT / "pipeline" / "cars"))
import assign  # noqa: E402
import sides as S  # noqa: E402

LON, LAT = -97.70, 30.33
M_LON, M_LAT = 1 / S.KX, 1 / S.KY  # degrees per metre


def pt(east_m, north_m):
    return [LON + east_m * M_LON, LAT + north_m * M_LAT]


class GridTest(unittest.TestCase):
    def test_finds_the_middle_of_a_long_straight_block(self):
        # 400 m block with vertices only at its ends; a point 10 m off its midpoint must find it.
        g = S.Grid(cell=60)
        g.add("a", [[pt(0, 0), pt(400, 0)]])
        self.assertIn("a", g.near(pt(200, 10)))
        self.assertIn("a", g.near(pt(310, -25)))
        self.assertNotIn("a", g.near(pt(200, 300)))


class ProjectTest(unittest.TestCase):
    def setUp(self):
        # L-shaped street: 100 m east, then 100 m north.
        self.pieces, self.total = S._pieces([[pt(0, 0), pt(100, 0), pt(100, 100)]])

    def test_piece_is_the_nearest_one_not_the_nearest_infinite_line(self):
        # 3 m west of the northbound leg, level with y = 50: the eastbound leg's infinite line is
        # 50 m away, the northbound leg 3 m. Direction must be north.
        x, y = S._xy(pt(97, 50))
        along, d, side, clamped, q = S._project(x, y, self.pieces)
        self.assertAlmostEqual(d, 3, delta=0.01)
        self.assertEqual(side, "L")
        self.assertFalse(clamped)
        self.assertAlmostEqual(q[2], 0, delta=0.01)   # dx
        self.assertGreater(q[3], 99)                   # dy: heading north
        self.assertAlmostEqual(along, 150, delta=0.01)

    def test_outside_of_a_bend_is_not_clamped_but_beyond_an_end_is(self):
        x, y = S._xy(pt(104, -4))          # outside the corner
        self.assertFalse(S._project(x, y, self.pieces)[3])
        x, y = S._xy(pt(-5, 2))            # before the start
        self.assertTrue(S._project(x, y, self.pieces)[3])
        x, y = S._xy(pt(98, 106))          # past the end
        self.assertTrue(S._project(x, y, self.pieces)[3])


class DedupeTest(unittest.TestCase):
    def test_same_car_twice_counts_once_and_keeps_the_confident_one(self):
        a, b, c = pt(0, 0) + [0.6], pt(0.9, 0.4) + [0.9], pt(0, 6) + [0.7]
        out = assign.dedupe([a, b, c])
        self.assertEqual(len(out), 2)
        self.assertIn(b[:2], out)
        self.assertNotIn(a[:2], out)


class LaneListingTest(unittest.TestCase):
    def row(self, detail, general="2U-OP"):
        return {"CROSS_SECTION_DETAIL": detail, "CROSS_SECTION_GENERAL": general, "PAVEMENT_WIDTH": 40}

    def test_both_curbs_one_curb_none(self):
        self.assertEqual(S.lane_listing(self.row("P-T-CL-T-P")), 1)
        self.assertEqual(S.lane_listing(self.row("P-BL-T-CL-T-BL")), 2)
        self.assertEqual(S.lane_listing(self.row("BL-T-CL-T-BL-P")), 2)
        self.assertEqual(S.lane_listing(self.row("T-CL-T", "2U-N")), 0)
        self.assertEqual(S.lane_listing(None), 0)


NP = {"t": "No Parking", "w": [[d, 0, 1440] for d in range(7)], "q": "ok"}
PERMIT = {"t": "Residential Parking Permit", "w": [[d, 1080, 1920] for d in range(7)], "q": "ok"}


class SignStretchTest(unittest.TestCase):
    def test_arrow_wording(self):
        from signs import arrow
        self.assertEqual(arrow("NO PARKING SYMBOL LEFT ARROW"), "left")
        self.assertEqual(arrow("PAY TO PARK RIGHT ARROW"), "right")
        self.assertEqual(arrow("NO PARKING BIKE LANE DOUBLE ARROW"), "both")
        self.assertEqual(arrow("NO PARKING BOTH ARROWS TOW-AWAY ZONE"), "both")
        self.assertIsNone(arrow("NO PARKING IN BIKE LANE"))

    def test_left_side_right_arrow_points_forward(self):
        # 100 m block, left side: RIGHT arrow at 80 m covers 80..100 (to the corner); the rest is open.
        st = S.sign_stretches([(80.0, "right", NP, "NO PARKING RIGHT ARROW")], "L", 100.0)
        self.assertEqual([(lo, hi, len(r)) for lo, hi, r, _ in st], [(0.0, 80.0, 0), (80.0, 100.0, 1)])
        self.assertEqual(st[0][3], [])
        self.assertEqual(st[1][3], ["NO PARKING RIGHT ARROW"])

    def test_right_side_mirrors(self):
        st = S.sign_stretches([(80.0, "right", NP, "m")], "R", 100.0)
        self.assertEqual([(lo, hi, len(r)) for lo, hi, r, _ in st], [(0.0, 80.0, 1), (80.0, 100.0, 0)])

    def test_paired_signs_bound_a_stretch(self):
        # left side: RIGHT arrow (forward) at 20 starts it, LEFT arrow (back) at 60 ends it
        st = S.sign_stretches([(20.0, "right", NP, "a"), (60.0, "left", NP, "b"), (40.0, "both", NP, "c")], "L", 150.0)
        self.assertEqual([(lo, hi, len(r)) for lo, hi, r, _ in st], [(0.0, 20.0, 0), (20.0, 60.0, 1), (60.0, 150.0, 0)])

    def test_no_arrow_or_unclosed_double_covers_the_whole_side(self):
        self.assertIsNone(S.sign_stretches([(50.0, None, NP, "NO PARKING ANY TIME")], "L", 100.0))
        self.assertIsNone(S.sign_stretches([(50.0, "both", NP, "x")], "L", 100.0))

    def test_arrow_and_plain_sign_at_the_same_spot(self):
        self.assertIsNone(S.sign_stretches([(50.0, "left", NP, "a"), (50.0, None, NP, "b")], "L", 100.0))

    def test_short_gap_is_not_left_open(self):
        # corner gap of 9 m (< one car + 20 ft corner clearance) is folded into the stretch
        self.assertIsNone(S.sign_stretches([(91.0, "left", NP, "x")], "L", 100.0))

    def test_two_rules_each_where_their_arrows_point(self):
        st = S.sign_stretches([(30.0, "left", NP, "np"), (30.5, "right", PERMIT, "permit")], "L", 120.0)
        self.assertEqual([(r[0]["t"] if r else None) for _, _, r, _ in st], ["No Parking", "Residential Parking Permit"])


class ClearanceTest(unittest.TestCase):
    def test_hydrant_stop_sign_and_signal(self):
        import json
        import tempfile
        tmp = pathlib.Path(tempfile.mkdtemp())
        pts = lambda *ps: json.dumps({"type": "FeatureCollection", "features": [
            {"type": "Feature", "geometry": {"type": "Point", "coordinates": p}, "properties": {}} for p in ps]})
        # 100 m two-way street heading east; left = north
        (tmp / "hydrants.geojson").write_text(pts(pt(50, 8)))
        (tmp / "stop_signs.geojson").write_text(pts(pt(95, -7), pt(95, 7)))  # R: our approach; L: faces the cross street
        (tmp / "signals.geojson").write_text(pts(pt(102, 0)))
        old, S.RAW = S.RAW, tmp
        try:
            lines = {"a": [[pt(0, 0), pt(100, 0)]]}
            geo = {"a": S._pieces(lines["a"])}
            grid = S.Grid(cell=60)
            grid.add("a", lines["a"])
            spans, st = S.clearance_spans(geo, grid, {"a": 30}, {"a": "B"})
        finally:
            S.RAW = old
        r = lambda v: [(round(a, 1), round(b, 1)) for a, b in v]
        self.assertEqual(r(spans[("a", "L")]), [(45.4, 54.6)])                 # hydrant: 15 ft each way
        self.assertEqual(r(spans[("a", "R")]), [(85.9, 95.0), (84.8, 100.0)])  # stop sign 30 ft back; signal 30 ft + corner
        self.assertEqual(st, {"hydrants": 1, "stop_yield": 1, "signal_ends": 1})


class CutLinesTest(unittest.TestCase):
    def test_cut_middle_of_a_bent_line(self):
        line = [pt(0, 0), pt(100, 0), pt(100, 100)]
        parts = S.cut_lines([line], 50, 150)
        self.assertEqual(len(parts), 1)
        self.assertEqual(len(parts[0]), 3)  # start, the bend, end
        (sx, sy), (ex, ey) = S._xy(parts[0][0]), S._xy(parts[0][-1])
        ox, oy = S._xy(pt(0, 0))
        self.assertAlmostEqual(sx - ox, 50, delta=0.05)
        self.assertAlmostEqual(ey - oy, 50, delta=0.05)


if __name__ == "__main__":
    unittest.main()
