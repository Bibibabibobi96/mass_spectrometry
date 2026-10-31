"""Independent mechanical vectors for the OA assembly provider boundary."""
from __future__ import annotations

from projects.orthogonal_accelerator.analysis.sectioned_geometry import resolve_bare_three_zone_component

import copy
import json
import subprocess
import sys
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
    render_bare_three_zone_electrode_body,
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
        with patch("projects.orthogonal_accelerator.simion.two_zone_candidate.render_closed_two_zone_local_pa",
                   side_effect=AssertionError("interface query must not render GEM")):
            result = resolve_assembly_interface(two_zone_requirements(), geometry_profile_id=TWO_ZONE_PROFILE)
        self.assertEqual(set(result["ports"]), {"side_entry", "axial_exit"})
        validate_schema(result, "component_geometry_interface.schema.json")
        self.assertEqual(result["local_frame_id"], "orthogonal_accelerator_exit_origin_v1")
        port = result["ports"]["side_entry"]
        self.assertEqual(port, {
            "surface_kind": "aperture_outer_face", "center_mm": [0, -17, 32],
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
        self.assertEqual(result["local_frame_id"], "orthogonal_accelerator_exit_origin_v1")
        self.assertEqual(result["ports"]["axial_exit"], {
            "surface_kind": "aperture_outer_face", "center_mm": [0.0, 0.0, 0.0],
            "outward_normal": [0, 0, -1], "wall_thickness_mm": opening["z_max_mm"] - opening["z_min_mm"],
            "cross_section": {"shape": "rectangle", "width_mm": opening["x_max_mm"] - opening["x_min_mm"],
                              "height_mm": opening["y_max_mm"] - opening["y_min_mm"],
                              "width_axis": [1, 0, 0], "height_axis": [0, 1, 0]},
        })
        self.assertEqual(result["ports"]["axial_exit"]["center_mm"][2] + compiled.local_exit_z_mm,
                         compiled.local_exit_z_mm)
        self.assertEqual([(item["component_electrode_id"], item["role"])
                          for item in result["component_electrodes"][:4]],
                         [(15, "grounded_shield"), (22, "repeller"), (23, "grid1"), (24, "exit_grid")])

    def test_three_zone_outer_face_and_component_ids(self) -> None:
        result = resolve_assembly_interface(three_zone_requirements_fixture(), geometry_profile_id=None)
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
            (two_zone_requirements(), TWO_ZONE_PROFILE, [[1, 0, 0], [0, 1, 0], [0, 0, 1]], [0, -50, 0]),
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

    def test_pa_grid_envelope_and_origin_do_not_change_mechanical_interface(self) -> None:
        request = two_zone_requirements()
        expected = resolve_assembly_interface(request, geometry_profile_id=TWO_ZONE_PROFILE)
        for local in (None, {"span_mm": [1, 1, 1], "mesh_mm_per_gu": [0, 0, 0],
                             "exit_z_mm": 23, "margin_z_mm": -1},
                      {"span_mm": [100, 100, 100], "mesh_mm_per_gu": [.5, .5, .5],
                       "exit_z_mm": 17, "margin_z_mm": 3}):
            with self.subTest(local=local):
                candidate = copy.deepcopy(request)
                if local is None:
                    candidate.pop("local_pa")
                else:
                    candidate["local_pa"] = local
                self.assertEqual(resolve_assembly_interface(candidate, geometry_profile_id=TWO_ZONE_PROFILE), expected)
        request["local_pa"]["span_mm"] = [1, 1, 1]
        with self.assertRaises(ValueError):
            compile_closed_two_zone_accelerator(request)

    def test_physical_profile_changes_reach_interface_and_emitter_together(self) -> None:
        from projects.orthogonal_accelerator.analysis.two_zone_geometry import load_geometry_profile
        profile = dict(load_geometry_profile(TWO_ZONE_PROFILE))
        profile["aperture_width_x_mm"] = 24.0
        with patch("projects.orthogonal_accelerator.analysis.two_zone_geometry.load_geometry_profile",
                   return_value=profile):
            interface = resolve_assembly_interface(two_zone_requirements(), geometry_profile_id=TWO_ZONE_PROFILE)
            compiled = compile_closed_two_zone_accelerator(two_zone_requirements())
        self.assertEqual(interface["ports"]["axial_exit"]["cross_section"]["width_mm"], 24)
        self.assertEqual(compiled.resolved_electrodes.aperture_half_x_mm, 12)
        invalid = two_zone_requirements()
        invalid["side_entry"]["half_width_z_mm"] = 4
        with self.assertRaises(ValueError):
            resolve_assembly_interface(invalid, geometry_profile_id=TWO_ZONE_PROFILE)

    def test_interface_import_and_query_need_no_simion_module(self) -> None:
        code = """import builtins,json,sys
original=builtins.__import__
def guarded(name,*args,**kwargs):
    if name.startswith('projects.orthogonal_accelerator.simion'):
        raise AssertionError('mechanical query imported solver adapter')
    return original(name,*args,**kwargs)
builtins.__import__=guarded
from projects.orthogonal_accelerator.analysis.assembly_interface import resolve_assembly_interface
request=json.loads(sys.argv[1]);request.pop('local_pa')
result=resolve_assembly_interface(request,geometry_profile_id=sys.argv[2])
assert result['ports']['axial_exit']['center_mm']==[0.0,0.0,0.0]
"""
        completed = subprocess.run([sys.executable, "-c", code, json.dumps(two_zone_requirements()),
                                    TWO_ZONE_PROFILE], cwd=Path(__file__).resolve().parents[4],
                                    capture_output=True, text=True, timeout=15)
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)

    def test_actual_frontend_adapter_does_not_render_unused_local_pa(self) -> None:
        from integrations.runtime.single_flight_frontend import _canonical_component
        from integrations.tests.frontend_fixtures import canonical_frontend_fixture
        _, _, component = canonical_frontend_fixture()
        with patch("projects.orthogonal_accelerator.simion.two_zone_candidate.render_closed_two_zone_local_pa",
                   side_effect=AssertionError("assembly must not render a discarded local PA")):
            projected = _canonical_component(component)
        self.assertEqual(projected["planes"]["exit"], 34)
        self.assertEqual(projected["canonical_electrodes"]["grounded_enclosure"]["outer_box_mm"]["z_min_mm"], 6)
        self.assertEqual(projected["accelerator_component"]["transform"]["translation_mm"], [0, 0, 40])
        shifted = copy.deepcopy(component)
        shifted["requirements"]["local_pa"]["exit_z_mm"] = 17
        after = _canonical_component(shifted)
        for key in ("planes", "ring_z_mm", "actual_bounds_mm", "port"):
            self.assertEqual(after[key], projected[key], key)
        self.assertEqual(after["accelerator_component"]["transform"]["translation_mm"], [0, 0, 51])

    def test_invalid_identity_fails_closed(self) -> None:
        for profile in (None, "", " padded ", 12):
            with self.subTest(profile=profile), self.assertRaises(ValueError):
                resolve_assembly_interface(two_zone_requirements(), geometry_profile_id=profile)
        with self.assertRaisesRegex(ValueError, "two_zone or three_zone"):
            resolve_assembly_interface({"variant_id": "four_zone"}, geometry_profile_id=None)


if __name__ == "__main__":
    unittest.main()
