"""Regression tests for solver-neutral two-zone accelerator geometry."""
from __future__ import annotations

import hashlib
import json
import re
import unittest

from projects.orthogonal_accelerator.analysis.two_zone_geometry import (
    TwoZoneGeometryError,
    derive_shielded_rectangular_enclosure,
    derive_uniform_ring_planes,
)
from projects.orthogonal_accelerator.simion.two_zone_candidate import (
    compile_closed_two_zone_accelerator,
    render_closed_two_zone_electrode_body,
)


class TwoZoneGeometryTest(unittest.TestCase):
    def test_body_is_exact_full_gem_electrode_block_without_storage_placement(self) -> None:
        for version in (1, 2):
            request = self.requirements()
            if version == 2:
                request.update(schema_version=2, side_entry=dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.4))
            compiled = compile_closed_two_zone_accelerator(request)
            body = render_closed_two_zone_electrode_body(compiled.resolved_electrodes)
            full = compiled.gem.splitlines()
            start = full.index("locate(0,$(y_span/2),0) {")+1
            self.assertEqual(body, full[start:-1])
            text = "\n".join(body)
            self.assertNotIn("pa_define", text)
            self.assertNotIn("locate(", text)
            self.assertNotIn("y_span", text)
            self.assertIn("box3D(-20,-15,40,20,15,42)", text)

    def test_body_namespace_changes_only_ids_and_never_mutates_canonical_geometry(self) -> None:
        request = self.requirements()
        request.update(schema_version=2, side_entry=dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.4))
        compiled = compile_closed_two_zone_accelerator(request)
        resolved = compiled.resolved_electrodes
        before = json.dumps(resolved.to_dict(), sort_keys=True)
        original = "\n".join(render_closed_two_zone_electrode_body(resolved))
        mapping = {key: value+100 for key, value in resolved.local_electrode_ids.items()}
        renamed = "\n".join(render_closed_two_zone_electrode_body(resolved, local_electrode_ids=mapping))
        expected = re.sub(r"\be\((\d+)\)", lambda m: f"e({int(m[1])+100})", original)
        self.assertEqual(renamed, expected)
        self.assertIn("e(101)", renamed)
        self.assertIn("notin_inside { box3D(-1.5,-17.25,36.6,1.5,-15.75,39.4) }", renamed)
        self.assertEqual(before, json.dumps(resolved.to_dict(), sort_keys=True))

    def test_body_namespace_rejects_missing_extra_alias_and_invalid_ids(self) -> None:
        resolved = compile_closed_two_zone_accelerator(self.requirements()).resolved_electrodes
        original = dict(resolved.local_electrode_ids)
        bad = []
        value = dict(original); value.pop(15); bad.append(value)
        value = dict(original); value[99] = 999; bad.append(value)
        value = dict(original); value[15] = value[22]; bad.append(value)
        for identifier in (0, -1, True, "1", 1.5):
            value = dict(original); value[15] = identifier; bad.append(value)
        value = dict(original); value["15"] = value.pop(15); bad.append(value)
        for mapping in bad:
            with self.subTest(mapping=mapping), self.assertRaises(TwoZoneGeometryError):
                render_closed_two_zone_electrode_body(resolved, local_electrode_ids=mapping)

    def test_closed_schema1_frozen_gem_and_projection_bytes_unchanged(self) -> None:
        compiled = compile_closed_two_zone_accelerator(self.requirements())
        self.assertEqual(hashlib.sha256(compiled.gem.encode()).hexdigest(),
                         "1105dfb1e01fbb3995832f879e65f5981572fa7eae5efac16deb37441cb87939")
        for value, expected in [
            (compiled.layout.to_dict(), "8f39793ef46f99f97e95b8d7f039826da5c4afd24c57f5366dfeec39c5961e4d"),
            (compiled.resolved_electrodes.to_dict(), "7b78faa7c2993a598f2c8f74492dfc852661627c22748204e85f906fbc4ad8ea"),
        ]:
            self.assertEqual(hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest(), expected)

    def test_explicit_negative_y_side_entry_has_provider_center_and_distinct_identity(self) -> None:
        request = self.requirements()
        closed = compile_closed_two_zone_accelerator(request)
        request.update(schema_version=2, side_entry=dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.4))
        compiled = compile_closed_two_zone_accelerator(request)
        port = compiled.layout.to_dict()["side_entry"]
        self.assertEqual(port["center_mm"], [0.0, -16.5, 38.0])
        self.assertEqual(port["physical_cutout_box_mm"], [-1.5, -17, 36.6, 1.5, -16, 39.4])
        self.assertEqual(port["boolean_cut_padding_y_mm"], .25)
        self.assertEqual(port["boolean_transverse_expansion_mm"], 0)
        self.assertEqual(compiled.resolved_electrodes.to_dict()["schema_version"], 2)
        self.assertEqual(compiled.resolved_electrodes.to_dict()["grounded_enclosure"]["side_entry"], port)
        self.assertIn("notin_inside { box3D(-1.5,-17.25,36.6,1.5,-15.75,39.4) }", compiled.gem)
        self.assertNotEqual(hashlib.sha256(compiled.gem.encode()).hexdigest(), hashlib.sha256(closed.gem.encode()).hexdigest())
        before, after = closed.resolved_electrodes.to_dict(), compiled.resolved_electrodes.to_dict()
        for name in ("repeller", "grid_supports", "rings", "local_to_pa_translation_mm"):
            self.assertEqual(before[name], after[name])
        self.assertEqual(compiled.gem.count("e("), closed.gem.count("e("))
        self.assertEqual(compiled.static_axial_length_mm, closed.static_axial_length_mm)

    def test_side_port_z_overlap_with_support_slab_is_not_solid_intersection(self) -> None:
        request = self.requirements()
        request.update(schema_version=2, side_entry=dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.8))
        compiled = compile_closed_two_zone_accelerator(request)
        data = compiled.resolved_electrodes.to_dict()
        cut = data["grounded_enclosure"]["side_entry"]["physical_cutout_box_mm"]
        support = data["grid_supports"][0]["frame_outer_box_mm"]
        self.assertLess(cut[2], support["z_max_mm"])
        self.assertLess(cut[4], support["y_min_mm"])

    def test_side_entry_requires_version2_exact_fields_and_strict_first_gap(self) -> None:
        for change in (
            dict(schema_version=2),
            dict(side_entry=dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.4)),
            *[dict(schema_version=2, side_entry=port) for port in (
                dict(face="negative_x", half_width_x_mm=1.5, half_width_z_mm=1.4),
                dict(face="negative_y", half_width_x_mm=22, half_width_z_mm=1.4),
                dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=2),
                dict(face="negative_y", half_width_x_mm=True, half_width_z_mm=1.4),
                dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=float("nan")),
                dict(face="negative_y", half_width_x_mm=1.5, half_width_z_mm=1.4, center_z_mm=38),
            )],
        ):
            request = self.requirements()
            request.update(change)
            with self.subTest(change=change), self.assertRaises(TwoZoneGeometryError):
                compile_closed_two_zone_accelerator(request)

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
