from __future__ import annotations

import json
import copy
import hashlib
import unittest
from pathlib import Path

from integrations.rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer.runtime.single_flight_frontend import (
    compile_accelerator_overlay,
    compile_frontend,
)


REPO = Path(__file__).resolve().parents[3]
INTEGRATION = REPO / "integrations" / "rf_multipole_ion_optics_to_single_reflection_oa_tof_mass_analyzer"


class SingleFlightFrontendTests(unittest.TestCase):
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
                "flange_thickness_binding": "oatof.geometry_mm.accelerator_shield_wall",
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
        self.assertGreaterEqual(gem.count("e(9)"), 6)
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
            "35d331a4d46e73abbcde140cc9e5a9bee7e10a9a6b2ab099fe1db90ddc376217",
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
        self.assertEqual(
            contract["junction_enclosure"],
            {
                "rod_end_to_accelerator_shield_mm": 1.0,
                "profile_gap_mm": 0.0,
                "topology": "grounded_circular_sleeve_with_apertured_flange",
                "shield_potential_V": 0.0,
                "grounded_sleeve_length_mm": 0.5,
                "flange_thickness_mm": 4.0,
                "full_radial_enclosure": True,
                "shared_ground_electrode_id": 9,
                "aperture_discretization": {
                    "schema_version": 2,
                    "role": "simion_rectangular_aperture_discretization",
                    "mechanical_width_mm": 1.0,
                    "mechanical_height_mm": 0.9,
                    "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.2},
                    "boolean_boundary_policy": "exclude_shape_inside_or_on_v1",
                    "numerical_carve_width_mm": 1.0,
                    "numerical_carve_height_mm": 0.9,
                    "compiled_pa_open_column_check_required": True,
                    "flange_x_min_mm": -67.8,
                    "flange_x_max_mm": -63.8,
                    "grid_alignment": {
                        "width_cells": 5.0,
                        "height_cells": 4.5,
                        "width_is_integer_cell_multiple": True,
                        "height_is_integer_cell_multiple": False,
                        "edge_grid_coordinates": {
                            "y_min": 103.5,
                            "y_max": 108.5,
                            "z_min": 104.25,
                            "z_max": 108.75,
                        },
                        "edges_on_grid_nodes": {
                            "y_min": False,
                            "y_max": False,
                            "z_min": False,
                            "z_max": False,
                        },
                        "warnings": [
                            "aperture_height_not_integer_cell_multiple",
                            "aperture_y_edges_not_on_grid_nodes",
                            "aperture_z_edges_not_on_grid_nodes",
                        ],
                    },
                },
            },
        )
        self.assertLessEqual(contract["dimensions"]["nx"] * contract["dimensions"]["ny"] * contract["dimensions"]["nz"], 30_000_000)

    def test_positive_gap_extends_the_closed_grounded_sleeve(self) -> None:
        connection = json.loads(json.dumps(self.connection))
        connection["connector"]["length_mm"] = 1.0
        connection["spatial_registration"]["expected_gap_mm"] = 1.0
        connection["spatial_registration"]["translation_mm"][0] -= 1.0
        _, contract = compile_frontend(self.upstream, self.oatof, connection)
        self.assertEqual(contract["junction_enclosure"]["profile_gap_mm"], 1.0)
        self.assertEqual(
            contract["junction_enclosure"]["grounded_sleeve_length_mm"], 1.5
        )
        self.assertEqual(
            contract["junction_enclosure"]["rod_end_to_accelerator_shield_mm"], 2.0
        )

    def test_grounded_reducer_can_narrow_but_not_enlarge_terminal_aperture(self) -> None:
        connection = copy.deepcopy(self.connection)
        connection["transition_aperture"]["full_width_mm"] = 0.5
        connection["transition_aperture"]["full_height_mm"] = 0.5
        connection["connector"]["aperture_reducer_profile_id"] = (
            "grounded_rectangular_aperture_reducer_v1"
        )
        _, contract = compile_frontend(self.upstream, self.oatof, connection)
        self.assertEqual(
            contract["aperture"],
            {"shape": "rectangular", "width_mm": 0.5, "height_mm": 0.5},
        )
        self.assertEqual(
            contract["aperture_reducer"],
            {
                "present": True,
                "profile_id": "grounded_rectangular_aperture_reducer_v1",
                "potential_V": 0.0,
                "terminal_envelope_width_mm": 1.0,
                "terminal_envelope_height_mm": 0.9,
            },
        )
        connection["transition_aperture"]["full_width_mm"] = 1.1
        with self.assertRaisesRegex(ValueError, "cannot enlarge"):
            compile_frontend(self.upstream, self.oatof, connection)

    def test_grounded_reducer_parameters_support_independent_z_aperture(self) -> None:
        connection = copy.deepcopy(self.connection)
        connection["transition_aperture"]["full_width_mm"] = 0.5
        connection["transition_aperture"]["full_height_mm"] = 0.2
        connection["connector"]["aperture_reducer_profile_id"] = (
            "grounded_rectangular_aperture_reducer_v1"
        )
        gem, contract = compile_frontend(self.upstream, self.oatof, connection)
        self.assertEqual(
            contract["aperture"],
            {"shape": "rectangular", "width_mm": 0.5, "height_mm": 0.2},
        )
        self.assertIn(
            "notin_inside_or_on { centered_box3D(-65.8,0,-18.4291868034,4.4,0.5,0.2)",
            gem,
        )
        self.assertGreaterEqual(gem.count("notin_inside_or_on"), 2)
        self.assertEqual(
            contract["junction_enclosure"]["aperture_discretization"],
            {
                "schema_version": 2,
                "role": "simion_rectangular_aperture_discretization",
                "mechanical_width_mm": 0.5,
                "mechanical_height_mm": 0.2,
                "cell_mm_xyz": {"x": 0.2, "y": 0.2, "z": 0.2},
                "boolean_boundary_policy": "exclude_shape_inside_or_on_v1",
                "numerical_carve_width_mm": 0.5,
                "numerical_carve_height_mm": 0.2,
                "compiled_pa_open_column_check_required": True,
                "flange_x_min_mm": -67.8,
                "flange_x_max_mm": -63.8,
                "grid_alignment": {
                    "width_cells": 2.5,
                    "height_cells": 1.0,
                    "width_is_integer_cell_multiple": False,
                    "height_is_integer_cell_multiple": True,
                    "edge_grid_coordinates": {
                        "y_min": 104.75,
                        "y_max": 107.25,
                        "z_min": 106.0,
                        "z_max": 107.0,
                    },
                    "edges_on_grid_nodes": {
                        "y_min": False,
                        "y_max": False,
                        "z_min": True,
                        "z_max": True,
                    },
                    "warnings": [
                        "aperture_width_not_integer_cell_multiple",
                        "aperture_y_edges_not_on_grid_nodes",
                    ],
                },
            },
        )

    def test_rejects_uncontracted_aperture_mismatch(self) -> None:
        connection = copy.deepcopy(self.connection)
        connection["transition_aperture"]["full_width_mm"] = 0.5
        with self.assertRaisesRegex(ValueError, "requires the governed grounded reducer"):
            compile_frontend(self.upstream, self.oatof, connection)

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

    def test_accelerator_overlay_supports_same_grid_identity_validation(self) -> None:
        _, frontend = compile_frontend(self.upstream, self.oatof, self.connection)
        _, overlay = compile_accelerator_overlay(
            frontend, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.2}
        )
        self.assertEqual(overlay["cell_mm_xyz"], frontend["cell_mm_xyz"])

    def test_accelerator_overlay_rejects_asymmetric_coarse_or_transverse_grid(self) -> None:
        _, asymmetric = compile_frontend(
            self.upstream,
            self.oatof,
            self.connection,
            cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.1},
        )
        with self.assertRaisesRegex(ValueError, "isotropic coarse"):
            compile_accelerator_overlay(
                asymmetric, cell_mm_xyz={"x": 0.2, "y": 0.2, "z": 0.05}
            )
        _, frontend = compile_frontend(self.upstream, self.oatof, self.connection)
        with self.assertRaisesRegex(ValueError, "x-y transverse"):
            compile_accelerator_overlay(
                frontend, cell_mm_xyz={"x": 0.2, "y": 0.1, "z": 0.05}
            )

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
