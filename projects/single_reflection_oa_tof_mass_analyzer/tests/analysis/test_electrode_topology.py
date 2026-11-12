"""Actual OA provider composition retains the complete analyzer and domain scope."""
from __future__ import annotations

import copy
import unittest

from projects.orthogonal_accelerator.analysis.electrode_topology import _at_pointer
from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import resolve_oa_provider
from projects.single_reflection_oa_tof_mass_analyzer.analysis.electrode_topology import (
    build_electrode_topology, resolve_frontend_field_domain,
)
from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_physical_geometry
from projects.single_reflection_oa_tof_mass_analyzer.tests.analysis.test_assembly_interface import (
    candidate_300mm_fixture, projected_candidate,
)


class ElectrodeTopologyTests(unittest.TestCase):
    def test_neutral_groups_and_drives_ignore_backend_payload_and_adapter(self):
        from unittest.mock import patch

        resolved, projection = candidate_300mm_fixture(), projected_candidate()
        expected = build_electrode_topology(resolved, projection=projection)
        before = copy.deepcopy((resolved, projection))
        for mode in ("remove", "perturb"):
            changed = copy.deepcopy(resolved)
            for key in list(changed):
                if key.startswith("simion") or key in {"solver_numerics", "comsol_runtime"}:
                    if mode == "remove":
                        del changed[key]
                    else:
                        changed[key] = {"not_a_backend_contract": True, "local_electrode_id": 997}
            with self.subTest(mode=mode), patch(
                "projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract.resolve_physical_geometry",
                side_effect=AssertionError("neutral topology must not call native adapter"),
            ):
                self.assertEqual(build_electrode_topology(changed, projection=projection), expected)
                self.assertEqual(resolve_frontend_field_domain(changed, projection=projection),
                                 resolve_frontend_field_domain(resolved, projection=projection))
        self.assertEqual((resolved, projection), before)

    def test_actual_complete_provider_preserves_four_ground_members_and_exit(self):
        resolved, projection = candidate_300mm_fixture(), projected_candidate()
        before = copy.deepcopy((resolved, projection))
        topology = build_electrode_topology(resolved, projection=projection)
        groups = {row["electrode_group_id"]: row for row in topology["groups"]}
        expected = {"common_ground", "accelerator_repeller", "accelerator_intermediate_grid_1",
                    "accelerator_intermediate_grid_2", "accelerator_exit_grid",
                    "reflectron_midgrid", "reflectron_backplate"}
        expected.update(f"accelerator_ring_{index:04d}" for index in range(1, 21))
        expected.update(f"reflectron_stage1_ring_{index}" for index in range(1, 11))
        expected.update(f"reflectron_stage2_ring_{index}" for index in range(1, 6))
        self.assertEqual(set(groups), expected)
        self.assertEqual(len(groups), 42)
        physical = resolve_physical_geometry(resolved, accelerator_projection=projection)
        self.assertEqual(len(physical["electrodes"]), 45)
        self.assertEqual({row["role"] for row in physical["electrodes"] if row["electrical_group_id"] == 1},
                         {"accelerator_side_shield", "flight_tube_shield", "reflectron_entry_grid", "detector"})
        common = groups["common_ground"]
        self.assertEqual({ref.split("/")[3] for ref in common["member_refs"] if ref.startswith("/sources/downstream/")},
                         {"flight_tube_shield", "reflectron_entry_grid", "detector"})
        self.assertTrue(any(ref.startswith("/sources/oa_mechanical/geometry/") for ref in common["member_refs"]))
        self.assertNotIn("accelerator_exit_grid", common["member_refs"])
        self.assertEqual(_at_pointer(topology, groups["accelerator_exit_grid"]["voltage_source"]["pointer"]), 0)
        for row in groups.values():
            self.assertTrue(row["member_refs"])
            for ref in row["member_refs"]:
                self.assertIsNotNone(_at_pointer(topology, ref))
            self.assertIsInstance(_at_pointer(topology, row["voltage_source"]["pointer"]), (int, float))
        self.assertNotIn("marker", repr(topology))
        self.assertEqual((resolved, projection), before)

    def test_frontend_scope_is_recompiled_from_provider_and_retains_complete_topology(self):
        resolved, projection = candidate_300mm_fixture(), projected_candidate()
        domain = resolve_frontend_field_domain(resolved, projection=projection)
        expected = {"common_ground", "accelerator_repeller", "accelerator_intermediate_grid_1",
                    "accelerator_intermediate_grid_2", "accelerator_exit_grid"}
        expected.update(f"accelerator_ring_{index:04d}" for index in range(1, 21))
        self.assertEqual(set(domain["electrode_group_ids"]), expected)
        self.assertEqual(len(domain["members"]), 25)
        self.assertTrue(all(ref.startswith("/sources/oa_mechanical/")
                            for row in domain["members"] for ref in row["member_refs"]))
        # A record cannot persist a shortened expected scope into this pure compiler.
        domain["electrode_group_ids"].pop()
        self.assertEqual(set(resolve_frontend_field_domain(resolved, projection=projection)["electrode_group_ids"]), expected)
        topology = build_electrode_topology(resolved, projection=projection)
        self.assertIn("reflectron_backplate", {row["electrode_group_id"] for row in topology["groups"]})

    def test_actual_oa_compiler_uses_physical_aperture_and_canonical_roles(self):
        resolved, projection = candidate_300mm_fixture(), projected_candidate(width=1.07, height=4)
        # Deliberate backend-only projection perturbation: it cannot become a mechanical input.
        projection.local_region["numerical_port_width_mm"] += .25
        provider = resolve_oa_provider(resolved, projection=projection, geometry_profile_id=None)
        self.assertEqual(provider["source"]["geometry"]["numerical_port_width_mm"], 1.07)
        self.assertEqual(provider["source"]["geometry"]["numerical_port_height_mm"], 4)
        self.assertNotEqual(projection.local_region["numerical_port_width_mm"], 1.07)
        self.assertFalse(provider["mechanical"]["standalone_component_capability"])
        self.assertEqual(provider["ports"]["side_entry"]["center_mm"], [-122.8, 0, -340.74261546154855])
        values = provider["electrical"]["operating_voltages_v"]
        self.assertEqual([values[key] for key in ("repeller", "intermediate_grid_1", "intermediate_grid_2", "exit_grid")],
                         [2140, 1860, 372.96685170832035, 0])
        self.assertEqual(provider["frame_transform"]["translation_mm"], [0, 0, 0])
        self.assertEqual(provider["mechanical"]["geometry"]["ring_z_mm"], resolved["rings"]["accelerator_placement"]["ring_z_mm"])

    def test_original_height4_port_keeps_physical_opening_without_standalone_qualification(self):
        from projects.orthogonal_accelerator.analysis.sectioned_geometry import resolve_bare_three_zone_component

        resolved, projection = candidate_300mm_fixture(), projected_candidate()
        provider = resolve_oa_provider(resolved, projection=projection, geometry_profile_id=None)
        mechanical = provider["mechanical"]
        g = mechanical["geometry"]
        self.assertEqual(g["port_center_z_mm"] - g["numerical_port_height_mm"]/2, g["repeller_front_z_mm"])
        # Side wall ends 5mm before the repeller edge in x: equal z is not contact.
        self.assertEqual((g["shield_inner_width_mm"] - g["electrode_width_mm"])/2, 5)
        request = dict(schema_version=1, role="orthogonal_accelerator_bare_three_zone_requirements",
                       variant_id="three_zone", geometry=copy.deepcopy(g))
        from msplatform.components.orthogonal_accelerator.assembly_interface import build_assembly_interface
        physical = resolve_bare_three_zone_component(request)
        with self.assertRaisesRegex(ValueError, "first gap"):
            build_assembly_interface(physical, geometry_profile_id=None)
        self.assertEqual(mechanical["role"], "instrument_sectioned_accelerator_mechanics_projection")
        self.assertFalse(mechanical["standalone_component_capability"])
        self.assertEqual(mechanical["port"]["height_mm"], 4)
        self.assertAlmostEqual(mechanical["canonical_electrodes"]["repeller"]["solid_box_mm"]["x_min_mm"]
                               - (g["negative_x_face_mm"] + g["shield_wall_mm"]), 5)

    def test_provider_rejects_missing_opening_wrong_body_and_legacy_capability(self):
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.accelerator_geometry import resolve_accelerator_geometry
        from projects.single_reflection_oa_tof_mass_analyzer.analysis.geometry_contract import resolve_contract

        resolved = candidate_300mm_fixture()
        projection = projected_candidate()
        projection.local_region["electrode_width_mm"] += 1
        with self.assertRaisesRegex(ValueError, "physical body"):
            build_electrode_topology(resolved, projection=projection)
        with self.assertRaisesRegex(ValueError, "opening"):
            build_electrode_topology(resolved, projection=resolve_accelerator_geometry(resolved, variant_id="three_zone_square"))
        old = resolve_contract()
        with self.assertRaisesRegex(ValueError, "three_zone_square"):
            build_electrode_topology(old, projection=resolve_accelerator_geometry(old, variant_id="two_zone_square"))

    def test_downstream_geometry_and_voltage_oracle_preserves_original_dividers(self):
        resolved, projection = candidate_300mm_fixture(), projected_candidate()
        resolved["rings"].update(stage1_count=2, stage2_count=3)
        resolved["electrodes_V"].update(midgrid=1500, backplate=2500)
        topology = build_electrode_topology(resolved, projection=projection)
        downstream = topology["sources"]["downstream"]
        self.assertEqual([downstream[f"reflectron_stage1_ring_{i}"]["operating_voltage_v"] for i in (1, 2)], [500, 1000])
        self.assertEqual([downstream[f"reflectron_stage2_ring_{i}"]["operating_voltage_v"] for i in (1, 2, 3)], [1750, 2000, 2250])
        geometry = downstream["reflectron_stage1_ring_1"]["geometry"]
        g = resolved["geometry_mm"]
        center = g["L_flight"] + g["L_stage1"] / 3
        self.assertEqual(geometry["axial_mm"], [center-g["ring_thickness"]/2, center+g["ring_thickness"]/2])
        self.assertEqual(geometry["radius_mm"], [g["bore_r"], g["ring_outer_r"]])
