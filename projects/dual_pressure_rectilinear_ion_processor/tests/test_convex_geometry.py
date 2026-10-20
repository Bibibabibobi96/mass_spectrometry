"""Analytic finite-volume wedges and exact tangent section regressions."""
from __future__ import annotations

import copy
import unittest

import numpy as np

from projects.dual_pressure_rectilinear_ion_processor.analysis.convex_geometry import (
    contains_shape,
    convex_planes,
    convex_section,
    shape_bounds,
)


def _wedge() -> dict:
    # 0 <= x <= 4, |y| <= 1, 0 <= z <= x/2.
    return {"shape": "convex_polyhedron", "vertices_mm":
            [[x, y, z] for y in (-1., 1.) for x, z in ((0., 0.), (4., 0.), (4., 2.))]}


class ConvexGeometryTests(unittest.TestCase):
    def test_analytic_wedge_halfspaces_are_unique_normalized_and_outward(self) -> None:
        shape = _wedge()
        planes = np.array(convex_planes(shape))
        self.assertEqual(planes.shape, (5, 4))
        np.testing.assert_allclose(np.linalg.norm(planes[:, :3], axis=1), 1., atol=8 * np.finfo(float).eps, rtol=0.)
        vertices = np.array(shape["vertices_mm"])
        self.assertLessEqual(float(np.max(vertices @ planes[:, :3].T + planes[:, 3])), 64 * np.finfo(float).eps * 4)
        self.assertTrue(contains_shape(shape, [1., 0., .25]))
        self.assertTrue(contains_shape(shape, [1., 1., .5]))
        self.assertFalse(contains_shape(shape, [1., 0., .500001]))
        self.assertFalse(contains_shape(shape, [4.1, 0., 1.]))
        self.assertEqual(shape_bounds(shape), ([0., -1., 0.], [4., 1., 2.]))

    def test_oblique_wedge_section_matches_rectangle_and_counterclockwise_order(self) -> None:
        polygon = np.array(convex_section(_wedge(), 2, 1.))
        self.assertEqual(len(polygon), 4)
        self.assertEqual({tuple(point) for point in polygon}, {(2., -1., 1.), (4., -1., 1.), (4., 1., 1.), (2., 1., 1.)})
        projected = polygon[:, :2]
        signed_area = .5 * np.sum(projected[:, 0] * np.roll(projected[:, 1], -1) - projected[:, 1] * np.roll(projected[:, 0], -1))
        self.assertAlmostEqual(signed_area, 4.)
        self.assertEqual(convex_section(_wedge(), 2, 2.001), [])

    def test_face_edge_point_and_thin_sections_preserve_dimension(self) -> None:
        self.assertEqual(len(convex_section(_wedge(), 1, 1.)), 3)
        edge = convex_section(_wedge(), 0, 0.)
        self.assertEqual({tuple(point) for point in edge}, {(0., -1., 0.), (0., 1., 0.)})
        thin = convex_section(_wedge(), 0, 1e-9)
        self.assertEqual(len(thin), 4)
        self.assertEqual(max(point[2] for point in thin), 5e-10)
        tetrahedron = {"shape": "convex_polyhedron", "vertices_mm": [[0., 0., 0.], [1., 0., 0.], [0., 1., 0.], [0., 0., 1.]]}
        self.assertEqual(convex_section(tetrahedron, 0, 1.), [[1., 0., 0.]])

    def test_box_and_cylinder_bounds_and_boundary_containment(self) -> None:
        box = {"shape": "box", "min_mm": [-1., -2., -3.], "max_mm": [1., 2., 3.]}
        self.assertEqual(shape_bounds(box), ([-1., -2., -3.], [1., 2., 3.]))
        self.assertTrue(contains_shape(box, [1., -2., 0.]))
        self.assertFalse(contains_shape(box, [1.01, 0., 0.]))
        cylinder = {"shape": "cylinder_x", "x_min_mm": 0., "x_max_mm": 10., "center_y_mm": 2., "center_z_mm": -3., "radius_mm": 2.}
        self.assertEqual(shape_bounds(cylinder), ([0., 0., -5.], [10., 4., -1.]))
        self.assertTrue(contains_shape(cylinder, [10., 4., -3.]))
        self.assertFalse(contains_shape(cylinder, [5., 4., -1.]))

    def test_invalid_vertices_and_duplicate_geometry_authorities_fail_closed(self) -> None:
        invalid = []
        for value in (float("nan"), float("inf"), True, "1"):
            shape = _wedge()
            shape["vertices_mm"][0][0] = value
            invalid.append(shape)
        invalid.extend([
            {"shape": "convex_polyhedron", "vertices_mm": [[0, 0, 0]] * 4},
            {"shape": "convex_polyhedron", "vertices_mm": [[0, 0, 0], [1, 0, 0], [0, 1, 0], [1, 1, 0]]},
            {"shape": "convex_polyhedron", "vertices_mm": [[0, 0, 0]]},
            dict(_wedge(), planes=[[1., 0., 0., -4.]]),
            {"shape": "box", "min_mm": [1., 0., 0.], "max_mm": [0., 1., 1.]},
            {"shape": "cylinder_x", "x_min_mm": 0., "x_max_mm": 1., "center_y_mm": 0., "center_z_mm": 0., "radius_mm": -1.},
        ])
        for shape in invalid:
            with self.subTest(shape=shape), self.assertRaises(ValueError):
                shape_bounds(shape)
        for axis in (True, -1, 3, 1.5):
            with self.subTest(axis=axis), self.assertRaises(ValueError):
                convex_section(_wedge(), axis, 0.)
        with self.assertRaises(ValueError):
            contains_shape(_wedge(), [0., 0., float("nan")])

    def test_geometry_inputs_are_not_mutated(self) -> None:
        shape = _wedge()
        original = copy.deepcopy(shape)
        shape_bounds(shape)
        convex_planes(shape)
        convex_section(shape, 0, 2.)
        contains_shape(shape, [1., 0., .25])
        self.assertEqual(shape, original)


if __name__ == "__main__":
    unittest.main()
