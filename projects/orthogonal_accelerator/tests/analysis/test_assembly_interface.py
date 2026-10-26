"""Independent mechanical vectors for the OA assembly provider boundary."""
from __future__ import annotations

import copy
import unittest
from pathlib import Path
from unittest.mock import patch

from common.contracts.machine_contracts import validate_schema
from common.contracts.rigid_transform import FramedPosition, FramedVector, RigidTransform
from projects.orthogonal_accelerator.analysis.assembly_interface import (
    resolve_assembly_interface,
)
from projects.orthogonal_accelerator.analysis.component_focus_pa_plan import derive
from projects.orthogonal_accelerator.simion.two_zone_candidate import compile_closed_two_zone_accelerator
from projects.orthogonal_accelerator.simion.bare_three_zone_component import (
    resolve_bare_three_zone_component, render_bare_three_zone_electrode_body,
)
from projects.orthogonal_accelerator.tests.analysis import test_two_zone_geometry as two_zone
from projects.orthogonal_accelerator.tests.analysis.test_bare_three_zone_component import three_zone_requirements_fixture


TWO_ZONE_PROFILE = "closed_two_zone_compact_mr_axial_r3_gap1_4mm"


def two_zone_requirements() -> dict:
    request = two_zone.TwoZoneGeometryTest.requirements()
    request.update(schema_version=2, side_entry={
        "face": "negative_y", "half_width_x_mm": 1.5, "half_width_z_mm": 1.4,
    })
    return request


class AssemblyInterfaceTests(unittest.TestCase):
    def test_two_zone_outer_face_and_component_ids(self) -> None:
        with patch(
            "projects.orthogonal_accelerator.analysis.assembly_interface.compile_closed_two_zone_accelerator",
            wraps=compile_closed_two_zone_accelerator,
        ) as compiler:
            result = resolve_assembly_interface(two_zone_requirements(), geometry_profile_id=TWO_ZONE_PROFILE)
        self.assertEqual(compiler.call_count, 1)
        self.assertEqual(set(result["ports"]), {"side_entry", "axial_exit"})
        validate_schema(result, "component_geometry_interface.schema.json")
        self.assertEqual(result["local_frame_id"], "accelerator_centered_transverse_local_z_mm")
        port = result["ports"]["side_entry"]
        self.assertEqual(port, {
            "surface_kind": "aperture_outer_face", "center_mm": [0, -17, 38],
            "outward_normal": [0, -1, 0], "wall_thickness_mm": 1,
            "cross_section": {"shape": "rectangle", "width_mm": 3, "height_mm": 2.8,
                              "width_axis": [1, 0, 0], "height_axis": [0, 0, 1]},
        })
        electrodes = result["component_electrodes"]
        self.assertEqual([(e["component_electrode_id"], e["role"]) for e in electrodes[:4]],
                         [(15, "grounded_shield"), (22, "repeller"), (23, "grid1"), (24, "exit_grid")])
        self.assertEqual([e["component_electrode_id"] for e in electrodes[4:]], list(range(26, 41)))

    def test_closed_two_zone_actual_provider_publishes_its_real_axial_exit(self) -> None:
        project_root = Path(__file__).resolve().parents[2]
        plan = derive(project_root / "config" / "two_zone_component_focus_campaign.json")
        compiled = compile_closed_two_zone_accelerator(
            plan["requirements"], geometry_profile_id=plan["geometry_profile_id"],
        )
        result = resolve_assembly_interface(
            plan["requirements"], geometry_profile_id=plan["geometry_profile_id"],
        )
        validate_schema(result, "component_geometry_interface.schema.json")
        self.assertEqual(set(result["ports"]), {"axial_exit"})
        opening = compiled.resolved_electrodes.to_dict()["grounded_enclosure"]["exit_opening_box_mm"]
        self.assertEqual(result["local_frame_id"], "accelerator_centered_transverse_local_z_mm")
        self.assertEqual(result["ports"]["axial_exit"], {
            "surface_kind": "aperture_outer_face", "center_mm": [0.0, 0.0, opening["z_min_mm"]],
            "outward_normal": [0, 0, -1], "wall_thickness_mm": opening["z_max_mm"] - opening["z_min_mm"],
            "cross_section": {"shape": "rectangle", "width_mm": opening["x_max_mm"] - opening["x_min_mm"],
                              "height_mm": opening["y_max_mm"] - opening["y_min_mm"],
                              "width_axis": [1, 0, 0], "height_axis": [0, 1, 0]},
        })
        self.assertEqual(result["ports"]["axial_exit"]["center_mm"][2], compiled.local_exit_z_mm)
        self.assertEqual([(item["component_electrode_id"], item["role"])
                          for item in result["component_electrodes"][:4]],
                         [(15, "grounded_shield"), (22, "repeller"), (23, "grid1"), (24, "exit_grid")])

    def test_three_zone_outer_face_and_component_ids(self) -> None:
        with patch(
            "projects.orthogonal_accelerator.analysis.assembly_interface.resolve_bare_three_zone_component",
            wraps=resolve_bare_three_zone_component,
        ) as compiler:
            result = resolve_assembly_interface(three_zone_requirements_fixture(), geometry_profile_id=None)
        self.assertEqual(compiler.call_count, 1)
        self.assertEqual(set(result["ports"]), {"side_entry"})
        self.assertIsNone(result["geometry_profile_id"])
        self.assertEqual(result["local_frame_id"], "sectioned_accelerator_cartesian")
        self.assertEqual(result["ports"]["side_entry"], {
            "surface_kind": "aperture_outer_face", "center_mm": [-17, 0, 2],
            "outward_normal": [-1, 0, 0], "wall_thickness_mm": 1,
            "cross_section": {"shape": "rectangle", "width_mm": 3, "height_mm": 2.8,
                              "width_axis": [0, 1, 0], "height_axis": [0, 0, 1]},
        })
        self.assertEqual(result["component_electrodes"], [
            {"component_electrode_id": i, "role": role}
            for i, role in enumerate(
                ["grounded_shield", "repeller", "grid1", "intermediate2", "exit_grid", *["ring"] * 4], 1
            )
        ])

    def test_three_zone_offset_axis_moves_the_actual_wall(self) -> None:
        request = three_zone_requirements_fixture()
        request["geometry"].update(axis_x_mm=3, axis_y_mm=2, negative_x_face_mm=-14, port_center_y_mm=2)
        result = resolve_assembly_interface(request, geometry_profile_id=None)
        self.assertEqual(result["ports"]["side_entry"]["center_mm"], [-14, 2, 2])

    def test_two_variants_place_the_same_outer_face_without_half_wall_error(self) -> None:
        cases = (
            (two_zone_requirements(), TWO_ZONE_PROFILE, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, -50, -6]),
            (three_zone_requirements_fixture(), None, [[0, 1, 0], [1, 0, 0], [0, 0, -1]], [0, -50, 34]),
        )
        for request, profile, rotation, translation in cases:
            with self.subTest(variant=request["variant_id"]):
                result = resolve_assembly_interface(request, geometry_profile_id=profile)
                frame = result["local_frame_id"]
                transform = RigidTransform(frame, "mrtof_global_cartesian", rotation, translation)
                port = result["ports"]["side_entry"]
                self.assertEqual(transform.transform_position(FramedPosition(frame, port["center_mm"])).coordinates_mm,
                                 (0, -67, 32))
                self.assertEqual(transform.transform_vector(FramedVector(frame, port["outward_normal"])).components,
                                 (0, -1, 0))

    def test_provider_inputs_and_existing_geometry_remain_unchanged(self) -> None:
        two = two_zone_requirements()
        three = three_zone_requirements_fixture()
        original = copy.deepcopy((two, three))
        before_two = compile_closed_two_zone_accelerator(two)
        before_three = resolve_bare_three_zone_component(three)
        ids = {i: i + 40 for i in range(1, 10)}
        cells = dict(x=.2, y=.1, z=.1)
        before_body = render_bare_three_zone_electrode_body(before_three, cell_mm_xyz=cells, local_electrode_ids=ids)
        resolve_assembly_interface(two, geometry_profile_id=TWO_ZONE_PROFILE)
        resolve_assembly_interface(three, geometry_profile_id=None)
        after_two = compile_closed_two_zone_accelerator(two)
        after_three = resolve_bare_three_zone_component(three)
        self.assertEqual((two, three), original)
        self.assertEqual(after_two.gem, before_two.gem)
        self.assertEqual(after_two.resolved_electrodes.to_dict(), before_two.resolved_electrodes.to_dict())
        self.assertEqual(after_three, before_three)
        self.assertEqual(render_bare_three_zone_electrode_body(after_three, cell_mm_xyz=cells, local_electrode_ids=ids), before_body)

    def test_invalid_identity_fails_closed(self) -> None:
        for profile in (None, "", " padded ", 12):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                resolve_assembly_interface(two_zone_requirements(), geometry_profile_id=profile)
        with self.assertRaisesRegex(ValueError, "two_zone or three_zone"):
            resolve_assembly_interface({"variant_id": "four_zone"}, geometry_profile_id=None)


if __name__ == "__main__":
    unittest.main()
