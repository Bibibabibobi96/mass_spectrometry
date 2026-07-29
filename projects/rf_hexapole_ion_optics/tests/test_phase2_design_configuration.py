from __future__ import annotations

import copy
import hashlib
import json
import unittest
from pathlib import Path

from common.contracts.machine_contracts import validate_schema
from common.multipole.compile_design_request import (
    MultipoleDesignCompileError,
    compile_design_request,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUEST_PATH = PROJECT_ROOT / "config" / "requests" / "mechanical_base.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pointer_value(document: dict, pointer: str):
    value = document
    for token in pointer.lstrip("/").split("/"):
        value = value[token.replace("~1", "/").replace("~0", "~")]
    return value


class Phase2DesignConfigurationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.request = load(REQUEST_PATH)
        cls.catalog = load(PROJECT_ROOT / "config" / "design_variables.json")
        cls.envelope = load(PROJECT_ROOT / "config" / "optimization_envelope.json")
        cls.baseline = load(PROJECT_ROOT / "config" / "baseline.json")
        cls.finite = load(PROJECT_ROOT / "config" / "finite_3d_transport.json")
        cls.screen = load(PROJECT_ROOT / "config" / "round_rod_field_screen.json")
        cls.comsol_numerics = load(
            PROJECT_ROOT / "config" / "comsol_solver_numerics.json"
        )
        cls.runtime_profiles = load(
            PROJECT_ROOT / "config" / "runtime_profiles.json"
        )
        cls.identity = {
            "project_id": "rf_hexapole_ion_optics",
            "family_id": "rf_multipole_ion_optics",
            "radial_order_n": 3,
            "electrode_count": 6,
        }

    def test_contracts_are_schema_valid_and_identity_is_locked(self) -> None:
        validate_schema(self.request, "multipole_design_request.schema.json")
        validate_schema(self.catalog, "design_variable_catalog.schema.json")
        validate_schema(self.envelope, "optimization_envelope.schema.json")
        self.assertEqual(self.request["identity"], self.identity)
        changed = copy.deepcopy(self.request)
        changed["identity"]["electrode_count"] = 8
        with self.assertRaisesRegex(MultipoleDesignCompileError, "identity"):
            compile_design_request(changed, expected_identity=self.identity)

    def test_request_compiles_to_current_rods_interfaces_drive_and_segmentation(self) -> None:
        compiled = compile_design_request(self.request, expected_identity=self.identity)
        geometry = self.request["geometry_mm"]
        self.assertEqual(len(compiled["geometry_mm"]["rod_array"]["rods"]), 6)
        self.assertEqual(geometry["inscribed_radius_r0"], self.baseline["geometry_mm"]["inscribed_radius_r0"])
        self.assertEqual(geometry["rod_radius_ratio"], 0.5)
        self.assertIn(geometry["rod_radius_ratio"], self.screen["geometry_mm"]["rod_radius_ratio_sweep"])
        self.assertEqual(geometry["rod_z_min"], self.finite["geometry_mm"]["rod_z_min"])
        self.assertEqual(geometry["rod_z_max"], self.baseline["geometry_mm"]["effective_length"])
        self.assertEqual(compiled["geometry_mm"]["enclosure"], geometry["enclosure"])
        self.assertEqual(
            geometry["enclosure"],
            {
                "model": "cylindrical_grounded_shield_v1",
                "role": "full_length_grounded_shield",
                "working_region_radius_mm": self.finite["geometry_mm"]["working_region_radius"],
                "vacuum_z_min_mm": -2.5,
                "vacuum_z_max_mm": 82.1,
                "shield_inner_radius_mm": self.finite["geometry_mm"]["grounded_shield_inner_radius"],
                "shield_outer_radius_mm": 21.0,
                "entrance_outer_endcap_upstream_face_z_mm": -2.5,
                "entrance_outer_endcap_downstream_face_z_mm": -2.0,
                "exit_outer_endcap_upstream_face_z_mm": 81.6,
                "exit_outer_endcap_downstream_face_z_mm": 82.1,
            },
        )
        for side in ("entrance_interface", "exit_interface"):
            self.assertEqual(
                geometry[side],
                {
                    key: value
                    for key, value in self.finite["geometry_mm"][side].items()
                    if key != "outer_ground_clearance_mm"
                },
            )
        rf = self.baseline["rf"]
        self.assertEqual(
            self.request["drive"],
            {
                "waveform": rf["waveform"],
                "rf_amplitude_V_zero_to_peak_per_group": rf["amplitude_V_peak"],
                "dc_amplitude_V_per_group": 0.0,
                "common_mode_offset_V": rf["common_mode_offset_V"],
                "frequency_Hz": rf["frequency_Hz"],
                "phase_rad": rf["phase_rad"],
            },
        )
        self.assertEqual(
            self.request["segmentation"],
            {
                "strategy": "uniform",
                "segment_count": 4,
                "intersegment_gap_mm": 0.4,
                "entrance_common_mode_V": 0.0,
                "exit_common_mode_V": 0.0,
                "output_reference_V": 0.0,
            },
        )
        self.assertEqual(
            compiled["segmentation"]["axial_acceleration"]["segmentation"]["segment_count"],
            4,
        )

    def test_envelope_has_complete_bounded_unit_coverage(self) -> None:
        variables = self.catalog["variables"]
        pointers = {item["json_pointer"] for item in variables}
        self.assertEqual(len(pointers), len(variables))
        for variable in variables:
            current = pointer_value(self.request, variable["json_pointer"])
            self.assertLess(variable["minimum"], variable["maximum"])
            self.assertLessEqual(variable["minimum"], current)
            self.assertLessEqual(current, variable["maximum"])
            self.assertIn(variable["unit"], {"mm", "ratio", "V", "Hz", "rad", "count"})
        bounded = next(item for item in self.envelope["constraints"] if item["kind"] == "bounded_variable")
        self.assertEqual(set(bounded["request_json_pointers"]), pointers)
        self.assertEqual(
            self.envelope["reference"]["design_request_sha256"],
            hashlib.sha256(REQUEST_PATH.read_bytes()).hexdigest().upper(),
        )
        self.assertIn("connector_shape_supported", self.catalog["invariants"])

    def test_comsol_baseline_freezes_verified_working_region_mesh_limit(self) -> None:
        profiles = self.comsol_numerics["profiles"]
        self.assertEqual(
            profiles["baseline_finite_3d"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.5,
        )
        self.assertEqual(
            profiles["n100_spatial_refined"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.35,
        )
        self.assertEqual(
            profiles["n100_temporal_refined"]["mesh"][
                "working_region_maximum_element_size_mm"
            ],
            0.35,
        )
        self.assertEqual(
            profiles["n100_temporal_refined"]["trajectory"]["rf_steps_per_period"],
            160,
        )

    def test_local_sensitive_mesh_sequence_changes_only_registered_size(
        self,
    ) -> None:
        profile_ids = (
            "hybrid_local_sensitive_050_cg_amg_field_screen",
            "hybrid_local_sensitive_040_cg_amg_field_screen",
            "hybrid_local_sensitive_032_cg_amg_field_screen",
        )
        profiles = [
            self.comsol_numerics["profiles"][profile_id]
            for profile_id in profile_ids
        ]
        sizes = [
            profile["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            for profile in profiles
        ]
        self.assertEqual(sizes, [0.5, 0.4, 0.32])
        self.assertEqual([sizes[0] / sizes[1], sizes[1] / sizes[2]], [1.25, 1.25])
        for profile in profiles:
            hybrid = profile["mesh"]["hybrid"]
            self.assertEqual(
                hybrid["sensitive_region"]["particle_corridor_radius_mm"], 3.6
            )
            self.assertEqual(hybrid["axial_layers_per_swept_segment"], 10)
            self.assertEqual(profile["electric_potential_element_order"], "quadratic")
            self.assertEqual(profile["stationary_linear_solver_backend"], "cg_amg")
        normalized = copy.deepcopy(profiles[0])
        del normalized["mesh"]["hybrid"]["sensitive_region"][
            "maximum_element_size_mm"
        ]
        for profile in profiles[1:]:
            peer = copy.deepcopy(profile)
            del peer["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            self.assertEqual(peer, normalized)

    def test_both_static_topologies_bind_all_local_field_levels(self) -> None:
        runtime = self.runtime_profiles["profiles"]
        for mode in (
            "exit_aperture_plate_acceleration",
            "segmented_rod_axial_acceleration",
        ):
            for size in ("050", "040", "032"):
                profile = runtime[
                    f"{mode}_n100_hybrid_local_sensitive_{size}_field_screen"
                ]
                self.assertEqual(profile["stop_stage"], "field_solve")
                self.assertEqual(profile["design_profile_id"], mode)
                self.assertEqual(
                    profile["comsol_solver_numerics_profile_id"],
                    f"hybrid_local_sensitive_{size}_cg_amg_field_screen",
                )

    def test_c1_background_sequence_changes_only_sensitive_size(self) -> None:
        profile_ids = (
            "hybrid_c1_background_sensitive_050_cg_amg_field_screen",
            "hybrid_c1_background_sensitive_040_cg_amg_field_screen",
            "hybrid_c1_background_sensitive_032_cg_amg_field_screen",
        )
        profiles = [
            self.comsol_numerics["profiles"][profile_id]
            for profile_id in profile_ids
        ]
        sizes = [
            profile["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            for profile in profiles
        ]
        self.assertEqual(sizes, [0.5, 0.4, 0.32])
        for profile in profiles:
            hybrid = profile["mesh"]["hybrid"]
            self.assertEqual(hybrid["radial_core_and_rod_hmax_mm"], 0.7)
            self.assertEqual(hybrid["transition_and_end_tetra_hmax_mm"], 0.7)
            self.assertEqual(hybrid["outer_vacuum_hmax_mm"], 1.4)
            self.assertEqual(hybrid["axial_layers_per_swept_segment"], 10)
        normalized = copy.deepcopy(profiles[0])
        del normalized["mesh"]["hybrid"]["sensitive_region"][
            "maximum_element_size_mm"
        ]
        for profile in profiles[1:]:
            peer = copy.deepcopy(profile)
            del peer["mesh"]["hybrid"]["sensitive_region"][
                "maximum_element_size_mm"
            ]
            self.assertEqual(peer, normalized)

    def test_both_static_topologies_bind_c1_background_levels(self) -> None:
        runtime = self.runtime_profiles["profiles"]
        for mode in (
            "exit_aperture_plate_acceleration",
            "segmented_rod_axial_acceleration",
        ):
            for size in ("050", "040", "032"):
                profile = runtime[
                    f"{mode}_n100_hybrid_c1_background_sensitive_{size}_field_screen"
                ]
                self.assertEqual(profile["stop_stage"], "field_solve")
                self.assertEqual(profile["design_profile_id"], mode)
                self.assertEqual(
                    profile["comsol_solver_numerics_profile_id"],
                    f"hybrid_c1_background_sensitive_{size}_cg_amg_field_screen",
                )

    def test_local_sensitive_050_preregistration_freezes_complete_runner(
        self,
    ) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_local_sensitive_050_field_preregistration.json"
        )
        self.assertEqual(
            preregistration["status"], "completed_resource_budget_exceeded"
        )
        self.assertEqual(
            preregistration["frozen_mesh"]["planned_sequence_mm"],
            [0.5, 0.4, 0.32],
        )
        self.assertEqual(preregistration["frozen_mesh"]["refinement_ratio"], 1.25)
        frozen_paths = {
            entry["path"] for entry in preregistration["frozen_implementation"]["files"]
        }
        self.assertIn(
            "common/multipole/configure_comsol_segment_hybrid_mesh.m",
            frozen_paths,
        )
        for entry in preregistration["frozen_implementation"]["files"]:
            self.assertEqual(
                entry["sha256"],
                hashlib.sha256((PROJECT_ROOT.parents[1] / entry["path"]).read_bytes())
                .hexdigest()
                .upper(),
            )
        execution = preregistration["execution_result"]
        self.assertEqual(
            execution["result"], "INCONCLUSIVE_RESOURCE_BUDGET_EXCEEDED"
        )
        self.assertEqual(execution["observed"]["mesh_global_elements"], 1_019_364)
        self.assertFalse(execution["later_field_levels_authorized"])

    def test_c1_background_050_preregistration_is_single_run(self) -> None:
        preregistration = load(
            PROJECT_ROOT
            / "config"
            / "qualification"
            / "comsol_c1_background_sensitive_050_field_preregistration.json"
        )
        self.assertEqual(preregistration["status"], "authorized_not_run")
        self.assertEqual(
            preregistration["authorization"]["maximum_commercial_run_count"], 1
        )
        self.assertEqual(
            preregistration["authorization"]["automatic_retry_count"], 0
        )
        mesh = preregistration["frozen_mesh"]
        self.assertEqual(mesh["radial_core_and_rod_hmax_mm"], 0.7)
        self.assertEqual(mesh["transition_and_end_tetra_hmax_mm"], 0.7)
        self.assertEqual(mesh["outer_vacuum_hmax_mm"], 1.4)
        self.assertEqual(
            mesh["sensitive_region"]["maximum_element_size_mm"], 0.5
        )
        self.assertEqual(
            mesh["predecessor_failed_strategy"]["mesh_global_elements"],
            1_019_364,
        )


if __name__ == "__main__":
    unittest.main()
