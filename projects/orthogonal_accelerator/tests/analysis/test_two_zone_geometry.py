"""Regression tests for solver-neutral two-zone accelerator geometry."""
from __future__ import annotations

import unittest

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    TwoZoneGeometryError,
    derive_shielded_rectangular_enclosure,
    derive_uniform_ring_planes,
)
from projects.orthogonal_accelerator.simion.two_zone_candidate import (
    compile_closed_two_zone_accelerator,
)


class TwoZoneGeometryTest(unittest.TestCase):
    @staticmethod
    def requirements() -> dict[str, object]:
        return {
            "schema_version": 1,
            "role": "orthogonal_accelerator_two_zone_requirements",
            "variant_id": "two_zone",
            "acceleration_direction": "-z",
            "source_cylinder": {"radius_mm": 1.0, "height_mm": 1.0},
            "focus": {"mode": "two_zone_time_focus", "focus_plane": "consumer_plane"},
            "compaction": {"axes": ["y", "z"], "objective": "minimize_subject_to_focus"},
            "local_pa": {"span_mm": [64.0, 64.0, 84.0], "mesh_mm_per_gu": [0.25, 0.25, 0.1],
                         "exit_z_mm": 6.0, "margin_z_mm": 6.0},
            "placement": {"focus_y_mm": 20.0, "global_repeller_z_mm": 34.0,
                          "global_exit_z_mm": 0.0},
        }

    def test_provider_compiles_only_closed_end_topology_from_cylindrical_request(self) -> None:
        result = compile_closed_two_zone_accelerator(self.requirements())
        self.assertEqual((result.source_cylinder_radius_mm, result.source_cylinder_height_mm), (1.0, 1.0))
        self.assertEqual(result.source_center_z_mm, 32.0)
        self.assertEqual(result.static_minimum_y_extent_mm, 34.0)
        self.assertEqual(result.static_axial_length_mm, 38.0)
        layout = result.layout.to_dict()
        self.assertEqual(layout["geometry_profile_id"], "closed_two_zone_compact_mr_axial_r3_gap1_4mm")
        self.assertEqual(layout["acceleration_direction"], "-z")
        self.assertEqual(layout["source_cylinder"], {"radius_mm": 1.0, "height_mm": 1.0})
        self.assertEqual(layout["source_z_minimum_mm"], 37.0)
        self.assertEqual(layout["source_z_maximum_mm"], 39.0)
        self.assertEqual(layout["aperture_height_y_mm"], 26.0)
        self.assertEqual(layout["static_minimum_y_extent_mm"], 34.0)
        self.assertEqual(layout["static_axial_length_mm"], 38.0)
        self.assertEqual(layout["ring_count"], 15)
        expected_centers = tuple(36.0 - 30.0 * index / 16.0 for index in range(1, 16))
        for actual, expected in zip(layout["ring_centers_z_mm"], expected_centers):
            self.assertAlmostEqual(actual, expected)
        self.assertIn("Closed positive-z grounded cap", result.gem)
        self.assertIn("Solid repeller; no coaxial return aperture", result.gem)
        self.assertIn("e(3)", result.gem)
        self.assertIn("e(4)", result.gem)

    def test_resolved_electrodes_match_closed_gem_and_local_frame(self) -> None:
        compiled = compile_closed_two_zone_accelerator(self.requirements())
        geometry = compiled.resolved_electrodes.to_dict()
        self.assertEqual(geometry["coordinate_frame"], "accelerator_centered_transverse_local_z_mm")
        self.assertEqual(geometry["local_to_pa_translation_mm"], [0.0, 32.0, 0.0])
        grounded = geometry["grounded_enclosure"]
        self.assertEqual(grounded["component_electrode_id"], 15)
        self.assertEqual(grounded["local_pa_electrode_id"], 1)
        self.assertEqual(grounded["outer_box_mm"], {
            "x_min_mm": -22.0, "x_max_mm": 22.0, "y_min_mm": -17.0,
            "y_max_mm": 17.0, "z_min_mm": 6.0, "z_max_mm": 44.0,
        })
        self.assertEqual(grounded["cavity_box_mm"]["z_max_mm"], 43.0)
        self.assertEqual(grounded["exit_opening_box_mm"]["x_max_mm"], 12.5)
        self.assertEqual(geometry["repeller"]["solid_box_mm"]["z_min_mm"], 40.0)
        self.assertEqual(geometry["repeller"]["solid_box_mm"]["z_max_mm"], 42.0)
        supports = geometry["grid_supports"]
        self.assertEqual([(item["component_electrode_id"], item["local_pa_electrode_id"])
                          for item in supports], [(23, 3), (24, 4)])
        self.assertEqual([item["ideal_sheet_mm"]["z_mm"] for item in supports], [36.0, 6.0])
        self.assertTrue(all(item["transmission"] == "ideal_transparent" for item in supports))
        self.assertIn("e(3) { box3D(-12.5,-13,36,12.5,13,36) }", compiled.gem)
        self.assertIn("e(4) { box3D(-12.5,-13,6,12.5,13,6) }", compiled.gem)
        rings = geometry["rings"]
        self.assertEqual(len(rings), 15)
        self.assertEqual([(item["component_electrode_id"], item["local_pa_electrode_id"])
                          for item in rings], [(26 + i, 5 + i) for i in range(15)])
        self.assertEqual(rings[0]["outer_box_mm"]["z_min_mm"], 33.625)
        self.assertEqual(rings[-1]["outer_box_mm"]["z_max_mm"], 8.375)
        for ring in rings:
            self.assertEqual(ring["aperture_box_mm"]["x_max_mm"], 12.5)
            self.assertEqual(ring["aperture_box_mm"]["y_max_mm"], 13.0)
            self.assertIn(f"e({ring['local_pa_electrode_id']})", compiled.gem)

    def test_provider_rejects_consumer_topology_override_and_geometry_override(self) -> None:
        request = self.requirements()
        request["end_topology"] = "grid"
        with self.assertRaisesRegex(TwoZoneGeometryError, "unknown"):
            compile_closed_two_zone_accelerator(request)
        request = self.requirements()
        request["two_zone"] = {"gap_1_mm": 2.0}
        with self.assertRaisesRegex(TwoZoneGeometryError, "unknown"):
            compile_closed_two_zone_accelerator(request)

    def test_provider_rejects_source_that_does_not_fit_first_gap_or_rigid_placement(self) -> None:
        request = self.requirements()
        request["source_cylinder"] = {"radius_mm": 3.0, "height_mm": 1.0}
        with self.assertRaisesRegex(TwoZoneGeometryError, "first gap"):
            compile_closed_two_zone_accelerator(request)
        request = self.requirements()
        request["placement"]["global_repeller_z_mm"] = 34.1  # type: ignore[index]
        with self.assertRaisesRegex(TwoZoneGeometryError, "repeller-to-exit"):
            compile_closed_two_zone_accelerator(request)

    def test_descending_second_region_has_uniform_interior_ring_planes(self) -> None:
        layout = derive_uniform_ring_planes(33.0, 0.0, 5, ring_thickness_mm=1.0)
        self.assertAlmostEqual(layout.pitch_mm, 5.5)
        self.assertEqual(len(layout.centers_mm), 5)
        for actual, expected in zip(layout.centers_mm, (27.5, 22.0, 16.5, 11.0, 5.5)):
            self.assertAlmostEqual(actual, expected)

    def test_overlapping_ring_thickness_is_rejected(self) -> None:
        with self.assertRaises(TwoZoneGeometryError):
            derive_uniform_ring_planes(0.0, 5.0, 1, ring_thickness_mm=2.5)

    def test_shell_derivation_requires_declared_lateral_clearance(self) -> None:
        enclosure = derive_shielded_rectangular_enclosure(
            electrode_outer_width_x_mm=40.0, electrode_outer_height_y_mm=40.0,
            guard_outer_width_x_mm=48.0, guard_outer_height_y_mm=48.0,
            guard_wall_thickness_mm=2.0, lateral_clearance_mm=2.0,
            repeller_z_mm=45.6, repeller_thickness_z_mm=2.0, rear_gap_mm=5.0,
        )
        self.assertAlmostEqual(enclosure.rear_cap_inner_z_mm, 52.6)


if __name__ == "__main__":
    unittest.main()
