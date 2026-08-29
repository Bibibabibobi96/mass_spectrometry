from __future__ import annotations

import json
import copy
import hashlib
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import (
    compile_accelerator_main,
    compile_accelerator_overlay,
    compile_frontend,
    compile_upstream_bridge,
    resolve_positive_gap_domain_split,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations" / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightFrontendTests(unittest.TestCase):
    THREE_ZONE_TOPOLOGY = {
        "topology_id": "three_zone_accelerator_ideal_v1",
        "planes_global_z_mm": {
            "repeller": -19.92918680341103,
            "intermediate1": -16.87918680341103,
            "intermediate2": -11.57918680341103,
            "exit": -0.12918680341102995,
        },
        "potentials_v": {
            "repeller": 2000.0,
            "intermediate1": 1750.0,
            "intermediate2": 1450.0,
            "exit": 0.0,
        },
    }
    GRID_010_THREE_ZONE_TOPOLOGY = {
        "topology_id": "three_zone_accelerator_ideal_v1",
        "planes_global_z_mm": {
            "repeller": -342.74261546154855,
            "intermediate1": -335.74261546154855,
            "intermediate2": -279.64261546154853,
            "exit": -42.742615461548496,
        },
        "potentials_v": {
            "repeller": 2140.0,
            "intermediate1": 1860.0,
            "intermediate2": 372.96685170832035,
            "exit": 0.0,
        },
    }
    @classmethod
    def setUpClass(cls) -> None:
        source = (
            REPO.parent
            / "artifacts/projects/rf_octupole_ion_optics/runs"
            / "20260804_112000__sim__simion__oct-segmented-aperture050__n1000"
            / "inputs/multipole_resolved_design.json"
        )
        if not source.is_file():
            raise unittest.SkipTest("local N=1000 octupole source artifact is unavailable")
        cls.upstream = json.loads(source.read_text(encoding="utf-8-sig"))
        cls.oatof = json.loads(
            (REPO / "projects/single_reflection_oa_tof_mass_analyzer/config/resolved_geometry.json").read_text()
        )
        cls.connection = json.loads(
            (
                REPO.parent
                / "artifacts/projects/rf_octupole_ion_optics/runs"
                / "20260804_125500__sim__simion__oct-aperture100x090-interface__n459"
                / "inputs/resolved_connection.json"
            ).read_text(encoding="utf-8-sig")
        )
        cls.upstream = copy.deepcopy(cls.upstream)
        cls.upstream["axial_dc"]["upstream_shield_potential_V"] = 0.0
        cls.upstream["axial_dc"]["entrance_plate_potential_V"] = 3.0
        cls.upstream["axial_dc"]["entrance_reference_sleeve"] = {
            "profile_id": "source_reference_sleeve_v1",
            "role": "functional_source_reference_not_shield",
            "potential_V": 3.0,
            "inner_radius_mm": 1.0,
            "outer_radius_mm": 1.4,
            "upstream_face_z_mm": -2.5,
            "downstream_face_z_mm": -0.1,
            "minimum_insulation_gap_mm": 0.2,
        }
        cls.upstream["downstream_terminal"]["terminal_potential_V"] = 0.0
        cls.connection["connector"].update(
            {
                "shield_connection_profile_id": "grounded_circular_to_rectangular_shield_v1",
                "shield_potential_V": 0.0,
                "cross_section_binding": "upstream_grounded_shield_v1",
            }
        )

    def test_compiles_one_grounded_shield_and_connector_electrode(self) -> None:
        gem, contract = compile_frontend(self.upstream, self.oatof, self.connection)
        self.assertEqual(contract["electrodes"]["grounded_shield_id"], 9)
        self.assertEqual(contract["electrodes"]["accelerator_grid2_id"], 17)
        self.assertIn("9=all grounded shields and connector", gem)
        self.assertEqual(contract["electrodes"]["entrance_reference_sleeve_id"], 18)
        self.assertEqual(contract["electrodes"]["entrance_plate_id"], 19)
        self.assertIn("e(18)", gem)
        self.assertIn("e(19)", gem)
        self.assertIn("Functional source-reference sleeve", gem)
        self.assertNotIn("Numerical absorber", gem)
        self.assertNotIn(",1,-90) { cylinder", gem)
        self.assertIn(",1,90) { cylinder", gem)
        self.assertGreaterEqual(gem.count("e(9)"), 5)
        self.assertEqual(
            contract["ideal_grid_model"]["model_id"],
            "simion_one_row_zero_width_native_transmission",
        )
        self.assertEqual(
            contract["ideal_grid_model"]["grid_roles"],
            ["accelerator_grid1", "accelerator_grid2"],
        )
        self.assertTrue(
            contract["ideal_grid_model"][
                "real_wire_mesh_requires_separate_profile"
            ]
        )
        grid1 = contract["accelerator_local_region"]["grid1_z_mm"]
        grid2 = contract["accelerator_local_region"]["grid2_z_mm"]
        self.assertIn(f",{grid1:.12g},", gem)
        self.assertIn(f",{grid2:.12g},", gem)
        self.assertGreaterEqual(gem.count(",0) } } }"), 2)

    def test_cylindrical_three_zone_realization_uses_circular_accelerator_electrodes(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        oatof["geometry_derivation"]["accelerator"]["realization_id"] = "cylindrical_3d"
        gem, contract = compile_frontend(self.upstream, oatof, self.connection)
        region = contract["accelerator_local_region"]
        self.assertEqual(region["cross_section"], "cylindrical")
        self.assertIn("Zero-grid-unit circular sheets", gem)
        self.assertIn("cylinder(0,0,0,15", gem)
        self.assertNotIn(
            "unsupported", gem.lower(),
        )

    def _three_zone_main_oatof(self, realization_id: str) -> dict:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        oatof["geometry_derivation"]["accelerator"]["realization_id"] = realization_id
        planes = oatof["accelerator_topology"]["planes_global_z_mm"]
        zone2 = (planes["intermediate1"] + planes["intermediate2"]) / 2.0
        zone3_pitch = (planes["exit"] - planes["intermediate2"]) / 5.0
        oatof["rings"]["accelerator_placement"] = {
            "policy_id": "three_zone_zonewise_equal_subdivision_1p4_v1",
            "zone_ring_counts": {"zone2": 1, "zone3": 4},
            "minimum_grid_to_ring_edge_clearance_mm": 1.0,
            "minimum_observed_grid_to_ring_edge_clearance_mm": zone3_pitch - 0.5,
            "ring_z_mm": [
                zone2,
                *[
                    planes["intermediate2"] + index * zone3_pitch
                    for index in range(1, 5)
                ],
            ],
        }
        return oatof

    def test_standalone_three_zone_accelerator_main_preserves_shared_axial_design(self) -> None:
        results: dict[str, tuple[str, dict]] = {}
        for realization_id in ("square_3d", "cylindrical_3d"):
            with self.subTest(realization_id=realization_id):
                oatof = self._three_zone_main_oatof(realization_id)
                _, frontend = compile_frontend(self.upstream, oatof, self.connection)
                results[realization_id] = compile_accelerator_main(
                    frontend,
                    oatof,
                    cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
                )
        square_gem, square = results["square_3d"]
        cylindrical_gem, cylindrical = results["cylindrical_3d"]
        self.assertEqual(square["cross_section"], "square")
        self.assertEqual(cylindrical["cross_section"], "cylindrical")
        for field in ("axial_planes_global_z_mm", "potentials_v", "ring_placement"):
            self.assertEqual(square[field], cylindrical[field])
        self.assertEqual(square["ring_placement"]["zone_ring_counts"], {"zone2": 1, "zone3": 4})
        self.assertEqual(square["status"], "bridge_coupling_required")
        self.assertTrue(square["boundary_condition"]["direct_refinement_prohibited"])
        self.assertIn("bridge-electrode-basis Dirichlet", square_gem)
        self.assertIn("centered_box3D", square_gem)
        self.assertIn("cylinder(0,0,0", cylindrical_gem)
        self.assertNotEqual(square_gem, cylindrical_gem)

    def test_domain_main_encloses_the_intermediate_overlay_boundary(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.GRID_010_THREE_ZONE_TOPOLOGY)
        oatof["geometry_derivation"]["accelerator"]["realization_id"] = "square_3d"
        planes = oatof["accelerator_topology"]["planes_global_z_mm"]
        zone2 = (planes["intermediate1"] + planes["intermediate2"]) / 2.0
        zone3_pitch = (planes["exit"] - planes["intermediate2"]) / 5.0
        oatof["rings"]["accelerator_placement"] = {
            "policy_id": "three_zone_zonewise_equal_subdivision_1p4_v1",
            "zone_ring_counts": {"zone2": 1, "zone3": 4},
            "minimum_grid_to_ring_edge_clearance_mm": (planes["intermediate2"] - planes["intermediate1"]) / 2.0 - 0.5,
            "minimum_observed_grid_to_ring_edge_clearance_mm": (planes["intermediate2"] - planes["intermediate1"]) / 2.0 - 0.5,
            "ring_z_mm": [
                zone2,
                *[planes["intermediate2"] + index * zone3_pitch for index in range(1, 5)],
            ],
        }
        _, frontend = compile_frontend(
            self.upstream,
            oatof,
            self.connection,
            cell_mm_xyz={"x": 0.5, "y": 0.5, "z": 0.5},
        )
        _, main = compile_accelerator_main(
            frontend,
            oatof,
            cell_mm_xyz={"x": 0.25, "y": 0.25, "z": 0.1},
            connection=self.connection,
        )
        _, intermediate = compile_accelerator_overlay(
            frontend,
            cell_mm_xyz={"x": 0.25, "y": 0.25, "z": 0.05},
            region_id="intermediate2",
            intermediate_half_span_mm=2.0,
        )
        for axis in ("x", "y", "z"):
            self.assertLessEqual(
                main["instance_bounds_mm"][f"{axis}_min"],
                intermediate["instance_bounds_mm"][f"{axis}_min"],
            )
            self.assertGreaterEqual(
                main["instance_bounds_mm"][f"{axis}_max"],
                intermediate["instance_bounds_mm"][f"{axis}_max"],
            )

    def test_grid_realized_300mm_candidate_places_all_accelerator_grids_on_010mm_nodes(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.GRID_010_THREE_ZONE_TOPOLOGY)
        oatof["geometry_derivation"]["accelerator"]["realization_id"] = "square_3d"
        planes = oatof["accelerator_topology"]["planes_global_z_mm"]
        zone2 = (planes["intermediate1"] + planes["intermediate2"]) / 2.0
        zone3_pitch = (planes["exit"] - planes["intermediate2"]) / 5.0
        oatof["rings"]["accelerator_placement"] = {
            "policy_id": "three_zone_zonewise_equal_subdivision_1p4_v1",
            "zone_ring_counts": {"zone2": 1, "zone3": 4},
            "minimum_grid_to_ring_edge_clearance_mm": (planes["intermediate2"] - planes["intermediate1"]) / 2.0 - 0.5,
            "minimum_observed_grid_to_ring_edge_clearance_mm": (planes["intermediate2"] - planes["intermediate1"]) / 2.0 - 0.5,
            "ring_z_mm": [
                zone2,
                *[
                    planes["intermediate2"] + index * zone3_pitch
                    for index in range(1, 5)
                ],
            ],
        }
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        _, main = compile_accelerator_main(
            frontend,
            oatof,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.1},
            connection=self.connection,
        )
        origin = main["instance_origin_mm"]["z"]
        for role in ("intermediate1", "intermediate2", "exit"):
            index = (main["axial_planes_global_z_mm"][role] - origin) / 0.1
            self.assertAlmostEqual(index, round(index), places=8)
        aperture = main["accelerator_port_aperture"]
        self.assertEqual(aperture["authority"], "fine_accelerator_main_pa_v1")
        self.assertTrue(
            aperture["discretization"]["grid_alignment"]
            ["height_is_integer_cell_multiple"]
        )
        self.assertTrue(
            aperture["coarse_frontend_discretization_is_non_authoritative"]
        )

    def test_long_connector_split_leaves_the_middle_sleeve_to_the_coarse_pa(self) -> None:
        frontend = {"source_exit_center_mm": {"x": 100.0}}
        self.assertIsNone(
            resolve_positive_gap_domain_split(
                frontend, {"connector": {"length_mm": 49.9}}
            )
        )
        split = resolve_positive_gap_domain_split(
            frontend, {"connector": {"length_mm": 98.4}}
        )
        self.assertIsNotNone(split)
        assert split is not None
        self.assertAlmostEqual(split["terminal_end_x_mm"], 1.6)
        self.assertAlmostEqual(split["upstream_end_x_mm"], 11.6)
        self.assertAlmostEqual(split["accelerator_start_x_mm"], 90.0)
        self.assertAlmostEqual(split["coarse_sleeve_x_min_mm"], 11.6)
        self.assertAlmostEqual(split["coarse_sleeve_x_max_mm"], 90.0)

    def test_standalone_accelerator_main_fails_closed_without_exact_three_zone_contract(self) -> None:
        oatof = self._three_zone_main_oatof("square_3d")
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        missing_topology = copy.deepcopy(self.oatof)
        with self.assertRaisesRegex(ValueError, "three-zone accelerator topology"):
            compile_accelerator_main(
                frontend,
                missing_topology,
                cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
            )
        malformed_frontend = copy.deepcopy(frontend)
        malformed_frontend["accelerator_local_region"]["ring_placement"][
            "zone_ring_counts"
        ] = {"zone2": 2, "zone3": 3}
        with self.assertRaisesRegex(ValueError, "one-plus-four ring placement"):
            compile_accelerator_main(
                malformed_frontend,
                oatof,
                cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
            )
        mismatched_oatof = copy.deepcopy(oatof)
        mismatched_oatof["accelerator_topology"]["potentials_v"]["intermediate2"] = 1800.0
        with self.assertRaisesRegex(ValueError, "potentials must be strictly decreasing"):
            compile_accelerator_main(
                frontend,
                mismatched_oatof,
                cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
            )

    def test_canonical_octupole_rod_semantics_and_frontend_hash(self) -> None:
        segmented = self.upstream["segmentation"]["segmented_rod_array"]
        rods = segmented["electrodes"]
        self.assertEqual(segmented["segment_count"], 4)
        self.assertEqual(len(rods), 32)
        self.assertEqual(len({(rod["center_x_mm"], rod["center_y_mm"]) for rod in rods}), 8)
        self.assertEqual({rod["radius_mm"] for rod in rods}, {2.0})
        self.assertEqual({int(rod["electrode_id"]) for rod in rods}, set(range(1, 9)))
        self.assertEqual(len({(rod["z_min_mm"], rod["z_max_mm"]) for rod in rods}), 4)
        gem, contract = compile_frontend(self.upstream, self.oatof, self.connection)
        self.assertEqual(
            hashlib.sha256(gem.encode()).hexdigest(),
            "0463482b343f0ed5b628facea8795e58e1645cc7c6490e32f121d3d32ce1fc68",
        )
        self.assertEqual(contract["electrodes"]["multipole_rod_ids"], list(range(1, 9)))

    def test_frontend_accepts_shared_quadrupole_and_hexapole_segmented_rods(self) -> None:
        for family, rod_count in (("quadrupole", 16), ("hexapole", 24)):
            with self.subTest(family=family):
                resolved = json.loads(
                    (
                        REPO
                        / f"projects/rf_{family}_ion_optics/config/resolved_design_no_acceleration_full_length.json"
                    ).read_text(encoding="utf-8")
                )
                upstream = copy.deepcopy(self.upstream)
                upstream["segmentation"]["segmented_rod_array"] = resolved["segmentation"][
                    "segmented_rod_array"
                ]
                gem, contract = compile_frontend(upstream, self.oatof, self.connection)
                self.assertEqual(
                    gem.count("{ cylinder(0,0,0,2,,19.6)"), rod_count
                )
                self.assertEqual(
                    contract["electrodes"]["multipole_rod_ids"], list(range(1, 9))
                )

    def test_frontend_fails_closed_outside_published_electrode_basis(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["rings"]["accelerator_count"] = 4
        with self.assertRaisesRegex(ValueError, "exactly five accelerator rings"):
            compile_frontend(self.upstream, oatof, self.connection)
        upstream = copy.deepcopy(self.upstream)
        upstream["segmentation"]["segmented_rod_array"]["electrodes"][0][
            "electrode_id"
        ] = 9
        with self.assertRaisesRegex(ValueError, "namespace"):
            compile_frontend(upstream, self.oatof, self.connection)

    def test_preserves_direct_mating_aperture_and_global_origin(self) -> None:
        _, contract = compile_frontend(self.upstream, self.oatof, self.connection)
        self.assertEqual(contract["aperture"], {"shape": "rectangular", "width_mm": 1.0, "height_mm": 0.9})
        self.assertAlmostEqual(contract["source_exit_center_mm"]["x"], -67.8)
        enclosure = contract["junction_enclosure"]
        self.assertEqual(enclosure["profile_gap_mm"], 0.0)
        self.assertEqual(enclosure["length_mm"], 0.0)
        self.assertEqual(enclosure["topology"], "fixed_upstream_grounded_shield_connector_v1")
        self.assertNotIn("flange_thickness_mm", enclosure)
        self.assertLessEqual(contract["dimensions"]["nx"] * contract["dimensions"]["ny"] * contract["dimensions"]["nz"], 30_000_000)

    def _positive_gap_connection(self, length_mm: float = 5.0) -> dict:
        connection = json.loads(json.dumps(self.connection))
        connection["connector"]["length_mm"] = length_mm
        connection["spatial_registration"]["expected_gap_mm"] = length_mm
        connection["spatial_registration"]["translation_mm"][0] -= length_mm
        return connection

    def test_gap_zero_has_no_connector_terminal_or_sleeve(self) -> None:
        _, contract = compile_frontend(self.upstream, self.oatof, self.connection)
        self.assertFalse(contract["connector_terminal"]["present"])
        self.assertEqual(contract["junction_enclosure"]["length_mm"], 0.0)

    def test_positive_gap_has_connector_owned_circular_terminal_and_fixed_sleeve(self) -> None:
        upstream = copy.deepcopy(self.upstream)
        upstream["downstream_terminal"]["aperture"] = {
            "shape": "circular",
            "radius_mm": 1.5,
        }
        connection = self._positive_gap_connection()
        connection["transition_aperture"]["full_height_mm"] = 2.5
        gem, contract = compile_frontend(upstream, self.oatof, connection)
        self.assertEqual(
            contract["connector_terminal"]["aperture"],
            {"shape": "circular", "radius_mm": 1.5},
        )
        self.assertEqual(contract["connector_terminal"]["outer_radius_mm"], 20.0)
        self.assertEqual(contract["junction_enclosure"]["length_mm"], 1.0)
        self.assertIn("Integration-owned grounded connector terminal", gem)

    def test_upstream_bridge_keeps_only_upstream_junction_for_gap_zero(self) -> None:
        gem, bridge = compile_upstream_bridge(
            self.upstream,
            self.oatof,
            self.connection,
            cell_mm_xyz={"x": 0.1, "y": 0.1, "z": 0.1},
        )
        self.assertEqual(bridge["role"], "rf_oatof_simion_upstream_bridge_contract")
        self.assertEqual(bridge["status"], "bridge_coupling_required")
        self.assertEqual(
            bridge["boundary_condition"]["mode"],
            "bridge_electrode_basis_dirichlet_required_v1",
        )
        self.assertFalse(bridge["connector_terminal"]["present"])
        self.assertNotIn("Integration-owned grounded connector terminal", gem)
        self.assertIn("Local grounded accelerator-entry screen", gem)
        self.assertNotIn("Zero-grid-unit", gem)
        self.assertNotIn("ring", gem.lower())
        self.assertEqual(bridge["cell_mm_xyz"]["x"], bridge["cell_mm_xyz"]["y"])
        self.assertAlmostEqual(
            bridge["instance_bounds_mm"]["y_min"],
            -bridge["instance_bounds_mm"]["y_max"],
        )

    def test_upstream_bridge_gap_connector_and_port_height_discretization(self) -> None:
        upstream = copy.deepcopy(self.upstream)
        upstream["downstream_terminal"]["aperture"] = {
            "shape": "circular",
            "radius_mm": 1.5,
        }
        for height_mm in (0.9, 1.5, 2.0, 2.5):
            with self.subTest(height_mm=height_mm):
                connection = self._positive_gap_connection()
                connection["transition_aperture"]["full_height_mm"] = height_mm
                gem, bridge = compile_upstream_bridge(
                    upstream,
                    self.oatof,
                    connection,
                    cell_mm_xyz={"x": 0.1, "y": 0.1, "z": 0.1},
                )
                aperture = bridge["accelerator_entry_shield"][
                    "numerical_port_aperture_discretization"
                ]
                self.assertTrue(bridge["connector_terminal"]["present"])
                self.assertIn("Integration-owned grounded connector terminal", gem)
                self.assertEqual(aperture["numerical_carve_height_mm"], height_mm)
                self.assertEqual(aperture["cell_mm_xyz"]["z"], 0.1)
                self.assertIn("Boundary-only sentinels", gem)

    def test_circular_terminal_shape_and_radius_fail_closed(self) -> None:
        for aperture, message in (
            ({"shape": "oval", "radius_mm": 1.5}, "shape is unsupported"),
            ({"shape": "circular", "radius_mm": 0.0}, "radius must be finite and positive"),
            ({"shape": "circular", "radius_mm": True}, "radius is invalid"),
            ({"shape": "circular"}, "radius is invalid"),
        ):
            with self.subTest(aperture=aperture):
                upstream = copy.deepcopy(self.upstream)
                upstream["downstream_terminal"]["aperture"] = aperture
                with self.assertRaisesRegex(ValueError, message):
                    compile_frontend(upstream, self.oatof, self._positive_gap_connection())

    def test_accelerator_shield_opening_is_independent_of_connector_terminal(self) -> None:
        connection = copy.deepcopy(self.connection)
        connection["transition_aperture"]["full_height_mm"] = 1.5
        _, contract = compile_frontend(self.upstream, self.oatof, connection)
        self.assertEqual(contract["aperture"]["height_mm"], 1.5)
        self.assertFalse(contract["connector_terminal"]["present"])

    def test_acceleration_axis_grid_can_be_refined_without_transverse_refinement(self) -> None:
        baseline_gem, baseline = compile_frontend(
            self.upstream, self.oatof, self.connection
        )
        refined_gem, refined = compile_frontend(
            self.upstream,
            self.oatof,
            self.connection,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
        )
        self.assertEqual(refined["cell_mm_xyz"], {"x": 0.2, "y": 0.2, "z": 0.05})
        self.assertEqual(refined["dimensions"]["nx"], baseline["dimensions"]["nx"])
        self.assertEqual(refined["dimensions"]["ny"], baseline["dimensions"]["ny"])
        self.assertGreater(refined["dimensions"]["nz"], 3 * baseline["dimensions"]["nz"])
        self.assertIn(",0.2,0.2,0.05,surface=none)", refined_gem)
        self.assertNotIn("surface=fractional", refined_gem)
        self.assertNotEqual(refined_gem, baseline_gem)


    def test_accelerator_overlay_refines_only_local_acceleration_axis(self) -> None:
        _, frontend = compile_frontend(self.upstream, self.oatof, self.connection)
        gem, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        self.assertEqual(
            overlay["role"], "rf_oatof_simion_accelerator_overlay_contract"
        )
        self.assertEqual(overlay["cell_mm_xyz"], {"x": 0.2, "y": 0.2, "z": 0.05})
        self.assertGreaterEqual(gem.count(",0) } } }"), 2)
        self.assertEqual(
            overlay["instance_origin_mm"]["x"],
            frontend["accelerator_local_region"]["negative_x_face_mm"],
        )
        self.assertEqual(
            overlay["boundary_condition"]["mode"],
            "coarse_electrode_basis_dirichlet_v1",
        )
        self.assertEqual(
            overlay["boundary_condition"]["basis_electrode_ids"], list(range(20))
        )
        self.assertAlmostEqual(
            overlay["active_bounds_mm"]["z_max"],
            frontend["accelerator_local_region"]["grid2_z_mm"] + 0.2,
        )
        self.assertLess(overlay["dimensions"]["nx"], frontend["dimensions"]["nx"])
        self.assertIn(",0.2,0.2,0.05,surface=none)", gem)
        self.assertNotIn("surface=fractional", gem)
        self.assertIn("Boundary-only sentinels", gem)
        self.assertEqual(
            overlay["boundary_family_sentinel_electrode_ids"],
            [1, 2, 3, 4, 5, 6, 7, 8, 18, 19],
        )
        for electrode_id in [1, 2, 3, 4, 5, 6, 7, 8, 18, 19]:
            self.assertIn(f"e({electrode_id})", gem)

    def test_accelerator_overlay_boundary_stays_inside_coarse_frontend(self) -> None:
        _, frontend = compile_frontend(self.upstream, self.oatof, self.connection)
        _, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        coarse = frontend["cell_mm_xyz"]
        coarse_origin = frontend["instance_origin_mm"]
        for axis, count_name in (("x", "nx"), ("y", "ny"), ("z", "nz")):
            coarse_min = coarse_origin[axis]
            coarse_max = coarse_min + (frontend["dimensions"][count_name] - 1) * coarse[axis]
            self.assertGreaterEqual(overlay["instance_bounds_mm"][f"{axis}_min"], coarse_min)
            self.assertLessEqual(overlay["instance_bounds_mm"][f"{axis}_max"], coarse_max + 1e-9)

    def test_three_zone_publishes_id20_but_overlay_owns_exact_sheet(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        coarse_gem, frontend = compile_frontend(
            self.upstream, oatof, self.connection
        )
        self.assertEqual(
            frontend["accelerator_topology_id"],
            "three_zone_accelerator_ideal_v1",
        )
        self.assertEqual(frontend["electrodes"]["accelerator_intermediate2_id"], 20)
        local = frontend["accelerator_local_region"]
        self.assertEqual(local["intermediate2_grid_provider"], "accelerator_overlay")
        self.assertEqual(len(local["ring_z_mm"]), 5)
        self.assertEqual(coarse_gem.count("e(20)"), 1)
        overlay_gem, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        self.assertEqual(
            overlay["boundary_condition"]["basis_electrode_ids"], list(range(21))
        )
        self.assertEqual(overlay_gem.count("e(20)"), 1)
        self.assertIn(f",{local['intermediate2_z_mm']:.12g},", overlay_gem)

        misaligned = copy.deepcopy(frontend)
        misaligned["accelerator_local_region"]["intermediate2_z_mm"] += 0.01
        with self.assertRaisesRegex(ValueError, "intermediate2_z_mm is not aligned"):
            compile_accelerator_overlay(
                misaligned, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
            )

    def test_three_zone_local_overlay_regions_keep_only_the_required_fine_span(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        _, whole = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        entrance_gem, entrance = compile_accelerator_overlay(
            frontend,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
            region_id="entrance",
        )
        intermediate_gem, intermediate = compile_accelerator_overlay(
            frontend,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
            region_id="intermediate2",
            intermediate_half_span_mm=2.0,
        )
        local = frontend["accelerator_local_region"]
        self.assertEqual(entrance["region_id"], "entrance")
        self.assertEqual(intermediate["region_id"], "intermediate2")
        self.assertLess(entrance["dimensions"]["nz"], whole["dimensions"]["nz"])
        self.assertLess(intermediate["dimensions"]["nz"], entrance["dimensions"]["nz"])
        self.assertGreater(
            entrance["instance_bounds_mm"]["z_max"], local["grid1_z_mm"]
        )
        self.assertLess(
            entrance["instance_bounds_mm"]["z_max"], local["intermediate2_z_mm"]
        )
        self.assertLess(
            intermediate["instance_bounds_mm"]["z_min"], local["intermediate2_z_mm"]
        )
        self.assertGreater(
            intermediate["instance_bounds_mm"]["z_max"], local["intermediate2_z_mm"]
        )
        self.assertIn(f",{local['intermediate2_z_mm']:.12g},", intermediate_gem)
        self.assertIn("e(20)", intermediate_gem)
        self.assertIn("e(10)", entrance_gem)

    def test_accelerator_overlay_rejects_unknown_or_invalid_local_region(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        with self.assertRaisesRegex(ValueError, "region_id"):
            compile_accelerator_overlay(
                frontend,
                cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
                region_id="unknown",
            )
        with self.assertRaisesRegex(ValueError, "half span"):
            compile_accelerator_overlay(
                frontend,
                cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05},
                region_id="intermediate2",
                intermediate_half_span_mm=0.0,
            )

    def test_three_zone_accepts_registered_topology_identity_with_same_semantics(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        oatof["accelerator_topology"]["topology_id"] = "registered_three_zone_topology_v2"
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        self.assertEqual(
            frontend["accelerator_topology_id"], "registered_three_zone_topology_v2"
        )

    def test_three_zone_frontend_consumes_exact_zonewise_one_plus_four_rings(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        topology = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        grid1 = -17.12918680341103
        intermediate2 = grid1 + 5.1
        exit_z = intermediate2 + 11.9
        topology["planes_global_z_mm"].update(
            {"intermediate1": grid1, "intermediate2": intermediate2, "exit": exit_z}
        )
        ring_z = [
            grid1 + 2.55,
            *[intermediate2 + index * 2.38 for index in range(1, 5)],
        ]
        oatof["accelerator_topology"] = topology
        oatof["rings"]["accelerator_placement"] = {
            "policy_id": "three_zone_zonewise_equal_subdivision_1p4_v1",
            "zone_ring_counts": {"zone2": 1, "zone3": 4},
            "minimum_grid_to_ring_edge_clearance_mm": 1.0,
            "minimum_observed_grid_to_ring_edge_clearance_mm": 1.88,
            "ring_z_mm": ring_z,
        }
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        local = frontend["accelerator_local_region"]
        self.assertEqual(local["ring_z_mm"], ring_z)
        self.assertNotIn("ring_pitch_mm", local)
        self.assertEqual(
            local["ring_placement"]["zone_ring_counts"], {"zone2": 1, "zone3": 4}
        )

        invalid = copy.deepcopy(oatof)
        invalid["rings"]["accelerator_placement"]["zone_ring_counts"] = {
            "zone2": 2, "zone3": 3
        }
        with self.assertRaisesRegex(ValueError, "placement count differs"):
            compile_frontend(self.upstream, invalid, self.connection)
        invalid = copy.deepcopy(oatof)
        invalid["rings"]["accelerator_placement"][
            "minimum_grid_to_ring_edge_clearance_mm"
        ] = 2.0
        with self.assertRaisesRegex(ValueError, "edge clearance differs"):
            compile_frontend(self.upstream, invalid, self.connection)

    def test_accelerator_overlay_supports_same_grid_identity_validation(self) -> None:
        _, frontend = compile_frontend(self.upstream, self.oatof, self.connection)
        _, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.2}
        )
        self.assertEqual(overlay["cell_mm_xyz"], frontend["cell_mm_xyz"])

    def test_accelerator_overlay_expands_unaligned_envelope_to_coarse_nodes(self) -> None:
        oatof = copy.deepcopy(self.oatof)
        oatof["accelerator_topology"] = copy.deepcopy(self.THREE_ZONE_TOPOLOGY)
        _, frontend = compile_frontend(self.upstream, oatof, self.connection)
        frontend["accelerator_local_region"]["shield_back_z_mm"] -= 0.05
        _, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        origin_z = frontend["instance_origin_mm"]["z"]
        z_min = overlay["instance_bounds_mm"]["z_min"]
        desired_min = (
            frontend["accelerator_local_region"]["shield_back_z_mm"] - 0.2
        )
        self.assertLessEqual(z_min, desired_min)
        self.assertAlmostEqual((z_min - origin_z) / 0.2, round((z_min - origin_z) / 0.2))
        intermediate2 = frontend["accelerator_local_region"]["intermediate2_z_mm"]
        self.assertAlmostEqual(
            (intermediate2 - z_min) / 0.05, round((intermediate2 - z_min) / 0.05)
        )

    def test_accelerator_overlay_accepts_axial_coarse_refinement_but_rejects_transverse_asymmetry(self) -> None:
        _, axial_refined = compile_frontend(
            self.upstream,
            self.oatof,
            self.connection,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.1},
        )
        _, overlay = compile_accelerator_overlay(
            axial_refined, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
        )
        self.assertEqual(overlay["cell_mm_xyz"], {"x": 0.2, "y": 0.2, "z": 0.05})
        _, frontend = compile_frontend(self.upstream, self.oatof, self.connection)
        with self.assertRaisesRegex(ValueError, "x-y transverse"):
            compile_accelerator_overlay(
                frontend, cell_mm_xyz={"x": 0.2, "y": 0.1, "z": 0.05}
            )

    def test_accelerator_overlay_accepts_integer_transverse_refinement_of_coarse_bridge(self) -> None:
        _, coarse = compile_frontend(
            self.upstream,
            self.oatof,
            self.connection,
            cell_mm_xyz={"x": 0.5, "y": 0.5, "z": 0.5},
        )
        _, overlay = compile_accelerator_overlay(
            coarse, cell_mm_xyz={"x": 0.25, "y": 0.25, "z": 0.05}
        )
        self.assertEqual(overlay["cell_mm_xyz"], {"x": 0.25, "y": 0.25, "z": 0.05})

    def test_rejects_incomplete_or_nonpositive_axis_grid(self) -> None:
        for cells in (
            {"x": 0.2, "y": 0.2},
            {"x": 0.2, "y": 0.2, "z": 0.0},
        ):
            with self.subTest(cells=cells):
                with self.assertRaisesRegex(ValueError, "cell"):
                    compile_frontend(
                        self.upstream,
                        self.oatof,
                        self.connection,
                        cell_mm_xyz=cells,
                    )

    def test_rejects_gap_that_disagrees_with_registration(self) -> None:
        connection = json.loads(json.dumps(self.connection))
        connection["connector"]["length_mm"] = 1.0
        with self.assertRaisesRegex(ValueError, "gap and length"):
            compile_frontend(self.upstream, self.oatof, connection)

    def test_rejects_non_grounded_shield(self) -> None:
        upstream = copy.deepcopy(self.upstream)
        upstream["axial_dc"]["upstream_shield_potential_V"] = 3.0
        with self.assertRaisesRegex(ValueError, "exactly 0 V"):
            compile_frontend(upstream, self.oatof, self.connection)


if __name__ == "__main__":
    unittest.main()
