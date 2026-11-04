import unittest
from building_footprints import contains_point


class CourtyardGeometryTests(unittest.TestCase):
    def test_filled_parts_preserve_area_and_holes_for_concave_buildings(self):
        from building_footprints import subtract_courtyards
        outer=[(0,0),(100,0),(100,100),(60,100),(60,80),(0,80)]
        holes=[[(10,10),(30,10),(30,30),(10,30)],[(70,50),(90,50),(90,90),(70,90)]]
        parts=subtract_courtyards([outer],holes)
        def area(r):return abs(sum(a[0]*b[1]-b[0]*a[1] for a,b in zip(r,r[1:]+r[:1])))/2
        self.assertAlmostEqual(sum(area(r) for r in parts),8800-400-800)
        self.assertFalse(any(contains_point(r,(20,20)) for r in parts))
        self.assertFalse(any(contains_point(r,(80,70)) for r in parts))
        self.assertTrue(any(contains_point(r,(50,50)) for r in parts))

    def test_courtyard_outside_the_exterior_is_rejected(self):
        from building_footprints import subtract_courtyards
        with self.assertRaises(ValueError):
            subtract_courtyards([[(0,0),(10,0),(10,10),(0,10)]],
                               [[(9,9),(12,9),(12,12),(9,12)]])
