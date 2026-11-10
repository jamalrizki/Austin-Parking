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


if __name__ == "__main__":
    unittest.main()
