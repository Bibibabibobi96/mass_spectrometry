"""Pure tests of the authored symmetric mirror convergence candidate."""
from __future__ import annotations

import copy
import math
from pathlib import Path
import unittest

from projects.parallel_mirror_dual_stripe_mr_tof.analysis.resolved_geometry import (
    _converging_mirror_solid, resolve_geometry,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_candidate_reference import (
    CandidateContractError, load_contract,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.analyzer_candidate_geometry import (
    _mirror_lines, _mirror_ground_shield_lines,
)
from projects.parallel_mirror_dual_stripe_mr_tof.analysis.simion_event_analysis import collision_diagnostics


PROJECT = Path(__file__).resolve().parents[2]


class MirrorConvergenceGeometryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_contract(PROJECT / "config/simion_candidate_two_zone.json")
        cls.parallel = resolve_geometry(cls.contract)
        cls.authored = copy.deepcopy(cls.contract)
        cls.authored["mirror"]["convergence_transform"] = {"angle_deg": 0.025688743, "pivot_y_mm": 0.0}
        cls.tilted = resolve_geometry(cls.authored)

    def test_zero_angle_preserves_complete_parallel_geometry_and_gem(self):
        contract = copy.deepcopy(self.contract)
        contract["mirror"]["convergence_transform"] = {"angle_deg": 0.0, "pivot_y_mm": 0.0}
        resolved = resolve_geometry(contract)
        self.assertEqual(resolved, self.parallel)
        self.assertEqual(_mirror_lines(resolved), _mirror_lines(self.parallel))
        self.assertEqual(_mirror_ground_shield_lines(resolved), _mirror_ground_shield_lines(self.parallel))

    def test_all_solids_and_holes_are_exact_z_reflections_and_keep_ids(self):
        for key in ("mirror_electrodes", "mirror_ground_shields", "mirror_e_closures"):
            group = self.tilted[key]
            for right, left in zip(group[::2], group[1::2], strict=True):
                self.assertEqual(left["polygon_yz_mm"], [[y, -z] for y, z in right["polygon_yz_mm"]])
                self.assertEqual(left["x"], right["x"])
                for hright, hleft in zip(right["holes"], left["holes"], strict=True):
                    self.assertEqual(hleft["polygon_yz_mm"], [[y, -z] for y, z in hright["polygon_yz_mm"]])
                    self.assertEqual(hleft["x"], hright["x"])
        self.assertEqual([i["id"] for i in self.tilted["mirror_e_closures"]], [5, 10])
        self.assertEqual(self.tilted["mirror_electrodes"][0]["holes"][0]["x"], [-15.0, 15.0])
        self.assertEqual(self.tilted["mirror_ground_shields"][0]["holes"][0]["x"], [-2.0, 2.0])
        p, q = self.tilted["mirror_electrodes"][0]["polygon_yz_mm"][:2]
        self.assertAlmostEqual(math.dist(p, q), self.contract["mirror"]["length_y_mm"], places=10)

    def test_gem_uses_real_polygons_and_preserves_e_cover_voltage_ids(self):
        gem = "\n".join(_mirror_lines(self.tilted) + _mirror_ground_shield_lines(self.tilted))
        self.assertIn("extrude_yz", gem)
        self.assertNotIn("box3D", gem)
        self.assertIn("e(5)", gem)
        self.assertIn("e(10)", gem)
        self.assertIn("notin_inside { extrude_yz(-15,15)", gem)

    def test_clearance_and_low_field_face_are_real_plane_not_aabb(self):
        self.assertGreater(self.tilted["metadata"]["resolved_minimum_stripe_to_inner_shield_clearance_mm"], 0.0)
        self.assertLess(self.tilted["metadata"]["resolved_minimum_stripe_to_inner_shield_clearance_mm"], 5.0)
        self.assertEqual(self.authored["mirror"]["inner_clearance_to_stripe_mm"], 5.0)
        self.assertFalse(self.tilted["metadata"]["mirror_stripe_clearance_pass"])
        face = self.tilted["two_prism_low_field_reference_section"]["derivation"]["mirror_inner_face"]
        y = self.tilted["two_prism_low_field_reference_section"]["transit_aperture_project_mm"]["y_mm"]
        expected = min(face["z_at_pivot_mm"] + face["dz_dy"] * (v-face["pivot_y_mm"]) for v in y)
        actual = self.tilted["two_prism_low_field_reference_section"]["derivation"]["upper_boundary_candidates_mm"]
        self.assertEqual(actual["positive_grounded_mirror_inner_face_z_mm"], expected)
        self.assertEqual(self.parallel["prism_electrodes"], self.tilted["prism_electrodes"])
        self.assertEqual(self.parallel["prism_ground_shields"], self.tilted["prism_ground_shields"])

    def test_overlap_and_invalid_transform_are_rejected(self):
        for transform in ({}, {"angle_deg": -1.0, "pivot_y_mm": 0.0},
                          {"angle_deg": True, "pivot_y_mm": 0.0},
                          {"angle_deg": float("nan"), "pivot_y_mm": 0.0},
                          {"angle_deg": 10.0, "pivot_y_mm": 0.0}):
            contract = copy.deepcopy(self.contract)
            contract["mirror"]["convergence_transform"] = transform
            with self.subTest(transform=transform), self.assertRaises(CandidateContractError):
                resolve_geometry(contract)

    def test_collision_uses_tilted_occupancy_and_x_bounded_hole(self):
        angle = math.radians(20)
        solid = _converging_mirror_solid([-3, 0, 10, 3, 10, 12], angle, 0, 10)
        solid["id"] = 1
        solid["holes"] = [_converging_mirror_solid([-1, 1, 9, 1, 9, 13], angle, 0, 10)]
        geometry = {"mesh_mm_per_gu": 0.01, "mirror_electrodes": [solid]}
        def world(y, z):
            return math.cos(angle)*y+math.sin(angle)*(z-10), 10-math.sin(angle)*y+math.cos(angle)*(z-10)
        y, z = world(5, 11)
        outside = (solid["box"][1]+0.1, solid["box"][5]-0.1)
        events = [{"kind": "terminal", "ion": n, "splat": -1, "t_us": 1.0,
                   "x_mm": x, "y_mm": yz[0], "z_mm": yz[1]}
                  for n, (x, yz) in enumerate(((2.0, (y,z)), (0.0, (y,z)), (2.0, outside)), start=1)]
        result = collision_diagnostics(events, geometry)
        self.assertEqual([i["component"] for i in result["collision_particles"]],
                         ["mirror_electrodes", "unclassified", "unclassified"])


if __name__ == "__main__":
    unittest.main()
