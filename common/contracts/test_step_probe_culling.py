import math
import unittest
from types import SimpleNamespace

from msplatform.exporters.step import _probe_inside, _probe_solid_bounds


class FakeSolid:
    def __init__(self, bounds, *, reported=None):
        self.bounds = bounds
        self.reported = bounds if reported is None else reported
        self.probes = []
        self.box_calls = 0

    def BoundingBox(self):
        self.box_calls += 1
        return SimpleNamespace(**dict(zip(("xmin", "xmax", "ymin", "ymax", "zmin", "zmax"), self.reported)))

    def isInside(self, point, tolerance):
        self.probes.append(point)
        # Distance to the closed box: independent of the per-axis culling predicate.
        distance = math.sqrt(sum(max(lo - value, 0, value - hi) ** 2
                                 for value, lo, hi in zip(point, self.bounds[::2], self.bounds[1::2])))
        return distance <= tolerance


class StepProbeCullingTests(unittest.TestCase):
    def test_matches_original_oracle_and_preserves_short_circuit(self):
        tolerance = 0.125
        bounds = [(-5., -3., 2., 4., -2., 0.), (10., 12., -2., 0., 4., 6.),
                  (-5., -3., 2., 4., -2., 0.)]
        originals = [FakeSolid(b) for b in bounds]
        candidates = [FakeSolid(b) for b in bounds]
        cached = _probe_solid_bounds(candidates)
        points = [(-4., 3., -1.), (-5.125, 3., -1.), (-5.125001, 3., -1.),
                  (-4., 4.125, -1.), (-4., 4.125001, -1.), (11., -1., 5.),
                  (100., 100., 100.), (-5.125, 4.125, -1.)]
        for point in points:
            expected = any(s.isInside(point, tolerance) for s in originals)
            self.assertEqual(_probe_inside(cached, point, tolerance), expected, point)
        self.assertEqual([s.box_calls for s in candidates], [1, 1, 1])
        self.assertLess(sum(len(s.probes) for s in candidates), sum(len(s.probes) for s in originals))
        self.assertNotIn(points[0], candidates[2].probes)
        self.assertIn(points[1], candidates[0].probes)
        self.assertNotIn(points[2], candidates[0].probes)

    def test_unusable_bounds_do_not_suppress_original_query(self):
        b = (0., 1., 0., 1., 0., 1.)
        for reported in [(float("nan"), 1., 0., 1., 0., 1.), (1., 0., 0., 1., 0., 1.)]:
            solid = FakeSolid(b, reported=reported)
            self.assertFalse(_probe_inside(_probe_solid_bounds([solid]), (9., 9., 9.), .1))
            self.assertEqual(solid.probes, [(9., 9., 9.)])
